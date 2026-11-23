from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CV_ASSETS = ROOT / "data" / "datasets" / "synthetic" / "cv"


@pytest.fixture(scope="module")
def real_models():
    from app.config import CV_MODEL_DIR
    from app.cv.models import MODEL_SPECS, model_status

    missing = [
        spec.filename
        for spec in MODEL_SPECS.values()
        if not (ROOT / "data" / "models" / spec.filename).is_file()
    ]
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


def _asset(name: str) -> Path:
    path = CV_ASSETS / name
    if not path.is_file():
        pytest.skip(f"Missing synthetic CV test asset: {path}")
    return path


def _face_observation(record: dict[str, Any]) -> dict[str, Any]:
    from app.config import absolute_from_data

    crop_path = Path(str(record.get("crop_path") or ""))
    if crop_path and not crop_path.is_absolute():
        crop_path = absolute_from_data(str(crop_path))
    crop_retrievable = bool(record.get("crop_path")) and crop_path.is_file() and crop_path.stat().st_size > 0
    return {
        "observation_id": str(record["observation_id"]),
        "cv_sample_id": str(record["sample_id"]),
        "cv_run_id": "best-face-real-run",
        "case_id": "best-face-real-case",
        "original_frame_number": int(record["frame_number"]),
        "original_video_timestamp_seconds": float(record["timestamp"]),
        "bbox": list(record["bbox"]),
        "detector_confidence": float(record["detector_confidence"]),
        "track_id": record.get("track_id"),
        "quality": record["quality"],
        "pose": record["pose"],
        "review_flags": record["flags"],
        "crop": {
            "crop_id": str(record["observation_id"]),
            "available": crop_retrievable,
            "status": "available" if crop_retrievable else "unavailable",
            "retrieval_state": "retrievable" if crop_retrievable else "expired",
        },
    }


def _person_observation(record: dict[str, Any]) -> dict[str, Any]:
    x, y, width, height = [float(value) for value in record["bbox"][:4]]
    return {
        "observation_id": f"person-{record['observation_id']}",
        "track_id": 7,
        "frame_number": int(record["frame_number"]),
        "timestamp": float(record["timestamp"]),
        "bbox": [max(0.0, x - 80.0), max(0.0, y - 20.0), width + 160.0, height + 220.0],
        "detector_confidence": 0.8,
    }


def test_real_yunet_quality_feeds_best_face_selection(real_models) -> None:
    from app.cv.pipeline import CVPipeline
    from app.services.best_face import select_from_observations

    pipeline = CVPipeline()
    analysis = pipeline.analyze_video(
        _asset("subject_a_front.mp4"),
        case_id="best-face-real-case",
        source_id="best-face-front",
        max_frames=12,
        save_crops=True,
        cv_run_id="best-face-real-run",
        video_id="best-face-front",
    )
    face_records = [face for frame in analysis.frames for face in frame.faces]
    assert analysis.summary["face_detections"] > 0
    assert face_records

    faces = [_face_observation(record) for record in face_records]
    persons = [_person_observation(record) for record in face_records]
    association = {
        "association_id": "best-face-real-association",
        "case_id": "best-face-real-case",
        "cv_run_id": "best-face-real-run",
        "person_track_id": 7,
        "review_state": "proposed",
    }
    payload = select_from_observations(association, faces, persons)

    considered = payload["ranked_frames"] + payload["rejected_frames"] + payload["other_person_frames"]
    assert considered
    source_by_id = {face["observation_id"]: face for face in faces}
    for item in considered:
        observation_id = item["observation"]["observation_id"]
        source = source_by_id[observation_id]
        assert item["quality_indicators"]["quality_score"] == source["quality"]["quality_score"]
        assert item["rationale"]

    if payload["selected"] is None:
        assert payload["no_selection_reason"] == "no_eligible_face_for_person"
    else:
        selected_id = payload["selected"]["observation"]["observation_id"]
        assert selected_id in source_by_id
        assert payload["selected"]["rank"] == 1
        assert payload["selected"]["quality_indicators"]["quality_score"] == source_by_id[selected_id]["quality"]["quality_score"]
        assert payload["selected"]["link"]["person_track_id"] == 7
        reliability = payload["selected"]["reliability"]
        assert reliability["status"] in {"usable", "limited", "poor", "not_assessed"}
        assert reliability["requires_human_verification"] is True
        assert any(i["name"] == "potential_concealment" and i["measured"]["mask"] == "not_assessed" for i in reliability["indicators"])
