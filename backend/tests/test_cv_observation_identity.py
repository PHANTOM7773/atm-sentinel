import json
import sqlite3
from typing import Any

import numpy as np

from app.cv import pipeline as pipeline_module
from app.cv.types import FaceDetection, FrameAnalysis
from app.db import get_db
from app.services import cv_integration as integration


def _face_detection() -> FaceDetection:
    return FaceDetection(
        (20.0, 20.0, 80.0, 80.0),
        0.9,
        (
            (35.0, 45.0),
            (65.0, 45.0),
            (50.0, 60.0),
            (40.0, 75.0),
            (60.0, 75.0),
        ),
    )


def _pipeline(tmp_path: Any) -> pipeline_module.CVPipeline:
    return pipeline_module.CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path,
        crop_dir=tmp_path / "crops",
    )


def _face_record(
    pipeline: pipeline_module.CVPipeline,
    run_id: str,
    *,
    compute_embedding: bool = False,
    add_to_index: bool = False,
    cv_run_id: str = "",
    video_id: str = "",
) -> dict[str, Any]:
    frame = np.full((160, 160, 3), 128, dtype=np.uint8)
    record = pipeline._build_face_record(
        frame=frame,
        face=_face_detection(),
        frame_number=4,
        timestamp=0.4,
        case_id="case-identity",
        source_id="video-identity",
        add_to_index=add_to_index,
        label="unlabelled",
        run_id=run_id,
        cv_run_id=cv_run_id,
        video_id=video_id,
        compute_embedding=compute_embedding,
    )
    assert record is not None
    return record


def test_embedding_is_staged_before_publication_without_legacy_write(tmp_path, monkeypatch):
    pipeline = _pipeline(tmp_path)
    monkeypatch.setattr(pipeline_module, "CV_MIN_EMBED_QUALITY", 0)

    class StubEmbedder:
        def alignCrop(self, frame, landmarks):
            return frame

        def feature(self, aligned):
            assert pipeline._observation_sequence >= 1
            return np.array([1.0, 0.0], dtype=np.float32)

    pipeline.embedder = StubEmbedder()
    legacy_writes: list[dict[str, Any]] = []
    monkeypatch.setattr(pipeline.store, "add", lambda **kwargs: legacy_writes.append(kwargs))

    record = _face_record(
        pipeline,
        "analysis-embedding",
        compute_embedding=True,
        add_to_index=True,
        cv_run_id="cv-embedding",
        video_id="video-identity",
    )

    assert legacy_writes == []
    assert pipeline.store.status()["record_count"] == 0
    assert record["embedding_state"] == "staged_v4_candidate"
    assert record["observation_id"] != record["sample_id"]

    staged = pipeline.staged_embeddings()
    assert len(staged) == 1
    staged_record = staged[0].record
    assert staged_record["observation_id"] == record["observation_id"]
    assert staged_record["cv_run_id"] == "cv-embedding"
    assert staged_record["analysis_run_id"] == "analysis-embedding"
    assert staged_record["case_id"] == "case-identity"
    assert staged_record["video_id"] == "video-identity"
    assert staged_record["source_id"] == "video-identity"
    assert staged_record["sample_id"] == record["sample_id"]
    assert staged_record["model_key"] == "sface"
    assert staged_record["provenance_status"] == "known"
    assert staged_record["model_sha256"] == pipeline_module.MODEL_SPECS["sface"].sha256


def test_observation_ids_are_stable_per_run_and_distinct_across_runs(tmp_path):
    first_pipeline = _pipeline(tmp_path)
    first = _face_record(first_pipeline, "analysis-a")
    second = _face_record(first_pipeline, "analysis-a")

    replay_pipeline = _pipeline(tmp_path)
    replay = _face_record(replay_pipeline, "analysis-a")

    other_pipeline = _pipeline(tmp_path)
    other = _face_record(other_pipeline, "analysis-b")

    assert first["sample_id"] == replay["sample_id"] == other["sample_id"]
    assert first["observation_id"] == replay["observation_id"]
    assert first["observation_id"] != second["observation_id"]
    assert first["observation_id"] != other["observation_id"]


def _create_case(client: Any, suffix: str) -> dict[str, Any]:
    return client.post(
        "/api/cases",
        json={"case_number": f"CV-ID-{suffix}", "title": f"CV identity case {suffix}", "location": "Test"},
    ).json()


