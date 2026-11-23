from pathlib import Path
import shutil
import uuid

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
CV_ASSETS = ROOT / "data" / "datasets" / "synthetic" / "cv"


@pytest.fixture(scope="module")
def real_models():
    from app.config import CV_MODEL_DIR
    from app.cv.models import MODEL_SPECS, model_status

    missing = [spec.filename for spec in MODEL_SPECS.values() if not (ROOT / "data" / "models" / spec.filename).is_file()]
    if missing:
        pytest.skip("Missing pinned model files: " + ", ".join(missing))

    CV_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for spec in MODEL_SPECS.values():
        source = ROOT / "data" / "models" / spec.filename
        shutil.copy2(source, CV_MODEL_DIR / spec.filename)

    status = model_status()
    assert status["all_usable"] is True
    for item in status["models"].values():
        assert item["verification"] == "verified"
    return CV_MODEL_DIR


def _asset(name):
    path = CV_ASSETS / name
    if not path.is_file():
        pytest.skip(f"Missing synthetic CV test asset: {path}")
    return path


def test_real_yolox_person_detection_on_synthetic_asset(real_models):
    from app.cv.detection import YOLOXPersonDetector

    detector = YOLOXPersonDetector(score_threshold=0.1)
    capture = cv2.VideoCapture(str(_asset("subject_a_front.mp4")))
    assert capture.isOpened()
    detections = 0
    frames = 0
    try:
        while frames < 20:
            ok, image = capture.read()
            if not ok:
                break
            detections += len(detector.detect(image))
            frames += 1
    finally:
        capture.release()

    assert frames > 0
    assert detections > 0


def test_real_yunet_sface_and_quality_on_synthetic_asset(real_models):
    from app.cv.pipeline import CVPipeline

    pipeline = CVPipeline()
    analysis = pipeline.analyze_video(
        _asset("subject_a_front.mp4"),
        case_id="p06-real-face",
        source_id="p06-front",
        max_frames=12,
        add_to_index=True,
        cv_run_id="p06-real-face-run",
        video_id="p06-front",
    )

    faces = [face for frame in analysis.frames for face in frame.faces]
    assert analysis.summary["face_detections"] > 0
    assert faces
    assert any(face.get("embedding_state") == "staged_v4_candidate" for face in faces)
    assert any(face.get("embedding_dim") == 128 for face in faces)
    for face in faces:
        quality = face["quality"]
        assert 0 <= float(quality["quality_score"]) <= 100
        assert quality["components"]
        assert "not an identity" in quality["disclaimer"]
        assert face["verification_status"] == "candidate_only"
        assert face["flags"]["identity_confirmed"] is False


def test_real_embedding_candidate_similarity_on_synthetic_assets(real_models):
    from app.cv.embeddings import EmbeddingStore
    from app.cv.pipeline import CVPipeline

    case_id = "p06-real-" + uuid.uuid4().hex
    pipeline = CVPipeline()
    store = EmbeddingStore(pipeline.output_dir)
    staged_counts = []

    for filename, source_id, run_id in (
        ("subject_a_front.mp4", "p06-gallery", "p06-gallery-run"),
        ("subject_a_side.mp4", "p06-query", "p06-query-run"),
    ):
        pipeline.analyze_video(
            _asset(filename),
            case_id=case_id,
            source_id=source_id,
            max_frames=12,
            add_to_index=True,
            cv_run_id=run_id,
            video_id=source_id,
        )
        staged = pipeline.staged_embeddings()
        staged_counts.append(len(staged))
        assert store.publish_staged_records(staged) == len(staged)
        if source_id == "p06-query":
            query_analysis = pipeline.analyze_video(
                _asset(filename),
                case_id=case_id,
                source_id=source_id,
                max_frames=12,
                retain_observations=True,
            )
            query_face = next(face for frame in query_analysis.frames for face in frame.faces if face.get("embedding"))

    assert all(count > 0 for count in staged_counts)
    hits = store.search(
        np.asarray(query_face["embedding"], dtype=np.float32),
        case_id=case_id,
        top_k=5,
        exclude_sample_id=query_face["sample_id"],
        exclude_source_id="p06-query",
    )
    assert hits
    assert all(hit["metadata"].get("source_id") == "p06-gallery" for hit in hits)
    assert all(-1 <= float(hit["cosine_similarity"]) <= 1 for hit in hits)
    assert all(hit["verification_status"] == "candidate_only" for hit in hits)
    assert all(hit["v4_eligible"] is True for hit in hits)
