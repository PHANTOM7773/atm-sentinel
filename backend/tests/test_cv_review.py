import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.config import SCHEMA_VERSION, absolute_from_data
from app.cv.crop import safe_segment, save_crop
from app.db import get_db
from app.schemas import CvHumanReviewDecision, CvReviewUpsertRequest, CvRunSummary
from app.services import cv_integration as integration


def _fake_analysis() -> dict[str, Any]:
    return {
        "source": "synthetic",
        "source_id": "video-review",
        "fps": 10.0,
        "frame_count": 60,
        "analyzed_frame_count": 1,
        "analysis_run_id": "analysis-review",
        "frames": [
            {
                "frame_number": 4,
                "timestamp": 1.5,
                "faces": [
                    {
                        "sample_id": "sample-review-1",
                        "frame_number": 4,
                        "timestamp": 1.5,
                        "bbox": [10.0, 20.0, 30.0, 40.0],
                        "detector_confidence": 0.91,
                        "track_id": 2,
                        "quality": {"quality_score": 82.0},
                        "pose": {"frontal_score": 0.74},
                        "flags": {},
                        "crop_state": "saved",
                    }
                ],
                "persons": [],
                "counts": {"faces": 1, "persons": 0},
                "total_counts": {"faces": 1, "persons": 0},
                "truncated": False,
                "truncation": {},
                "duration_ms": 1.0,
            }
        ],
        "summary": {"face_detections": 1},
        "truncation": {},
        "runtime": {},
    }


class _FakeAnalysis:
    def to_dict(self) -> dict[str, Any]:
        return _fake_analysis()


class _FakePipeline:
    runtime: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def analyze_video(self, **kwargs: Any) -> _FakeAnalysis:
        return _FakeAnalysis()


