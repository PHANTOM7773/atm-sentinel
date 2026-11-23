from __future__ import annotations

import json
import logging
import threading
from typing import Any

import cv2
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse

from ..config import (
    CV_BACKEND,
    CV_FACE_SCORE_THRESHOLD,
    CV_MAX_FRAMES,
    CV_MAX_RANKED_CANDIDATES,
    CV_MAX_RESPONSE_BYTES,
    CV_MIN_EMBED_QUALITY,
    CV_PERSON_SCORE_THRESHOLD,
    CV_TARGET,
    DATA_DIR,
    absolute_from_data,
    cv_limits,
)
from ..cv import CVPipeline, CVError, model_status
from ..cv.embeddings import EmbeddingStore
from ..cv.quality import LIMITATIONS
from ..cv.runtime import configured_model_runtime, configured_runtime_summary
from ..db import get_db
from ..schemas import (
    CVAnalyzeRequest,
    CvCandidateSearchRequest,
    CvReviewUpsertRequest,
    CvRunCreateRequest,
    TransactionPersonAssociationReviewRequest,
)
from ..services import atm_association, best_face, cv_integration
from ..services.atm_association import AtmAssociationError
from ..services.best_face import BestFaceError
from ..services.cv_integration import resolve_observation_crop
from ..services.security import new_id

logger = logging.getLogger("atm_sentinel.cv")
router = APIRouter(prefix="/api/cv", tags=["computer-vision"])
_analysis_slots = threading.BoundedSemaphore(max(1, cv_limits()["concurrent_analyses"]))

DISCLAIMER = (
    "Candidate retrieval and track labels only. This endpoint never confirms identity and must not be "
    "used as a sole basis for decisions about a person."
)


def _public_error(exc: Exception) -> str:
    text = str(exc).replace("\\", "/")
    data_root = str(DATA_DIR).replace("\\", "/")
    if not text or data_root in text or "/" in text or "\\" in text or text.lower().startswith("traceback"):
        return "CV analysis failed"
    return text[:300]


def _embedding_status() -> dict[str, object]:
    try:
        return EmbeddingStore().status()
    except (CVError, OSError) as exc:
        logger.warning("Embedding status unavailable: %s", type(exc).__name__)
        return {
            "record_count": 0,
            "consistency": "unavailable",
            "provenance": {"known": 0, "legacy_unknown": 0},
        }


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _apply_ranking_budget(ranking: dict[str, Any] | None) -> None:
    if not ranking or ranking.get("omitted"):
        return
    candidates = ranking.get("candidates")
    if not isinstance(candidates, dict):
        return
    rows: list[tuple[float, str, int, dict[str, Any]]] = []
    for sample_id, items in candidates.items():
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if isinstance(item, dict):
                rows.append((float(item.get("cosine_similarity", 0.0)), str(sample_id), index, item))
    total = len(rows)
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    allowed = {(row[1], row[2]) for row in rows[:CV_MAX_RANKED_CANDIDATES]}
    retained: dict[str, list[dict[str, Any]]] = {}
    for sample_id, items in candidates.items():
        if not isinstance(items, list):
            retained[sample_id] = items
            continue
        retained[sample_id] = [item for index, item in enumerate(items) if (str(sample_id), index) in allowed]
    ranking["candidates"] = retained
    ranking["candidate_count"] = total
    ranking["retained_candidate_count"] = min(total, CV_MAX_RANKED_CANDIDATES)
    ranking["truncated"] = total > CV_MAX_RANKED_CANDIDATES
    ranking["truncation"] = {
        "candidates_omitted": total - min(total, CV_MAX_RANKED_CANDIDATES),
        "reason": "ranked_candidate_budget",
    }


