import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.config import absolute_from_data
from app.cv.crop import safe_segment, save_crop
from app.cv.embeddings import EMBEDDING_SCHEMA_VERSION, EmbeddingStore, build_v4_embedding_record
from app.cv.models import MODEL_SPECS
from app.cv.types import FrameAnalysis, VideoAnalysis
from app.db import get_db, utc_now
from app.services import cv_integration as integration
from app.services import image_enhancement as enhancement_service

TRANSACTION_TS = "2026-01-15T09:00:03+00:00"
CCTV_TS = "2026-01-15T09:00:03+00:00"
VIDEO_START_TS = "2026-01-15T09:00:00+00:00"
ZONE = {"name": "atm_keypad", "x": 0.5, "y": 0.5, "width": 0.25, "height": 0.25}


class _FakeCapture:
    def __init__(self, path: Any) -> None:
        self.path = path
        self.index = 0

    def isOpened(self) -> bool:
        return True

    def set(self, property_id: int, value: int) -> bool:
        self.index = int(value)
        return True

    def get(self, property_id: int) -> float:
        return float(self.index)

    def read(self) -> tuple[bool, Any]:
        if self.index >= 60:
            return False, None
        self.index += 1
        return True, object()

    def release(self) -> None:
        pass


def _quality() -> dict[str, Any]:
    return {
        "quality_score": 89.0,
        "sharpness": 90.0,
        "brightness": 128.0,
        "contrast": 58.0,
        "face_size_px": 50,
        "crop_size_px": 75,
        "occlusion_status": "not_suspected",
        "components": {
            "sharpness_component": 0.9,
            "illumination_component": 0.9,
            "contrast_component": 0.9,
            "size_component": 0.9,
            "landmark_component": 0.9,
            "frontal_component": 0.9,
        },
        "warnings": [],
        "disclaimer": "Image usability only; not identity.",
    }


class _FakePipeline:
    runtime = {"fake": True}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.analysis_run_id = ""

    def begin_analysis(self, analysis_run_id: str) -> None:
        self.analysis_run_id = analysis_run_id

    def analyze_frame(self, frame: Any, frame_number: int = 0, timestamp: float = 0.0, **kwargs: Any) -> FrameAnalysis:
        sample_prefix = str(kwargs.get("cv_run_id") or "run")
        faces = [{
            "observation_id": f"obs-{sample_prefix}-{frame_number}",
            "sample_id": f"sample-{sample_prefix}-{frame_number}",
            "frame_number": int(frame_number),
            "timestamp": float(timestamp),
            "bbox": [170.0, 125.0, 50.0, 50.0],
            "detector_confidence": 0.93,
            "track_id": 7,
            "quality": _quality(),
            "pose": {"frontal_score": 0.9, "warnings": []},
            "flags": {
                "low_sharpness": False,
                "underexposed": False,
                "overexposed": False,
                "small_face": False,
                "pose_away": False,
                "partial_occlusion_suspected": False,
                "occlusion_review": False,
            },
            "crop_state": "saved",
            "crop_path": "not-persisted",
        }]
        persons = [{
            "bbox": [160.0, 120.0, 80.0, 60.0],
            "confidence": 0.93,
            "class_id": 0,
            "track_id": 7,
        }]
        return FrameAnalysis(
            frame_number=int(frame_number),
            timestamp=float(timestamp),
            faces=faces,
            persons=persons,
            counts={"faces": 1, "persons": 1},
            total_counts={"faces": 1, "persons": 1},
            person_track_ids=[7],
            face_track_ids=[7],
            duration_ms=1.0,
        )

    def analyze_video(self, **kwargs: Any) -> VideoAnalysis:
        analysis_run_id = str(kwargs.get("run_id") or kwargs.get("analysis_run_id") or "analysis")
        frame = self.analyze_frame(
            object(),
            frame_number=4,
            timestamp=1.5,
            cv_run_id=kwargs.get("cv_run_id"),
        )
        return VideoAnalysis(
            source="synthetic",
            source_id=str(kwargs.get("source_id") or "video"),
            fps=10.0,
            frame_count=60,
            analyzed_frame_count=1,
            analysis_run_id=analysis_run_id,
            frames=[frame],
            summary={"face_detections": 1, "person_detections": 1},
        )

    def _apply_analysis_caps(self, frames: list[Any]) -> tuple[list[Any], dict[str, int]]:
        return frames, {}

    def finalize_staged_embeddings(self, frames: list[Any]) -> list[Any]:
        return []


