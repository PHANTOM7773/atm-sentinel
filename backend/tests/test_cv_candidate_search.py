import json
from typing import Any

import numpy as np
import pytest

from app.cv.embeddings import EmbeddingStore, build_v4_embedding_record
from app.cv.errors import CVError
from app.cv.models import MODEL_SPECS
from app.db import get_db, utc_now
from app.routers import cv as cv_router
from app.services import cv_integration as integration

DIGEST = "a" * 64
MODEL_DIGEST = MODEL_SPECS["sface"].sha256
OTHER_MODEL_DIGEST = "c" * 64
VECTOR_A = 0.31415926
VECTOR_B = 0.27182818
VECTOR_C = 0.16180339
RUNTIME = {"backend": "cpu", "target": "cpu"}


def _upload_video(client: Any, synthetic_video: Any, case_id: str) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": ("candidate_test.mp4", handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _analysis_run_id(sample_id: str) -> str:
    return f"analysis-{sample_id}"


def _insert_observation(
    client: Any,
    case_id: str,
    video: dict[str, Any],
    sample_id: str,
    *,
    frame: int = 4,
    timestamp: float = 1.5,
    crop: bool = False,
    status: str = "completed",
) -> tuple[str, str]:
    run_id = f"run-{sample_id}"
    observation_id = f"obs-{sample_id}"
    now = utc_now()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO cv_runs(
                id, case_id, video_id, source_video_sha256, status, window_mode,
                analysis_run_id, disclaimer, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                case_id,
                video["id"],
                video["sha256"],
                status,
                "full_video",
                _analysis_run_id(sample_id),
                "candidate only",
                now,
            ),
        )
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
                observation_id,
                run_id,
                case_id,
                video["id"],
                sample_id,
                video["sha256"],
                frame,
                timestamp,
                None,
                None,
                "[]",
                0.9,
                1,
                json.dumps(
                    {
                        "quality_score": 88.0,
                        "sharpness": 70.0,
                        "brightness": 120.0,
                        "contrast": 40.0,
                        "face_size_px": 60,
                    }
                ),
                json.dumps({"frontal_score": 0.8}),
                json.dumps({"low_sharpness": False}),
                f"crop-{sample_id}" if crop else None,
                1 if crop else 0,
                "available" if crop else "not_generated",
                "retrievable" if crop else "not_supported",
                "candidate_only",
                now,
            ),
        )
    return run_id, observation_id


def _publish_v4(
    store: EmbeddingStore,
    *,
    observation_id: str,
    cv_run_id: str,
    sample_id: str,
    case_id: str,
    video_id: str,
    vector: list[float],
    analysis_run_id: str | None = None,
    model_sha256: str = MODEL_DIGEST,
    model_key: str = "sface",
    provenance_status: str = "known",
    **field_overrides: Any,
) -> None:
    metadata = {
        "model_filename": "sface.onnx",
        "model_source_url": "local://sface",
        "backend": "cpu",
        "target": "cpu",
        "runtime_state": "observed",
        "runtime": dict(RUNTIME),
        "opencv_version": "4.0.0",
        "pipeline_version": "cv-stage4",
        "frame_number": 4,
        "timestamp": 1.5,
    }
    values = {
        "embedding_id": f"emb-{observation_id}",
        "observation_id": observation_id,
        "cv_run_id": cv_run_id,
        "analysis_run_id": analysis_run_id or _analysis_run_id(sample_id),
        "case_id": case_id,
        "video_id": video_id,
        "source_id": video_id,
        "sample_id": sample_id,
        "vector": vector,
        "model_key": model_key,
        "provenance_status": provenance_status,
        "model_sha256": model_sha256,
        "generated_at": "2026-01-15T09:00:00+00:00",
        "metadata": metadata,
    }
    values.update(field_overrides)
    store.publish_staged_records([build_v4_embedding_record(**values)])


