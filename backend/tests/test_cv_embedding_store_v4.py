import json
import threading

import numpy as np
import pytest

from app.cv.embeddings import (
    EMBEDDING_SCHEMA_VERSION,
    LEGACY_EMBEDDING_SCHEMA_VERSION,
    EmbeddingStore,
    build_v4_embedding_record,
)
from app.cv.errors import CVError


MODEL_SHA256 = "b" * 64


def _v4(observation_id: str = "obs-1", embedding_id: str = "emb-1", **overrides):
    values = {
        "embedding_id": embedding_id,
        "observation_id": observation_id,
        "cv_run_id": "run-1",
        "analysis_run_id": "analysis-1",
        "case_id": "case-1",
        "video_id": "video-1",
        "source_id": "video-1",
        "sample_id": "sample-1",
        "vector": [1.0, 0.0, 0.0],
        "model_key": "sface",
        "provenance_status": "known",
        "model_sha256": MODEL_SHA256,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "metadata": {
            "model_filename": "sface.onnx",
            "pipeline_version": "test",
            "opencv_version": "4.0.0",
        },
    }
    values.update(overrides)
    return build_v4_embedding_record(**values)


def test_v4_record_structure_and_validation(tmp_path):
    staged = _v4()
    assert staged.record["embedding_id"] == "emb-1"
    assert staged.record["observation_id"] == "obs-1"
    assert staged.record["embedding_schema_version"] == EMBEDDING_SCHEMA_VERSION
    assert staged.record["model_key"] == "sface"
    assert staged.record["provenance_status"] == "known"
    assert staged.record["v4_eligible"] is True
    assert np.isfinite(staged.vector).all()

    with pytest.raises(CVError):
        _v4(observation_id="")
    with pytest.raises(CVError):
        _v4(model_key="unknown")
    with pytest.raises(CVError):
        _v4(provenance_status="legacy_unknown")
    with pytest.raises(CVError):
        _v4(model_sha256="abc")
    with pytest.raises(CVError):
        _v4(vector=[float("nan"), 0.0, 0.0])


