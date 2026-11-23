from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cv2

from ..config import (
    CV_BACKEND,
    CV_CROP_DIR,
    CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS,
    CV_MAX_TOP_K,
    CV_TARGET,
    absolute_from_data,
    cv_limits,
    relative_to_data,
)
from ..cv import CVError, CVPipeline, model_status
from ..cv.crop import safe_segment
from ..cv.embeddings import EMBEDDING_SCHEMA_VERSION, V4_RECORD_FORMAT, EmbeddingStore, StagedEmbedding
from ..cv.types import VideoAnalysis
from ..db import audit, get_db, parse_json, utc_now
from ..schemas import (
    CV_CANDIDATE_DISCLAIMER,
    CV_SIMILARITY_SCORE_MEANING,
    CvCandidateSearchRequest,
    CvCandidateSummary,
    CvCropSummary,
    CvModelProvenance,
    CvPoseSummary,
    CvQualitySummary,
    CvReviewFlags,
    CvReviewUpsertRequest,
    CvRunCreateRequest,
    CvVideoProvenance,
)
from .atm_association import (
    CV_MAX_ASSOCIATIONS,
    AtmAssociationError,
    build_associations,
    build_zone_record,
    get_associations,
    insert_associations,
    insert_person_observations,
    person_observations_from_analysis,
)
from .security import new_id
from .timestamp import TimestampError, analyze_window, compute_alignment

logger = logging.getLogger("atm_sentinel.cv_integration")

ALLOWED_TRANSITIONS = {
    "queued": {"running", "failed"},
    "running": {"completed", "completed_with_warnings", "failed"},
    "completed": set(),
    "completed_with_warnings": set(),
    "failed": set(),
}
TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed"}
ELIGIBLE_RUN_STATUSES = {"completed", "completed_with_warnings"}
V4_HEX_DIGITS = frozenset("0123456789abcdef")
CANDIDATE_SCAN_LIMIT = max(1, int(CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS))
UNSUPPORTED_ATTRIBUTES = ("mask", "helmet", "cap")
QUALITY_FIELDS = set(CvQualitySummary.model_fields)
POSE_FIELDS = set(CvPoseSummary.model_fields)
REVIEW_FLAG_FIELDS = set(CvReviewFlags.model_fields)


class IntegrationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InvalidTransition(IntegrationError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"invalid CV run transition {current} -> {target}", 409)


class RunFailed(IntegrationError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail, 500)


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _public_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if "path" in lowered or "embedding" in lowered or "identity" in lowered:
            continue
        if isinstance(item, dict):
            result[key] = _public_mapping(item)
        elif isinstance(item, list):
            result[key] = [_public_mapping(entry) if isinstance(entry, dict) else entry for entry in item]
        else:
            result[key] = item
    return result


def _allowlisted_mapping(value: Any, fields: set[str]) -> dict[str, Any]:
    source = _public_mapping(value)
    return {key: item for key, item in source.items() if key in fields}


def _sanitize_failure(exc: Exception) -> str:
    text = str(exc).replace("\\", "/")
    if not text or "/" in text or "traceback" in text.lower():
        return "CV analysis failed"
    return text[:300]


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _video_provenance(video: dict[str, Any], normalized: dict[str, Any] | None) -> dict[str, Any]:
    if normalized is None:
        return {
            "source_video_id": str(video["id"]),
            "source_video_sha256": str(video["sha256"]),
            "derivative_kind": "none",
        }
    return {
        "source_video_id": str(video["id"]),
        "source_video_sha256": str(video["sha256"]),
        "derivative_kind": "normalized",
        "normalized_video_id": str(normalized["id"]),
        "normalized_video_sha256": str(normalized["sha256"]),
    }


def _strict_timestamp(value: str | None, label: str) -> datetime | None:
    if not value:
        return None
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise IntegrationError(f"Invalid {label}", 422)
    return parsed


def _alignment_from_request(
    request: CvRunCreateRequest,
    transaction: dict[str, Any] | None,
    video_duration: float,
) -> dict[str, Any]:
    transaction_ts = request.transaction_ts or (transaction["transaction_ts"] if transaction else None)
    cctv_ts = request.cctv_ts or (transaction["cctv_ts"] if transaction else None)
    if transaction_ts and cctv_ts:
        try:
            alignment = compute_alignment(
                transaction_ts,
                cctv_ts,
                video_duration,
                request.video_start_ts,
                request.cctv_reference_video_time,
                request.clock_offset_minutes,
            )
        except TimestampError as exc:
            raise IntegrationError(f"Invalid transaction alignment: {exc}", 422) from exc
        return {
            "transaction_utc": alignment["transaction_utc"],
            "cctv_clock_utc": alignment["cctv_utc"],
            "applied_alignment_offset_seconds": alignment["offset_seconds"],
            "alignment_source": alignment["offset_source"],
            "video_start_utc": alignment["video_start_utc"],
            "transaction_video_seconds": alignment["transaction_video_seconds"],
            "video_duration": video_duration,
            "warnings": list(alignment["warnings"]),
        }

    parsed_transaction = _strict_timestamp(transaction_ts, "transaction timestamp")
    parsed_cctv = _strict_timestamp(cctv_ts, "CCTV timestamp")
    parsed_video_start = _strict_timestamp(request.video_start_ts, "video start timestamp")
    warnings: list[str] = []
    offset = request.clock_offset_minutes * 60 if request.clock_offset_minutes is not None else None
    alignment_source = "manual_clock_offset_minutes" if offset is not None else None
    if offset is None and parsed_transaction and parsed_cctv:
        offset = (parsed_cctv - parsed_transaction).total_seconds()
        alignment_source = "derived_from_transaction_and_cctv_timestamps"
        if offset < 0:
            warnings.append("CCTV clock appears behind the transaction clock; verify the offset sign.")
    if parsed_video_start is None and parsed_cctv and request.cctv_reference_video_time:
        parsed_video_start = parsed_cctv - timedelta(seconds=request.cctv_reference_video_time)
    return {
        "transaction_utc": _iso(parsed_transaction),
        "cctv_clock_utc": _iso(parsed_cctv),
        "applied_alignment_offset_seconds": offset,
        "alignment_source": alignment_source,
        "video_start_utc": _iso(parsed_video_start),
        "transaction_video_seconds": None,
        "video_duration": video_duration,
        "warnings": warnings,
    }


