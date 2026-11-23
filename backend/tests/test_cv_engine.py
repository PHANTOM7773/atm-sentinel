from __future__ import annotations

import json
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]


def _face_detection(x: float, y: float = 0.0, size: float = 10.0, confidence: float = 0.9):
    from app.cv.types import FaceDetection

    return FaceDetection(
        (float(x), float(y), float(size), float(size)),
        confidence,
        (
            (x + 1.0, y + 1.0),
            (x + 2.0, y + 1.0),
            (x + 3.0, y + 3.0),
            (x + 4.0, y + 5.0),
            (x + 5.0, y + 5.0),
        ),
    )


class StubStore:
    def status(self):
        return {
            "record_count": 0,
            "consistency": "empty",
            "provenance": {"known": 0, "legacy_unknown": 0},
        }


class StubAnalysis:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self) -> dict:
        return self.payload


def _stub_analysis(frame_count: int = 2, faces_per_frame: int = 2) -> StubAnalysis:
    frames = []
    for frame_index in range(frame_count):
        faces = [
            {
                "sample_id": f"f{frame_index}-face{face_index}",
                "track_id": face_index + 1,
                "quality": {"quality_score": 40.0 + face_index},
                "confidence": 0.9,
                "embedding": [0.1] * 4,
            }
            for face_index in range(faces_per_frame)
        ]
        frames.append(
            {
                "frame_number": frame_index,
                "timestamp": float(frame_index) / 10.0,
                "faces": faces,
                "persons": [],
                "counts": {"faces": len(faces), "persons": 0},
                "total_counts": {"faces": len(faces), "persons": 0},
                "truncation": {},
                "truncated": False,
            }
        )
    return StubAnalysis(
        {
            "source": "synthetic_test",
            "source_id": "clip",
            "fps": 10.0,
            "frame_count": frame_count,
            "analyzed_frame_count": frame_count,
            "analysis_run_id": "stub-run",
            "frames": frames,
            "summary": {
                "face_detections": frame_count * faces_per_frame,
                "person_detections": 0,
                "retained_face_observations": frame_count * faces_per_frame,
                "retained_person_observations": 0,
                "truncated_observations": 0,
            },
            "truncation": {},
            "runtime": {"models": {}},
        }
    )


@pytest.fixture
def cv_models():
    from app.config import CV_MODEL_DIR
    from app.cv.models import MODEL_SPECS

    CV_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for spec in MODEL_SPECS.values():
        source = ROOT / "data" / "models" / spec.filename
        if not source.exists():
            pytest.skip(f"Missing pinned model file: {source}")
        shutil.copy2(source, CV_MODEL_DIR / spec.filename)
    return CV_MODEL_DIR


def test_cv_models_have_verified_hashes(cv_models):
    from app.cv.models import MODEL_SPECS, model_status

    status = model_status()
    assert status["all_usable"] is True
    assert set(status["models"]) == set(MODEL_SPECS)
    for item in status["models"].values():
        assert item["verification"] == "verified"
        assert item["size_bytes"] > 1000
        assert item["license"]


def test_tracker_keeps_ids_and_expires_missing_tracks():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    tracker = SimpleTracker(max_misses=2)
    first = tracker.update([PersonDetection((0, 0, 20, 20), 0.9)], frame_number=0)[0]
    second = tracker.update([PersonDetection((1, 1, 20, 20), 0.9)], frame_number=1)[0]
    assert first.track_id == second.track_id == 1
    tracker.update([], frame_number=2)
    tracker.update([], frame_number=3)
    replacement = tracker.update([PersonDetection((5, 5, 20, 20), 0.9)], frame_number=4)[0]
    assert replacement.track_id == 2


def test_tracker_assigns_each_existing_track_once():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    tracker = SimpleTracker()
    tracker.update(
        [PersonDetection((0, 0, 20, 20), 0.9), PersonDetection((200, 200, 20, 20), 0.9)],
        frame_number=0,
    )
    results = tracker.update(
        [PersonDetection((1, 1, 20, 20), 0.9), PersonDetection((2, 2, 20, 20), 0.9)],
        frame_number=1,
    )
    assert len({item.track_id for item in results}) == 2
    assert 1 in {item.track_id for item in results}
    assert all(item.track_id != 2 for item in results)


def test_tracker_never_reuses_track_id_within_frame():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    tracker = SimpleTracker()
    results = tracker.update(
        [PersonDetection((10, 10, 20, 20), 0.9), PersonDetection((12, 12, 20, 20), 0.9)],
        frame_number=0,
    )
    assert [item.track_id for item in results] == [1, 2]


def test_single_detection_updates_only_one_existing_track():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    tracker = SimpleTracker()
    tracker.update(
        [PersonDetection((0, 0, 20, 20), 0.9), PersonDetection((2, 2, 20, 20), 0.9)],
        frame_number=0,
    )
    tracker.update([PersonDetection((1, 1, 20, 20), 0.9)], frame_number=1)
    assert sorted(track.hits for track in tracker._tracks.values()) == [1, 2]


def test_tracker_assignment_is_deterministic():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    def run() -> list[int]:
        tracker = SimpleTracker()
        frames = [
            [(0, 0, 20, 20), (4, 4, 20, 20)],
            [(1, 1, 20, 20), (5, 5, 20, 20)],
            [(2, 2, 20, 20)],
        ]
        identifiers: list[int] = []
        for frame_number, boxes in enumerate(frames):
            results = tracker.update(
                [PersonDetection(box, 0.9) for box in boxes],
                frame_number=frame_number,
            )
            identifiers.extend(int(item.track_id) for item in results)
        return identifiers

    assert run() == run()