def _create_case(client: Any, suffix: str) -> dict[str, Any]:
    response = client.post(
        "/api/cases",
        json={"case_number": f"T19-{suffix}", "title": f"Task 19 case {suffix}", "location": "ATM-TEST"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_transaction(client: Any, case_id: str, suffix: str) -> dict[str, Any]:
    response = client.post(
        f"/api/cases/{case_id}/transactions",
        json={
            "reference": f"T19-TX-{suffix}",
            "atm_id": "ATM-TEST",
            "transaction_ts": TRANSACTION_TS,
            "cctv_ts": CCTV_TS,
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "synthetic workflow verification",
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _upload_video(client: Any, case_id: str, synthetic_video: Any, name: str) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": (name, handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _save_crop(case_id: str, video_id: str, observation: dict[str, Any]) -> Path:
    root = integration.CV_CROP_DIR
    path = (
        root
        / safe_segment(case_id)
        / safe_segment(video_id)
        / f"frame_{int(observation['original_frame_number']):06d}"
        / f"{safe_segment(str(observation['cv_sample_id']))}.jpg"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    save_crop(np.full((50, 50, 3), 110, dtype=np.uint8), path)
    return path


def _publish_store(client: Any, store: EmbeddingStore, runs: list[dict[str, Any]], observations: list[dict[str, Any]], suffix: str) -> None:
    for index, (run, observation) in enumerate(zip(runs, observations)):
        provenance = run["model_provenance"][0]
        metadata = {
            "model_filename": provenance["model_filename"],
            "model_source_url": provenance.get("model_source_url"),
            "backend": provenance["backend"],
            "target": provenance["target"],
            "runtime_state": provenance["runtime_state"],
            "runtime": provenance.get("runtime") or {},
            "opencv_version": provenance["opencv_version"],
            "pipeline_version": provenance["pipeline_version"],
            "embedding_schema_version": EMBEDDING_SCHEMA_VERSION,
            "frame_number": observation["original_frame_number"],
            "timestamp": observation["original_video_timestamp_seconds"],
        }
        vector = [0.31, 0.27, 0.16] if index == 0 else [0.30, 0.28, 0.17]
        store.publish_staged_records([build_v4_embedding_record(
            embedding_id=f"emb-{suffix}-{index}",
            observation_id=observation["observation_id"],
            cv_run_id=run["cv_run_id"],
            analysis_run_id=run["analysis_run_id"],
            case_id=run["case_id"],
            video_id=run["video_provenance"]["source_video_id"],
            source_id=run["video_provenance"]["source_video_id"],
            sample_id=observation["cv_sample_id"],
            vector=vector,
            model_key="sface",
            provenance_status="known",
            model_sha256=MODEL_SPECS["sface"].sha256,
            generated_at=provenance["generated_at"],
            metadata=metadata,
        )])


def test_task19_full_workflow_and_failure_cases(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any) -> None:
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    enhanced_root = tmp_path / "task19-enhancements"
    enhanced_root.mkdir()
    store = EmbeddingStore(tmp_path / "embeddings")
    monkeypatch.setattr(integration, "CV_CROP_DIR", crop_root)
    monkeypatch.setattr(integration, "CVPipeline", _FakePipeline)
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    monkeypatch.setattr(enhancement_service, "DEFAULT_OUTPUT_ROOT", enhanced_root)

    case = _create_case(client, "FLOW")
    other_case = _create_case(client, "OTHER")
    transaction = _create_transaction(client, case["id"], "FLOW")
    video = _upload_video(client, case["id"], synthetic_video, "task19_flow.mp4")
    candidate_video = _upload_video(client, case["id"], synthetic_video, "task19_candidate.mp4")

    verify = client.post(f"/api/videos/{video['id']}/verify")
    assert verify.status_code == 200, verify.text
    assert verify.json()["status"] == "verified"
    normalized_response = client.post(
        f"/api/videos/{video['id']}/normalize",
        params={"case_id": case["id"]},
    )
    assert normalized_response.status_code == 201, normalized_response.text
    normalized = normalized_response.json()

    monkeypatch.setattr(integration.cv2, "VideoCapture", lambda path: _FakeCapture(path))
    run_response = client.post("/api/cv/runs", json={
        "case_id": case["id"],
        "video_id": video["id"],
        "normalized_video_id": normalized["id"],
        "normalized_video_sha256": normalized["sha256"],
        "transaction_id": transaction["id"],
        "transaction_ts": TRANSACTION_TS,
        "cctv_ts": CCTV_TS,
        "video_start_ts": VIDEO_START_TS,
        "window_mode": "transaction_aligned",
        "before_seconds": 1,
        "after_seconds": 1,
        "atm_zone": ZONE,
        "max_frames": 21,
        "frame_stride": 1,
        "save_crops": True,
        "add_to_index": False,
    })
    assert run_response.status_code == 200, run_response.text
    run_body = run_response.json()
    run = run_body["run"]
    assert run["status"] == "completed"
    assert run["video_provenance"]["derivative_kind"] == "normalized"
    assert run["video_provenance"]["normalized_video_sha256"] == normalized["sha256"]
    assert run["window"]["start_seconds"] == 2.0
    assert run["window"]["end_seconds"] == 4.0
    assert run["timestamp_provenance"]["transaction_video_seconds"] == 3.0
    assert run["atm_zone"] == ZONE

    observations = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations",
        params={"case_id": case["id"], "limit": 100, "offset": 0},
    ).json()
    assert observations["total"] >= 1
    observation = observations["items"][0]
    assert observation["crop"]["retrieval_state"] == "expired"
    assert observation["review_flags"]["mask"] == "not_assessed"
    assert "/" not in str(observation["crop"]["crop_id"])

    crop_path = _save_crop(case["id"], video["id"], observation)
    assert crop_path.exists()
    crop_response = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations/{observation['observation_id']}/crop",
        params={"case_id": case["id"], "crop_id": observation["crop"]["crop_id"]},
    )
    assert crop_response.status_code == 200, crop_response.text
    assert crop_response.content[:3] == b"\xff\xd8\xff"

    association_body = run_body["associations"]
    assert association_body["total"] == 1
    association = association_body["items"][0]
    assert association["review_state"] in {"proposed", "confirmed"}
    assert association["person_track_id"] == 7
    reviewed_association = client.post(
        f"/api/cv/person-associations/{association['association_id']}/review",
        params={"case_id": case["id"]},
        json={
            "case_id": case["id"],
            "cv_run_id": run["cv_run_id"],
            "decision": "confirmed",
            "reviewer_note": "Synthetic dwell and timing verified",
        },
    )
    assert reviewed_association.status_code == 200, reviewed_association.text
    assert reviewed_association.json()["review_state"] == "confirmed"

    refreshed_observations = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    ).json()["items"]
    refreshed_observation = next(
        item for item in refreshed_observations if item["observation_id"] == observation["observation_id"]
    )
    assert refreshed_observation["crop"]["retrieval_state"] == "retrievable"

    best_face = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/person-associations/{association['association_id']}/best-face",
        params={"case_id": case["id"]},
    )
    assert best_face.status_code == 200, best_face.text
    best = best_face.json()
    assert best["selected"]["observation"]["observation_id"] == observation["observation_id"]
    assert best["selected"]["eligible"] is True
    assert best["selected"]["link"]["person_track_id"] == 7
    assert "not identity" in best["limitation"].lower() or "do not identify" in best["limitation"].lower()

    enhancement = client.post("/api/cv/enhancement/face-crop", json={
        "case_id": case["id"],
        "cv_run_id": run["cv_run_id"],
        "observation_id": observation["observation_id"],
        "crop_id": observation["crop"]["crop_id"],
        "preset": "general_enhancement",
    })
    assert enhancement.status_code == 200, enhancement.text
    enhanced = enhancement.json()
    assert enhanced["original_sha256"] != enhanced["enhanced_sha256"]
    assert enhanced["derived_label"] == "AI-enhanced derived image - not original evidence"
    assert "Never use for face matching" in enhanced["forensic_notice"]
    enhanced_image = client.get(
        "/api/cv/enhancement/face-crop/image",
        params={
            "case_id": case["id"],
            "cv_run_id": run["cv_run_id"],
            "observation_id": observation["observation_id"],
            "crop_id": observation["crop"]["crop_id"],
            "preset": "general_enhancement",
        },
    )
    assert enhanced_image.status_code == 200, enhanced_image.text
    assert enhanced_image.content[:3] == b"\xff\xd8\xff"
    assert crop_path.read_bytes() == crop_path.read_bytes()

    monkeypatch.undo()
    monkeypatch.setattr(integration, "CV_CROP_DIR", crop_root)
    monkeypatch.setattr(integration, "CVPipeline", _FakePipeline)
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    monkeypatch.setattr(enhancement_service, "DEFAULT_OUTPUT_ROOT", enhanced_root)

    candidate_run_response = client.post("/api/cv/runs", json={
        "case_id": case["id"],
        "video_id": candidate_video["id"],
        "max_frames": 1,
        "frame_stride": 1,
        "save_crops": False,
        "add_to_index": False,
    })
    assert candidate_run_response.status_code == 200, candidate_run_response.text
    candidate_run = candidate_run_response.json()["run"]
    candidate_observation = candidate_run_response.json()["observations"]["items"][0]
    _publish_store(client, store, [run, candidate_run], [refreshed_observation, candidate_observation], "FLOW")

    search = client.post("/api/cv/candidates/search", json={
        "case_id": case["id"],
        "query_cv_run_id": run["cv_run_id"],
        "query_observation_id": observation["observation_id"],
        "top_k": 5,
    })
    assert search.status_code == 200, search.text
    candidates = search.json()
    assert candidates["count"] == 1
    candidate = candidates["items"][0]
    assert candidate["candidate_observation_id"] == candidate_observation["observation_id"]
    assert candidate["candidate_video_provenance"]["source_video_id"] == candidate_video["id"]
    assert candidate["verification_status"] == "candidate_only"
    assert -1 <= candidate["similarity_score"] <= 1

    query_review = client.post(
        f"/api/cv/runs/{run['cv_run_id']}/observations/{observation['observation_id']}/review",
        params={"case_id": case["id"]},
        json={"case_id": case["id"], "cv_run_id": run["cv_run_id"], "decision": "relevant", "reviewer_note": "Synthetic query reviewed"},
    )
    assert query_review.status_code in (200, 201), query_review.text
    candidate_review = client.post(
        f"/api/cv/runs/{candidate_run['cv_run_id']}/observations/{candidate_observation['observation_id']}/review",
        params={"case_id": case["id"]},
        json={"case_id": case["id"], "cv_run_id": candidate_run["cv_run_id"], "decision": "relevant", "reviewer_note": "Synthetic candidate reviewed"},
    )
    assert candidate_review.status_code in (200, 201), candidate_review.text

    manual_frame = client.post("/api/frames/manual", json={
        "case_id": case["id"],
        "video_id": video["id"],
        "timestamp": 3.0,
        "note": "Task 19 export frame",
    })
    assert manual_frame.status_code in (200, 201), manual_frame.text
    frame = manual_frame.json()

    export = client.post("/api/exports", json={
        "case_id": case["id"],
        "frame_ids": [frame["id"]],
        "cv_items": [
            {
                "kind": "observation",
                "cv_run_id": run["cv_run_id"],
                "observation_id": observation["observation_id"],
            },
            {
                "kind": "candidate",
                "cv_run_id": candidate_run["cv_run_id"],
                "observation_id": candidate_observation["observation_id"],
                "query_cv_run_id": run["cv_run_id"],
                "query_observation_id": observation["observation_id"],
                "candidate_id": candidate["candidate_id"],
                "selection_context": {"rank": candidate["rank"], "similarity_score": candidate["similarity_score"]},
            },
        ],
    })
    assert export.status_code == 201, export.text
    export_result = export.json()
    assert export_result["cv_selection_count"] == 2
    assert export_result["cv_observation_count"] == 1
    assert export_result["cv_candidate_count"] == 1
    manifest = json.loads(absolute_from_data(export_result["manifest_path"]).read_text())
    assert manifest["report_hash"] == export_result["report_hash"]
    assert manifest["cv_selections"][0]["verification_status"] == "candidate_only"
    assert manifest["cv_selections"][1]["selection_context"]["status"] == "unverified_client_selection_context"
    assert "do not identify" in manifest["cv_association_limitation"]
    assert absolute_from_data(export_result["pdf_path"]).read_bytes()[:4] == b"%PDF"

    failures = {
        "cross_case_run": client.get(f"/api/cv/runs/{run['cv_run_id']}", params={"case_id": other_case["id"]}).status_code,
        "wrong_crop": client.get(
            f"/api/cv/runs/{run['cv_run_id']}/observations/{observation['observation_id']}/crop",
            params={"case_id": case["id"], "crop_id": "not-the-crop-id"},
        ).status_code,
        "cross_case_search": client.post("/api/cv/candidates/search", json={
            "case_id": other_case["id"],
            "query_cv_run_id": run["cv_run_id"],
            "query_observation_id": observation["observation_id"],
            "top_k": 5,
        }).status_code,
        "cross_case_export": client.post("/api/exports", json={
            "case_id": other_case["id"],
            "frame_ids": [frame["id"]],
            "cv_items": [{
                "kind": "observation",
                "cv_run_id": run["cv_run_id"],
                "observation_id": observation["observation_id"],
            }],
        }).status_code,
        "stale_export": client.post("/api/exports", json={
            "case_id": case["id"],
            "frame_ids": [frame["id"]],
            "cv_items": [{
                "kind": "observation",
                "cv_run_id": run["cv_run_id"],
                "observation_id": observation["observation_id"],
                "expected_review_updated_at": "2000-01-01T00:00:00+00:00",
            }],
        }).status_code,
    }
    assert failures == {
        "cross_case_run": 404,
        "wrong_crop": 404,
        "cross_case_search": 404,
        "cross_case_export": 422,
        "stale_export": 422,
    }

    with get_db() as conn:
        audit_actions = [row["action"] for row in conn.execute(
            "SELECT action FROM audit_events WHERE case_id=? ORDER BY id", (case["id"],)
        ).fetchall()]
        enhanced_rows = conn.execute("SELECT COUNT(*) FROM cv_observations WHERE case_id=?", (case["id"],)).fetchone()[0]
    assert "video_normalized" in audit_actions
    assert "report_exported" in audit_actions
    assert enhanced_rows >= 2
    assert utc_now()
