import json
import sqlite3
from typing import Any

import numpy as np
import pytest

from app.cv.embeddings import EmbeddingStore, build_v4_embedding_record
from app.cv.models import MODEL_SPECS
from app.db import get_db
from app.services import cv_integration as integration

MODEL_SHA256 = MODEL_SPECS["sface"].sha256
GENERATED_AT = "2026-01-15T09:00:00+00:00"


def _staged(
    cv_run_id: str,
    analysis_run_id: str,
    observation_id: str,
    sample_id: str,
    case_id: str,
    video_id: str,
    vector: list[float] | None = None,
) -> Any:
    return build_v4_embedding_record(
        embedding_id=f"emb-{observation_id}",
        observation_id=observation_id,
        cv_run_id=cv_run_id,
        analysis_run_id=analysis_run_id,
        case_id=case_id,
        video_id=video_id,
        source_id=video_id,
        sample_id=sample_id,
        vector=np.asarray(vector or [1.0, 0.0, 0.0], dtype=np.float32),
        model_key="sface",
        provenance_status="known",
        model_sha256=MODEL_SHA256,
        generated_at=GENERATED_AT,
        metadata={
            "frame_number": 4,
            "timestamp": 1.5,
            "track_id": 1,
            "quality_score": 88.0,
            "synthetic_label": "unlabelled",
            "detector_confidence": 0.91,
        },
    )