def test_face_quality_is_explainable_and_does_not_classify_attributes():
    from app.cv.landmarks import estimate_pose
    from app.cv.quality import analyze_face_quality

    crop = np.full((100, 100, 3), 128, dtype=np.uint8)
    landmarks = [(35, 40), (65, 40), (50, 55), (40, 75), (60, 75)]
    quality = analyze_face_quality(crop, landmarks)
    pose = estimate_pose(landmarks)

    assert 0 <= quality["quality_score"] <= 100
    assert quality["flags"]["identity_confirmed"] is False
    assert quality["flags"]["mask"] == "unknown"
    assert quality["flags"]["helmet"] == "unknown"
    assert quality["flags"]["cap"] == "unknown"
    assert "not" in quality["disclaimer"].lower()
    assert pose["frontal_score"] > 0.5


def test_embedding_store_retrieves_candidate_only_results(tmp_path):
    from app.cv.embeddings import EmbeddingStore

    store = EmbeddingStore(tmp_path / "embeddings")
    store.add("sample-a", "case-1", np.array([1.0, 0.0, 0.0], dtype=np.float32))
    store.add("sample-b", "case-1", np.array([0.9, 0.1, 0.0], dtype=np.float32))
    store.add("sample-c", "case-2", np.array([1.0, 0.0, 0.0], dtype=np.float32))

    results = store.search([1.0, 0.0, 0.0], case_id="case-1", top_k=2, exclude_sample_id="sample-a")
    assert [item["sample_id"] for item in results] == ["sample-b"]
    assert results[0]["verification_status"] == "candidate_only"


def test_synthetic_generator_writes_labelled_clips(tmp_path):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.generate_synthetic_cv_assets import build_assets

    output = tmp_path / "synthetic"
    manifest = build_assets(output)
    assert manifest["synthetic"] is True
    assert manifest["real_people"] is False
    assert len(manifest["videos"]) == 6
    for entry in manifest["videos"].values():
        path = output / entry["file"]
        assert path.exists()
        assert path.stat().st_size > 0
    assert json.loads((output / "manifest.json").read_text())["synthetic"] is True


def test_pipeline_detects_synthetic_faces(cv_models):
    from app.cv import CVPipeline

    source = ROOT / "data" / "datasets" / "synthetic" / "cv" / "subject_a_front.mp4"
    if not source.exists():
        pytest.skip("Synthetic benchmark clips have not been generated")
    pipeline = CVPipeline()
    analysis = pipeline.analyze_video(
        source,
        case_id="synthetic",
        source_id="subject_a_front",
        max_frames=6,
        save_crops=False,
    )
    assert analysis.analyzed_frame_count == 6
    assert analysis.summary["face_detections"] >= 4
    for frame in analysis.frames:
        for face in frame.faces:
            assert face["verification_status"] == "candidate_only"
            assert face["flags"]["identity_confirmed"] is False
            assert face["flags"]["partial_occlusion_suspected"] is False


def test_cv_status_endpoint_reports_models_and_disclaimer(client, cv_models):
    response = client.get("/api/cv/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["models"]["all_usable"] is True
    assert "never confirms identity" in payload["disclaimer"]
    assert payload["embedding_store"]["record_count"] >= 0
    assert payload["limits"]["max_analysis_frames"] > 0
    assert payload["limits"]["concurrent_analyses"] >= 1
    assert payload["synchronous_analysis"] is True
    assert set(payload["runtime"]["models"]) == {"yunet", "sface", "yolox"}
    assert payload["person_detection"]["status"] == "experimental_unvalidated"


def test_embedding_store_generations_are_recoverable_and_exclude_source(tmp_path):
    from app.cv.embeddings import EmbeddingStore

    directory = tmp_path / "store"
    store = EmbeddingStore(directory)
    store.add(
        "sample-a",
        "case-1",
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        metadata={
            "source_id": "query-clip",
            "provenance_status": "known",
            "model_key": "sface",
            "model_sha256": "abc",
        },
    )
    assert store.status()["storage"] == "generation"
    assert store.status()["provenance"]["known"] == 1
    assert (directory / "manifest.json").exists()
    assert store.search([1.0, 0.0, 0.0], case_id="case-1", exclude_source_id="query-clip") == []

    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["generation"] = 999999
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    recovered = EmbeddingStore(directory)
    assert recovered.status()["record_count"] == 1
    assert recovered.status()["consistency"] == "verified"


def test_pipeline_rejects_resource_limits(synthetic_video, tmp_path):
    from app.config import CV_MAX_FRAMES, CV_MAX_FRAME_STRIDE
    from app.cv import CVPipeline, CVError

    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path,
    )
    with pytest.raises(CVError, match="Frame limit"):
        pipeline.analyze_video(synthetic_video, max_frames=CV_MAX_FRAMES + 1)
    with pytest.raises(CVError, match="Frame stride"):
        pipeline.analyze_video(synthetic_video, frame_stride=CV_MAX_FRAME_STRIDE + 1)


