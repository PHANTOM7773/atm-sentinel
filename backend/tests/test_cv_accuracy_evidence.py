from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest

from app.cv.errors import CVError
from app.cv.pipeline import CVPipeline
from app.cv.quality import analyze_face_quality
from app.cv.types import FaceDetection, FrameAnalysis
from app.schemas import CvRunCreateRequest, CvTruncationSummary
from app.services import cv_integration as integration

WIDTH = 160
HEIGHT = 120
FPS = 10.0


class StubFaceDetector:
    def __init__(self, scenario: str) -> None:
        self.scenario = scenario
        self.frame_number = 0

    def detect(self, frame: np.ndarray) -> list[FaceDetection]:
        frame_number = self.frame_number
        self.frame_number += 1
        if self.scenario == "no_face":
            return []
        if self.scenario == "multi_person":
            return [
                _face(1, (10, 20, 40, 55)),
                _face(2, (100, 22, 42, 56)),
            ]
        if self.scenario == "entering_leaving":
            if frame_number < 2 or frame_number > 5:
                return []
            return [_face(1, (50, 30, 60, 70))]
        if self.scenario == "side_facing":
            return [_face(1, (58, 28, 42, 66), eye_shift=12)]
        if self.scenario == "small_distant":
            return [_face(1, (70, 50, 16, 20))]
        return [_face(1, (50, 28, 60, 72))]


def _face(
    track_id: int,
    bbox: tuple[float, float, float, float],
    *,
    eye_shift: float = 0,
) -> FaceDetection:
    x, y, width, height = bbox
    right_eye = (x + width * 0.35 - eye_shift, y + height * 0.38)
    left_eye = (x + width * 0.65 + eye_shift, y + height * 0.38)
    nose = (x + width * 0.5, y + height * 0.55)
    right_mouth = (x + width * 0.38, y + height * 0.72)
    left_mouth = (x + width * 0.62, y + height * 0.72)
    return FaceDetection(
        bbox=bbox,
        confidence=0.9,
        landmarks=(right_eye, left_eye, nose, right_mouth, left_mouth),
        track_id=track_id,
    )