def _plan_window(
    request: CvRunCreateRequest,
    video: dict[str, Any],
    transaction: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    duration = float(video["duration"] or 0)
    alignment = _alignment_from_request(request, transaction, duration)
    if request.window_mode == "full_video":
        window = {
            "mode": "full_video",
            "start_seconds": 0.0,
            "end_seconds": duration,
            "duration_seconds": duration,
            "source_video_duration_seconds": duration,
            "is_full_video": True,
            "before_seconds": None,
            "after_seconds": None,
            "clamped": False,
            "warnings": list(alignment["warnings"]),
        }
        return window, alignment

    before = float(request.before_seconds or 0)
    after = float(request.after_seconds or 0)
    if before < 0 or after < 0:
        raise IntegrationError("Analysis window values cannot be negative", 422)
    if before + after < 1:
        raise IntegrationError("Analysis window must span at least 1 second", 422)
    center = float(alignment["transaction_video_seconds"])
    raw_start = center - before
    raw_end = center + after
    if raw_end <= raw_start:
        raise IntegrationError("Analysis window is inverted", 422)
    if raw_start >= duration:
        raise IntegrationError("Requested analysis window is after the video", 422)
    if raw_end <= 0:
        raise IntegrationError("Requested analysis window is before the video", 422)

    try:
        analyzed = analyze_window(alignment, before, after)
    except TimestampError as exc:
        raise IntegrationError(f"Invalid analysis window: {exc}", 422) from exc
    start = float(analyzed["window_start_seconds"])
    end = float(analyzed["window_end_seconds"])
    if end <= start:
        raise IntegrationError("Analysis window is outside the video", 422)
    if end - start > float(cv_limits()["max_clip_duration_seconds"]):
        raise IntegrationError("Requested analysis window exceeds the configured duration budget", 422)
    clamped = round(raw_start, 3) != start or round(raw_end, 3) != end
    window = {
        "mode": "transaction_aligned",
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": end - start,
        "source_video_duration_seconds": duration,
        "is_full_video": False,
        "before_seconds": before,
        "after_seconds": after,
        "clamped": clamped,
        "warnings": list(analyzed["warnings"]),
    }
    return window, analyzed


def _plan_run(
    request: CvRunCreateRequest,
    video: dict[str, Any],
    normalized: dict[str, Any] | None,
    transaction: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    window, alignment = _plan_window(request, video, transaction)
    timestamp = {
        "cv_run_id": "",
        "analysis_run_id": "",
        "video_provenance": _video_provenance(video, normalized),
        "transaction_id": request.transaction_id,
        "transaction_utc": alignment.get("transaction_utc"),
        "cctv_clock_utc": alignment.get("cctv_clock_utc"),
        "applied_alignment_offset_seconds": alignment.get("applied_alignment_offset_seconds"),
        "alignment_source": alignment.get("alignment_source"),
        "video_start_utc": alignment.get("video_start_utc"),
        "transaction_video_seconds": alignment.get("transaction_video_seconds"),
        "window_start_seconds": float(window["start_seconds"]),
        "window_end_seconds": float(window["end_seconds"]),
        "timebase": "source_video_seconds",
        "warnings": list(alignment.get("warnings", [])),
    }
    return window, timestamp


def _model_provenance() -> list[dict[str, Any]]:
    generated_at = utc_now()
    models: list[dict[str, Any]] = []
    for model_key, info in model_status().get("models", {}).items():
        digest = info.get("sha256") or info.get("expected_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            continue
        observed = bool(info.get("usable")) and info.get("verification") == "verified"
        models.append(
            {
                "model_key": str(model_key),
                "model_filename": str(info.get("filename") or model_key),
                "model_sha256": digest.lower(),
                "model_source_url": info.get("source_url"),
                "backend": CV_BACKEND,
                "target": CV_TARGET,
                "runtime_state": "observed" if observed else "unknown",
                "runtime": _public_mapping(
                    {
                        "verification": info.get("verification"),
                        "usable": bool(info.get("usable")),
                        "purpose": info.get("purpose"),
                    }
                ),
                "opencv_version": cv2.__version__,
                "pipeline_version": "cv-phase2-persistent-runs",
                "embedding_schema_version": EMBEDDING_SCHEMA_VERSION,
                "generated_at": generated_at,
            }
        )
    return models


def _budget(request: CvRunCreateRequest, analysis: dict[str, Any]) -> dict[str, Any]:
    limits = cv_limits()
    return {
        "requested_max_frames": request.max_frames or int(limits["max_analysis_frames"]),
        "analyzed_frames": int(analysis.get("analyzed_frame_count") or 0),
        "frame_stride": request.frame_stride,
        "max_analysis_frames": int(limits["max_analysis_frames"]),
        "max_frame_stride": int(limits["max_frame_stride"]),
        "max_decoded_frames": int(limits["max_decoded_frames"]),
        "max_clip_duration_seconds": float(limits["max_clip_duration_seconds"]),
        "max_top_k": int(limits["max_top_k"]),
        "max_response_bytes": int(limits["max_response_bytes"]),
        "concurrent_analyses": int(limits["concurrent_analyses"]),
        "synchronous": True,
    }


def _truncation(analysis: dict[str, Any]) -> dict[str, Any]:
    raw = analysis.get("truncation") if isinstance(analysis.get("truncation"), dict) else {}
    near_duplicates = int(raw.get("near_duplicate_faces_suppressed") or 0)
    analysis_drops = int(raw.get("face_observations_dropped_by_analysis") or 0)
    budget_faces = max(0, analysis_drops - near_duplicates) + int(raw.get("face_observations_dropped_by_frame") or 0)
    person_omitted = int(raw.get("person_observations_dropped_by_analysis") or 0) + int(
        raw.get("person_observations_dropped_by_frame") or 0
    )
    face_crop_failures = int(raw.get("face_observations_dropped_by_crop_failure") or 0)
    crop_unavailable = face_crop_failures + int(raw.get("face_observations_with_unavailable_crops") or 0)
    face_omitted = budget_faces + face_crop_failures + near_duplicates
    reasons: list[str] = []
    if budget_faces:
        reasons.append("face_observation_budget")
    if person_omitted:
        reasons.append("person_observation_budget")
    if near_duplicates:
        reasons.append("near_duplicate_faces_suppressed")
    if crop_unavailable:
        reasons.append("crop_unavailable")
    if raw.get("details_omitted_by_summary_only"):
        reasons.append("summary_only")
    return {
        "truncated": bool(face_omitted or person_omitted or crop_unavailable or reasons),
        "face_observations_omitted": face_omitted,
        "person_observations_omitted": person_omitted,
        "ranking_candidates_omitted": 0,
        "frames_omitted": 0,
        "near_duplicate_faces_suppressed": near_duplicates,
        "crop_observations_unavailable": crop_unavailable,
        "reasons": reasons,
    }


def _warnings(truncation: dict[str, Any], timestamp: dict[str, Any]) -> list[str]:
    return [*timestamp.get("warnings", []), *truncation.get("reasons", [])]


def _bbox(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        value = []
    values: list[float] = []
    for item in list(value)[:4]:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            values.append(0.0)
    while len(values) < 4:
        values.append(0.0)
    return values


def _observations_from_analysis(
    analysis: dict[str, Any],
    request: CvRunCreateRequest,
    video: dict[str, Any],
    cv_run_id: str,
    analysis_run_id: str,
    window: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    seen_observation_ids: set[str] = set()
    window_start = float(window.get("start_seconds", 0.0)) if window else 0.0
    windowed = bool(window and not window.get("is_full_video", True))
    for frame in analysis.get("frames", []) or []:
        if not isinstance(frame, dict):
            continue
        for face in frame.get("faces", []) or []:
            if not isinstance(face, dict):
                continue
            sample_id = str(face.get("sample_id") or new_id())
            observation_id = str(face.get("observation_id") or new_id())
            if observation_id in seen_observation_ids:
                raise IntegrationError("Duplicate observation identity in analysis", 500)
            seen_observation_ids.add(observation_id)
            face_analysis_run_id = str(face.get("analysis_run_id") or analysis_run_id)
            if face_analysis_run_id != analysis_run_id:
                raise IntegrationError("Observation analysis run identity mismatch", 500)
            flags = _allowlisted_mapping(face.get("flags"), REVIEW_FLAG_FIELDS)
            for attribute in UNSUPPORTED_ATTRIBUTES:
                flags[attribute] = "not_assessed"
            crop_state = str(face.get("crop_state") or "")
            crop_available = bool(face.get("crop_path") or crop_state in {"saved", "available"})
            crop_status = (
                "available"
                if crop_available
                else "unavailable" if crop_state in {"failed", "limit_reached"} else "not_generated"
            )
            observations.append(
                {
                    "id": observation_id,
                    "cv_run_id": cv_run_id,
                    "case_id": request.case_id,
                    "video_id": request.video_id,
                    "sample_id": sample_id,
                    "source_video_sha256": str(video["sha256"]),
                    "original_frame_number": int(face.get("frame_number", frame.get("frame_number", 0)) or 0),
                    "original_video_timestamp_seconds": float(
                        face.get("timestamp", frame.get("timestamp", 0)) or 0
                    ),
                    "analysis_relative_timestamp_seconds": (
                        round(max(0.0, float(face.get("timestamp", frame.get("timestamp", 0)) or 0) - window_start), 4)
                        if windowed
                        else None
                    ),
                    "extracted_frame_id": None,
                    "bbox": _bbox(face.get("bbox")),
                    "detector_confidence": float(face.get("detector_confidence") or 0),
                    "track_id": face.get("track_id"),
                    "quality": _allowlisted_mapping(face.get("quality"), QUALITY_FIELDS),
                    "pose": _allowlisted_mapping(face.get("pose"), POSE_FIELDS),
                    "review_flags": flags,
                    "crop_id": new_id() if crop_available else None,
                    "crop_available": crop_available,
                    "crop_status": crop_status,
                    "analysis_run_id": face_analysis_run_id,
                }
            )
    return observations


def _finalize_pipeline_staged(pipeline: Any, analysis: Any) -> list[StagedEmbedding]:
    finalizer = getattr(pipeline, "finalize_staged_embeddings", None)
    if not callable(finalizer):
        return []
    frames = getattr(analysis, "frames", None)
    if frames is None:
        payload = analysis.to_dict() if hasattr(analysis, "to_dict") else analysis
        if isinstance(payload, (list, tuple)):
            frames = payload
        else:
            frames = payload.get("frames", []) if isinstance(payload, dict) else []
    return list(finalizer(frames))


def _publishable_staged_embeddings(
    staged: list[StagedEmbedding],
    observations: list[dict[str, Any]],
    request: CvRunCreateRequest,
    cv_run_id: str,
    analysis_run_id: str,
) -> tuple[list[StagedEmbedding], str | None]:
    persisted: dict[str, dict[str, Any]] = {}
    for observation in observations:
        observation_id = str(observation.get("id") or "")
        if not observation_id or observation_id in persisted:
            return [], "duplicate_observation_id"
        persisted[observation_id] = observation

    selected: list[StagedEmbedding] = []
    seen: set[str] = set()
    reason: str | None = None
    for entry in staged:
        record = getattr(entry, "record", None)
        if not isinstance(record, dict):
            reason = "invalid_staged_record"
            continue
        observation_id = str(record.get("observation_id") or "")
        observation = persisted.get(observation_id)
        if observation is None:
            reason = "unpersisted_observation"
            continue
        if observation_id in seen:
            return [], "duplicate_observation_id"
        expected = {
            "cv_run_id": cv_run_id,
            "analysis_run_id": analysis_run_id,
            "case_id": request.case_id,
            "video_id": request.video_id,
            "source_id": request.video_id,
            "sample_id": str(observation.get("sample_id") or ""),
        }
        if any(str(record.get(field) or "") != str(value or "") for field, value in expected.items()):
            reason = "provenance_mismatch"
            continue
        seen.add(observation_id)
        selected.append(entry)
    return selected, reason


def _publish_analysis_embeddings(staged: list[StagedEmbedding]) -> int:
    return EmbeddingStore().publish_staged_records(staged)


def validate_request(conn: sqlite3.Connection, request: CvRunCreateRequest) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    case = conn.execute("SELECT id FROM cases WHERE id=?", (request.case_id,)).fetchone()
    if not case:
        raise IntegrationError("Case not found", 404)
    video = conn.execute("SELECT * FROM videos WHERE id=?", (request.video_id,)).fetchone()
    if not video or str(video["case_id"]) != request.case_id:
        raise IntegrationError("Video not found in case", 404)
    if request.atm_zone and (float(video["width"] or 0) <= 0 or float(video["height"] or 0) <= 0):
        raise IntegrationError("Video dimensions are unavailable for ATM zone geometry", 422)

    transaction = None
    if request.transaction_id:
        transaction = conn.execute("SELECT * FROM transactions WHERE id=?", (request.transaction_id,)).fetchone()
        if not transaction or str(transaction["case_id"]) != request.case_id:
            raise IntegrationError("Transaction does not belong to case", 422)

    normalized = None
    if request.normalized_video_id:
        normalized = conn.execute("SELECT * FROM videos WHERE id=?", (request.normalized_video_id,)).fetchone()
        if not normalized or str(normalized["case_id"]) != request.case_id:
            raise IntegrationError("Normalized video does not belong to case", 422)
        if request.normalized_video_sha256 and str(normalized["sha256"]) != request.normalized_video_sha256.lower():
            raise IntegrationError("Normalized video hash does not match stored video", 422)
    return dict(video), dict(normalized) if normalized else None, dict(transaction) if transaction else None


def transition_status(
    conn: sqlite3.Connection,
    cv_run_id: str,
    target: str,
    *,
    message: str = "",
    failure_detail: str = "",
    warnings: list[str] | None = None,
) -> None:
    row = conn.execute("SELECT status, started_at FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
    if not row:
        raise IntegrationError("CV run not found", 404)
    current = str(row["status"])
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(current, target)

    assignments = ["status=?"]
    values: list[Any] = [target]
    if target == "running" and not row["started_at"]:
        assignments.append("started_at=?")
        values.append(utc_now())
    if target in TERMINAL_STATUSES:
        assignments.append("finished_at=?")
        values.append(utc_now())
    if message:
        assignments.append("message=?")
        values.append(message[:1000])
    if failure_detail:
        assignments.append("failure_detail=?")
        values.append(failure_detail[:300])
    if warnings is not None:
        assignments.append("warnings_json=?")
        values.append(_dump(warnings))
    values.append(cv_run_id)
    values.append(current)
    cursor = conn.execute(
        f"UPDATE cv_runs SET {', '.join(assignments)} WHERE id=? AND status=?",
        values,
    )
    if cursor.rowcount != 1:
        raise InvalidTransition(current, target)


def create_run_record(
    request: CvRunCreateRequest,
    video: dict[str, Any],
    normalized: dict[str, Any] | None,
    transaction: dict[str, Any] | None,
) -> str:
    cv_run_id = new_id()
    analysis_run_id = new_id()
    window, timestamp = _plan_run(request, video, normalized, transaction)
    timestamp["cv_run_id"] = cv_run_id
    timestamp["analysis_run_id"] = analysis_run_id
    timestamp["video_provenance"] = _video_provenance(video, normalized)
    models = _model_provenance()
    zone_record = build_zone_record(
        request.atm_zone,
        request.case_id,
        request.video_id,
        str(video["sha256"]),
        video["width"],
        video["height"],
    )
    budget = _budget(request, {"analyzed_frame_count": 0})
    truncation = _truncation({})
    warnings = _warnings(truncation, timestamp)
    created_at = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO cv_runs(
                id, case_id, video_id, transaction_id, source_video_sha256,
                normalized_video_id, normalized_video_sha256, status, window_mode,
                before_seconds, after_seconds, window_start_seconds, window_end_seconds,
                source_video_duration_seconds, clamped, analysis_run_id, request_json,
                atm_zone_json, window_json, timestamp_provenance_json, model_provenance_json, budget_json,
                truncation_json, warnings_json, disclaimer, message, failure_detail,
                created_at, started_at, finished_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                cv_run_id,
                request.case_id,
                request.video_id,
                request.transaction_id,
                str(video["sha256"]),
                request.normalized_video_id,
                request.normalized_video_sha256.lower() if request.normalized_video_sha256 else None,
                "queued",
                request.window_mode,
                request.before_seconds,
                request.after_seconds,
                window["start_seconds"],
                window["end_seconds"],
                window["source_video_duration_seconds"],
                int(bool(window.get("clamped"))),
                analysis_run_id,
                _dump(request.model_dump(mode="json")),
                _dump(zone_record) if zone_record else "{}",
                _dump(window),
                _dump(timestamp),
                _dump(models),
                _dump(budget),
                _dump(truncation),
                _dump(warnings),
                CV_CANDIDATE_DISCLAIMER,
                "CV run queued",
                "",
                created_at,
                None,
                None,
            ),
        )
    return cv_run_id


def _labels(request: CvRunCreateRequest) -> dict[int, str] | None:
    if not request.labels:
        return None
    labels: dict[int, str] = {}
    for key, value in request.labels.items():
        try:
            labels[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return labels


def _run_full_analysis(
    request: CvRunCreateRequest,
    cv_run_id: str,
    video_path: Any,
    analysis_run_id: str,
) -> tuple[str, dict[str, Any], list[StagedEmbedding]]:
    if not analysis_run_id:
        raise IntegrationError("Analysis run ID is unavailable", 500)
    pipeline = CVPipeline()
    analysis = pipeline.analyze_video(
        video_path=video_path,
        case_id=request.case_id,
        source_id=request.video_id,
        max_frames=request.max_frames,
        frame_stride=request.frame_stride,
        save_crops=request.save_crops,
        add_to_index=request.add_to_index,
        labels=_labels(request),
        run_id=analysis_run_id,
        cv_run_id=cv_run_id,
        video_id=request.video_id,
        retain_observations=True,
    )
    staged = _finalize_pipeline_staged(pipeline, analysis)
    payload = analysis.to_dict() if hasattr(analysis, "to_dict") else dict(analysis)
    return analysis_run_id, payload, staged


def _run_window_analysis(
    request: CvRunCreateRequest,
    cv_run_id: str,
    video: dict[str, Any],
    video_path: Any,
    window: dict[str, Any],
    analysis_run_id: str,
) -> tuple[str, dict[str, Any], list[StagedEmbedding]]:
    if not analysis_run_id:
        raise IntegrationError("Analysis run ID is unavailable", 500)
    limits = cv_limits()
    selected_max = int(request.max_frames or limits["max_analysis_frames"])
    stride = int(request.frame_stride)
    if selected_max < 1 or selected_max > int(limits["max_analysis_frames"]):
        raise IntegrationError("Requested frame budget is outside configured limits", 422)
    if stride < 1 or stride > int(limits["max_frame_stride"]):
        raise IntegrationError("Requested frame stride is outside configured limits", 422)
    if selected_max * stride > int(limits["max_decoded_frames"]):
        raise IntegrationError("Requested frame budget exceeds the decoded-frame limit", 422)

    fps = float(video["fps"] or 0)
    if fps <= 0:
        raise IntegrationError("Video FPS metadata is unavailable", 422)
    start = float(window["start_seconds"])
    end = float(window["end_seconds"])
    if end <= start:
        raise IntegrationError("Analysis window has no duration", 422)
    if end - start > float(limits["max_clip_duration_seconds"]):
        raise IntegrationError("Analysis window exceeds the configured duration budget", 422)

    start_frame = int(math.floor(start * fps + 1e-6))
    end_frame = int(math.floor(end * fps + 1e-6))
    decode_budget = min(selected_max * stride, max(0, end_frame - start_frame + 1))
    if decode_budget < 1:
        raise IntegrationError("No frames are available in the analysis window", 422)

    pipeline = CVPipeline()
    begin_analysis = getattr(pipeline, "begin_analysis", None)
    if callable(begin_analysis):
        begin_analysis(analysis_run_id)
    else:
        pipeline.analysis_run_id = analysis_run_id
    labels = _labels(request)
    frames: list[Any] = []
    decoded = 0
    analyzed = 0
    source_frame = start_frame
    processed_faces = 0
    processed_persons = 0
    quality_total = 0.0
    quality_count = 0
    flag_counts: dict[str, int] = {}
    face_tracks: set[int] = set()
    person_tracks: set[int] = set()
    processing_ms_total = 0.0
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        capture.release()
        raise IntegrationError("Could not open video source", 500)
    try:
        seek_accepted = capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        if not seek_accepted:
            raise IntegrationError("Could not seek to the analysis window start", 500)
        seek_position = int(capture.get(cv2.CAP_PROP_POS_FRAMES) or 0)
        if seek_position != start_frame:
            raise IntegrationError("Video seek did not reach the analysis window start", 500)
        while analyzed < selected_max and decoded < decode_budget:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = source_frame / fps
            if decoded % stride == 0 and start - 1e-6 <= timestamp <= end + 1e-6:
                label = str(labels.get(source_frame, "unlabelled")) if labels else "unlabelled"
                analysis = pipeline.analyze_frame(
                    frame=frame,
                    frame_number=source_frame,
                    timestamp=timestamp,
                    case_id=request.case_id,
                    source_id=request.video_id,
                    save_crops=request.save_crops,
                    add_to_index=request.add_to_index,
                    label=label,
                    run_id=analysis_run_id,
                    cv_run_id=cv_run_id,
                    video_id=request.video_id,
                    retain_observations=True,
                )
                processed_faces += int(analysis.total_counts.get("faces", 0))
                processed_persons += int(analysis.total_counts.get("persons", 0))
                if processed_faces > int(limits["max_face_detections_per_analysis"]):
                    raise RuntimeError("Analysis face detection budget exceeded")
                if processed_persons > int(limits["max_person_detections_per_analysis"]):
                    raise RuntimeError("Analysis person detection budget exceeded")
                analyzed += 1
                processing_ms_total += float(analysis.duration_ms)
                face_tracks.update(analysis.face_track_ids)
                person_tracks.update(analysis.person_track_ids)
                quality_total += float(analysis.quality_total)
                quality_count += int(analysis.quality_count)
                for name, count in analysis.flag_counts.items():
                    flag_counts[name] = flag_counts.get(name, 0) + int(count)
                frames.append(analysis)
            decoded += 1
            source_frame += 1
    finally:
        capture.release()

    if analyzed < 1:
        raise IntegrationError("No frames were analyzed in the requested window", 422)
    frames, global_truncation = pipeline._apply_analysis_caps(frames)
    staged = _finalize_pipeline_staged(pipeline, frames)
    retained_faces = sum(frame.counts.get("faces", 0) for frame in frames)
    retained_persons = sum(frame.counts.get("persons", 0) for frame in frames)
    frame_dropped_faces = sum(frame.truncation.get("face_observations_dropped_by_frame", 0) for frame in frames)
    frame_dropped_persons = sum(frame.truncation.get("person_observations_dropped_by_frame", 0) for frame in frames)
    crop_failures = sum(frame.truncation.get("face_observations_dropped_by_crop_failure", 0) for frame in frames)
    crop_unavailable = sum(frame.truncation.get("face_observations_with_unavailable_crops", 0) for frame in frames)
    near_duplicate_faces = int(global_truncation.get("near_duplicate_faces_suppressed", 0))
    summary = {
        "face_detections": processed_faces,
        "person_detections": processed_persons,
        "retained_face_observations": retained_faces,
        "retained_person_observations": retained_persons,
        "truncated_observations": (processed_faces - retained_faces) + (processed_persons - retained_persons),
        "near_duplicate_faces_suppressed": near_duplicate_faces,
        "crops_unavailable": crop_unavailable,
        "unique_face_tracks": len(face_tracks),
        "unique_person_tracks": len(person_tracks),
        "average_face_quality": round(quality_total / quality_count, 2) if quality_count else 0.0,
        "flag_counts": flag_counts,
        "total_processing_ms": round(processing_ms_total, 2),
        "average_frame_ms": round(processing_ms_total / analyzed, 2) if analyzed else 0.0,
        "estimated_fps": round(1000.0 * analyzed / processing_ms_total, 3) if processing_ms_total > 0 else 0.0,
    }
    truncation = {
        **global_truncation,
        "face_observations_dropped_by_frame": frame_dropped_faces,
        "person_observations_dropped_by_frame": frame_dropped_persons,
        "face_observations_dropped_by_crop_failure": crop_failures,
        "face_observations_with_unavailable_crops": crop_unavailable,
        "details_omitted_by_summary_only": False,
    }
    frame_count = max(end_frame - start_frame + 1, 0)
    try:
        source_label = relative_to_data(video_path)
    except ValueError:
        source_label = str(video_path.name)
    runtime = dict(pipeline.runtime)
    staging_summary = getattr(pipeline, "staging_summary", None)
    if callable(staging_summary):
        runtime["embedding_staging"] = staging_summary()
    analysis = VideoAnalysis(
        source=source_label,
        source_id=request.video_id,
        fps=fps,
        frame_count=frame_count,
        analyzed_frame_count=analyzed,
        analysis_run_id=analysis_run_id,
        frames=frames,
        summary=summary,
        truncation=truncation,
        runtime=runtime,
    )
    return analysis_run_id, analysis.to_dict(), staged


def _run_analysis(
    cv_run_id: str,
    request: CvRunCreateRequest,
    video: dict[str, Any],
    video_path: Any,
    window: dict[str, Any],
    analysis_run_id: str,
) -> tuple[str, dict[str, Any], list[StagedEmbedding]]:
    if window.get("is_full_video", True):
        return _run_full_analysis(request, cv_run_id, video_path, analysis_run_id)
    return _run_window_analysis(request, cv_run_id, video, video_path, window, analysis_run_id)


def _insert_observations(conn: sqlite3.Connection, observations: list[dict[str, Any]]) -> None:
    for observation in observations:
        conn.execute(
            """
            INSERT INTO cv_observations(
                id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds,
                analysis_relative_timestamp_seconds, extracted_frame_id, bbox_json,
                detector_confidence, track_id, quality_json, pose_json, review_flags_json,
                crop_id, crop_available, crop_status, crop_retrieval_state,
                verification_status, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                observation["id"],
                observation["cv_run_id"],
                observation["case_id"],
                observation["video_id"],
                observation["sample_id"],
                observation["source_video_sha256"],
                observation["original_frame_number"],
                observation["original_video_timestamp_seconds"],
                observation["analysis_relative_timestamp_seconds"],
                observation["extracted_frame_id"],
                _dump(observation["bbox"]),
                observation["detector_confidence"],
                observation["track_id"],
                _dump(observation["quality"]),
                _dump(observation["pose"]),
                _dump(observation["review_flags"]),
                observation["crop_id"],
                int(observation["crop_available"]),
                observation["crop_status"],
                "retrievable" if observation["crop_available"] and observation["crop_status"] == "available" else "not_supported",
                "candidate_only",
                utc_now(),
            ),
        )


def execute_run(cv_run_id: str, request: CvRunCreateRequest, video: dict[str, Any], video_path: Any) -> None:
    with get_db() as conn:
        run_row = conn.execute(
            "SELECT window_json, atm_zone_json, analysis_run_id FROM cv_runs WHERE id=?",
            (cv_run_id,),
        ).fetchone()
        if not run_row:
            raise IntegrationError("CV run not found", 404)
        analysis_run_id = str(run_row["analysis_run_id"] or "")
        if not analysis_run_id:
            raise IntegrationError("Analysis run ID is unavailable", 500)
        zone_record = parse_json(run_row["atm_zone_json"], {})
        zone_record = zone_record if isinstance(zone_record, dict) and zone_record else None
        window = parse_json(run_row["window_json"], {})
        if not window:
            window, _ = _plan_run(request, video, None, None)
        transition_status(conn, cv_run_id, "running", message="CV analysis started")

    try:
        returned_analysis_run_id, analysis, staged = _run_analysis(
            cv_run_id,
            request,
            video,
            video_path,
            window,
            analysis_run_id,
        )
        if returned_analysis_run_id != analysis_run_id:
            raise IntegrationError("Analysis run identity changed during analysis", 500)
        with get_db() as conn:
            run_row = conn.execute("SELECT * FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
            if not run_row:
                raise IntegrationError("CV run not found", 404)
            transaction = None
            if request.transaction_id:
                transaction_row = conn.execute(
                    "SELECT * FROM transactions WHERE id=?", (request.transaction_id,)
                ).fetchone()
                transaction = dict(transaction_row) if transaction_row else None
            normalized = None
            if request.normalized_video_id:
                normalized_row = conn.execute("SELECT * FROM videos WHERE id=?", (request.normalized_video_id,)).fetchone()
                normalized = dict(normalized_row) if normalized_row else None
            window, timestamp = _plan_run(request, video, normalized, transaction)
            timestamp["cv_run_id"] = cv_run_id
            timestamp["analysis_run_id"] = analysis_run_id
            budget = _budget(request, analysis)
            truncation = _truncation(analysis)
            warnings = _warnings(truncation, timestamp)
            observations = _observations_from_analysis(analysis, request, video, cv_run_id, analysis_run_id, window)
            _insert_observations(conn, observations)
            if zone_record:
                try:
                    person_rows = person_observations_from_analysis(
                        analysis,
                        request,
                        video,
                        cv_run_id,
                        analysis_run_id,
                        window,
                        zone_record,
                    )
                    insert_person_observations(conn, person_rows)
                    associations = build_associations(
                        person_rows,
                        case_id=request.case_id,
                        transaction_id=str(request.transaction_id or ""),
                        cv_run_id=cv_run_id,
                        video_id=request.video_id,
                        zone_record=zone_record,
                        window=window,
                        timestamp=timestamp,
                        model_provenance=parse_json(run_row["model_provenance_json"], []),
                        transaction_ts=request.transaction_ts or (transaction or {}).get("transaction_ts"),
                        cctv_ts=request.cctv_ts or (transaction or {}).get("cctv_ts"),
                        fps=float(analysis.get("fps") or video.get("fps") or 0) or 10.0,
                    )
                    insert_associations(conn, associations)
                except AtmAssociationError as exc:
                    raise IntegrationError(exc.message, exc.status_code) from exc
            conn.execute(
                """
                UPDATE cv_runs
                SET analysis_run_id=?, timestamp_provenance_json=?, model_provenance_json=?, budget_json=?,
                    truncation_json=?, warnings_json=?, message=?
                WHERE id=?
                """,
                (
                    analysis_run_id,
                    _dump(timestamp),
                    _dump(_model_provenance()),
                    _dump(budget),
                    _dump(truncation),
                    _dump(warnings),
                    "CV analysis completed",
                    cv_run_id,
                ),
            )

        publishable, selection_reason = _publishable_staged_embeddings(
            staged,
            observations,
            request,
            cv_run_id,
            analysis_run_id,
        )
        indexing_warning = f"embedding_index_incomplete: {selection_reason}" if selection_reason else None
        if publishable:
            try:
                published = _publish_analysis_embeddings(publishable)
                if published != len(publishable):
                    indexing_warning = "embedding_index_incomplete: partial_publication"
            except Exception as exc:
                logger.warning(
                    "CV run %s embedding publication failed: %s",
                    cv_run_id,
                    _sanitize_failure(exc),
                )
                indexing_warning = "embedding_index_incomplete: publication_failed"

        final_warnings = [*warnings]
        if indexing_warning:
            final_warnings.append(indexing_warning)
        final_message = "CV analysis completed"
        if indexing_warning:
            final_message = "CV analysis completed; embedding index incomplete"
        with get_db() as conn:
            terminal = "completed_with_warnings" if final_warnings else "completed"
            transition_status(
                conn,
                cv_run_id,
                terminal,
                message=final_message,
                warnings=final_warnings,
            )
    except Exception as exc:
        detail = _sanitize_failure(exc)
        logger.warning("CV run %s failed: %s", cv_run_id, detail)
        with get_db() as conn:
            try:
                transition_status(conn, cv_run_id, "failed", message="CV analysis failed", failure_detail=detail)
            except InvalidTransition:
                pass
        raise RunFailed(detail) from exc


def create_and_execute_run(request: CvRunCreateRequest) -> dict[str, Any]:
    with get_db() as conn:
        video, normalized, transaction = validate_request(conn, request)
    try:
        video_path = absolute_from_data(str(video["stored_path"]))
    except ValueError as exc:
        raise IntegrationError("Invalid video path", 400) from exc

    cv_run_id = create_run_record(request, video, normalized, transaction)
    execute_run(cv_run_id, request, video, video_path)
    observations = get_observations(cv_run_id, request.case_id, limit=CV_MAX_OBSERVATIONS, offset=0)
    associations = get_associations(cv_run_id, request.case_id, limit=CV_MAX_ASSOCIATIONS, offset=0)
    return {"run": get_run_summary(cv_run_id), "observations": observations, "associations": associations}


CV_MAX_OBSERVATIONS = 500


def _run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    provenance = {
        "source_video_id": str(row["video_id"]),
        "source_video_sha256": str(row["source_video_sha256"]),
        "derivative_kind": "normalized" if row["normalized_video_id"] else "none",
    }
    if row["normalized_video_id"]:
        provenance["normalized_video_id"] = str(row["normalized_video_id"])
        provenance["normalized_video_sha256"] = row["normalized_video_sha256"]
    window = parse_json(row["window_json"], {})
    timestamp_provenance = parse_json(row["timestamp_provenance_json"], {})
    model_provenance = parse_json(row["model_provenance_json"], [])
    zone_record = parse_json(row["atm_zone_json"], {})
    atm_zone = None
    if isinstance(zone_record, dict) and isinstance(zone_record.get("geometry"), dict):
        atm_zone = {
            "name": zone_record.get("name", "atm_interaction"),
            **zone_record["geometry"],
        }
    return {
        "cv_run_id": str(row["id"]),
        "case_id": str(row["case_id"]),
        "video_provenance": provenance,
        "transaction_id": row["transaction_id"],
        "status": str(row["status"]),
        "window_mode": str(row["window_mode"]),
        "window": window if isinstance(window, dict) and window else None,
        "analysis_run_id": str(row["analysis_run_id"]),
        "created_at": str(row["created_at"]),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "message": str(row["message"]) if "message" in row.keys() else "",
        "warnings": parse_json(row["warnings_json"], []),
        "budget": parse_json(row["budget_json"], {}),
        "truncation": parse_json(row["truncation_json"], {}),
        "timestamp_provenance": timestamp_provenance if isinstance(timestamp_provenance, dict) else {},
        "model_provenance": model_provenance if isinstance(model_provenance, list) else [],
        "atm_zone": atm_zone,
        "disclaimer": str(row["disclaimer"]),
    }


def get_run_summary(cv_run_id: str, case_id: str | None = None) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
    if not row or (case_id and str(row["case_id"]) != case_id):
        raise IntegrationError("CV run not found", 404)
    return _run_from_row(row)


def list_runs(case_id: str, limit: int, offset: int) -> dict[str, Any]:
    with get_db() as conn:
        case = conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
        if not case:
            raise IntegrationError("Case not found", 404)
        total = int(conn.execute("SELECT COUNT(*) FROM cv_runs WHERE case_id=?", (case_id,)).fetchone()[0])
        rows = conn.execute(
            "SELECT * FROM cv_runs WHERE case_id=? ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            (case_id, limit, offset),
        ).fetchall()
    return {"items": [_run_from_row(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def _crop_path_for_row(row: Any) -> Path:
    sample_id = _validated_crop_identifier(row["sample_id"], 404)
    root = CV_CROP_DIR.resolve()
    expected = (
        root
        / safe_segment(row["case_id"])
        / safe_segment(str(row["video_id"]))
        / f"frame_{int(row['original_frame_number']):06d}"
        / f"{safe_segment(sample_id)}.jpg"
    )
    resolved = expected.resolve()
    if root != resolved and root not in resolved.parents:
        raise IntegrationError("Crop not available", 404)
    return resolved


def _crop_file_is_retrievable(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("rb") as handle:
            return handle.read(3) == b"\xff\xd8\xff"
    except OSError:
        return False


def _crop_retrieval_state(row: Any) -> str:
    if not row["crop_available"] or row["crop_status"] != "available" or not row["crop_id"]:
        stored = str(row["crop_retrieval_state"])
        allowed = {"not_requested", "retrievable", "pending", "expired", "not_supported"}
        return stored if stored in allowed else "not_supported"
    try:
        path = _crop_path_for_row(row)
    except IntegrationError:
        return "expired"
    return "retrievable" if _crop_file_is_retrievable(path) else "expired"


def _observation_from_row(row: sqlite3.Row, video_id: str, sha256: str) -> dict[str, Any]:
    return {
        "observation_id": str(row["id"]),
        "cv_sample_id": str(row["sample_id"]),
        "cv_run_id": str(row["cv_run_id"]),
        "case_id": str(row["case_id"]),
        "video_provenance": {
            "source_video_id": str(video_id),
            "source_video_sha256": str(sha256),
            "derivative_kind": "none",
        },
        "original_frame_number": int(row["original_frame_number"]),
        "original_video_timestamp_seconds": float(row["original_video_timestamp_seconds"]),
        "analysis_relative_timestamp_seconds": row["analysis_relative_timestamp_seconds"],
        "extracted_frame_id": row["extracted_frame_id"],
        "bbox": parse_json(row["bbox_json"], []),
        "detector_confidence": float(row["detector_confidence"]),
        "track_id": row["track_id"],
        "quality": parse_json(row["quality_json"], {}),
        "pose": parse_json(row["pose_json"], {}),
        "review_flags": parse_json(row["review_flags_json"], {}),
        "crop": {
            "crop_id": row["crop_id"],
            "available": bool(row["crop_available"]),
            "status": str(row["crop_status"]),
            "retrieval_state": _crop_retrieval_state(row),
        },
        "verification_status": str(row["verification_status"]),
        "requires_human_verification": True,
        "candidate_disclaimer": CV_CANDIDATE_DISCLAIMER,
    }


def get_observations(cv_run_id: str, case_id: str | None = None, *, limit: int, offset: int) -> dict[str, Any]:
    with get_db() as conn:
        run = conn.execute("SELECT * FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
        if not run or (case_id and str(run["case_id"]) != case_id):
            raise IntegrationError("CV run not found", 404)
        total = int(conn.execute("SELECT COUNT(*) FROM cv_observations WHERE cv_run_id=?", (cv_run_id,)).fetchone()[0])
        rows = conn.execute(
            "SELECT * FROM cv_observations WHERE cv_run_id=? ORDER BY original_frame_number, id LIMIT ? OFFSET ?",
            (cv_run_id, limit, offset),
        ).fetchall()
    return {
        "items": [
            _observation_from_row(row, str(run["video_id"]), str(run["source_video_sha256"]))
            for row in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _review_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "decision_id": str(row["decision_id"]),
        "case_id": str(row["case_id"]),
        "cv_run_id": str(row["cv_run_id"]),
        "target_type": str(row["target_type"]),
        "target_id": str(row["target_id"]),
        "decision": str(row["decision"]),
        "reviewer_note": row["reviewer_note"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "disclaimer": CV_CANDIDATE_DISCLAIMER,
    }


def _validate_review_run_scope(conn: sqlite3.Connection, case_id: str, cv_run_id: str) -> None:
    case = conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone()
    if not case:
        raise IntegrationError("Case not found", 404)
    run = conn.execute("SELECT id, case_id FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
    if not run or str(run["case_id"]) != case_id:
        raise IntegrationError("CV run not found", 404)


def _validate_review_scope(
    conn: sqlite3.Connection,
    case_id: str,
    cv_run_id: str,
    observation_id: str,
) -> sqlite3.Row:
    _validate_review_run_scope(conn, case_id, cv_run_id)
    observation = conn.execute(
        "SELECT * FROM cv_observations WHERE id=?",
        (observation_id,),
    ).fetchone()
    if not observation or str(observation["cv_run_id"]) != cv_run_id or str(observation["case_id"]) != case_id:
        raise IntegrationError("Observation not found", 404)
    return observation


def upsert_review(
    case_id: str,
    cv_run_id: str,
    observation_id: str,
    payload: CvReviewUpsertRequest,
) -> tuple[dict[str, Any], bool]:
    with get_db() as conn:
        _validate_review_scope(conn, case_id, cv_run_id, observation_id)
        if payload.case_id != case_id or payload.cv_run_id != cv_run_id or payload.target_type != "face_observation":
            raise IntegrationError("Review request does not match the requested scope", 422)
        reviewer_note = (payload.reviewer_note or "").strip() or None
        now = utc_now()
        existing = conn.execute(
            """
            SELECT decision_id, created_at FROM cv_review_decisions
            WHERE case_id=? AND cv_run_id=? AND target_type=? AND target_id=?
            """,
            (case_id, cv_run_id, "face_observation", observation_id),
        ).fetchone()
        created = existing is None
        decision_id = str(existing["decision_id"]) if existing else new_id()
        detail = {
            "decision_id": decision_id,
            "case_id": case_id,
            "cv_run_id": cv_run_id,
            "target_type": "face_observation",
            "target_id": observation_id,
            "decision": payload.decision,
        }
        try:
            if existing:
                conn.execute(
                    """
                    UPDATE cv_review_decisions
                    SET decision=?, reviewer_note=?, updated_at=?
                    WHERE decision_id=?
                    """,
                    (payload.decision, reviewer_note, now, decision_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO cv_review_decisions(
                        decision_id, case_id, cv_run_id, target_type, target_id,
                        decision, reviewer_note, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        decision_id,
                        case_id,
                        cv_run_id,
                        "face_observation",
                        observation_id,
                        payload.decision,
                        reviewer_note,
                        now,
                        now,
                    ),
                )
            audit(
                conn,
                case_id,
                "cv_review_decision_created" if created else "cv_review_decision_updated",
                detail,
                created_at=now,
            )
            row = conn.execute(
                "SELECT * FROM cv_review_decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
        except sqlite3.IntegrityError as exc:
            raise IntegrationError("Review conflict", 409) from exc
    return _review_from_row(row), created


def get_review(case_id: str, cv_run_id: str, observation_id: str) -> dict[str, Any]:
    with get_db() as conn:
        _validate_review_scope(conn, case_id, cv_run_id, observation_id)
        row = conn.execute(
            """
            SELECT * FROM cv_review_decisions
            WHERE case_id=? AND cv_run_id=? AND target_type=? AND target_id=?
            """,
            (case_id, cv_run_id, "face_observation", observation_id),
        ).fetchone()
    if not row:
        raise IntegrationError("Review not found", 404)
    return _review_from_row(row)


def list_reviews(case_id: str, cv_run_id: str, limit: int, offset: int) -> dict[str, Any]:
    with get_db() as conn:
        _validate_review_run_scope(conn, case_id, cv_run_id)
        bounded_limit = max(1, min(int(limit), 200))
        bounded_offset = max(0, int(offset))
        total = int(
            conn.execute(
                "SELECT COUNT(*) FROM cv_review_decisions WHERE case_id=? AND cv_run_id=?",
                (case_id, cv_run_id),
            ).fetchone()[0]
        )
        rows = conn.execute(
            """
            SELECT * FROM cv_review_decisions
            WHERE case_id=? AND cv_run_id=?
            ORDER BY updated_at DESC, decision_id DESC
            LIMIT ? OFFSET ?
            """,
            (case_id, cv_run_id, bounded_limit, bounded_offset),
        ).fetchall()
    return {
        "items": [_review_from_row(row) for row in rows],
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


def _validate_candidate_query(
    conn: sqlite3.Connection,
    request: CvCandidateSearchRequest,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case = conn.execute("SELECT id FROM cases WHERE id=?", (request.case_id,)).fetchone()
    if not case:
        raise IntegrationError("Case not found", 404)
    run = conn.execute(
        "SELECT * FROM cv_runs WHERE id=? AND case_id=?",
        (request.query_cv_run_id, request.case_id),
    ).fetchone()
    if not run or str(run["status"]) not in ELIGIBLE_RUN_STATUSES or not str(run["analysis_run_id"] or ""):
        raise IntegrationError("Query run not found", 404)
    video = conn.execute(
        "SELECT * FROM videos WHERE id=? AND case_id=?",
        (str(run["video_id"]), request.case_id),
    ).fetchone()
    if not video:
        raise IntegrationError("Query video not found", 404)
    observation = conn.execute(
        """
        SELECT * FROM cv_observations
        WHERE id=? AND cv_run_id=? AND case_id=? AND video_id=?
        """,
        (request.query_observation_id, request.query_cv_run_id, request.case_id, str(video["id"])),
    ).fetchone()
    if not observation:
        raise IntegrationError("Query observation not found", 404)
    return dict(observation), dict(run)


def _validate_selected_videos(conn: sqlite3.Connection, case_id: str, video_ids: list[str]) -> list[str]:
    selected: list[str] = []
    for video_id in video_ids:
        row = conn.execute("SELECT id FROM videos WHERE id=? AND case_id=?", (video_id, case_id)).fetchone()
        if not row:
            raise IntegrationError("Video not found in case", 404)
        if video_id not in selected:
            selected.append(video_id)
    return selected


def _model_provenance_from_record(record: dict[str, Any]) -> dict[str, Any]:
    digest = str(record.get("model_sha256") or "")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise IntegrationError("Candidate index is unavailable", 422)
    runtime = record.get("runtime") if isinstance(record.get("runtime"), dict) else {}
    runtime_state = str(record.get("runtime_state") or "unknown")
    if runtime_state not in {"configured", "observed", "fallback", "unknown"}:
        runtime_state = "unknown"
    source_url = record.get("model_source_url")
    if not isinstance(source_url, str) or not source_url or len(source_url) > 500:
        source_url = None
    try:
        schema_version = int(record.get("embedding_schema_version") or EMBEDDING_SCHEMA_VERSION)
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Candidate index is unavailable", 422) from exc
    return CvModelProvenance(
        model_key=str(record.get("model_key") or "sface"),
        model_filename=str(record.get("model_filename") or "unknown"),
        model_sha256=digest,
        model_source_url=source_url,
        backend=str(record.get("backend") or "unknown"),
        target=str(record.get("target") or "unknown"),
        runtime_state=runtime_state,
        runtime=runtime,
        opencv_version=str(record.get("opencv_version") or "unknown"),
        pipeline_version=str(record.get("pipeline_version") or "unknown"),
        embedding_schema_version=schema_version,
        generated_at=str(record.get("generated_at") or utc_now()),
    ).model_dump()


def _candidate_video_provenance(row: sqlite3.Row, run_row: sqlite3.Row) -> dict[str, Any]:
    normalized_video_id = run_row["normalized_video_id"]
    return CvVideoProvenance(
        source_video_id=str(row["video_id"]),
        source_video_sha256=str(row["source_video_sha256"]),
        derivative_kind="normalized" if normalized_video_id else "none",
        normalized_video_id=str(normalized_video_id) if normalized_video_id else None,
        normalized_video_sha256=str(run_row["normalized_video_sha256"]) if normalized_video_id else None,
    ).model_dump()


def _candidate_optional_summaries(row: sqlite3.Row) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    try:
        quality = CvQualitySummary.model_validate(parse_json(row["quality_json"], {})).model_dump()
    except Exception:
        quality = None
    try:
        flags = CvReviewFlags.model_validate(parse_json(row["review_flags_json"], {})).model_dump()
    except Exception:
        flags = None
    try:
        crop = CvCropSummary(
            crop_id=row["crop_id"],
            available=bool(row["crop_available"]),
            status=str(row["crop_status"]),
            retrieval_state=_crop_retrieval_state(row),
        ).model_dump()
    except Exception:
        crop = None
    return quality, flags, crop


def _valid_v4_digest(value: Any) -> bool:
    digest = str(value or "")
    return len(digest) == 64 and all(character in V4_HEX_DIGITS for character in digest)


def _is_v4_candidate_record(record: Any, vector: Any = None) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("record_format") != V4_RECORD_FORMAT or record.get("v4_eligible") is not True:
        return False
    try:
        version = int(record.get("embedding_schema_version") or 0)
        dimension = int(record.get("embedding_dim") or 0)
    except (TypeError, ValueError):
        return False
    if version != EMBEDDING_SCHEMA_VERSION or dimension <= 0:
        return False
    if record.get("model_key") != "sface" or record.get("provenance_status") != "known":
        return False
    if record.get("verification_status") != "candidate_only":
        return False
    if not _valid_v4_digest(record.get("model_sha256")):
        return False
    if vector is not None:
        values = list(vector)
        if len(values) != dimension:
            return False
        try:
            if not values or any(not math.isfinite(float(value)) for value in values):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _validate_v4_query_record(
    record: Any,
    query_observation: dict[str, Any],
    query_run: dict[str, Any],
) -> None:
    if not _is_v4_candidate_record(record):
        raise IntegrationError("Query embedding unavailable", 404)
    expected = {
        "observation_id": str(query_observation["id"]),
        "cv_run_id": str(query_run["id"]),
        "analysis_run_id": str(query_run["analysis_run_id"]),
        "case_id": str(query_observation["case_id"]),
        "video_id": str(query_observation["video_id"]),
        "source_id": str(query_observation["video_id"]),
        "sample_id": str(query_observation["sample_id"]),
    }
    if any(str(record.get(field) or "") != str(value or "") for field, value in expected.items()):
        raise IntegrationError("Query embedding unavailable", 404)


def _provenance_matches(query_provenance: dict[str, Any], record: dict[str, Any]) -> bool:
    try:
        candidate = _model_provenance_from_record(record)
    except (IntegrationError, TypeError, ValueError):
        return False
    fields = (
        "model_key",
        "model_filename",
        "model_sha256",
        "model_source_url",
        "backend",
        "target",
        "runtime_state",
        "runtime",
        "opencv_version",
        "pipeline_version",
        "embedding_schema_version",
    )
    return all(candidate.get(field) == query_provenance.get(field) for field in fields)


def _candidate_record_is_eligible(
    record: dict[str, Any],
    row: sqlite3.Row,
    run_row: sqlite3.Row,
    request: CvCandidateSearchRequest,
    query_observation: dict[str, Any],
    selected_set: set[str],
    query_provenance: dict[str, Any],
) -> bool:
    if not _is_v4_candidate_record(record):
        return False
    observation_id = str(record.get("observation_id") or "")
    if not observation_id or observation_id == str(query_observation["id"]):
        return False
    expected = {
        "observation_id": str(row["id"]),
        "cv_run_id": str(row["cv_run_id"]),
        "analysis_run_id": str(run_row["analysis_run_id"]),
        "case_id": request.case_id,
        "video_id": str(row["video_id"]),
        "source_id": str(row["video_id"]),
        "sample_id": str(row["sample_id"]),
    }
    if any(str(record.get(field) or "") != str(value or "") for field, value in expected.items()):
        return False
    record_source_id = str(record.get("source_id") or "")
    if record_source_id != str(record.get("video_id") or ""):
        return False
    query_video_id = str(query_observation["video_id"])
    if record_source_id == query_video_id or str(row["video_id"]) == query_video_id:
        return False
    if request.scope == "case_selected_videos" and record_source_id not in selected_set:
        return False
    return _provenance_matches(query_provenance, record)


def _query_vector(
    store: EmbeddingStore,
    request: CvCandidateSearchRequest,
    query_observation: dict[str, Any],
    query_run: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    found = store.find_by_observation_id(
        request.query_observation_id,
        case_id=request.case_id,
        cv_run_id=request.query_cv_run_id,
        eligible_only=True,
    )
    if not found or not found.get("v4_eligible"):
        raise IntegrationError("Query embedding unavailable", 404)
    record = found.get("metadata")
    vector = found.get("vector")
    _validate_v4_query_record(record, query_observation, query_run)
    values = list(vector if vector is not None else [])
    if not values:
        raise IntegrationError("Query embedding is malformed", 422)
    try:
        if any(not math.isfinite(float(value)) for value in values):
            raise IntegrationError("Query embedding is malformed", 422)
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Query embedding is malformed", 422) from exc
    return vector, record


def search_candidates(request: CvCandidateSearchRequest, store: EmbeddingStore | None = None) -> dict[str, Any]:
    bounded_top_k = max(1, min(int(request.top_k), CV_MAX_TOP_K))
    with get_db() as conn:
        query_observation, query_run = _validate_candidate_query(conn, request)
        selected_video_ids = _validate_selected_videos(conn, request.case_id, request.source_video_ids)
    selected_set = set(selected_video_ids)
    query_video_id = str(query_observation["video_id"])

    try:
        store = store or EmbeddingStore()
    except (CVError, OSError, TypeError, ValueError) as exc:
        raise IntegrationError("Candidate index unavailable", 503) from exc
    try:
        query_vector, query_record = _query_vector(store, request, query_observation, query_run)
        query_provenance = _model_provenance_from_record(query_record)
    except IntegrationError:
        raise
    except (CVError, TypeError, ValueError) as exc:
        raise IntegrationError("Candidate index unavailable", 422) from exc

    try:
        ranked = store.iter_ranked_records(
            query_vector,
            case_id=request.case_id,
            exclude_observation_id=request.query_observation_id,
            exclude_source_id=query_video_id,
            eligible_only=True,
        )
    except (CVError, TypeError, ValueError) as exc:
        raise IntegrationError("Candidate index unavailable", 422) from exc

    items: list[dict[str, Any]] = []
    seen_observation_ids: set[str] = set()
    scanned = 0
    truncated = False
    eligible_statuses = tuple(sorted(ELIGIBLE_RUN_STATUSES))
    ranked_iter = iter(ranked)
    with get_db() as conn:
        while scanned < CANDIDATE_SCAN_LIMIT and len(items) < bounded_top_k:
            try:
                result = next(ranked_iter)
            except StopIteration:
                break
            scanned += 1
            try:
                score = float(result.get("cosine_similarity"))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(score) or not -1.0 <= score <= 1.0:
                continue
            metadata = result.get("metadata")
            if not isinstance(metadata, dict):
                continue
            observation_id = str(metadata.get("observation_id") or "")
            if not observation_id or observation_id in seen_observation_ids:
                continue
            row = conn.execute(
                "SELECT * FROM cv_observations WHERE id=? AND case_id=?",
                (observation_id, request.case_id),
            ).fetchone()
            if not row:
                continue
            run_row = conn.execute(
                """
                SELECT * FROM cv_runs
                WHERE id=? AND case_id=? AND status IN (?,?)
                """,
                (str(row["cv_run_id"]), request.case_id, *eligible_statuses),
            ).fetchone()
            if not run_row:
                continue
            if not _candidate_record_is_eligible(
                metadata,
                row,
                run_row,
                request,
                query_observation,
                selected_set,
                query_provenance,
            ):
                continue
            try:
                model_provenance = _model_provenance_from_record(metadata)
                video_provenance = _candidate_video_provenance(row, run_row)
            except (IntegrationError, TypeError, ValueError):
                continue
            quality, flags, crop = _candidate_optional_summaries(row)
            review = conn.execute(
                """
                SELECT decision FROM cv_review_decisions
                WHERE case_id=? AND cv_run_id=? AND target_type='face_observation' AND target_id=?
                """,
                (request.case_id, str(row["cv_run_id"]), str(row["id"])),
            ).fetchone()
            items.append(
                CvCandidateSummary(
                    candidate_id=new_id(),
                    case_id=request.case_id,
                    query_cv_run_id=request.query_cv_run_id,
                    query_observation_id=request.query_observation_id,
                    candidate_cv_run_id=str(row["cv_run_id"]),
                    candidate_observation_id=str(row["id"]),
                    candidate_video_provenance=video_provenance,
                    candidate_original_frame_number=int(row["original_frame_number"]),
                    candidate_original_video_timestamp_seconds=float(row["original_video_timestamp_seconds"]),
                    candidate_analysis_relative_timestamp_seconds=row["analysis_relative_timestamp_seconds"],
                    candidate_extracted_frame_id=row["extracted_frame_id"],
                    similarity_score=score,
                    rank=len(items) + 1,
                    model_provenance=[model_provenance],
                    human_review_status=str(review["decision"]) if review else None,
                    candidate_quality=quality,
                    candidate_review_flags=flags,
                    candidate_crop=crop,
                ).model_dump()
            )
            seen_observation_ids.add(observation_id)
            if len(items) >= bounded_top_k:
                break
        else:
            if scanned >= CANDIDATE_SCAN_LIMIT:
                truncated = True

    if truncated:
        scan_reason = "scan_limit"
    elif len(items) >= bounded_top_k:
        scan_reason = "top_k_reached"
    else:
        scan_reason = "exhausted"

    with get_db() as conn:
        audit(
            conn,
            request.case_id,
            "cv_candidate_search",
            {
                "query_cv_run_id": request.query_cv_run_id,
                "query_observation_id": request.query_observation_id,
                "scope": request.scope,
                "top_k": bounded_top_k,
                "source_video_count": len(selected_video_ids),
                "result_count": len(items),
            },
        )

    return {
        "items": items,
        "count": len(items),
        "limit": bounded_top_k,
        "scope": request.scope,
        "source_video_ids": selected_video_ids if request.scope == "case_selected_videos" else [],
        "query": {
            "case_id": request.case_id,
            "cv_run_id": request.query_cv_run_id,
            "observation_id": request.query_observation_id,
        },
        "score_meaning": CV_SIMILARITY_SCORE_MEANING,
        "disclaimer": CV_CANDIDATE_DISCLAIMER,
        "index": {
            "generation": int(store.generation),
            "schema_version": EMBEDDING_SCHEMA_VERSION,
            "record_count": len(store.records),
            "provenance": {
                "known": sum(1 for record in store.records if record.get("provenance_status") == "known"),
                "legacy_unknown": sum(1 for record in store.records if record.get("provenance_status") != "known"),
            },
        },
        "limits": {
            "max_top_k": CV_MAX_TOP_K,
            "concurrent_analyses": int(cv_limits()["concurrent_analyses"]),
            "candidate_scan": {
                "limit": CANDIDATE_SCAN_LIMIT,
                "scanned": scanned,
                "truncated": truncated,
                "reason": scan_reason,
            },
        },
    }


def _validated_crop_identifier(value: Any, status_code: int) -> str:
    if not isinstance(value, str) or not value:
        raise IntegrationError("Invalid crop identifier", status_code)
    if any(character in value for character in ("/", "\\", ":", "\0")) or ".." in value:
        raise IntegrationError("Invalid crop identifier", status_code)
    return value


def resolve_observation_crop(
    case_id: str,
    cv_run_id: str,
    observation_id: str,
    crop_id: str,
) -> Path:
    with get_db() as conn:
        observation = _validate_review_scope(conn, case_id, cv_run_id, observation_id)
        row = dict(observation)
    crop_id = _validated_crop_identifier(crop_id, 422)
    if not row["crop_id"] or row["crop_id"] != crop_id or not row["crop_available"] or row["crop_status"] != "available":
        raise IntegrationError("Crop not available", 404)
    path = _crop_path_for_row(row)
    if not _crop_file_is_retrievable(path):
        raise IntegrationError("Crop not available", 404)
    return path