def _setup(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any, suffix: str) -> dict[str, Any]:
    crop_root = tmp_path / f"crops-{suffix}"
    crop_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(integration, "CV_CROP_DIR", crop_root)
    monkeypatch.setattr(integration, "CVPipeline", _FakePipeline)

    case = client.post(
        "/api/cases",
        json={"case_number": f"REVIEW-{suffix}", "title": f"Review case {suffix}", "location": "Test"},
    ).json()
    other_case = client.post(
        "/api/cases",
        json={"case_number": f"REVIEW-OTHER-{suffix}", "title": f"Other case {suffix}", "location": "Test"},
    ).json()
    with synthetic_video.open("rb") as handle:
        video = client.post(
            "/api/videos/upload",
            params={"case_id": case["id"]},
            files={"file": ("review_test.mp4", handle, "video/mp4")},
        ).json()
    response = client.post(
        "/api/cv/runs",
        json={"case_id": case["id"], "video_id": video["id"], "max_frames": 1, "frame_stride": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    observations = client.get(
        f"/api/cv/runs/{body['run']['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    ).json()
    assert observations["total"] == 1
    return {
        "case": case,
        "other_case": other_case,
        "video": video,
        "run": body["run"],
        "observation": observations["items"][0],
        "crop_root": crop_root,
    }


def _save_real_crop(monkeypatch: Any, path: Any) -> None:
    save_crop(np.full((12, 12, 3), 100, dtype=np.uint8), Path(path))


def _review_url(ctx: dict[str, Any]) -> str:
    return (
        f"/api/cv/runs/{ctx['run']['cv_run_id']}"
        f"/observations/{ctx['observation']['observation_id']}/review"
    )


def _crop_url(ctx: dict[str, Any]) -> str:
    return (
        f"/api/cv/runs/{ctx['run']['cv_run_id']}"
        f"/observations/{ctx['observation']['observation_id']}/crop"
    )


def _listed_crop(client: Any, ctx: dict[str, Any], observation_id: str | None = None) -> dict[str, Any]:
    response = client.get(
        f"/api/cv/runs/{ctx['run']['cv_run_id']}/observations",
        params={"case_id": ctx["case"]["id"]},
    )
    assert response.status_code == 200, response.text
    wanted = observation_id or ctx["observation"]["observation_id"]
    item = next(item for item in response.json()["items"] if item["observation_id"] == wanted)
    return item["crop"]


def _review_payload(ctx: dict[str, Any], decision: str = "relevant", note: str | None = None) -> dict[str, Any]:
    return {
        "case_id": ctx["case"]["id"],
        "cv_run_id": ctx["run"]["cv_run_id"],
        "decision": decision,
        "reviewer_note": note,
    }


def _crop_path(ctx: dict[str, Any], crop_root: Any = None) -> Any:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    return (
        (crop_root or ctx["crop_root"])
        / safe_segment(ctx["case"]["id"])
        / safe_segment(row["video_id"])
        / f"frame_{int(row['original_frame_number']):06d}"
        / f"{safe_segment(row['sample_id'])}.jpg"
    )


def test_review_create_retrieve_update_without_duplicate(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "CRUD")
    url = _review_url(ctx)
    case_id = ctx["case"]["id"]

    created = client.post(url, params={"case_id": case_id}, json=_review_payload(ctx, note="   "))
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["target_type"] == "face_observation"
    assert review["target_id"] == ctx["observation"]["observation_id"]
    assert review["reviewer_note"] is None
    assert review["created_at"] and review["updated_at"]
    assert CvHumanReviewDecision.model_validate(review).decision == "relevant"

    fetched = client.get(url, params={"case_id": case_id})
    assert fetched.status_code == 200
    assert fetched.json() == review

    updated = client.post(
        url,
        params={"case_id": case_id},
        json=_review_payload(ctx, decision="irrelevant", note="  reviewed note  "),
    )
    assert updated.status_code == 200, updated.text
    changed = updated.json()
    assert changed["decision_id"] == review["decision_id"]
    assert changed["decision"] == "irrelevant"
    assert changed["reviewer_note"] == "reviewed note"
    assert changed["created_at"] == review["created_at"]
    assert changed["updated_at"] >= review["updated_at"]

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM cv_review_decisions WHERE case_id=? AND cv_run_id=?",
            (case_id, ctx["run"]["cv_run_id"]),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["created_at"] == review["created_at"]
    assert rows[0]["decision"] == "irrelevant"


def test_review_list_pagination(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "PAGE")
    case_id = ctx["case"]["id"]
    run_id = ctx["run"]["cv_run_id"]
    base_id = ctx["observation"]["observation_id"]

    with get_db() as conn:
        for index in (1, 2):
            conn.execute(
                """
                INSERT INTO cv_observations(
                    id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                    original_frame_number, original_video_timestamp_seconds, bbox_json,
                    detector_confidence, crop_id, crop_available, crop_status,
                    crop_retrieval_state, verification_status, created_at
                )
                SELECT ?, cv_run_id, case_id, video_id, ?, source_video_sha256,
                    original_frame_number, original_video_timestamp_seconds, bbox_json,
                    detector_confidence, NULL, 0, 'not_generated', 'not_supported',
                    'candidate_only', created_at
                FROM cv_observations WHERE id=?
                """,
                (f"{base_id}-extra-{index}", f"sample-extra-{index}", base_id),
            )

    for index, observation_id in enumerate([base_id, f"{base_id}-extra-1", f"{base_id}-extra-2"]):
        dto, created = integration.upsert_review(
            case_id,
            run_id,
            observation_id,
            CvReviewUpsertRequest(case_id=case_id, cv_run_id=run_id, decision="needs_review"),
        )
        assert created
        assert dto["target_id"] == observation_id
        assert index >= 0

    first = client.get(
        f"/api/cv/runs/{run_id}/reviews",
        params={"case_id": case_id, "limit": 1, "offset": 0},
    )
    second = client.get(
        f"/api/cv/runs/{run_id}/reviews",
        params={"case_id": case_id, "limit": 1, "offset": 1},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["total"] == 3
    assert first.json()["limit"] == 1
    assert first.json()["offset"] == 0
    assert len(first.json()["items"]) == 1
    assert second.json()["total"] == 3
    assert len(second.json()["items"]) == 1
    assert first.json()["items"][0]["decision_id"] != second.json()["items"][0]["decision_id"]


def test_review_scope_and_payload_mismatches(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "SCOPE")
    url = _review_url(ctx)
    case_id = ctx["case"]["id"]
    run_id = ctx["run"]["cv_run_id"]

    cross_case = client.post(
        url,
        params={"case_id": ctx["other_case"]["id"]},
        json={
            "case_id": ctx["other_case"]["id"],
            "cv_run_id": run_id,
            "decision": "relevant",
        },
    )
    assert cross_case.status_code == 404
    cross_get = client.get(url, params={"case_id": ctx["other_case"]["id"]})
    assert cross_get.status_code == 404

    body_mismatch = client.post(
        url,
        params={"case_id": case_id},
        json={**_review_payload(ctx), "case_id": ctx["other_case"]["id"]},
    )
    assert body_mismatch.status_code == 422
    run_mismatch = client.post(
        url,
        params={"case_id": case_id},
        json={**_review_payload(ctx), "cv_run_id": "missing-run"},
    )
    assert run_mismatch.status_code == 422

    missing_observation = client.post(
        f"/api/cv/runs/{run_id}/observations/missing-observation/review",
        params={"case_id": case_id},
        json=_review_payload(ctx),
    )
    assert missing_observation.status_code == 404

    second_run = client.post(
        "/api/cv/runs",
        json={"case_id": case_id, "video_id": ctx["video"]["id"], "max_frames": 1, "frame_stride": 1},
    )
    assert second_run.status_code == 200
    wrong_run = client.post(
        f"/api/cv/runs/{second_run.json()['run']['cv_run_id']}/observations/{ctx['observation']['observation_id']}/review",
        params={"case_id": case_id},
        json=_review_payload(ctx),
    )
    assert wrong_run.status_code == 404

    wrong_target = client.post(
        url,
        params={"case_id": case_id},
        json={**_review_payload(ctx), "target_type": "candidate"},
    )
    assert wrong_target.status_code == 422

    with pytest.raises(integration.IntegrationError) as exc:
        integration.upsert_review(
            case_id,
            run_id,
            ctx["observation"]["observation_id"],
            CvReviewUpsertRequest(
                case_id=case_id,
                cv_run_id=run_id,
                target_type="face_observation",
                decision="relevant",
            ).model_copy(update={"target_type": "candidate"}),
        )
    assert exc.value.status_code == 422


def test_review_audit_events_contain_ids_only(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "AUDIT")
    url = _review_url(ctx)
    params = {"case_id": ctx["case"]["id"]}
    assert client.post(url, params=params, json=_review_payload(ctx)).status_code == 201
    assert client.post(
        url,
        params=params,
        json=_review_payload(ctx, decision="needs_review", note="private note text"),
    ).status_code == 200

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT action, detail_json FROM audit_events
            WHERE case_id=? AND action LIKE 'cv_review_decision_%'
            ORDER BY id
            """,
            (ctx["case"]["id"],),
        ).fetchall()
    assert [row["action"] for row in rows] == [
        "cv_review_decision_created",
        "cv_review_decision_updated",
    ]
    expected_keys = {
        "decision_id",
        "case_id",
        "cv_run_id",
        "target_type",
        "target_id",
        "decision",
    }
    for row in rows:
        detail = json.loads(row["detail_json"])
        assert set(detail) == expected_keys
        assert detail["target_type"] == "face_observation"
        assert "private note text" not in row["detail_json"]


def test_crop_retrieval_success(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "CROP")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id, crop_available, crop_status, crop_retrieval_state FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    assert row["crop_available"] == 1
    assert row["crop_status"] == "available"
    assert row["crop_retrieval_state"] == "retrievable"

    path = _crop_path(ctx)
    _save_real_crop(monkeypatch, path)
    assert path.exists()

    observations = client.get(
        f"/api/cv/runs/{ctx['run']['cv_run_id']}/observations",
        params={"case_id": ctx["case"]["id"]},
    )
    assert observations.status_code == 200, observations.text
    assert observations.json()["items"][0]["crop"] == {
        "crop_id": row["crop_id"],
        "available": True,
        "status": "available",
        "retrieval_state": "retrievable",
    }

    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.content.startswith(b"\xff\xd8\xff")


def test_crop_plain_writer_preserves_retrieval_and_security(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "PLAIN")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()

    path = _crop_path(ctx)
    save_crop(np.full((12, 12, 3), 110, dtype=np.uint8), path)
    assert path.read_bytes().startswith(b"\xff\xd8\xff")

    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"\xff\xd8\xff")

    traversal = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": "../escape"},
    )
    assert traversal.status_code == 422

    outside = tmp_path / "outside.jpg"
    save_crop(np.full((12, 12, 3), 120, dtype=np.uint8), outside)
    path.unlink()
    path.symlink_to(outside)
    escaped = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert escaped.status_code == 404
    assert str(tmp_path) not in escaped.text
    assert str(ctx["crop_root"]) not in escaped.text


def test_crop_metadata_for_observation_without_crop(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "NOCROP")
    base_id = ctx["observation"]["observation_id"]
    extra_id = f"{base_id}-nocrop"
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO cv_observations(
                id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds, bbox_json,
                detector_confidence, crop_id, crop_available, crop_status,
                crop_retrieval_state, verification_status, created_at
            )
            SELECT ?, cv_run_id, case_id, video_id, ?, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds, bbox_json,
                detector_confidence, NULL, 0, 'not_generated', 'not_supported',
                'candidate_only', created_at
            FROM cv_observations WHERE id=?
            """,
            (extra_id, "sample-nocrop", base_id),
        )

    response = client.get(
        f"/api/cv/runs/{ctx['run']['cv_run_id']}/observations",
        params={"case_id": ctx["case"]["id"]},
    )
    assert response.status_code == 200, response.text
    item = next(item for item in response.json()["items"] if item["observation_id"] == extra_id)
    assert item["crop"] == {
        "crop_id": None,
        "available": False,
        "status": "not_generated",
        "retrieval_state": "not_supported",
    }


@pytest.mark.parametrize("bad_crop_id", ["../escape", "bad/id", "bad\\id", "bad:id"])
def test_crop_invalid_identifier_is_422(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
    bad_crop_id: str,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "BADID")
    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": bad_crop_id},
    )
    assert response.status_code == 422


def test_crop_cross_case_access_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "XCASE")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    _save_real_crop(monkeypatch, _crop_path(ctx))

    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["other_case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404
    assert str(tmp_path) not in response.text
    assert str(ctx["crop_root"]) not in response.text


def test_crop_wrong_run_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "WRONGRUN")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    second = client.post(
        "/api/cv/runs",
        json={
            "case_id": ctx["case"]["id"],
            "video_id": ctx["video"]["id"],
            "max_frames": 1,
            "frame_stride": 1,
        },
    ).json()
    response = client.get(
        f"/api/cv/runs/{second['run']['cv_run_id']}"
        f"/observations/{ctx['observation']['observation_id']}/crop",
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404


def test_crop_wrong_observation_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "WRONGOBS")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    response = client.get(
        f"/api/cv/runs/{ctx['run']['cv_run_id']}/observations/missing-observation/crop",
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404


def test_crop_non_jpeg_content_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "NOTJPEG")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    path = _crop_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a jpeg")
    assert _listed_crop(client, ctx) == {
        "crop_id": row["crop_id"],
        "available": True,
        "status": "available",
        "retrieval_state": "expired",
    }
    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404


def test_crop_error_does_not_leak_filesystem_paths(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "NOLEAK")
    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": "missing-crop"},
    )
    assert response.status_code == 404
    assert str(tmp_path) not in response.text
    assert str(ctx["crop_root"]) not in response.text