def _add_legacy(
    store: EmbeddingStore,
    *,
    observation_id: str,
    cv_run_id: str,
    sample_id: str,
    case_id: str,
    video_id: str,
    vector: list[float],
) -> None:
    store.add(
        sample_id,
        case_id,
        np.array(vector, dtype=np.float32),
        metadata={
            "observation_id": observation_id,
            "cv_run_id": cv_run_id,
            "analysis_run_id": _analysis_run_id(sample_id),
            "source_id": video_id,
            "frame_number": 4,
            "timestamp": 1.5,
            "model_key": "sface",
            "model_filename": "sface.onnx",
            "model_source_url": "local://sface",
            "model_sha256": MODEL_DIGEST,
            "backend": "cpu",
            "target": "cpu",
            "runtime_state": "observed",
            "runtime": dict(RUNTIME),
            "opencv_version": "4.0.0",
            "pipeline_version": "cv-stage4",
            "embedding_schema_version": 3,
            "generated_at": "2026-01-15T09:00:00+00:00",
            "provenance_status": "known",
        },
    )


def _remove_v4(store: EmbeddingStore, observation_id: str) -> None:
    indexes = [
        index
        for index, record in enumerate(store.records)
        if str(record.get("observation_id") or "") == observation_id
    ]
    if not indexes:
        return
    removed = set(indexes)
    store.records = [record for index, record in enumerate(store.records) if index not in removed]
    store.vectors = np.delete(store.vectors, indexes, axis=0)
    store._save()


def _replace_v4(store: EmbeddingStore, observation_id: str, **overrides: Any) -> None:
    record = next(
        item
        for item in store.records
        if str(item.get("observation_id") or "") == observation_id
    )
    _remove_v4(store, observation_id)
    _publish_v4(
        store,
        observation_id=observation_id,
        cv_run_id=str(overrides.pop("cv_run_id", record["cv_run_id"])),
        sample_id=str(record["sample_id"]),
        case_id=str(overrides.pop("case_id", record["case_id"])),
        video_id=str(overrides.pop("video_id", record["video_id"])),
        vector=list(overrides.pop("vector", [VECTOR_A, VECTOR_C, VECTOR_B])),
        **overrides,
    )