def test_cv_analyze_validates_limits_and_supports_summary_only(
    client, cv_models, case_and_transaction, synthetic_video
):
    from app.config import CV_ANALYZE_MAX_FRAMES, CV_MAX_FRAME_STRIDE

    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    video_id = upload.json()["id"]

    oversized = client.post(
        "/api/cv/analyze",
        json={"video_id": video_id, "max_frames": CV_ANALYZE_MAX_FRAMES + 1},
    )
    assert oversized.status_code == 422
    oversized_stride = client.post(
        "/api/cv/analyze",
        json={"video_id": video_id, "frame_stride": CV_MAX_FRAME_STRIDE + 1},
    )
    assert oversized_stride.status_code == 422

    response = client.post(
        "/api/cv/analyze",
        json={
            "video_id": video_id,
            "max_frames": 2,
            "frame_stride": 1,
            "summary_only": True,
            "rank": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_only"] is True
    assert payload["analysis_run_id"]
    assert "frames" not in payload["analysis"]
    assert payload["ranking"]["omitted"] is True


def test_cv_analyze_hides_path_details_and_reports_busy(
    client, cv_models, case_and_transaction, synthetic_video, monkeypatch
):
    from app.cv.errors import CVError

    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    video_id = upload.json()["id"]

    class FailingPipeline:
        def __init__(self):
            raise CVError("Could not open video: /private/secrets/case.mp4")

    monkeypatch.setattr("app.routers.cv.CVPipeline", FailingPipeline)
    failure = client.post("/api/cv/analyze", json={"video_id": video_id, "max_frames": 2})
    assert failure.status_code == 400
    assert "secrets" not in failure.text
    assert "/private" not in failure.text

    monkeypatch.setattr("app.routers.cv.CVPipeline", lambda: None)
    monkeypatch.setattr("app.routers.cv._analysis_slots.acquire", lambda blocking=False: False)
    busy = client.post("/api/cv/analyze", json={"video_id": video_id, "max_frames": 2})
    assert busy.status_code == 503
    assert busy.headers["Retry-After"] == "5"


def test_frame_observation_cap_preserves_totals(tmp_path, monkeypatch):
    from app.cv import CVPipeline

    monkeypatch.setattr("app.cv.pipeline.CV_MAX_FACE_OBSERVATIONS_PER_FRAME", 2)
    monkeypatch.setattr("app.cv.pipeline.CV_MAX_FACE_DETECTIONS_PER_FRAME", 8)

    class Detector:
        def detect(self, frame):
            return [_face_detection(10 + index * 8) for index in range(5)]

    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path,
    )
    pipeline.face_detector = Detector()
    analysis = pipeline.analyze_frame(np.full((80, 100, 3), 128, dtype=np.uint8), frame_number=3)
    assert len(analysis.faces) == 2
    assert analysis.counts["faces"] == 2
    assert analysis.total_counts["faces"] == 5
    assert analysis.truncated is True
    assert analysis.truncation["face_observations_dropped_by_frame"] == 3
    assert len(analysis.face_track_ids) == 5


def test_analysis_observation_cap_retains_best_evidence(tmp_path, monkeypatch, synthetic_video):
    from app.cv import CVPipeline

    monkeypatch.setattr("app.cv.pipeline.CV_MAX_FACE_OBSERVATIONS_PER_FRAME", 3)
    monkeypatch.setattr("app.cv.pipeline.CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS", 2)

    class Detector:
        def detect(self, frame):
            return [_face_detection(10 + index * 10) for index in range(3)]

    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path,
    )
    pipeline.face_detector = Detector()
    analysis = pipeline.analyze_video(synthetic_video, max_frames=2)
    assert analysis.summary["face_detections"] == 6
    assert analysis.summary["retained_face_observations"] == 2
    assert analysis.summary["truncated_observations"] == 4
    dropped = sum(frame.truncation["face_observations_dropped_by_analysis"] for frame in analysis.frames)
    assert dropped == 4
    assert all(frame.total_counts["faces"] == 3 for frame in analysis.frames)


def test_hard_processing_budget_raises_controlled_error(tmp_path, monkeypatch, synthetic_video):
    from app.cv import CVError, CVPipeline

    monkeypatch.setattr("app.cv.pipeline.CV_MAX_FACE_DETECTIONS_PER_FRAME", 2)

    class Detector:
        def detect(self, frame):
            return [_face_detection(10 + index * 10) for index in range(3)]

    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path,
    )
    pipeline.face_detector = Detector()
    with pytest.raises(CVError, match="Frame face detection budget exceeded"):
        pipeline.analyze_video(synthetic_video, max_frames=1)


def test_summary_only_avoids_detail_retention_and_candidate_payload(
    client, case_and_transaction, synthetic_video, monkeypatch
):
    captured = []

    class SummaryPipeline:
        def __init__(self):
            self.store = StubStore()

        def analyze_video(self, **kwargs):
            captured.append(kwargs["retain_observations"])
            return _stub_analysis(frame_count=2, faces_per_frame=2)

        def rank_faces(self, *args, **kwargs):
            raise AssertionError("Summary-only mode must not compute ranking candidates")

    monkeypatch.setattr("app.routers.cv.CVPipeline", SummaryPipeline)
    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    response = client.post(
        "/api/cv/analyze",
        json={"video_id": upload.json()["id"], "summary_only": True, "rank": True, "max_frames": 2},
    )
    assert response.status_code == 200
    assert captured == [False]
    payload = response.json()
    assert "frames" not in payload["analysis"]
    assert payload["ranking"]["omitted"] is True
    assert "candidates" not in payload["ranking"]


def test_response_serialization_respects_budget_and_reports_truncation(
    client, case_and_transaction, synthetic_video, monkeypatch
):
    budget = 3000
    monkeypatch.setattr("app.routers.cv.CV_MAX_RESPONSE_BYTES", budget)
    monkeypatch.setattr("app.config.CV_MAX_RESPONSE_BYTES", budget)

    class StubPipeline:
        def __init__(self):
            self.store = StubStore()

        def analyze_video(self, **kwargs):
            return _stub_analysis(frame_count=20, faces_per_frame=5)

    monkeypatch.setattr("app.routers.cv.CVPipeline", StubPipeline)
    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    response = client.post(
        "/api/cv/analyze",
        json={"video_id": upload.json()["id"], "max_frames": 2},
    )
    assert response.status_code == 200
    assert len(response.content) <= budget
    payload = response.json()
    assert payload["response_truncation"]["truncated"] is True
    assert payload["response_truncation"]["observations_omitted"] > 0
    analysis = payload["analysis"]
    assert analysis["summary"]["retained_face_observations"] < analysis["summary"]["face_detections"]
    assert analysis["summary"]["truncated_observations"] > 0