def _analysis_payload(
    analysis_run_id: str,
    observation_id: str,
    sample_id: str,
    case_id: str,
    video_id: str,
) -> dict[str, Any]:
    return {
        "source": "synthetic",
        "source_id": video_id,
        "fps": 10.0,
        "frame_count": 60,
        "analyzed_frame_count": 1,
        "analysis_run_id": analysis_run_id,
        "frames": [
            {
                "frame_number": 4,
                "timestamp": 1.5,
                "faces": [
                    {
                        "sample_id": sample_id,
                        "observation_id": observation_id,
                        "analysis_run_id": analysis_run_id,
                        "frame_number": 4,
                        "timestamp": 1.5,
                        "bbox": [10.0, 20.0, 30.0, 40.0],
                        "detector_confidence": 0.91,
                        "track_id": 1,
                        "quality": {"quality_score": 88.0, "sharpness": 120.0},
                        "pose": {"frontal_score": 0.74},
                        "flags": {"low_sharpness": False},
                        "crop_state": "not_generated",
                    }
                ],
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


def _patch_pipeline(monkeypatch: Any, staged_mode: str = "valid") -> None:
    class FakePipeline:
        runtime = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.staged: list[Any] = []

        def analyze_video(self, **kwargs: Any) -> _Analysis:
            analysis_run_id = str(kwargs["run_id"])
            cv_run_id = str(kwargs["cv_run_id"])
            case_id = str(kwargs["case_id"])
            video_id = str(kwargs["video_id"])
            observation_id = f"obs-{analysis_run_id}"
            sample_id = f"sample-{analysis_run_id}"
            staged_run_id = cv_run_id
            staged_observation_id = observation_id
            if staged_mode == "unpersisted":
                staged_observation_id = "obs-ghost"
            elif staged_mode == "provenance":
                staged_run_id = "wrong-cv-run"
            elif staged_mode != "valid":
                raise AssertionError(f"unknown staged mode: {staged_mode}")
            if kwargs.get("add_to_index"):
                self.staged = [
                    _staged(
                        staged_run_id,
                        analysis_run_id,
                        staged_observation_id,
                        sample_id,
                        case_id,
                        video_id,
                    )
                ]
            return _Analysis(
                _analysis_payload(analysis_run_id, observation_id, sample_id, case_id, video_id)
            )

        def finalize_staged_embeddings(self, frames: Any) -> list[Any]:
            return list(self.staged)

        def staging_summary(self) -> dict[str, Any]:
            return {"staged_count": len(self.staged), "diagnostics": []}

        def _apply_analysis_caps(self, frames: Any) -> tuple[Any, dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)


def _create_case(client: Any, suffix: str) -> dict[str, Any]:
    return client.post(
        "/api/cases",
        json={"case_number": f"CV-PUB-{suffix}", "title": f"CV publication case {suffix}", "location": "Test"},
    ).json()


def _upload_video(client: Any, case_id: str, synthetic_video: Any) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": ("publication_test.mp4", handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_run(client: Any, case_id: str, video_id: str) -> Any:
    return client.post(
        "/api/cv/runs",
        json={
            "case_id": case_id,
            "video_id": video_id,
            "max_frames": 1,
            "frame_stride": 1,
            "add_to_index": True,
        },
    )


def _run_status(cv_run_id: str) -> Any:
    with get_db() as conn:
        return conn.execute(
            "SELECT status, message, warnings_json FROM cv_runs WHERE id=?",
            (cv_run_id,),
        ).fetchone()


def _observation_count(cv_run_id: str) -> int:
    with get_db() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM cv_observations WHERE cv_run_id=?",
                (cv_run_id,),
            ).fetchone()[0]
        )


def test_staged_v4_is_published_only_after_observations_are_persisted(client, synthetic_video, tmp_path, monkeypatch):
    store = EmbeddingStore(tmp_path / "embeddings")
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    _patch_pipeline(monkeypatch)

    real_publish = integration._publish_analysis_embeddings
    db_counts_at_publication: list[int] = []

    def spy_publish(staged: Any) -> int:
        with get_db() as conn:
            db_counts_at_publication.append(
                int(conn.execute("SELECT COUNT(*) FROM cv_observations").fetchone()[0])
            )
        return real_publish(staged)

    monkeypatch.setattr(integration, "_publish_analysis_embeddings", spy_publish)

    case = _create_case(client, "PUBLISH")
    video = _upload_video(client, case["id"], synthetic_video)
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200, response.text

    run = response.json()["run"]
    assert db_counts_at_publication == [1]

    published = store.find_by_observation_id(
        f"obs-{run['analysis_run_id']}",
        case_id=case["id"],
        cv_run_id=run["cv_run_id"],
    )
    assert published is not None
    assert published["v4_eligible"] is True
    record = published["metadata"]
    assert record["analysis_run_id"] == run["analysis_run_id"]
    assert record["case_id"] == case["id"]
    assert record["video_id"] == video["id"]
    assert record["source_id"] == video["id"]
    assert record["model_key"] == "sface"
    assert record["provenance_status"] == "known"
    assert record["model_sha256"] == MODEL_SHA256
    assert record["v4_eligible"] is True
    assert store.status()["record_formats"]["v4_eligible"] == 1
    assert _observation_count(run["cv_run_id"]) == 1

    status = _run_status(run["cv_run_id"])
    assert status["status"] == "completed"
    assert json.loads(status["warnings_json"]) == []


def test_publication_failure_keeps_persisted_observations_and_warns(client, synthetic_video, tmp_path, monkeypatch):
    store = EmbeddingStore(tmp_path / "embeddings")
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    _patch_pipeline(monkeypatch)

    def fail_publish(staged: Any) -> int:
        raise RuntimeError("forced publication failure")

    monkeypatch.setattr(integration, "_publish_analysis_embeddings", fail_publish)

    case = _create_case(client, "PUBFAIL")
    video = _upload_video(client, case["id"], synthetic_video)
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200, response.text

    run = response.json()["run"]
    status = _run_status(run["cv_run_id"])
    assert status["status"] == "completed_with_warnings"
    assert "embedding index incomplete" in status["message"]
    assert "embedding_index_incomplete: publication_failed" in json.loads(status["warnings_json"])
    assert _observation_count(run["cv_run_id"]) == 1
    assert store.status()["record_count"] == 0


def test_persistence_failure_prevents_publication(client, synthetic_video, tmp_path, monkeypatch):
    store = EmbeddingStore(tmp_path / "embeddings")
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    _patch_pipeline(monkeypatch)

    def fail_insert(conn: Any, observations: Any) -> None:
        raise sqlite3.IntegrityError("forced persistence failure")

    published: list[Any] = []

    def unexpected_publish(staged: Any) -> int:
        published.append(staged)
        return 0

    monkeypatch.setattr(integration, "_insert_observations", fail_insert)
    monkeypatch.setattr(integration, "_publish_analysis_embeddings", unexpected_publish)

    case = _create_case(client, "NOSAVE")
    video = _upload_video(client, case["id"], synthetic_video)
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 500

    assert published == []
    assert store.status()["record_count"] == 0


@pytest.mark.parametrize(
    ("staged_mode", "expected_warning"),
    [
        ("unpersisted", "embedding_index_incomplete: unpersisted_observation"),
        ("provenance", "embedding_index_incomplete: provenance_mismatch"),
    ],
)
def test_only_exact_persisted_observations_are_published(
    client, synthetic_video, tmp_path, monkeypatch, staged_mode, expected_warning
):
    store = EmbeddingStore(tmp_path / f"embeddings-{staged_mode}")
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)
    _patch_pipeline(monkeypatch, staged_mode=staged_mode)

    case = _create_case(client, f"FILTER-{staged_mode}")
    video = _upload_video(client, case["id"], synthetic_video)
    response = _create_run(client, case["id"], video["id"])
    assert response.status_code == 200, response.text

    run = response.json()["run"]
    status = _run_status(run["cv_run_id"])
    assert status["status"] == "completed_with_warnings"
    assert expected_warning in json.loads(status["warnings_json"])
    assert _observation_count(run["cv_run_id"]) == 1
    assert store.status()["record_count"] == 0