def _write_video(path: Path, frame_count: int, *, scenario: str) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    assert writer.isOpened()
    try:
        for index in range(frame_count):
            frame = np.full((HEIGHT, WIDTH, 3), 180, dtype=np.uint8)
            cv2.rectangle(frame, (20, 15), (WIDTH - 20, HEIGHT - 15), (30, 60, 90), 2)
            cv2.putText(frame, f"{scenario}-{index}", (8, HEIGHT - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.25, (240, 240, 240), 1)
            if scenario == "entering_leaving":
                for bit in range(4):
                    if index & (1 << bit):
                        cv2.rectangle(frame, (50 + bit * 15, 35), (62 + bit * 15, 95), (250, 250, 250), -1)
            if scenario == "low_illumination":
                frame = (frame * 0.12).astype(np.uint8)
            if scenario == "motion_blur":
                frame = cv2.GaussianBlur(frame, (11, 11), 0)
            if scenario == "partial_occlusion":
                cv2.rectangle(frame, (55, 35), (105, 90), (0, 0, 0), -1)
            if scenario == "duplicate":
                frame = np.full((HEIGHT, WIDTH, 3), 180, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return path


def _pipeline(tmp_path: Path, scenario: str) -> CVPipeline:
    pipeline = CVPipeline(
        load_face=False,
        load_person=False,
        load_embedder=False,
        output_dir=tmp_path / "output",
        crop_dir=tmp_path / "crops",
    )
    pipeline.face_detector = StubFaceDetector(scenario)
    return pipeline


SCENARIOS = (
    "front_facing",
    "side_facing",
    "multi_person",
    "no_face",
    "low_illumination",
    "motion_blur",
    "partial_occlusion",
    "small_distant",
    "duplicate",
    "entering_leaving",
)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_synthetic_video_fixtures_analyze_without_writing_project_data(
    tmp_path: Path,
    scenario: str,
) -> None:
    video = _write_video(tmp_path / f"synthetic_{scenario}.mp4", 8, scenario=scenario)
    pipeline = _pipeline(tmp_path, scenario)
    result = pipeline.analyze_video(
        video,
        case_id=f"synthetic-{scenario}",
        source_id=f"synthetic-{scenario}",
        max_frames=8,
        frame_stride=1,
        save_crops=False,
        add_to_index=False,
        run_id=f"synthetic-{scenario}-run",
        retain_observations=True,
    )
    payload = result.to_dict()
    assert payload["analyzed_frame_count"] == 8
    assert len(payload["frames"]) == 8
    assert payload["summary"]["face_detections"] >= 0
    if scenario == "no_face":
        assert payload["summary"]["face_detections"] == 0
    if scenario == "multi_person":
        assert payload["summary"]["unique_face_tracks"] == 2
    if scenario == "entering_leaving":
        face_frames = [frame for frame in payload["frames"] if frame["faces"]]
        assert {frame["frame_number"] for frame in face_frames} == {2, 3, 4, 5}
        assert [frame["timestamp"] for frame in face_frames] == pytest.approx([0.2, 0.3, 0.4, 0.5])
        assert payload["summary"]["face_detections"] == 4
        assert payload["summary"]["retained_face_observations"] == 4
        assert payload["summary"]["near_duplicate_faces_suppressed"] == 0


def test_quality_size_uses_detected_bbox_not_padded_crop() -> None:
    crop = np.full((120, 120, 3), 128, dtype=np.uint8)
    small = analyze_face_quality(crop, bbox=(10, 10, 20, 20))
    large = analyze_face_quality(crop, bbox=(10, 10, 100, 100))
    assert small["face_size_px"] == 20
    assert small["crop_size_px"] == 120
    assert large["components"]["size_component"] > small["components"]["size_component"]


def test_occlusion_review_flag_is_preserved() -> None:
    crop = np.full((80, 80, 3), 128, dtype=np.uint8)
    landmarks = ((5, 5), (70, 5), (40, 40), (500, 500), (-500, 500))
    quality = analyze_face_quality(crop, landmarks=landmarks, bbox=(0, 0, 60, 60))
    assert quality["occlusion_status"] == "review"
    assert quality["flags"]["occlusion_review"] is True
    assert any("borderline" in warning for warning in quality["warnings"])


def test_near_duplicate_faces_are_suppressed_but_reported(tmp_path: Path) -> None:
    video = _write_video(tmp_path / "synthetic_duplicate_frames.mp4", 8, scenario="duplicate")
    pipeline = _pipeline(tmp_path, "duplicate")
    result = pipeline.analyze_video(
        video,
        case_id="synthetic-duplicate",
        source_id="synthetic-duplicate",
        max_frames=8,
        frame_stride=1,
        save_crops=False,
        add_to_index=False,
        run_id="synthetic-duplicate-run",
        retain_observations=True,
    )
    payload = result.to_dict()
    assert payload["summary"]["face_detections"] == 8
    assert payload["summary"]["retained_face_observations"] == 1
    assert payload["summary"]["near_duplicate_faces_suppressed"] == 7
    assert "near_duplicate_faces_suppressed" in payload["truncation"]


def test_invalid_video_fixture_is_rejected(tmp_path: Path) -> None:
    invalid = tmp_path / "synthetic_invalid.mp4"
    invalid.write_bytes(b"not a video")
    pipeline = _pipeline(tmp_path, "front_facing")
    with pytest.raises(CVError):
        pipeline.analyze_video(invalid, case_id="synthetic-invalid", max_frames=2)


def test_crop_failure_is_exposed_as_unavailable() -> None:
    request = CvRunCreateRequest(case_id="case", video_id="video")
    video = {"sha256": "a" * 64}
    analysis = {
        "frames": [
            {
                "frame_number": 0,
                "timestamp": 0.0,
                "faces": [
                    {
                        "sample_id": "sample",
                        "observation_id": "observation",
                        "analysis_run_id": "run",
                        "frame_number": 0,
                        "timestamp": 0.0,
                        "bbox": [10, 10, 20, 20],
                        "detector_confidence": 0.9,
                        "quality": {"quality_score": 70.0},
                        "pose": {"frontal_score": 0.7},
                        "flags": {},
                        "crop_state": "failed",
                    }
                ],
            }
        ]
    }
    observations = integration._observations_from_analysis(analysis, request, video, "cv-run", "run")
    assert observations[0]["crop_status"] == "unavailable"
    truncation = integration._truncation(
        {"truncation": {"face_observations_with_unavailable_crops": 1}}
    )
    assert truncation["crop_observations_unavailable"] == 1
    assert "crop_unavailable" in truncation["reasons"]
    assert CvTruncationSummary(**truncation).crop_observations_unavailable == 1


def test_near_duplicate_suppression_is_not_double_counted() -> None:
    truncation = integration._truncation(
        {
            "truncation": {
                "face_observations_dropped_by_analysis": 7,
                "near_duplicate_faces_suppressed": 7,
            }
        }
    )
    assert truncation["face_observations_omitted"] == 7
    assert truncation["near_duplicate_faces_suppressed"] == 7
    assert "face_observation_budget" not in truncation["reasons"]
    assert CvTruncationSummary(**truncation).near_duplicate_faces_suppressed == 7


def _window_request() -> CvRunCreateRequest:
    return CvRunCreateRequest(
        case_id="case",
        video_id="video",
        transaction_id="tx",
        transaction_ts="2026-01-15T09:00:03+00:00",
        cctv_ts="2026-01-15T09:00:03+00:00",
        video_start_ts="2026-01-15T09:00:00+00:00",
        window_mode="transaction_aligned",
        before_seconds=1,
        after_seconds=1,
    )


def _window() -> dict[str, Any]:
    return {
        "start_seconds": 2.0,
        "end_seconds": 4.0,
        "duration_seconds": 2.0,
        "source_video_duration_seconds": 6.0,
        "is_full_video": False,
        "warnings": [],
    }


def _patch_window_capture(monkeypatch: Any, *, seek_mismatch: bool = False) -> list[int]:
    analyzed: list[int] = []

    class FakeCapture:
        def __init__(self, path: Any) -> None:
            self.index = 0

        def isOpened(self) -> bool:
            return True

        def set(self, property_id: int, value: int) -> bool:
            self.index = int(value)
            return True

        def get(self, property_id: int) -> float:
            return float(0 if seek_mismatch else self.index)

        def read(self) -> tuple[bool, Any]:
            if self.index >= 60:
                return False, None
            current = self.index
            self.index += 1
            return True, current

        def release(self) -> None:
            return None

    class FakePipeline:
        runtime = {"fake": True}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def begin_analysis(self, analysis_run_id: str) -> str:
            return analysis_run_id

        def analyze_frame(self, frame: Any, frame_number: int = 0, timestamp: float = 0.0, **kwargs: Any) -> FrameAnalysis:
            analyzed.append(int(frame_number))
            return FrameAnalysis(
                frame_number=int(frame_number),
                timestamp=float(timestamp),
                faces=[],
                persons=[],
                counts={"faces": 0, "persons": 0},
                total_counts={"faces": 0, "persons": 0},
                truncation={},
                duration_ms=1.0,
            )

        def _apply_analysis_caps(self, frames: list[FrameAnalysis]) -> tuple[list[FrameAnalysis], dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
                "near_duplicate_faces_suppressed": 0,
            }

    monkeypatch.setattr(integration.cv2, "VideoCapture", lambda path: FakeCapture(path))
    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)
    return analyzed


def test_window_analysis_includes_inclusive_end_boundary(monkeypatch: Any) -> None:
    analyzed = _patch_window_capture(monkeypatch)
    _, payload, _ = integration._run_window_analysis(
        _window_request(),
        "cv-run",
        {"fps": FPS},
        Path("synthetic_window.mp4"),
        _window(),
        "analysis-run",
    )
    assert analyzed[0] == 20
    assert analyzed[-1] == 40
    assert len(analyzed) == 21
    assert payload["frame_count"] == 21
    assert payload["frames"][-1]["timestamp"] == pytest.approx(4.0)


def test_window_analysis_rejects_unverified_seek(monkeypatch: Any) -> None:
    _patch_window_capture(monkeypatch, seek_mismatch=True)
    with pytest.raises(integration.IntegrationError):
        integration._run_window_analysis(
            _window_request(),
            "cv-run",
            {"fps": FPS},
            Path("synthetic_window.mp4"),
            _window(),
            "analysis-run",
        )