def test_real_concurrency_busy_completion_and_error_release(
    client, case_and_transaction, synthetic_video, monkeypatch
):
    started = threading.Event()
    release = threading.Event()

    class StubPipeline:
        def __init__(self):
            self.store = StubStore()

        def analyze_video(self, **kwargs):
            return _stub_analysis(frame_count=1, faces_per_frame=1)

    class BlockingPipeline(StubPipeline):
        def analyze_video(self, **kwargs):
            started.set()
            if not release.wait(timeout=10):
                from app.cv.errors import CVError

                raise CVError("blocking analysis timed out")
            return _stub_analysis(frame_count=1, faces_per_frame=1)

    class FailingPipeline(StubPipeline):
        def analyze_video(self, **kwargs):
            from app.cv.errors import CVError

            raise CVError("deliberate analysis failure")

    class HttpFailingPipeline(StubPipeline):
        def analyze_video(self, **kwargs):
            raise HTTPException(418, "deliberate HTTP failure")

    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    video_id = upload.json()["id"]
    payload = {"video_id": video_id, "max_frames": 1}

    monkeypatch.setattr("app.routers.cv.CVPipeline", BlockingPipeline)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            first = executor.submit(client.post, "/api/cv/analyze", json=payload)
            assert started.wait(timeout=10)
            busy = client.post("/api/cv/analyze", json=payload)
            assert busy.status_code == 503
            assert busy.headers["Retry-After"] == "5"
            release.set()
            assert first.result(timeout=10).status_code == 200
    finally:
        release.set()

    monkeypatch.setattr("app.routers.cv.CVPipeline", StubPipeline)
    assert client.post("/api/cv/analyze", json=payload).status_code == 200
    monkeypatch.setattr("app.routers.cv.CVPipeline", FailingPipeline)
    assert client.post("/api/cv/analyze", json=payload).status_code == 400
    monkeypatch.setattr("app.routers.cv.CVPipeline", HttpFailingPipeline)
    assert client.post("/api/cv/analyze", json=payload).status_code == 418
    monkeypatch.setattr("app.routers.cv.CVPipeline", StubPipeline)
    assert client.post("/api/cv/analyze", json=payload).status_code == 200


def test_benchmark_ranking_evidence_is_recomputable():
    benchmark_path = ROOT / "data" / "cv" / "benchmark.json"
    evidence_path = ROOT / "data" / "cv" / "benchmark_ranking_evidence.json"
    if not benchmark_path.exists() or not evidence_path.exists():
        pytest.skip("Benchmark artifacts have not been generated")
    report = json.loads(benchmark_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    rows = evidence["rows"]
    assert rows
    assert evidence["methodology_version"] == report["ranking_methodology"]["version"]
    assert evidence["synthetic_only"] is True
    assert all("embedding" not in row and "crop_path" not in row for row in rows)
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["query_sample_id"], []).append(row)
    rank_one = 0
    for group in groups.values():
        group.sort(key=lambda item: item["rank"])
        if group[0]["rank"] == 1 and group[0]["evaluation_outcome"] == "same_label":
            rank_one += 1
    hard_negatives = sum(1 for row in rows if row["evaluation_outcome"] == "hard_negative")
    metrics = report["clips"][report["ranking_methodology"]["query_clips"][0]]["ranking"]
    assert rank_one == metrics["same_label_rank1"]
    assert hard_negatives == metrics["hard_negative_candidates"]
    assert evidence["query_count"] == metrics["ranked_samples"]
    assert evidence["gallery_count"] == report["embedding_store"]["record_count"]


def test_cv_status_identifies_configured_runtime_as_unverified(client, cv_models):
    response = client.get("/api/cv/status")
    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert runtime["observed"] is False
    assert runtime["verification_state"] == "configured_not_yet_verified"
    assert runtime["fallback_observed"] is False
    for profile in runtime["models"].values():
        assert profile["observed"] is False
        assert profile["verification_state"] == "configured_not_yet_verified"
        assert profile["fallback_observed"] is False


def test_analyze_response_reports_observed_runtime(
    client, cv_models, case_and_transaction, synthetic_video
):
    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert upload.status_code == 201
    response = client.post(
        "/api/cv/analyze",
        json={"video_id": upload.json()["id"], "max_frames": 1, "summary_only": True},
    )
    assert response.status_code == 200
    models = response.json()["analysis"]["runtime"]["models"]
    assert models
    for profile in models.values():
        assert profile["observed"] is True
        assert profile["verification_state"] == "observed_from_instantiated_model"
        assert profile["fallback_observed"] in (True, False)


