import json
import sqlite3
from typing import Any

import pytest

from app.cv.types import FrameAnalysis
from app.db import get_db
from app.routers import cv as cv_router
from app.services import cv_integration as integration


def _create_case(client, suffix: str) -> dict[str, Any]:
    return client.post(
        "/api/cases",
        json={"case_number": f"CV-{suffix}", "title": f"CV case {suffix}", "location": "Test"},
    ).json()


def _upload_video_for_case(client, case_id: str, synthetic_video) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _fake_analysis(with_warning: bool = False, with_crop: bool = True) -> dict[str, Any]:
    return {
        "source": "synthetic",
        "source_id": "video-1",
        "fps": 10.0,
        "frame_count": 60,
        "analyzed_frame_count": 1,
        "analysis_run_id": "analysis-fake",
        "frames": [
            {
                "frame_number": 4,
                "timestamp": 1.5,
                "faces": [
                    {
                        "sample_id": "sample-fake-1",
                        "frame_number": 4,
                        "timestamp": 1.5,
                        "bbox": [10.0, 20.0, 30.0, 40.0],
                        "detector_confidence": 0.91,
                        "track_id": 2,
                        "quality": {"quality_score": 82.0, "sharpness": 120.0},
                        "pose": {"frontal_score": 0.74},
                        "flags": {
                            "low_sharpness": False,
                            "partial_occlusion_suspected": False,
                            "mask": "present",
                            "identity_marker": "should not be exposed",
                        },
                        "crop_path": "/secret/local/crop.png" if with_crop else None,
                        "crop_state": "saved" if with_crop else "not_generated",
                        "embedding": [0.1, 0.2],
                    }
                ],
                "persons": [],
                "counts": {"faces": 1, "persons": 0},
                "total_counts": {"faces": 1, "persons": 0},
                "truncated": False,
                "truncation": {},
                "quality_total": 82.0,
                "quality_count": 1,
                "flag_counts": {},
                "face_track_ids": [2],
                "person_track_ids": [],
                "duration_ms": 1.0,
            }
        ],
        "summary": {"face_detections": 1},
        "truncation": {
            "face_observations_dropped_by_analysis": 1 if with_warning else 0,
            "person_observations_dropped_by_analysis": 0,
            "face_observations_dropped_by_frame": 0,
            "person_observations_dropped_by_frame": 0,
            "details_omitted_by_summary_only": False,
        },
        "runtime": {},
    }


def _patch_fake_pipeline(monkeypatch, analysis: dict[str, Any]) -> None:
    class FakePipeline:
        runtime = {}

        def __init__(self, *args, **kwargs):
            pass

        def analyze_video(self, **kwargs):
            return FakeAnalysis()

        def analyze_frame(self, frame, frame_number=0, timestamp=0.0, **kwargs):
            record = {
                "sample_id": f"sample-{frame_number}",
                "frame_number": int(frame_number),
                "timestamp": float(timestamp),
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "detector_confidence": 0.9,
                "track_id": None,
                "quality": {"quality_score": 80.0},
                "pose": {"frontal_score": 0.8},
                "flags": {"low_sharpness": False},
            }
            return FrameAnalysis(
                frame_number=int(frame_number),
                timestamp=float(timestamp),
                faces=[record],
                persons=[],
                counts={"faces": 1, "persons": 0},
                total_counts={"faces": 1, "persons": 0},
                truncation={},
                duration_ms=1.0,
            )

        def _apply_analysis_caps(self, frames):
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

    class FakeAnalysis:
        def to_dict(self):
            return analysis

    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)


def _create_run(client, case_id: str, video_id: str, **extra):
    payload = {"case_id": case_id, "video_id": video_id, "max_frames": 1, "frame_stride": 1}
    payload.update(extra)
    return client.post("/api/cv/runs", json=payload)