def _setup(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any, suffix: str = "a") -> dict[str, Any]:
    store = EmbeddingStore(tmp_path / f"embeddings-{suffix}")
    case = client.post(
        "/api/cases",
        json={"case_number": f"SEARCH-{suffix}", "title": "Search case", "location": "ATM-1"},
    ).json()
    other_case = client.post(
        "/api/cases",
        json={"case_number": f"SEARCH-OTHER-{suffix}", "title": "Other case", "location": "ATM-2"},
    ).json()
    query_video = _upload_video(client, synthetic_video, case["id"])
    candidate_video_a = _upload_video(client, synthetic_video, case["id"])
    candidate_video_b = _upload_video(client, synthetic_video, case["id"])
    other_video = _upload_video(client, synthetic_video, other_case["id"])

    query_run, query_observation = _insert_observation(client, case["id"], query_video, f"sample-query-{suffix}")
    _, same_video_observation = _insert_observation(
        client, case["id"], query_video, f"sample-same-video-{suffix}", frame=8, timestamp=2.5
    )
    candidate_run_a, candidate_observation_a = _insert_observation(
        client, case["id"], candidate_video_a, f"sample-candidate-a-{suffix}", frame=20, timestamp=4.0, crop=True
    )
    _, candidate_observation_b = _insert_observation(
        client, case["id"], candidate_video_b, f"sample-candidate-b-{suffix}", frame=30, timestamp=6.0
    )
    _, cross_observation = _insert_observation(
        client, other_case["id"], other_video, f"sample-cross-{suffix}", frame=12, timestamp=3.0
    )

    _publish_v4(
        store,
        observation_id=query_observation,
        cv_run_id=query_run,
        sample_id=f"sample-query-{suffix}",
        case_id=case["id"],
        video_id=query_video["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    _publish_v4(
        store,
        observation_id=same_video_observation,
        cv_run_id=f"run-sample-same-video-{suffix}",
        sample_id=f"sample-same-video-{suffix}",
        case_id=case["id"],
        video_id=query_video["id"],
        vector=[VECTOR_B, VECTOR_A, VECTOR_C],
    )
    _publish_v4(
        store,
        observation_id=candidate_observation_a,
        cv_run_id=candidate_run_a,
        sample_id=f"sample-candidate-a-{suffix}",
        case_id=case["id"],
        video_id=candidate_video_a["id"],
        vector=[VECTOR_A, VECTOR_C, VECTOR_B],
    )
    _publish_v4(
        store,
        observation_id=candidate_observation_b,
        cv_run_id=f"run-sample-candidate-b-{suffix}",
        sample_id=f"sample-candidate-b-{suffix}",
        case_id=case["id"],
        video_id=candidate_video_b["id"],
        vector=[VECTOR_C, VECTOR_B, VECTOR_A],
    )
    _publish_v4(
        store,
        observation_id=cross_observation,
        cv_run_id=f"run-sample-cross-{suffix}",
        sample_id=f"sample-cross-{suffix}",
        case_id=other_case["id"],
        video_id=other_video["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    monkeypatch.setattr(integration, "EmbeddingStore", lambda: store)

    return {
        "store": store,
        "case": case,
        "other_case": other_case,
        "query_video": query_video,
        "candidate_video_a": candidate_video_a,
        "candidate_video_b": candidate_video_b,
        "other_video": other_video,
        "query_run": query_run,
        "query_observation": query_observation,
        "same_video_observation": same_video_observation,
        "candidate_run_a": candidate_run_a,
        "candidate_observation_a": candidate_observation_a,
        "candidate_observation_b": candidate_observation_b,
        "cross_observation": cross_observation,
    }


def _payload(ctx: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = {
        "case_id": ctx["case"]["id"],
        "query_cv_run_id": ctx["query_run"],
        "query_observation_id": ctx["query_observation"],
        "top_k": 5,
    }
    payload.update(overrides)
    return payload


def _search(client: Any, ctx: dict[str, Any], **overrides: Any):
    return client.post("/api/cv/candidates/search", json=_payload(ctx, **overrides))


def _observation_ids(response: Any) -> set[str]:
    return {item["candidate_observation_id"] for item in response.json()["items"]}


def test_candidate_search_returns_bounded_case_scoped_candidates(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path)
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert body["limit"] == 5
    assert [item["rank"] for item in body["items"]] == [1, 2]
    assert _observation_ids(response) == {ctx["candidate_observation_a"], ctx["candidate_observation_b"]}
    assert ctx["query_observation"] not in _observation_ids(response)
    assert ctx["same_video_observation"] not in _observation_ids(response)
    assert ctx["cross_observation"] not in _observation_ids(response)
    assert all(item["case_id"] == ctx["case"]["id"] for item in body["items"])
    assert all(item["query_cv_run_id"] == ctx["query_run"] for item in body["items"])
    assert all(item["verification_status"] == "candidate_only" for item in body["items"])
    assert all(item["requires_human_verification"] is True for item in body["items"])
    assert all(-1 <= item["similarity_score"] <= 1 for item in body["items"])
    assert "not identity verification" in body["score_meaning"]
    assert "Never identity confirmation" in body["disclaimer"]
    assert "index_path" not in body["index"]
    assert "vectors_path" not in body["index"]

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT action, detail_json FROM audit_events
            WHERE case_id=? AND action='cv_candidate_search'
            """,
            (ctx["case"]["id"],),
        ).fetchall()
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail_json"])
    assert detail["result_count"] == 2
    assert str(tmp_path) not in rows[0]["detail_json"]


def test_candidate_result_contract_has_provenance_and_no_raw_data(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO cv_review_decisions(
                decision_id, case_id, cv_run_id, target_type, target_id,
                decision, reviewer_note, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "review-candidate-a",
                ctx["case"]["id"],
                ctx["candidate_run_a"],
                "face_observation",
                ctx["candidate_observation_a"],
                "relevant",
                "secret note",
                utc_now(),
                utc_now(),
            ),
        )
    response = _search(client, ctx, top_k=1)
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["candidate_observation_id"] == ctx["candidate_observation_a"]
    assert item["human_review_status"] == "relevant"
    assert item["candidate_quality"]["quality_score"] == 88.0
    assert item["candidate_review_flags"]["low_sharpness"] is False
    assert item["candidate_crop"]["retrieval_state"] == "expired"
    assert item["model_provenance"][0]["model_key"] == "sface"
    assert item["candidate_video_provenance"]["source_video_id"] == ctx["candidate_video_a"]["id"]
    text = response.text
    assert "secret note" not in text
    assert str(VECTOR_A) not in text
    assert str(VECTOR_B) not in text
    assert str(tmp_path) not in text
    assert "embedding" not in json.dumps(item["candidate_video_provenance"]).lower()
    assert "metadata" not in item
    assert "vector" not in item


def test_query_embedding_uses_exact_observation_lookup(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path)
    store: EmbeddingStore = ctx["store"]
    real_find = store.find_by_observation_id
    calls: list[tuple[str, dict[str, Any]]] = []

    def spy_find(observation_id: str, **kwargs: Any) -> Any:
        calls.append((observation_id, kwargs))
        return real_find(observation_id, **kwargs)

    monkeypatch.setattr(store, "find_by_observation_id", spy_find)
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert calls
    assert calls[0][0] == ctx["query_observation"]
    assert calls[0][1]["case_id"] == ctx["case"]["id"]
    assert calls[0][1]["cv_run_id"] == ctx["query_run"]
    assert calls[0][1]["eligible_only"] is True


def test_legacy_query_embedding_is_rejected_without_fallback(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path)
    _remove_v4(ctx["store"], ctx["query_observation"])
    _add_legacy(
        ctx["store"],
        observation_id=ctx["query_observation"],
        cv_run_id=ctx["query_run"],
        sample_id=f"sample-query-a",
        case_id=ctx["case"]["id"],
        video_id=ctx["query_video"]["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    response = _search(client, ctx)
    assert response.status_code == 404
    assert str(tmp_path) not in response.text


def test_query_run_and_analysis_run_provenance_mismatch_are_rejected(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path)
    with get_db() as conn:
        conn.execute("UPDATE cv_runs SET status='running' WHERE id=?", (ctx["query_run"],))
    ineligible = _search(client, ctx)
    assert ineligible.status_code == 404

    with get_db() as conn:
        conn.execute("UPDATE cv_runs SET status='completed' WHERE id=?", (ctx["query_run"],))
    _replace_v4(ctx["store"], ctx["query_observation"], analysis_run_id="wrong-analysis")
    mismatched = _search(client, ctx)
    assert mismatched.status_code == 404
    assert "wrong-analysis" not in mismatched.text


@pytest.mark.parametrize(
    ("mode", "overrides"),
    [
        ("cv_run_id", {"cv_run_id": "wrong-run"}),
        ("analysis_run_id", {"analysis_run_id": "wrong-analysis"}),
    ],
)
def test_candidate_observation_and_run_provenance_mismatch_are_excluded(
    client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any, mode: str, overrides: Any
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix=mode)
    _replace_v4(ctx["store"], ctx["candidate_observation_a"], **overrides)
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_b"]}


@pytest.mark.parametrize(
    ("mode", "overrides"),
    [
        ("case", {"case_id": "other-case"}),
        ("video", {"video_id": "other-video", "source_id": "other-video"}),
    ],
)
def test_candidate_case_and_video_source_mismatches_are_excluded(
    client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any, mode: str, overrides: Any
):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix=mode)
    resolved = {
        key: ctx["other_case"]["id"] if value == "other-case" else ctx["other_video"]["id"] if value == "other-video" else value
        for key, value in overrides.items()
    }
    _replace_v4(ctx["store"], ctx["candidate_observation_a"], **resolved)
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_b"]}


def test_candidate_model_mismatch_is_excluded(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="model")
    _replace_v4(ctx["store"], ctx["candidate_observation_a"], model_sha256=OTHER_MODEL_DIGEST)
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_b"]}


def test_legacy_v3_candidates_are_excluded(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="legacy")
    _remove_v4(ctx["store"], ctx["candidate_observation_a"])
    _add_legacy(
        ctx["store"],
        observation_id=ctx["candidate_observation_a"],
        cv_run_id=ctx["candidate_run_a"],
        sample_id=f"sample-candidate-a-legacy",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_a"]["id"],
        vector=[1.0, 0.0, 0.0],
    )
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_b"]}


def test_ineligible_runs_and_unpersisted_candidates_are_excluded(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="partial")
    pending_run, pending_observation = _insert_observation(
        client,
        ctx["case"]["id"],
        ctx["candidate_video_a"],
        "sample-pending-partial",
        status="running",
    )
    _publish_v4(
        ctx["store"],
        observation_id=pending_observation,
        cv_run_id=pending_run,
        sample_id="sample-pending-partial",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_a"]["id"],
        vector=[1.0, 0.0, 0.0],
    )
    _publish_v4(
        ctx["store"],
        observation_id="obs-unpersisted-partial",
        cv_run_id="run-unpersisted-partial",
        sample_id="sample-unpersisted-partial",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_b"]["id"],
        vector=[1.0, 0.0, 0.0],
    )
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"], ctx["candidate_observation_b"]}


def test_candidate_search_validates_selected_video_subset(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="subset")
    selected = _search(
        client,
        ctx,
        scope="case_selected_videos",
        source_video_ids=[ctx["candidate_video_a"]["id"]],
    )
    assert selected.status_code == 200, selected.text
    assert [item["candidate_observation_id"] for item in selected.json()["items"]] == [ctx["candidate_observation_a"]]

    missing = _search(client, ctx, scope="case_selected_videos", source_video_ids=["video-missing"])
    assert missing.status_code == 404
    cross_case = _search(
        client,
        ctx,
        scope="case_selected_videos",
        source_video_ids=[ctx["other_video"]["id"]],
    )
    assert cross_case.status_code == 404
    path_like = _search(client, ctx, scope="case_selected_videos", source_video_ids=["bad/id"])
    assert path_like.status_code == 422


def test_invalid_observation_cannot_retrieve_another_embedding(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="invalid")
    cross_run = _search(client, ctx, query_observation_id=ctx["candidate_observation_a"])
    assert cross_run.status_code == 404
    wrong_case = _search(client, ctx, case_id=ctx["other_case"]["id"])
    assert wrong_case.status_code == 404
    wrong_run = _search(client, ctx, query_cv_run_id="run-missing")
    assert wrong_run.status_code == 404
    with get_db() as conn:
        conn.execute(
            "UPDATE cv_observations SET video_id=? WHERE id=?",
            (ctx["candidate_video_a"]["id"], ctx["query_observation"]),
        )
    moved = _search(client, ctx)
    assert moved.status_code == 404


def test_missing_and_malformed_query_embeddings_are_generic(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="missing")
    _remove_v4(ctx["store"], ctx["query_observation"])
    missing = _search(client, ctx)
    assert missing.status_code == 404
    assert str(tmp_path) not in missing.text

    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="malformed")
    store: EmbeddingStore = ctx["store"]
    record = next(
        item for item in store.records if str(item.get("observation_id") or "") == ctx["query_observation"]
    )
    malformed_vector = np.array([np.nan, 0.0, 0.0], dtype=np.float32)

    def malformed_find(observation_id: str, **kwargs: Any) -> Any:
        if observation_id == ctx["query_observation"]:
            return {
                "metadata": dict(record),
                "vector": malformed_vector,
                "generation": store.generation,
                "v4_eligible": True,
            }
        return EmbeddingStore.find_by_observation_id(store, observation_id, **kwargs)

    monkeypatch.setattr(store, "find_by_observation_id", malformed_find)
    malformed = _search(client, ctx)
    assert malformed.status_code == 422
    assert "nan" not in malformed.text.lower()
    assert str(tmp_path) not in malformed.text


def test_index_unavailable_and_corrupt_are_controlled(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="unavailable")

    def broken_store():
        raise CVError("corrupt index at /secret/path")

    monkeypatch.setattr(integration, "EmbeddingStore", broken_store)
    unavailable = _search(client, ctx)
    assert unavailable.status_code == 503
    assert "/secret/path" not in unavailable.text

    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="corrupt")

    def broken_find(*args: Any, **kwargs: Any) -> Any:
        raise CVError("corrupt index at /secret/path")

    monkeypatch.setattr(ctx["store"], "find_by_observation_id", broken_find)
    corrupt = _search(client, ctx)
    assert corrupt.status_code == 422
    assert "/secret/path" not in corrupt.text


def test_candidate_search_empty_index_and_bounded_results(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="empty")
    _remove_v4(ctx["store"], ctx["candidate_observation_a"])
    _remove_v4(ctx["store"], ctx["candidate_observation_b"])
    _remove_v4(ctx["store"], ctx["same_video_observation"])
    _remove_v4(ctx["store"], ctx["cross_observation"])
    empty = _search(client, ctx)
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []
    assert empty.json()["count"] == 0

    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="bounded")
    bounded = _search(client, ctx, top_k=1)
    assert bounded.status_code == 200, bounded.text
    assert len(bounded.json()["items"]) == 1
    assert bounded.json()["limit"] == 1


def test_candidate_search_rejects_invalid_top_k(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="topk")
    assert _search(client, ctx, top_k=0).status_code == 422
    assert _search(client, ctx, top_k=26).status_code == 422


def test_candidate_search_busy_uses_existing_cv_control(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="busy")
    monkeypatch.setattr(cv_router._analysis_slots, "acquire", lambda blocking=False: False)
    response = _search(client, ctx)
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert response.json()["detail"] == "CV analysis busy; retry later"


def _add_candidate(
    client: Any,
    ctx: dict[str, Any],
    sample_id: str,
    vector: list[float],
    *,
    video: dict[str, Any] | None = None,
    **overrides: Any,
) -> str:
    selected_video = video or ctx["candidate_video_a"]
    run_id, observation_id = _insert_observation(
        client,
        ctx["case"]["id"],
        selected_video,
        sample_id,
        frame=40,
        timestamp=8.0,
    )
    _publish_v4(
        ctx["store"],
        observation_id=observation_id,
        cv_run_id=run_id,
        sample_id=sample_id,
        case_id=ctx["case"]["id"],
        video_id=selected_video["id"],
        vector=vector,
        **overrides,
    )
    return observation_id


def _first_ranked_result(ctx: dict[str, Any]) -> dict[str, Any]:
    store: EmbeddingStore = ctx["store"]
    query = store.find_by_observation_id(ctx["query_observation"], eligible_only=True)
    assert query is not None
    return next(
        store.iter_ranked_records(
            query["vector"],
            case_id=ctx["case"]["id"],
            exclude_observation_id=ctx["query_observation"],
            exclude_source_id=ctx["query_video"]["id"],
            eligible_only=True,
        )
    )


def _scan_diagnostics(response: Any) -> dict[str, Any]:
    return response.json()["limits"]["candidate_scan"]


def test_refill_skips_invalid_top_ranked_records_and_preserves_ranking(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="refill")
    _publish_v4(
        ctx["store"],
        observation_id="obs-unpersisted-top",
        cv_run_id="run-unpersisted-top",
        sample_id="sample-unpersisted-top",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_a"]["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    _add_legacy(
        ctx["store"],
        observation_id="obs-legacy-top",
        cv_run_id="run-legacy-top",
        sample_id="sample-legacy-top",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_a"]["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    response = _search(client, ctx, top_k=2)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"], ctx["candidate_observation_b"]}
    scores = [item["similarity_score"] for item in response.json()["items"]]
    assert scores == sorted(scores, reverse=True)
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["scanned"] >= 3
    assert diagnostics["truncated"] is False
    assert diagnostics["reason"] == "top_k_reached"


def test_refill_reaches_requested_top_k_when_enough_eligible_records_exist(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="enough")
    extra_ids = [
        _add_candidate(client, ctx, f"sample-extra-{index}", vector)
        for index, vector in enumerate(
            ([0.0, 0.9, 0.1], [0.0, 0.7, 0.3], [0.0, 0.5, 0.5]),
            start=1,
        )
    ]
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 5
    assert len(body["items"]) == 5
    assert _observation_ids(response) == {
        ctx["candidate_observation_a"],
        ctx["candidate_observation_b"],
        *extra_ids,
    }
    scores = [item["similarity_score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    assert [item["rank"] for item in body["items"]] == [1, 2, 3, 4, 5]
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["scanned"] >= 5
    assert diagnostics["truncated"] is False
    assert diagnostics["reason"] == "top_k_reached"


def test_refill_reports_exhaustion_when_fewer_eligible_than_top_k(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="fewer")
    _remove_v4(ctx["store"], ctx["candidate_observation_b"])
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["truncated"] is False
    assert diagnostics["reason"] == "exhausted"


def test_genuine_iterator_exhaustion_reports_exhausted(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="exhaust")
    monkeypatch.setattr(ctx["store"], "iter_ranked_records", lambda *args, **kwargs: iter(()))
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["scanned"] == 0
    assert diagnostics["truncated"] is False
    assert diagnostics["reason"] == "exhausted"


def test_scan_limit_truncation_returns_partial_results_and_diagnostics(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="scanlimit")
    for index, vector in enumerate(([VECTOR_A, VECTOR_B, VECTOR_C], [VECTOR_A, VECTOR_B, 0.0]), start=1):
        _publish_v4(
            ctx["store"],
            observation_id=f"obs-unpersisted-scan-{index}",
            cv_run_id=f"run-unpersisted-scan-{index}",
            sample_id=f"sample-unpersisted-scan-{index}",
            case_id=ctx["case"]["id"],
            video_id=ctx["candidate_video_a"]["id"],
            vector=vector,
        )
    monkeypatch.setattr(integration, "CANDIDATE_SCAN_LIMIT", 3)
    response = _search(client, ctx, top_k=2)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["limit"] == 3
    assert diagnostics["scanned"] == 3
    assert diagnostics["truncated"] is True
    assert diagnostics["reason"] == "scan_limit"


def test_scan_limit_prevents_unbounded_iteration(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="infinite")
    monkeypatch.setattr(integration, "CANDIDATE_SCAN_LIMIT", 4)
    produced = 0

    def endless() -> Any:
        nonlocal produced
        while True:
            produced += 1
            if produced > 1000:
                raise AssertionError("unbounded iteration")
            yield {
                "cosine_similarity": 0.99,
                "metadata": {"observation_id": "obs-missing"},
            }

    monkeypatch.setattr(ctx["store"], "iter_ranked_records", lambda *args, **kwargs: endless())
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    diagnostics = _scan_diagnostics(response)
    assert diagnostics["scanned"] == 4
    assert diagnostics["truncated"] is True
    assert diagnostics["reason"] == "scan_limit"
    assert produced == 4


def test_duplicate_observation_results_are_deduplicated(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="duplicate")
    result = _first_ranked_result(ctx)
    monkeypatch.setattr(ctx["store"], "iter_ranked_records", lambda *args, **kwargs: iter([result, dict(result)]))
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    assert response.json()["count"] == 1
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}


def test_malformed_ranked_results_are_skipped_and_refilled(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="malformedrank")
    valid = _first_ranked_result(ctx)
    malformed = [
        {"cosine_similarity": "bad", "metadata": dict(valid["metadata"])},
        {"cosine_similarity": 0.9, "metadata": "not-a-dict"},
        {"cosine_similarity": 2.0, "metadata": dict(valid["metadata"])},
        valid,
    ]
    monkeypatch.setattr(ctx["store"], "iter_ranked_records", lambda *args, **kwargs: iter(malformed))
    response = _search(client, ctx, top_k=1)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}
    assert _scan_diagnostics(response)["scanned"] == 4


def test_query_and_source_video_exclusion_remain_enforced_during_refill(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="queryexclude")
    _replace_v4(ctx["store"], ctx["same_video_observation"], vector=[VECTOR_A, VECTOR_B, VECTOR_C])
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    ids = _observation_ids(response)
    assert ctx["query_observation"] not in ids
    assert ctx["same_video_observation"] not in ids
    assert {ctx["candidate_observation_a"], ctx["candidate_observation_b"]} <= ids


def test_selected_video_scope_remains_enforced_during_refill(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="scope")
    _replace_v4(ctx["store"], ctx["candidate_observation_b"], vector=[VECTOR_A, VECTOR_B, VECTOR_C])
    response = _search(
        client,
        ctx,
        scope="case_selected_videos",
        source_video_ids=[ctx["candidate_video_a"]["id"]],
        top_k=5,
    )
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}


def test_legacy_and_cross_run_records_are_excluded_during_refill(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="crossrun")
    _add_legacy(
        ctx["store"],
        observation_id="obs-legacy-exclude",
        cv_run_id="run-legacy-exclude",
        sample_id="sample-legacy-exclude",
        case_id=ctx["case"]["id"],
        video_id=ctx["candidate_video_a"]["id"],
        vector=[VECTOR_A, VECTOR_B, VECTOR_C],
    )
    _replace_v4(ctx["store"], ctx["candidate_observation_b"], cv_run_id="wrong-run", vector=[VECTOR_A, VECTOR_B, VECTOR_C])
    _replace_v4(ctx["store"], ctx["cross_observation"], vector=[VECTOR_A, VECTOR_B, VECTOR_C])
    response = _search(client, ctx, top_k=5)
    assert response.status_code == 200, response.text
    assert _observation_ids(response) == {ctx["candidate_observation_a"]}


def test_candidate_search_response_contract_remains_compatible(client: Any, synthetic_video: Any, monkeypatch: Any, tmp_path: Any):
    ctx = _setup(client, synthetic_video, monkeypatch, tmp_path, suffix="contract")
    response = _search(client, ctx)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "items",
        "count",
        "limit",
        "scope",
        "source_video_ids",
        "query",
        "score_meaning",
        "disclaimer",
        "index",
        "limits",
    }
    assert set(body["limits"]) == {"max_top_k", "concurrent_analyses", "candidate_scan"}
    assert set(body["limits"]["candidate_scan"]) == {"limit", "scanned", "truncated", "reason"}