def test_observation_keyed_records_allow_same_sample_id(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    published = store.publish_staged_records(
        [_v4(observation_id="obs-1", embedding_id="emb-1", sample_id="sample-shared")]
    )
    published += store.publish_staged_records(
        [_v4(observation_id="obs-2", embedding_id="emb-2", sample_id="sample-shared")]
    )
    assert published == 2
    assert store.status()["record_count"] == 2
    assert store.find_by_observation_id("obs-1")["metadata"]["sample_id"] == "sample-shared"
    assert store.find_by_observation_id("obs-2")["metadata"]["sample_id"] == "sample-shared"
    ranked = list(store.iter_ranked_records([1.0, 0.0, 0.0], case_id="case-1"))
    assert len(ranked) == 2


def test_duplicate_observation_and_embedding_ids_rejected(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    store.publish_staged_records([_v4(observation_id="obs-1", embedding_id="emb-1")])

    with pytest.raises(CVError):
        store.publish_staged_records([_v4(observation_id="obs-1", embedding_id="emb-2")])
    with pytest.raises(CVError):
        store.publish_staged_records([_v4(observation_id="obs-2", embedding_id="emb-1")])

    assert store.status()["record_count"] == 1
    assert store.status()["generation"] == 1


def test_invalid_dimension_and_provenance_are_rejected(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    store.publish_staged_records([_v4(vector=[1.0, 0.0, 0.0])])
    with pytest.raises(CVError):
        store.publish_staged_records([_v4(observation_id="obs-2", embedding_id="emb-2", vector=[1.0, 0.0])])
    with pytest.raises(CVError):
        store.publish_staged_records(
            [
                _v4(
                    observation_id="obs-3",
                    embedding_id="emb-3",
                    model_sha256="short",
                )
            ]
        )
    assert store.status()["record_count"] == 1


def test_legacy_v3_records_are_quarantined_from_v4_search(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()
    (directory / "embeddings.json").write_text(
        json.dumps(
            {
                "records": [
                    {
                        "sample_id": "legacy-sample",
                        "case_id": "case-1",
                        "source_id": "video-1",
                        "provenance_status": "known",
                        "model_key": "sface",
                        "embedding_schema_version": LEGACY_EMBEDDING_SCHEMA_VERSION,
                        "embedding_dim": 3,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    np.save(directory / "embeddings.npy", np.array([[1.0, 0.0, 0.0]], dtype=np.float32))

    store = EmbeddingStore(directory)
    assert store.status()["quarantine"]["legacy_v3"] == 1
    assert store.status()["record_formats"]["v4_eligible"] == 0
    assert list(store.iter_ranked_records([1.0, 0.0, 0.0], case_id="case-1")) == []
    assert len(store.search([1.0, 0.0, 0.0], case_id="case-1")) == 1


def test_legacy_add_and_search_remain_compatible(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    store.add(
        "sample-a",
        "case-1",
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        metadata={"source_id": "video-a", "provenance_status": "known", "model_key": "sface"},
    )
    store.add("sample-b", "case-1", np.array([0.9, 0.1, 0.0], dtype=np.float32))
    results = store.search([1.0, 0.0, 0.0], case_id="case-1", top_k=2, exclude_sample_id="sample-a")
    assert [item["sample_id"] for item in results] == ["sample-b"]
    assert store.status()["provenance"]["known"] == 1
    assert store.status()["quarantine"]["legacy_v3"] == 2
    assert all(item["v4_eligible"] is False for item in store.search([1.0, 0.0, 0.0], case_id="case-1"))


def test_ranked_iterator_does_not_truncate_before_v4_filtering(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    store.add(
        "legacy-high",
        "case-1",
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        metadata={"source_id": "legacy-video", "provenance_status": "known", "model_key": "sface"},
    )
    store.publish_staged_records(
        [
            _v4(
                observation_id="obs-v4",
                embedding_id="emb-v4",
                sample_id="sample-v4",
                vector=[0.1, 1.0, 0.0],
            )
        ]
    )
    ranked = list(store.iter_ranked_records([1.0, 0.0, 0.0], case_id="case-1"))
    assert [item["metadata"]["observation_id"] for item in ranked] == ["obs-v4"]
    assert all(item["v4_eligible"] for item in ranked)


def test_atomic_publication_and_generation_recovery(tmp_path):
    directory = tmp_path / "store"
    store = EmbeddingStore(directory)
    store.publish_staged_records([_v4()])
    assert store.status()["generation"] == 1

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generation"] = 999999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    recovered = EmbeddingStore(directory)
    assert recovered.status()["record_count"] == 1
    assert recovered.status()["generation"] == 1
    assert recovered.find_by_observation_id("obs-1") is not None


def test_corrupt_generation_is_rejected_without_valid_fallback(tmp_path):
    directory = tmp_path / "store"
    store = EmbeddingStore(directory)
    store.add("sample-a", "case-1", np.array([1.0, 0.0, 0.0], dtype=np.float32))
    generation = directory / "generations" / "000000000001"
    (generation / "embeddings.json").write_bytes(b"{corrupt")

    with pytest.raises(CVError):
        EmbeddingStore(directory)


def test_search_status_and_publish_share_process_lock(tmp_path):
    store = EmbeddingStore(tmp_path / "store")
    assert store._lock is EmbeddingStore._lock

    errors: list[Exception] = []

    def writer(worker: int) -> None:
        try:
            for index in range(3):
                suffix = f"{worker}-{index}"
                store.publish_staged_records(
                    [
                        _v4(
                            observation_id=f"obs-{suffix}",
                            embedding_id=f"emb-{suffix}",
                            sample_id=f"sample-{suffix}",
                        )
                    ]
                )
        except Exception as exc:
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(5):
                store.status()
                list(store.iter_ranked_records([1.0, 0.0, 0.0], case_id="case-1"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(3)]
    threads.append(threading.Thread(target=reader))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.status()["record_count"] == 9
    assert len(list(store.iter_ranked_records([1.0, 0.0, 0.0], case_id="case-1"))) == 9