def test_create_run_persists_summary_observations_and_retrieves_after_reopen(client, synthetic_video, monkeypatch):
    case = _create_case(client, "PERSIST")
    video = _upload_video_for_case(client, case["id"], synthetic_video)
    _patch_fake_pipeline(monkeypatch, _fake_analysis(with_crop=False))

    response = _create_run(client, case["id"], video["id"], save_crops=False)
    assert response.status_code == 200, response.text
    body = response.json()
    run = body["run"]
    assert run["status"] == "completed"
    assert run["cv_run_id"]
    assert run["video_provenance"]["source_video_id"] == video["id"]
    assert run["video_provenance"]["source_video_sha256"] == video["sha256"]
    assert run["started_at"] and run["finished_at"]
    assert body["observations"]["total"] == 1

    fetched = client.get(f"/api/cv/runs/{run['cv_run_id']}", params={"case_id": case["id"]})
    assert fetched.status_code == 200
    assert fetched.json() == run

    observations = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    )
    assert observations.status_code == 200
    observation = observations.json()["items"][0]
    assert observation["cv_sample_id"] == "sample-fake-1"
    assert observation["original_frame_number"] == 4
    assert observation["original_video_timestamp_seconds"] == 1.5
    assert observation["bbox"] == [10.0, 20.0, 30.0, 40.0]
    assert observation["review_flags"]["mask"] == "not_assessed"
    assert observation["review_flags"]["helmet"] == "not_assessed"
    assert observation["review_flags"]["cap"] == "not_assessed"
    assert "identity_marker" not in observation["review_flags"]
    assert observation["crop"]["status"] == "not_generated"
    assert observation["crop"]["retrieval_state"] == "not_supported"
    assert "/" not in str(observation["crop"]["crop_id"])
    assert "crop_path" not in str(observation)
    assert "embedding" not in str(observation)

    listed = client.get("/api/cv/runs", params={"case_id": case["id"], "limit": 10, "offset": 0})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert integration.get_run_summary(run["cv_run_id"])["status"] == "completed"

    with get_db() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(cv_observations)")}
        assert "embedding" not in columns
        assert "embedding_vector" not in columns
        assert "crop_path" not in columns
        stored = conn.execute(
            "SELECT analysis_run_id, timestamp_provenance_json FROM cv_runs WHERE id=?",
            (run["cv_run_id"],),
        ).fetchone()
    timestamp = json.loads(stored["timestamp_provenance_json"])
    assert timestamp["analysis_run_id"] == stored["analysis_run_id"] == run["analysis_run_id"]