def test_crop_symlink_escape_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "SYMLINK")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    outside = tmp_path / "outside.jpg"
    _save_real_crop(monkeypatch, outside)
    expected = _crop_path(ctx)
    expected.parent.mkdir(parents=True, exist_ok=True)
    expected.symlink_to(outside)

    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404


def test_crop_missing_is_404(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "MISSING")
    with get_db() as conn:
        row = conn.execute(
            "SELECT crop_id FROM cv_observations WHERE id=?",
            (ctx["observation"]["observation_id"],),
        ).fetchone()
    assert _listed_crop(client, ctx) == {
        "crop_id": row["crop_id"],
        "available": True,
        "status": "available",
        "retrieval_state": "expired",
    }
    response = client.get(
        _crop_url(ctx),
        params={"case_id": ctx["case"]["id"], "crop_id": row["crop_id"]},
    )
    assert response.status_code == 404
    assert str(tmp_path) not in response.text
    assert str(ctx["crop_root"]) not in response.text


def test_review_insert_rolls_back_when_audit_fails(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "ROLLBACK")
    case_id = ctx["case"]["id"]
    run_id = ctx["run"]["cv_run_id"]
    observation_id = ctx["observation"]["observation_id"]

    def fail_audit(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(integration, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        integration.upsert_review(
            case_id,
            run_id,
            observation_id,
            CvReviewUpsertRequest(case_id=case_id, cv_run_id=run_id, decision="relevant"),
        )

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_review_decisions").fetchone()[0]
    assert count == 0


def _field_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        names = {str(key).lower() for key in value}
        for item in value.values():
            names.update(_field_names(item))
        return names
    if isinstance(value, (list, tuple)):
        names: set[str] = set()
        for item in value:
            names.update(_field_names(item))
        return names
    return set()


def test_run_and_review_schema_expose_no_raw_embedding_or_identity(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "SCHEMA")
    assert SCHEMA_VERSION == 5
    forbidden = {
        "embedding",
        "embedding_vector",
        "face_embedding",
        "face_encoding",
        "identity",
        "identity_vector",
    }
    with get_db() as conn:
        for table in ("cv_runs", "cv_observations", "cv_review_decisions"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert not columns & forbidden
            assert "crop_path" not in columns

    run = integration.get_run_summary(ctx["run"]["cv_run_id"], ctx["case"]["id"])
    validated = CvRunSummary.model_validate(run)
    assert validated.window is not None
    assert validated.window.mode == "full_video"
    assert not _field_names(run) & forbidden
    assert not {name.lower() for name in CvRunSummary.model_fields} & forbidden
    assert not {name.lower() for name in CvHumanReviewDecision.model_fields} & forbidden


def _create_run_in_case(client: Any, synthetic_video: Any, case_id: str, suffix: str) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        video = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": (f"export_{suffix}.mp4", handle, "video/mp4")},
        ).json()
    response = client.post(
        "/api/cv/runs",
        json={"case_id": case_id, "video_id": video["id"], "max_frames": 1, "frame_stride": 1},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    observations = client.get(
        f"/api/cv/runs/{body['run']['cv_run_id']}/observations",
        params={"case_id": case_id},
    ).json()
    assert observations["total"] == 1
    return {
        "case_id": case_id,
        "video": video,
        "run": body["run"],
        "observation": observations["items"][0],
    }


def _manual_frame(client: Any, case_id: str, video_id: str, timestamp: float) -> dict[str, Any]:
    if not client.get(f"/api/cases/{case_id}/transactions").json():
        created = client.post(
            f"/api/cases/{case_id}/transactions",
            json={
                "reference": f"EXPORT-TX-{case_id[:8]}",
                "transaction_ts": "2026-01-15T09:00:05+00:00",
                "cctv_ts": "2026-01-15T09:00:35+00:00",
            },
        )
        assert created.status_code == 201, created.text
    response = client.post(
        "/api/frames/manual",
        json={"case_id": case_id, "video_id": video_id, "timestamp": timestamp, "note": "Export anchor"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _review_observation(client: Any, case_id: str, run_id: str, observation_id: str, decision: str, note: str) -> dict[str, Any]:
    response = client.post(
        f"/api/cv/runs/{run_id}/observations/{observation_id}/review",
        params={"case_id": case_id},
        json={"case_id": case_id, "cv_run_id": run_id, "decision": decision, "reviewer_note": note},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _model_digest(run: dict[str, Any]) -> str:
    return str(run["model_provenance"][0]["model_sha256"])


def test_cv_observation_export_preserves_provenance_review_and_limits(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "EXPOBS")
    case_id = ctx["case"]["id"]
    frame = _manual_frame(client, case_id, ctx["video"]["id"], 1.0)
    review = _review_observation(
        client,
        case_id,
        ctx["run"]["cv_run_id"],
        ctx["observation"]["observation_id"],
        "relevant",
        "Investigator review note",
    )
    cv_item = {
        "kind": "observation",
        "cv_run_id": ctx["run"]["cv_run_id"],
        "observation_id": ctx["observation"]["observation_id"],
        "expected_review_updated_at": review["updated_at"],
        "expected_model_sha256": _model_digest(ctx["run"]),
    }
    response = client.post(
        "/api/exports",
        json={"case_id": case_id, "frame_ids": [frame["id"]], "cv_items": [cv_item]},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["cv_selection_count"] == 1
    assert result["cv_observation_count"] == 1
    assert result["cv_candidate_count"] == 0
    manifest_path = absolute_from_data(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text())
    selection = manifest["cv_selections"][0]
    assert selection["kind"] == "observation"
    assert selection["cv_run_id"] == ctx["run"]["cv_run_id"]
    assert selection["observation_id"] == ctx["observation"]["observation_id"]
    assert selection["source_video_id"] == ctx["video"]["id"]
    assert selection["source_video_sha256"] == ctx["video"]["sha256"]
    assert selection["model_provenance"][0]["model_sha256"] == _model_digest(ctx["run"])
    assert selection["human_review"]["decision"] == "relevant"
    assert selection["human_review"]["reviewer_note"] == "Investigator review note"
    assert "do not identify the ATM operator" in manifest["cv_association_limitation"]
    assert manifest["report_hash"] == result["report_hash"]
    cv_json = json.dumps(selection).lower()
    for forbidden in ("embedding_vector", "face_embedding", "face_encoding", "stored_path", "image_path", "crop_path"):
        assert forbidden not in cv_json
    pdf = absolute_from_data(result["pdf_path"])
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"


def test_cv_candidate_export_validates_query_context_and_marks_score_unverified(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "EXPCAND")
    case_id = ctx["case"]["id"]
    candidate = _create_run_in_case(client, synthetic_video, case_id, "EXPCAND2")
    frame = _manual_frame(client, case_id, ctx["video"]["id"], 1.0)
    review = _review_observation(
        client,
        case_id,
        candidate["run"]["cv_run_id"],
        candidate["observation"]["observation_id"],
        "relevant",
        "Candidate accepted",
    )
    cv_item = {
        "kind": "candidate",
        "cv_run_id": candidate["run"]["cv_run_id"],
        "observation_id": candidate["observation"]["observation_id"],
        "query_cv_run_id": ctx["run"]["cv_run_id"],
        "query_observation_id": ctx["observation"]["observation_id"],
        "candidate_id": "candidate-trace-1",
        "expected_review_updated_at": review["updated_at"],
        "selection_context": {
            "rank": 1,
            "similarity_score": 0.8125,
            "score_meaning": "Ranking only, not identity confidence",
        },
    }
    response = client.post(
        "/api/exports",
        json={"case_id": case_id, "frame_ids": [frame["id"]], "cv_items": [cv_item]},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    manifest = json.loads(absolute_from_data(result["manifest_path"]).read_text())
    selection = manifest["cv_selections"][0]
    assert result["cv_candidate_count"] == 1
    assert selection["kind"] == "candidate"
    assert selection["query"]["query_cv_run_id"] == ctx["run"]["cv_run_id"]
    assert selection["query"]["query_observation_id"] == ctx["observation"]["observation_id"]
    assert selection["query"]["query_video_id"] == ctx["video"]["id"]
    assert selection["selection_context"]["status"] == "unverified_client_selection_context"
    assert selection["selection_context"]["similarity_score"] == 0.8125
    assert selection["human_review"]["reviewer_note"] == "Candidate accepted"


def test_cv_export_rejects_cross_case_ineligible_stale_and_duplicate_selections(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
    tmp_path: Any,
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, "EXPSEC")
    case_id = ctx["case"]["id"]
    frame = _manual_frame(client, case_id, ctx["video"]["id"], 1.0)
    review = _review_observation(
        client,
        case_id,
        ctx["run"]["cv_run_id"],
        ctx["observation"]["observation_id"],
        "relevant",
        "Accepted",
    )
    valid_item = {
        "kind": "observation",
        "cv_run_id": ctx["run"]["cv_run_id"],
        "observation_id": ctx["observation"]["observation_id"],
    }

    def post_cv(cv_items: list[dict[str, Any]]) -> Any:
        return client.post(
            "/api/exports",
            json={"case_id": case_id, "frame_ids": [frame["id"]], "cv_items": cv_items},
        )

    cross_case = _create_run_in_case(client, synthetic_video, ctx["other_case"]["id"], "EXPSEC-OTHER")
    cross_item = {
        "kind": "observation",
        "cv_run_id": cross_case["run"]["cv_run_id"],
        "observation_id": cross_case["observation"]["observation_id"],
    }
    assert post_cv([cross_item]).status_code == 422

    path_item = {"kind": "observation", "cv_run_id": "../run", "observation_id": ctx["observation"]["observation_id"]}
    assert post_cv([path_item]).status_code == 422

    assert post_cv([valid_item, valid_item]).status_code == 422

    stale_item = dict(valid_item)
    stale_item["expected_review_updated_at"] = "2000-01-01T00:00:00+00:00"
    assert post_cv([stale_item]).status_code == 422

    assert review["decision"] == "relevant"
    with get_db() as conn:
        conn.execute(
            "UPDATE cv_runs SET status='running' WHERE id=?",
            (ctx["run"]["cv_run_id"],),
        )
    assert post_cv([valid_item]).status_code == 422

    candidate = _create_run_in_case(client, synthetic_video, case_id, "EXPSEC-CAND")
    candidate_item = {
        "kind": "candidate",
        "cv_run_id": candidate["run"]["cv_run_id"],
        "observation_id": candidate["observation"]["observation_id"],
        "query_cv_run_id": ctx["run"]["cv_run_id"],
        "query_observation_id": ctx["observation"]["observation_id"],
        "candidate_id": "candidate-trace-2",
        "selection_context": {"rank": 2, "similarity_score": 0.4},
    }
    assert post_cv([candidate_item]).status_code == 422