def _enforce_response_budget(payload: dict[str, Any]) -> None:
    limit = CV_MAX_RESPONSE_BYTES
    if _payload_size(payload) <= limit:
        return
    truncation = payload.setdefault(
        "response_truncation",
        {
            "truncated": True,
            "observations_omitted": 0,
            "ranking_candidates_omitted": 0,
            "frames_omitted": 0,
            "reason": "response_payload_budget",
        },
    )
    analysis = payload.get("analysis")
    frames = analysis.get("frames") if isinstance(analysis, dict) else None
    summary = analysis.get("summary") if isinstance(analysis, dict) else None
    if isinstance(frames, list):
        while frames and _payload_size(payload) > limit:
            rows: list[tuple[float, str, int, int]] = []
            for frame_index, frame in enumerate(frames):
                if not isinstance(frame, dict):
                    continue
                for record_index, record in enumerate(frame.get("faces", [])):
                    score = ((record.get("quality") or {}).get("quality_score", 0.0)) if isinstance(record, dict) else 0.0
                    rows.append((float(score or 0.0), "faces", frame_index, record_index))
                for record_index, record in enumerate(frame.get("persons", [])):
                    score = record.get("confidence", 0.0) if isinstance(record, dict) else 0.0
                    rows.append((float(score or 0.0), "persons", frame_index, record_index))
            if not rows:
                break
            rows.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
            batch = max(1, min(len(rows), max(1, len(rows) // 16)))
            selected = rows[:batch]
            grouped: dict[int, dict[str, list[int]]] = {}
            for _, kind, frame_index, record_index in selected:
                grouped.setdefault(frame_index, {}).setdefault(kind, []).append(record_index)
            removed = 0
            for frame_index, kinds in grouped.items():
                frame = frames[frame_index]
                if not isinstance(frame, dict):
                    continue
                for kind, indices in kinds.items():
                    records = frame.get(kind)
                    if not isinstance(records, list):
                        continue
                    for record_index in sorted(indices, reverse=True):
                        if 0 <= record_index < len(records):
                            records.pop(record_index)
                            removed += 1
                counts = frame.get("counts") if isinstance(frame.get("counts"), dict) else {}
                for kind in ("faces", "persons"):
                    values = frame.get(kind)
                    counts[kind] = len(values) if isinstance(values, list) else 0
                frame["counts"] = counts
                frame_truncation = frame.setdefault("truncation", {})
                for kind in kinds:
                    key = f"{kind}_omitted_by_response_budget"
                    frame_truncation[key] = int(frame_truncation.get(key, 0)) + len(kinds[kind])
                frame["truncated"] = True
            truncation["observations_omitted"] = int(truncation.get("observations_omitted", 0)) + removed
            if isinstance(summary, dict):
                summary["retained_face_observations"] = sum(
                    len(item.get("faces", [])) for item in frames if isinstance(item, dict)
                )
                summary["retained_person_observations"] = sum(
                    len(item.get("persons", [])) for item in frames if isinstance(item, dict)
                )
                summary["truncated_observations"] = int(summary.get("truncated_observations", 0)) + removed

    ranking = payload.get("ranking")
    if isinstance(ranking, dict) and isinstance(ranking.get("candidates"), dict):
        while ranking["candidates"] and _payload_size(payload) > limit:
            rows: list[tuple[float, str, int]] = []
            for sample_id, items in ranking["candidates"].items():
                if isinstance(items, list):
                    for index, item in enumerate(items):
                        if isinstance(item, dict):
                            rows.append((float(item.get("cosine_similarity", 0.0)), str(sample_id), index))
            if not rows:
                break
            rows.sort(key=lambda row: (row[0], row[1], row[2]))
            _, sample_id, index = rows[0]
            ranking["candidates"][sample_id].pop(index)
            truncation["ranking_candidates_omitted"] = int(truncation.get("ranking_candidates_omitted", 0)) + 1
            ranking["retained_candidate_count"] = max(
                0, int(ranking.get("retained_candidate_count", 0)) - 1
            )
            ranking["truncated"] = True

    if isinstance(frames, list) and frames and _payload_size(payload) > limit:
        truncation["frames_omitted"] = len(frames)
        frames.clear()
        if isinstance(summary, dict):
            summary["retained_face_observations"] = 0
            summary["retained_person_observations"] = 0

    if _payload_size(payload) > limit:
        raise HTTPException(500, "CV response budget exceeded")


@router.get("/status")
def cv_status():
    runtime = configured_runtime_summary(CV_BACKEND, CV_TARGET)
    runtime["models"] = configured_model_runtime(CV_BACKEND, CV_TARGET)
    return {
        "models": model_status(),
        "runtime": runtime,
        "opencv_version": cv2.__version__,
        "thresholds": {
            "face_score": CV_FACE_SCORE_THRESHOLD,
            "person_score": CV_PERSON_SCORE_THRESHOLD,
            "minimum_embedding_quality": CV_MIN_EMBED_QUALITY,
            "default_max_frames": CV_MAX_FRAMES,
        },
        "person_detection": {
            "status": "experimental_unvalidated",
            "score_threshold": CV_PERSON_SCORE_THRESHOLD,
            "zero_detections_means": (
                "No person detected by this unvalidated detector, not proof that no person was present."
            ),
        },
        "limits": cv_limits(),
        "synchronous_analysis": True,
        "embedding_store": _embedding_status(),
        "limitations": [
            *LIMITATIONS,
            "Analysis is synchronous; long clips tie up the request worker and are bounded by configured limits.",
            "Track IDs are local to a single analysis run and are not persistent identities.",
        ],
        "disclaimer": DISCLAIMER,
    }


@router.get("/embeddings")
def cv_embeddings():
    return {"store": _embedding_status(), "disclaimer": DISCLAIMER}


@router.post("/runs")
def cv_create_run(request: CvRunCreateRequest):
    if not _analysis_slots.acquire(blocking=False):
        raise HTTPException(503, "CV analysis busy; retry later", headers={"Retry-After": "5"})
    try:
        return cv_integration.create_and_execute_run(request)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except Exception:
        logger.exception("CV run failed")
        raise HTTPException(500, "CV run failed")
    finally:
        _analysis_slots.release()


@router.get("/runs")
def cv_list_runs(
    case_id: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return cv_integration.list_runs(case_id, limit, offset)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}")
def cv_get_run(
    cv_run_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        return cv_integration.get_run_summary(cv_run_id, case_id)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}/observations")
def cv_get_observations(
    cv_run_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(100, ge=1, le=cv_integration.CV_MAX_OBSERVATIONS),
    offset: int = Query(0, ge=0),
):
    try:
        return cv_integration.get_observations(cv_run_id, case_id, limit=limit, offset=offset)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/runs/{cv_run_id}/observations/{observation_id}/review")
def cv_upsert_review(
    cv_run_id: str,
    observation_id: str,
    request: CvReviewUpsertRequest,
    response: Response,
    case_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        review, created = cv_integration.upsert_review(case_id, cv_run_id, observation_id, request)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    response.status_code = 201 if created else 200
    return review


@router.get("/runs/{cv_run_id}/observations/{observation_id}/review")
def cv_get_review(
    cv_run_id: str,
    observation_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        return cv_integration.get_review(case_id, cv_run_id, observation_id)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}/reviews")
def cv_list_reviews(
    cv_run_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return cv_integration.list_reviews(case_id, cv_run_id, limit, offset)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}/person-associations")
def cv_list_person_associations(
    cv_run_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
    transaction_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        return atm_association.get_associations(
            cv_run_id,
            case_id,
            transaction_id,
            limit=limit,
            offset=offset,
        )
    except AtmAssociationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}/person-associations/{association_id}/best-face")
def cv_get_best_face(
    cv_run_id: str,
    association_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        return best_face.get_selection(case_id, cv_run_id, association_id)
    except BestFaceError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.post("/person-associations/{association_id}/review")
def cv_review_person_association(
    association_id: str,
    request: TransactionPersonAssociationReviewRequest,
    case_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        return atm_association.review_association(
            case_id,
            request.cv_run_id,
            association_id,
            request.decision,
            request.reviewer_note,
        )
    except AtmAssociationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


@router.get("/runs/{cv_run_id}/observations/{observation_id}/crop")
def cv_get_observation_crop(
    cv_run_id: str,
    observation_id: str,
    case_id: str = Query(..., min_length=1, max_length=120),
    crop_id: str = Query(..., min_length=1, max_length=120),
):
    try:
        path = resolve_observation_crop(case_id, cv_run_id, observation_id, crop_id)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/candidates/search")
def cv_candidate_search(request: CvCandidateSearchRequest):
    if not _analysis_slots.acquire(blocking=False):
        raise HTTPException(503, "CV analysis busy; retry later", headers={"Retry-After": "5"})
    try:
        payload = cv_integration.search_candidates(request)
    except cv_integration.IntegrationError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc
    except (CVError, TypeError, ValueError):
        logger.warning("Candidate search rejected: unexpected input")
        raise HTTPException(422, "Candidate search input is invalid")
    except Exception as exc:
        logger.error("Candidate search failed: %s", type(exc).__name__)
        raise HTTPException(500, "Candidate search failed") from exc
    finally:
        _analysis_slots.release()
    _enforce_response_budget(payload)
    return payload


@router.post("/analyze")
def cv_analyze(request: CVAnalyzeRequest):
    with get_db() as conn:
        video = conn.execute("SELECT * FROM videos WHERE id=?", (request.video_id,)).fetchone()
    if not video:
        raise HTTPException(404, "Video not found")
    try:
        path = absolute_from_data(video["stored_path"])
    except ValueError as exc:
        logger.warning("Rejected unsafe video path for %s", request.video_id)
        raise HTTPException(400, "Invalid video path") from exc

    labels: dict[int, str] | None = None
    if request.labels:
        labels = {}
        for key, value in request.labels.items():
            try:
                labels[int(key)] = str(value)
            except ValueError:
                continue

    if not _analysis_slots.acquire(blocking=False):
        raise HTTPException(503, "CV analysis busy; retry later", headers={"Retry-After": "5"})

    try:
        run_id = new_id()
        pipeline = CVPipeline()
        analysis = pipeline.analyze_video(
            video_path=path,
            case_id=str(video["case_id"]),
            source_id=request.video_id,
            max_frames=request.max_frames,
            frame_stride=request.frame_stride,
            save_crops=request.save_crops,
            add_to_index=request.add_to_index,
            labels=labels,
            run_id=run_id,
            retain_observations=not request.summary_only,
        )
        ranking = (
            pipeline.rank_faces(analysis, str(video["case_id"]), request.top_k)
            if request.rank and not request.summary_only
            else None
        )
    except HTTPException:
        raise
    except CVError as exc:
        logger.warning("CV request rejected: %s", exc)
        raise HTTPException(400, _public_error(exc)) from exc
    except (cv2.error, OSError, ValueError) as exc:
        logger.exception("CV analysis failed")
        raise HTTPException(400, "Invalid video source or CV input") from exc
    except Exception:
        logger.exception("CV analysis failed")
        raise HTTPException(500, "CV analysis failed")
    finally:
        _analysis_slots.release()

    payload = analysis.to_dict()
    for frame in payload.get("frames", []):
        for face in frame.get("faces", []):
            face.pop("embedding", None)
    if request.summary_only:
        payload.pop("frames", None)
        if request.rank:
            ranking = {
                "candidate_count": 0,
                "retained_candidate_count": 0,
                "omitted": True,
                "disclaimer": "Ranked candidate retrieval only; no identity confirmation is made.",
                "truncation": {"reason": "summary_only"},
            }
    _apply_ranking_budget(ranking)
    response = {
        "analysis": payload,
        "ranking": ranking,
        "embedding_store": pipeline.store.status(),
        "analysis_run_id": run_id,
        "summary_only": request.summary_only,
        "limits": cv_limits(),
        "disclaimer": DISCLAIMER,
    }
    _enforce_response_budget(response)
    return response