def test_run_lifecycle_sequence_is_queued_running_completed(client, synthetic_video, monkeypatch):
    case = _create_case(client, "LIFECYCLE")
    video = _upload_video_for_case(client, case["id"], synthetic_video)
    _patch_fake_pipeline(monkeypatch, _fake_analysis())

    observed: list[str] = []
    real_create = integration.create_run_record
    real_transition = integration.transition_status

    def spy_create(*args, **kwargs):
        cv_run_id = real_create(*args, **kwargs)
        with get_db() as conn:
            row = conn.execute("SELECT status FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
            observed.append(str(row["status"]))
        return cv_run_id

    def spy_transition(conn, cv_run_id, target, **kwargs):
        observed.append(target)
        return real_transition(conn, cv_run_id, target, **kwargs)

    monkeypatch.setattr(integration, "create_run_record", spy_create)
    monkeypatch.setattr(integration, "transition_status", spy_transition)

    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200
    assert observed == ["queued", "running", "completed"]


def test_completed_with_warnings_status_and_invalid_terminal_transition(client, synthetic_video, monkeypatch):
    case = _create_case(client, "WARN")
    video = _upload_video_for_case(client, case["id"], synthetic_video)
    _patch_fake_pipeline(monkeypatch, _fake_analysis(with_warning=True))

    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "completed_with_warnings"
    assert "face_observation_budget" in run["warnings"]

    with pytest.raises(integration.InvalidTransition):
        with get_db() as conn:
            integration.transition_status(conn, run["cv_run_id"], "running")


def test_engine_failure_marks_run_failed_without_orphans(client, synthetic_video, monkeypatch):
    case = _create_case(client, "ENGFAIL")
    video = _upload_video_for_case(client, case["id"], synthetic_video)

    class FailingPipeline:
        def __init__(self, *args, **kwargs):
            pass

        def analyze_video(self, **kwargs):
            raise RuntimeError("failed at /secret/path")

    monkeypatch.setattr(integration, "CVPipeline", FailingPipeline)
    observed: list[str] = []
    real_create = integration.create_run_record
    real_transition = integration.transition_status

    def spy_create(*args, **kwargs):
        cv_run_id = real_create(*args, **kwargs)
        with get_db() as conn:
            row = conn.execute("SELECT status FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
            observed.append(str(row["status"]))
        return cv_run_id

    def spy_transition(conn, cv_run_id, target, **kwargs):
        observed.append(target)
        return real_transition(conn, cv_run_id, target, **kwargs)

    monkeypatch.setattr(integration, "create_run_record", spy_create)
    monkeypatch.setattr(integration, "transition_status", spy_transition)

    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 500
    assert observed == ["queued", "running", "failed"]

    runs = integration.list_runs(case["id"], 50, 0)
    assert runs["total"] == 1
    run = runs["items"][0]
    assert run["status"] == "failed"
    assert run["message"] == "CV analysis failed"
    assert run["finished_at"]

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_observations WHERE cv_run_id=?", (run["cv_run_id"],)).fetchone()[0]
    assert count == 0


def test_observation_persistence_failure_marks_run_failed(client, synthetic_video, monkeypatch):
    case = _create_case(client, "DBFAIL")
    video = _upload_video_for_case(client, case["id"], synthetic_video)
    _patch_fake_pipeline(monkeypatch, _fake_analysis())

    def fail_insert(conn, observations):
        raise sqlite3.IntegrityError("forced persistence failure")

    monkeypatch.setattr(integration, "_insert_observations", fail_insert)
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 500

    run = integration.list_runs(case["id"], 50, 0)["items"][0]
    assert run["status"] == "failed"

    with get_db() as conn:
        row = conn.execute("SELECT failure_detail FROM cv_runs WHERE id=?", (run["cv_run_id"],)).fetchone()
        count = conn.execute("SELECT COUNT(*) FROM cv_observations WHERE cv_run_id=?", (run["cv_run_id"],)).fetchone()[0]
    assert row["failure_detail"] == "forced persistence failure"
    assert count == 0


def test_validation_isolates_cases_and_derives_hash(client, synthetic_video, monkeypatch):
    case = _create_case(client, "VALID1")
    other_case = _create_case(client, "VALID2")
    video = _upload_video_for_case(client, case["id"], synthetic_video)
    _patch_fake_pipeline(monkeypatch, _fake_analysis())

    missing_case = _create_run(client, "missing-case", video["id"])
    assert missing_case.status_code == 404

    wrong_case = _create_run(client, other_case["id"], video["id"])
    assert wrong_case.status_code == 404

    tx = client.post(
        f"/api/cases/{other_case['id']}/transactions",
        json={
            "reference": "CV-TX-OTHER",
            "atm_id": "ATM-OTHER",
            "transaction_ts": "2026-01-15T09:00:05+00:00",
            "cctv_ts": "2026-01-15T09:00:35+00:00",
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "test",
        },
    ).json()
    wrong_tx = _create_run(client, case["id"], video["id"], transaction_id=tx["id"])
    assert wrong_tx.status_code == 422

    own_tx = client.post(
        f"/api/cases/{case['id']}/transactions",
        json={
            "reference": "CV-TX-OWN",
            "atm_id": "ATM-OWN",
            "transaction_ts": "2026-01-15T09:00:05+00:00",
            "cctv_ts": "2026-01-15T09:00:35+00:00",
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "test",
        },
    ).json()
    aligned = _create_run(
        client,
        case["id"],
        video["id"],
        transaction_id=own_tx["id"],
        window_mode="transaction_aligned",
        transaction_ts="2026-01-15T09:00:05+00:00",
        cctv_ts="2026-01-15T09:00:35+00:00",
        before_seconds=1,
        after_seconds=1,
    )
    assert aligned.status_code == 200, aligned.text
    aligned_run = aligned.json()["run"]
    assert aligned_run["status"] == "completed_with_warnings"
    assert aligned_run["window_mode"] == "transaction_aligned"
    assert any("clamped" in warning.lower() for warning in aligned_run["warnings"])

    response = _create_run(
        client,
        case["id"],
        video["id"],
        source_video_sha256="0" * 64,
    )
    assert response.status_code == 200
    assert response.json()["run"]["video_provenance"]["source_video_sha256"] == video["sha256"]
    run_id = response.json()["run"]["cv_run_id"]

    denied_run = client.get(f"/api/cv/runs/{run_id}", params={"case_id": other_case["id"]})
    assert denied_run.status_code == 404
    denied_observations = client.get(
        f"/api/cv/runs/{run_id}/observations",
        params={"case_id": other_case["id"]},
    )
    assert denied_observations.status_code == 404

    other_list = client.get("/api/cv/runs", params={"case_id": other_case["id"]})
    assert other_list.status_code == 200
    assert other_list.json()["total"] == 0


def test_busy_analysis_returns_503_with_retry_after(client, synthetic_video, monkeypatch):
    case = _create_case(client, "BUSY")
    video = _upload_video_for_case(client, case["id"], synthetic_video)

    class BusySlot:
        def acquire(self, blocking=False):
            return False

        def release(self):
            pass

    monkeypatch.setattr(cv_router, "_analysis_slots", BusySlot())
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["detail"] == "CV analysis busy; retry later"