def _upload_video(client: Any, case_id: str, synthetic_video: Any) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": ("identity_test.mp4", handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_run(client: Any, case_id: str, video_id: str, **extra: Any) -> Any:
    payload = {"case_id": case_id, "video_id": video_id, "max_frames": 1, "frame_stride": 1}
    payload.update(extra)
    return client.post("/api/cv/runs", json=payload)


def _face(run_id: str, observation_id: str, sample_id: str) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "observation_id": observation_id,
        "analysis_run_id": run_id,
        "frame_number": 4,
        "timestamp": 1.5,
        "bbox": [10.0, 20.0, 30.0, 40.0],
        "detector_confidence": 0.91,
        "track_id": 2,
        "quality": {"quality_score": 82.0, "sharpness": 120.0},
        "pose": {"frontal_score": 0.74},
        "flags": {"low_sharpness": False},
        "crop_state": "not_generated",
    }


def _analysis_payload(run_id: str, observation_id: str, sample_id: str = "sample-fake-1") -> dict[str, Any]:
    return {
        "source": "synthetic",
        "source_id": "video-identity",
        "fps": 10.0,
        "frame_count": 60,
        "analyzed_frame_count": 1,
        "analysis_run_id": run_id,
        "frames": [
            {
                "frame_number": 4,
                "timestamp": 1.5,
                "faces": [_face(run_id, observation_id, sample_id)],
                "persons": [],
                "counts": {"faces": 1, "persons": 0},
                "total_counts": {"faces": 1, "persons": 0},
                "truncated": False,
                "truncation": {},
            }
        ],
        "summary": {"face_detections": 1},
        "truncation": {},
        "runtime": {},
    }


class _Analysis:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self.payload


def _patch_pipeline(monkeypatch: Any, observed_run_ids: list[str], mode: str = "video") -> None:
    class FakePipeline:
        runtime = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def analyze_video(self, **kwargs: Any) -> _Analysis:
            run_id = str(kwargs["run_id"])
            observed_run_ids.append(run_id)
            return _Analysis(_analysis_payload(run_id, f"obs-{run_id}"))

        def analyze_frame(self, frame: Any, frame_number: int = 0, timestamp: float = 0.0, **kwargs: Any) -> FrameAnalysis:
            run_id = str(kwargs["run_id"])
            observed_run_ids.append(run_id)
            observation_id = f"obs-{run_id}-frame-{frame_number}"
            return FrameAnalysis(
                frame_number=int(frame_number),
                timestamp=float(timestamp),
                faces=[_face(run_id, observation_id, f"window-sample-{frame_number}")],
                persons=[],
                counts={"faces": 1, "persons": 0},
                total_counts={"faces": 1, "persons": 0},
                truncation={},
                duration_ms=1.0,
            )

        def _apply_analysis_caps(self, frames: Any) -> tuple[Any, dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

    assert mode in {"video", "window"}
    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)


def _capture_initial_run_ids(monkeypatch: Any) -> list[str]:
    initial_ids: list[str] = []
    real_create = integration.create_run_record

    def spy_create(*args: Any, **kwargs: Any) -> str:
        cv_run_id = real_create(*args, **kwargs)
        with get_db() as conn:
            row = conn.execute("SELECT analysis_run_id FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
            initial_ids.append(str(row["analysis_run_id"]))
        return cv_run_id

    monkeypatch.setattr(integration, "create_run_record", spy_create)
    return initial_ids


def test_full_analysis_uses_one_run_id_and_persists_observation_id(client, synthetic_video, monkeypatch):
    case = _create_case(client, "FULL")
    video = _upload_video(client, case["id"], synthetic_video)
    observed_run_ids: list[str] = []
    initial_ids = _capture_initial_run_ids(monkeypatch)
    _patch_pipeline(monkeypatch, observed_run_ids)

    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200, response.text
    body = response.json()
    run = body["run"]
    initial_id = initial_ids[0]

    assert observed_run_ids == [initial_id]
    assert run["analysis_run_id"] == initial_id

    with get_db() as conn:
        stored = conn.execute(
            "SELECT analysis_run_id, timestamp_provenance_json FROM cv_runs WHERE id=?",
            (run["cv_run_id"],),
        ).fetchone()
    timestamp = json.loads(stored["timestamp_provenance_json"])
    assert stored["analysis_run_id"] == timestamp["analysis_run_id"] == initial_id

    observations = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    )
    assert observations.status_code == 200
    observation = observations.json()["items"][0]
    assert observation["observation_id"] == f"obs-{initial_id}"
    assert observation["cv_run_id"] == run["cv_run_id"]
    assert observation["cv_sample_id"] == "sample-fake-1"

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, cv_run_id, sample_id FROM cv_observations WHERE id=?",
            (observation["observation_id"],),
        ).fetchone()
    assert row["id"] == observation["observation_id"]
    assert row["cv_run_id"] == run["cv_run_id"]
    assert row["sample_id"] == "sample-fake-1"