def test_save_crop_uses_jpeg_temporary_path_and_writes_jpeg(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop

    destination = tmp_path / "nested" / "face.jpg"
    written_paths: list[Path] = []
    real_imwrite = crop_module.cv2.imwrite

    def recording_imwrite(filename, image, *args, **kwargs):
        written_paths.append(Path(filename))
        return bool(real_imwrite(filename, image, *args, **kwargs))

    monkeypatch.setattr(crop_module.cv2, "imwrite", recording_imwrite)
    save_crop(np.full((24, 18, 3), 123, dtype=np.uint8), destination)

    assert len(written_paths) == 1
    temporary = written_paths[0]
    assert temporary.suffix == ".jpg"
    assert temporary.name.startswith(".face.jpg.")
    assert temporary.parent == destination.parent
    assert not temporary.exists()
    assert destination.read_bytes().startswith(b"\xff\xd8\xff")
    assert not [path for path in destination.parent.iterdir() if path.name.startswith(".")]


def test_save_crop_replaces_final_atomically(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop

    destination = tmp_path / "face.jpg"
    destination.write_bytes(b"old-final")
    replacements: list[tuple[Path, Path]] = []
    real_replace = crop_module.os.replace

    def recording_replace(source, target, *args, **kwargs):
        replacements.append((Path(source), Path(target)))
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(crop_module.os, "replace", recording_replace)
    save_crop(np.full((20, 20, 3), 90, dtype=np.uint8), destination)

    assert len(replacements) == 1
    source, target = replacements[0]
    assert source.suffix == ".jpg"
    assert source.parent == destination.parent
    assert target == destination
    assert not source.exists()
    assert destination.read_bytes().startswith(b"\xff\xd8\xff")


def test_save_crop_cleans_partial_temporary_file_on_failure(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop
    from app.cv.errors import CVError

    destination = tmp_path / "nested" / "face.jpg"

    def failing_imwrite(path, image):
        Path(path).write_bytes(b"partial")
        return False

    monkeypatch.setattr(crop_module.cv2, "imwrite", failing_imwrite)
    with pytest.raises(CVError, match="Could not encode face crop"):
        save_crop(np.zeros((20, 20, 3), dtype=np.uint8), destination)
    assert not destination.exists()
    assert list(destination.parent.iterdir()) == []


def test_save_crop_encoder_exception_leaves_no_partial_files(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop
    from app.cv.errors import CVError

    destination = tmp_path / "nested" / "face.jpg"

    def raising_imwrite(path, image):
        Path(path).write_bytes(b"partial")
        raise cv2.error("encoder unavailable")

    monkeypatch.setattr(crop_module.cv2, "imwrite", raising_imwrite)
    with pytest.raises(CVError, match="Could not encode face crop"):
        save_crop(np.zeros((20, 20, 3), dtype=np.uint8), destination)
    assert not destination.exists()
    assert not [path for path in destination.parent.iterdir() if path.name.startswith(".")]


def test_save_crop_failed_write_preserves_existing_final(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop
    from app.cv.errors import CVError

    destination = tmp_path / "face.jpg"
    destination.write_bytes(b"old-final")

    def failing_imwrite(path, image):
        Path(path).write_bytes(b"partial")
        return False

    monkeypatch.setattr(crop_module.cv2, "imwrite", failing_imwrite)
    with pytest.raises(CVError, match="Could not encode face crop"):
        save_crop(np.zeros((20, 20, 3), dtype=np.uint8), destination)
    assert destination.read_bytes() == b"old-final"
    assert not [path for path in destination.parent.iterdir() if path.name.startswith(".")]


def test_save_crop_rejects_non_jpeg_output(tmp_path, monkeypatch):
    from app.cv import crop as crop_module
    from app.cv.crop import save_crop
    from app.cv.errors import CVError

    destination = tmp_path / "face.jpg"

    def non_jpeg_imwrite(path, image):
        Path(path).write_bytes(b"not a jpeg")
        return True

    monkeypatch.setattr(crop_module.cv2, "imwrite", non_jpeg_imwrite)
    with pytest.raises(CVError, match="Could not encode face crop"):
        save_crop(np.zeros((20, 20, 3), dtype=np.uint8), destination)
    assert not destination.exists()
    assert not [path for path in destination.parent.iterdir() if path.name.startswith(".")]


def test_pipeline_save_crops_true_writes_jpeg_crops(cv_models):
    from app.config import CV_CROP_DIR
    from app.cv import CVPipeline
    from app.cv.crop import safe_segment

    source = ROOT / "data" / "datasets" / "synthetic" / "cv" / "subject_a_front.mp4"
    if not source.exists():
        pytest.skip("Synthetic benchmark clips have not been generated")

    case_id = "crop-write-case"
    source_id = "subject_a_front"
    analysis = CVPipeline().analyze_video(
        source,
        case_id=case_id,
        source_id=source_id,
        max_frames=6,
        save_crops=True,
    )

    saved = [
        (frame.frame_number, face)
        for frame in analysis.frames
        for face in frame.faces
        if face.get("crop_state") == "saved"
    ]
    assert saved
    for frame_number, face in saved:
        path = (
            CV_CROP_DIR
            / safe_segment(case_id)
            / safe_segment(source_id)
            / f"frame_{frame_number:06d}"
            / f"{face['sample_id']}.jpg"
        )
        assert path.is_file()
        assert path.read_bytes().startswith(b"\xff\xd8\xff")
        assert not [item for item in path.parent.iterdir() if item.name.startswith(".")]


def test_cv_run_save_crops_true_creates_retrievable_crop(client, cv_models):
    source = ROOT / "data" / "datasets" / "synthetic" / "cv" / "subject_a_front.mp4"
    if not source.exists():
        pytest.skip("Synthetic benchmark clips have not been generated")

    case = client.post(
        "/api/cases",
        json={"case_number": "CROP-E2E-001", "title": "Crop write test", "location": "Test"},
    ).json()
    with source.open("rb") as handle:
        video = client.post(
            "/api/videos/upload",
            params={"case_id": case["id"]},
            files={"file": ("subject_a_front.mp4", handle, "video/mp4")},
        ).json()
    response = client.post(
        "/api/cv/runs",
        json={
            "case_id": case["id"],
            "video_id": video["id"],
            "max_frames": 6,
            "frame_stride": 1,
            "save_crops": True,
        },
    )
    assert response.status_code == 200, response.text

    observations = client.get(
        f"/api/cv/runs/{response.json()['run']['cv_run_id']}/observations",
        params={"case_id": case["id"]},
    ).json()
    item = next(entry for entry in observations["items"] if entry["crop"]["available"])
    assert item["crop"]["status"] == "available"
    assert item["crop"]["retrieval_state"] == "retrievable"

    crop = client.get(
        f"/api/cv/runs/{response.json()['run']['cv_run_id']}/observations/{item['observation_id']}/crop",
        params={"case_id": case["id"], "crop_id": item["crop"]["crop_id"]},
    )
    assert crop.status_code == 200, crop.text
    assert crop.headers["content-type"].startswith("image/jpeg")
    assert crop.content.startswith(b"\xff\xd8\xff")


def test_prune_crops_ignores_temporary_files(tmp_path):
    from app.cv.crop import prune_crops

    completed = tmp_path / "completed.jpg"
    completed.write_bytes(b"valid")
    temporary = tmp_path / ".pending.jpg.pid.tmp"
    temporary.write_bytes(b"partial")
    jpeg_temporary = tmp_path / ".pending.jpg.pid.uuid.jpg"
    jpeg_temporary.write_bytes(b"partial")
    assert prune_crops(tmp_path, 0) == 1
    assert not completed.exists()
    assert temporary.exists()
    assert jpeg_temporary.exists()


def test_embedding_status_handles_corrupt_storage(client, tmp_path, monkeypatch):
    from app.cv.embeddings import EmbeddingStore

    directory = tmp_path / "store"
    directory.mkdir()
    (directory / "manifest.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("app.routers.cv.EmbeddingStore", lambda: EmbeddingStore(directory))
    response = client.get("/api/cv/status")
    assert response.status_code == 200
    status = response.json()["embedding_store"]
    assert status["consistency"] == "unavailable"
    assert str(directory) not in response.text


def test_new_embedding_records_include_complete_provenance(tmp_path):
    from app.cv import CVPipeline
    from app.cv.embeddings import EMBEDDING_SCHEMA_VERSION

    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path / "cv",
    )
    provenance = pipeline._embedding_provenance("run-123")
    assert provenance["opencv_version"] == cv2.__version__
    assert provenance["embedding_schema_version"] == EMBEDDING_SCHEMA_VERSION
    assert provenance["analysis_run_id"] == "run-123"
    assert provenance["provenance_status"] == "known"


def test_legacy_embedding_records_keep_unknown_provenance(tmp_path):
    from app.cv.embeddings import EmbeddingStore

    directory = tmp_path / "legacy"
    directory.mkdir()
    (directory / "embeddings.json").write_text(
        json.dumps({"records": [{"sample_id": "legacy-a", "case_id": "case-1", "embedding_dim": 1}]}),
        encoding="utf-8",
    )
    np.save(directory / "embeddings.npy", np.array([[1.0]], dtype=np.float32))
    store = EmbeddingStore(directory)
    assert store.status()["storage"] == "legacy"
    assert store.status()["consistency"] == "legacy_unknown"
    record = store.records[0]
    assert record["provenance_status"] == "legacy_unknown"
    assert "opencv_version" not in record
    assert "embedding_schema_version" not in record


def test_tracker_is_deterministic_under_equivalent_orderings():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    initial = [
        PersonDetection((0.0, 0.0, 20.0, 20.0), 0.9),
        PersonDetection((50.0, 50.0, 20.0, 20.0), 0.9),
    ]
    second = [
        PersonDetection((45.0, 45.0, 20.0, 20.0), 0.9),
        PersonDetection((5.0, 5.0, 20.0, 20.0), 0.9),
    ]

    def run(reverse_second: bool = False, reorder_tracks: bool = False):
        tracker = SimpleTracker()
        tracker.update(list(initial), frame_number=0)
        if reorder_tracks:
            tracker._tracks = dict(reversed(list(tracker._tracks.items())))
        detections = list(second)
        if reverse_second:
            detections.reverse()
        results = tracker.update(detections, frame_number=1)
        return {tuple(result.bbox): int(result.track_id) for result in results}

    baseline = run()
    assert run(reverse_second=True) == baseline
    assert run(reorder_tracks=True) == baseline
    assert run(reverse_second=True, reorder_tracks=True) == baseline
    assert baseline[(45.0, 45.0, 20.0, 20.0)] != baseline[(5.0, 5.0, 20.0, 20.0)]


def test_tracker_crossing_and_crowded_assignments_remain_one_to_one():
    from app.cv.tracking import SimpleTracker
    from app.cv.types import PersonDetection

    tracker = SimpleTracker()
    initial = [PersonDetection((index * 25.0, 0.0, 20.0, 20.0), 0.9) for index in range(6)]
    tracker.update(initial, frame_number=0)
    crowded = [PersonDetection((index * 25.0 + 1.0, 1.0, 20.0, 20.0), 0.9) for index in range(6)]
    reversed_crowded = list(reversed(crowded))
    first_ids = sorted(int(item.track_id) for item in tracker.update(crowded, frame_number=1))
    second_tracker = SimpleTracker()
    second_tracker.update(initial, frame_number=0)
    second_ids = sorted(int(item.track_id) for item in second_tracker.update(reversed_crowded, frame_number=1))
    assert first_ids == second_ids
    assert len(set(first_ids)) == 6

    crossing = [PersonDetection((1.0, 1.0, 20.0, 20.0), 0.9), PersonDetection((100.0, 100.0, 20.0, 20.0), 0.9)]
    crossing_tracker = SimpleTracker()
    crossing_tracker.update(
        [PersonDetection((0.0, 0.0, 20.0, 20.0), 0.9), PersonDetection((101.0, 101.0, 20.0, 20.0), 0.9)],
        frame_number=0,
    )
    results = crossing_tracker.update(crossing, frame_number=1)
    assert len({int(item.track_id) for item in results}) == 2


def test_cv_contract_run_creation_validation():
    from pydantic import ValidationError

    from app.schemas import CvRunCreateRequest

    full_video = CvRunCreateRequest(case_id="case-1", video_id="video-1", max_frames=2)
    assert full_video.window_mode == "full_video"
    assert "embedding" not in full_video.model_dump()

    aligned = CvRunCreateRequest(
        case_id="case-1",
        video_id="video-1",
        transaction_id="tx-1",
        transaction_ts="2026-11-22T00:00:00Z",
        cctv_ts="2026-11-22T00:00:30Z",
        window_mode="transaction_aligned",
        before_seconds=2,
        after_seconds=3,
    )
    assert aligned.before_seconds == 2
    assert aligned.after_seconds == 3

    with pytest.raises(ValidationError, match="transaction_ts"):
        CvRunCreateRequest(
            case_id="case-1",
            video_id="video-1",
            transaction_id="tx-1",
            window_mode="transaction_aligned",
            before_seconds=2,
            after_seconds=3,
        )
    with pytest.raises(ValidationError, match="at least 1 second"):
        CvRunCreateRequest(
            case_id="case-1",
            video_id="video-1",
            transaction_id="tx-1",
            transaction_ts="2026-11-22T00:00:00Z",
            cctv_ts="2026-11-22T00:00:30Z",
            window_mode="transaction_aligned",
            before_seconds=0,
            after_seconds=0,
        )
    with pytest.raises(ValidationError, match="only valid"):
        CvRunCreateRequest(
            case_id="case-1",
            video_id="video-1",
            window_mode="full_video",
            before_seconds=2,
        )
    with pytest.raises(ValidationError, match="must be supplied together"):
        CvRunCreateRequest(case_id="case-1", video_id="video-1", normalized_video_id="video-norm-1")


def test_cv_contract_traceability_and_candidate_only_fields():
    from app.schemas import (
        CV_CANDIDATE_DISCLAIMER,
        CvCandidateSummary,
        CvCropSummary,
        CvFaceObservationSummary,
        CvModelProvenance,
        CvPoseSummary,
        CvQualitySummary,
        CvReviewFlags,
        CvVideoProvenance,
    )

    digest = "a" * 64
    derivative_digest = "b" * 64
    video_provenance = CvVideoProvenance(
        source_video_id="video-1",
        source_video_sha256=digest,
        derivative_kind="normalized",
        normalized_video_id="video-norm-1",
        normalized_video_sha256=derivative_digest,
    )
    provenance = CvModelProvenance(
        model_key="sface",
        model_filename="sface.onnx",
        model_sha256=digest,
        backend="cpu",
        target="cpu",
        opencv_version="5.1.0",
        pipeline_version="cv-phase1-remediated",
        embedding_schema_version=3,
        generated_at="2026-11-22T00:00:00Z",
    )
    observation = CvFaceObservationSummary(
        observation_id="obs-1",
        cv_sample_id="sample-1",
        cv_run_id="run-1",
        case_id="case-1",
        video_provenance=video_provenance,
        original_frame_number=12,
        original_video_timestamp_seconds=1.2,
        analysis_relative_timestamp_seconds=0.2,
        extracted_frame_id=None,
        bbox=[1.0, 2.0, 3.0, 4.0],
        detector_confidence=0.8,
        track_id=1,
        quality=CvQualitySummary(
            quality_score=70.0,
            sharpness=100.0,
            brightness=120.0,
            contrast=40.0,
            face_size_px=90,
        ),
        review_flags=CvReviewFlags(),
        pose=CvPoseSummary(frontal_score=0.7),
        crop=CvCropSummary(
            crop_id="crop-opaque-1",
            available=True,
            status="available",
            retrieval_state="not_supported",
        ),
    )
    candidate = CvCandidateSummary(
        candidate_id="candidate-1",
        case_id="case-1",
        query_cv_run_id="run-1",
        query_observation_id="obs-1",
        candidate_cv_run_id="run-2",
        candidate_observation_id="obs-2",
        candidate_video_provenance=video_provenance,
        candidate_original_frame_number=20,
        candidate_original_video_timestamp_seconds=2.0,
        candidate_analysis_relative_timestamp_seconds=None,
        similarity_score=0.91,
        rank=1,
        model_provenance=[provenance],
    )
    payload = candidate.model_dump()
    required = {
        "query_cv_run_id",
        "query_observation_id",
        "candidate_cv_run_id",
        "candidate_observation_id",
        "case_id",
        "candidate_video_provenance",
        "candidate_original_frame_number",
        "candidate_original_video_timestamp_seconds",
        "similarity_score",
        "rank",
        "model_provenance",
        "human_review_status",
        "verification_status",
        "requires_human_verification",
    }
    assert required <= set(payload)
    assert payload["verification_status"] == "candidate_only"
    assert payload["requires_human_verification"] is True
    assert payload["candidate_disclaimer"] == CV_CANDIDATE_DISCLAIMER
    assert isinstance(payload["model_provenance"], list)
    assert "embedding" not in payload
    assert "embedding_vector" not in payload
    assert "crop_bytes" not in payload
    assert "crop_path" not in candidate.model_dump()
    assert "crop_path" not in observation.model_dump()
    assert observation.crop.crop_id == "crop-opaque-1"
    assert observation.crop.retrieval_state == "not_supported"
    assert observation.video_provenance.source_video_sha256 == digest
    assert observation.video_provenance.normalized_video_sha256 == derivative_digest
    assert observation.verification_status == "candidate_only"
    assert observation.review_flags.mask == "not_assessed"
    assert observation.review_flags.helmet == "not_assessed"
    assert observation.review_flags.cap == "not_assessed"
    assert "confirmed" not in observation.review_flags.model_dump()


def test_cv_contract_rejects_invalid_lifecycle_review_crop_and_derivative_values():
    from pydantic import ValidationError

    from app.schemas import (
        CvBudgetSummary,
        CvCropSummary,
        CvHumanReviewDecision,
        CvRunSummary,
        CvTruncationSummary,
        CvVideoProvenance,
    )

    digest = "b" * 64
    video_provenance = CvVideoProvenance(source_video_id="video-1", source_video_sha256=digest)
    budget = CvBudgetSummary(
        requested_max_frames=10,
        analyzed_frames=10,
        frame_stride=1,
        max_analysis_frames=300,
        max_frame_stride=20,
        max_decoded_frames=3000,
        max_clip_duration_seconds=300,
        max_top_k=25,
        max_response_bytes=750000,
        concurrent_analyses=1,
    )
    with pytest.raises(ValidationError, match="status"):
        CvRunSummary(
            cv_run_id="run-1",
            case_id="case-1",
            video_provenance=video_provenance,
            status="done",
            window_mode="full_video",
            analysis_run_id="analysis-1",
            created_at="2026-11-22T00:00:00Z",
            budget=budget,
            truncation=CvTruncationSummary(),
        )
    with pytest.raises(ValidationError, match="decision"):
        CvHumanReviewDecision(
            decision_id="review-1",
            case_id="case-1",
            cv_run_id="run-1",
            target_type="candidate",
            target_id="candidate-1",
            decision="approved",
            created_at="2026-11-22T00:00:00Z",
        )
    with pytest.raises(ValidationError, match="available crop"):
        CvCropSummary(status="available", crop_id=None)
    with pytest.raises(ValidationError, match="normalized"):
        CvVideoProvenance(source_video_id="video-1", source_video_sha256=digest, derivative_kind="normalized")
    needs_review = CvHumanReviewDecision(
        decision_id="review-2",
        case_id="case-1",
        cv_run_id="run-1",
        target_type="candidate",
        target_id="candidate-1",
        decision="needs_review",
        created_at="2026-11-22T00:00:00Z",
    )
    assert needs_review.reviewer_note is None


def test_cv_contract_candidate_search_scope_has_no_client_exclusion_option():
    from pydantic import ValidationError

    from app.schemas import CvCandidateSearchRequest

    base = {
        "case_id": "case-1",
        "query_cv_run_id": "run-1",
        "query_observation_id": "obs-1",
    }
    default = CvCandidateSearchRequest(**base)
    default_payload = default.model_dump()
    assert default.scope == "case_all_eligible_videos"
    assert default.source_video_ids == []
    assert "exclude_query_source" not in default_payload

    selected = CvCandidateSearchRequest(**base, scope="case_selected_videos", source_video_ids=["video-2"])
    assert selected.scope == "case_selected_videos"
    assert "exclude_query_source" not in selected.model_dump()

    with pytest.raises(ValidationError, match="source_video_ids are required"):
        CvCandidateSearchRequest(**base, scope="case_selected_videos")
    with pytest.raises(ValidationError, match="only valid"):
        CvCandidateSearchRequest(**base, source_video_ids=["video-2"])


def test_cv_contract_timestamp_and_window_semantics():
    from pydantic import ValidationError

    from app.schemas import CvAnalysisWindow, CvTimestampProvenance, CvVideoProvenance

    digest = "c" * 64
    video_provenance = CvVideoProvenance(source_video_id="video-1", source_video_sha256=digest)
    timestamp = CvTimestampProvenance(
        cv_run_id="run-1",
        analysis_run_id="analysis-1",
        video_provenance=video_provenance,
        transaction_utc="2026-11-22T00:00:00Z",
        cctv_clock_utc="2026-11-22T00:00:30Z",
        applied_alignment_offset_seconds=30.0,
        transaction_video_seconds=100.0,
        window_start_seconds=80.0,
        window_end_seconds=120.0,
    )
    assert timestamp.timebase == "source_video_seconds"
    assert timestamp.video_provenance.source_video_id == "video-1"
    assert timestamp.applied_alignment_offset_seconds == 30.0

    window = CvAnalysisWindow(
        mode="transaction_aligned",
        start_seconds=0.0,
        end_seconds=200.0,
        duration_seconds=200.0,
        source_video_duration_seconds=200.0,
        is_full_video=False,
        before_seconds=150.0,
        after_seconds=50.0,
        clamped=True,
        warnings=["window_start_clamped_to_zero"],
    )
    assert window.clamped is True
    with pytest.raises(ValidationError, match="within source_video_duration_seconds"):
        CvAnalysisWindow(
            mode="full_video",
            start_seconds=0.0,
            end_seconds=201.0,
            duration_seconds=201.0,
            source_video_duration_seconds=200.0,
            is_full_video=True,
        )


def test_existing_cv_request_and_status_contracts_are_unchanged(client):
    from app.schemas import CVAnalyzeRequest

    request = CVAnalyzeRequest(video_id="video-1")
    assert request.model_dump() == {
        "video_id": "video-1",
        "max_frames": None,
        "frame_stride": 1,
        "save_crops": False,
        "add_to_index": False,
        "rank": False,
        "summary_only": False,
        "top_k": 5,
        "labels": None,
    }

    response = client.get("/api/cv/status")
    assert response.status_code == 200
    required = {
        "models",
        "runtime",
        "opencv_version",
        "thresholds",
        "person_detection",
        "limits",
        "synchronous_analysis",
        "embedding_store",
        "limitations",
        "disclaimer",
    }
    assert required <= set(response.json())