def test_window_analysis_reuses_one_run_id_for_every_frame(client, synthetic_video, monkeypatch):
    case = _create_case(client, "WINDOW")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = client.post(
        f"/api/cases/{case['id']}/transactions",
        json={
            "reference": "CV-ID-TX",
            "atm_id": "ATM-ID",
            "transaction_ts": "2026-01-15T09:00:05+00:00",
            "cctv_ts": "2026-01-15T09:00:35+00:00",
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "test",
        },
    ).json()
    observed_run_ids: list[str] = []
    initial_ids = _capture_initial_run_ids(monkeypatch)
    _patch_pipeline(monkeypatch, observed_run_ids, mode="window")

    response = _create_run(
        client,
        case["id"],
        video["id"],
        transaction_id=tx["id"],
        window_mode="transaction_aligned",
        transaction_ts="2026-01-15T09:00:05+00:00",
        cctv_ts="2026-01-15T09:00:35+00:00",
        before_seconds=1,
        after_seconds=1,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    run = body["run"]
    initial_id = initial_ids[0]

    assert observed_run_ids
    assert set(observed_run_ids) == {initial_id}
    assert run["analysis_run_id"] == initial_id

    observations = client.get(
        f"/api/cv/runs/{run['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    )
    assert observations.status_code == 200
    items = observations.json()["items"]
    assert items
    assert all(item["observation_id"].startswith(f"obs-{initial_id}-frame-") for item in items)
    assert all(item["cv_run_id"] == run["cv_run_id"] for item in items)


def test_failed_and_retried_analyses_do_not_share_observation_identity(client, synthetic_video, monkeypatch):
    case = _create_case(client, "RETRY")
    video = _upload_video(client, case["id"], synthetic_video)
    observed_run_ids: list[str] = []
    _patch_pipeline(monkeypatch, observed_run_ids)

    real_insert = integration._insert_observations
    attempts: list[list[dict[str, Any]]] = []

    def fail_first_insert(conn: Any, observations: list[dict[str, Any]]) -> None:
        attempts.append(observations)
        if len(attempts) == 1:
            raise sqlite3.IntegrityError("forced persistence failure")
        real_insert(conn, observations)

    monkeypatch.setattr(integration, "_insert_observations", fail_first_insert)

    failed = _create_run(client, case["id"], video["id"])
    assert failed.status_code == 500
    succeeded = _create_run(client, case["id"], video["id"])
    assert succeeded.status_code == 200, succeeded.text

    assert len(observed_run_ids) == 2
    assert observed_run_ids[0] != observed_run_ids[1]
    assert attempts[0][0]["id"] == f"obs-{observed_run_ids[0]}"
    assert attempts[1][0]["id"] == f"obs-{observed_run_ids[1]}"

    with get_db() as conn:
        rows = conn.execute(
            "SELECT cv_run_id, id FROM cv_observations ORDER BY created_at"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["cv_run_id"] == succeeded.json()["run"]["cv_run_id"]
    assert rows[0]["id"] == f"obs-{observed_run_ids[1]}"


def test_mismatched_observation_analysis_run_id_is_rejected(client, synthetic_video, monkeypatch):
    case = _create_case(client, "MISMATCH")
    video = _upload_video(client, case["id"], synthetic_video)

    class MismatchPipeline:
        runtime = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def analyze_video(self, **kwargs: Any) -> _Analysis:
            payload = _analysis_payload(str(kwargs["run_id"]), "obs-mismatch")
            payload["frames"][0]["faces"][0]["analysis_run_id"] = "different-run"
            return _Analysis(payload)

    monkeypatch.setattr(integration, "CVPipeline", MismatchPipeline)

    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 500

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_observations").fetchone()[0]
    assert count == 0
