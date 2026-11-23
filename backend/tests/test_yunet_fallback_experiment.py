from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.cv.face_detection_experiments import DetectionRecord
from app.cv.types import FaceDetection
from app.cv.yunet_fallback_experiment import (
    FallbackStrategy,
    detect_with_strategy,
    evaluate_fallback_strategies,
)


def _lm(x, y):
    return tuple((float(x + i), float(y + i)) for i in range(5))


class FakeDetector:
    def __init__(self, fn):
        self.fn = fn
        self.calls = []

    def detect(self, image):
        h, w = image.shape[:2]
        self.calls.append((w, h))
        return self.fn(w, h)


def test_zero_detection_fallback_triggers_and_preserves_timestamp():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def fn(w, h):
        if w == 100:
            return []
        return [FaceDetection(bbox=(30, 30, 20, 20), confidence=0.8, landmarks=_lm(35, 35))]

    det = FakeDetector(fn)
    strat = FallbackStrategy("z", "zero_detection_fallback", "z", fallback_scale=1.5)
    res = detect_with_strategy(frame, detector=det, strategy=strat, frame_number=3, timestamp=0.3)
    assert res.fallback_triggered is True
    assert res.fallback_reason == "baseline_zero_detections"
    assert res.timestamp == 0.3
    assert len(res.baseline_detections) == 0
    assert len(res.fallback_detections) == 1
    assert len(res.final_detections) == 1
    assert res.final_detections[0].bbox[0] == 20.0 and res.final_detections[0].bbox[1] == 20.0


def test_no_fallback_when_zero_detection_not_met():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeDetector(lambda w, h: [FaceDetection(bbox=(10, 10, 20, 20), confidence=0.9, landmarks=_lm(12, 12))])
    strat = FallbackStrategy("z", "zero_detection_fallback", "z", fallback_scale=1.5)
    res = detect_with_strategy(frame, detector=det, strategy=strat, frame_number=1, timestamp=0.1)
    assert res.fallback_triggered is False
    assert res.fallback_detections == []
    assert len(res.final_detections) == 1


def test_confidence_fallback_triggered_below_threshold():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def fn(w, h):
        if w == 100:
            return [FaceDetection(bbox=(10, 10, 20, 20), confidence=0.6, landmarks=_lm(12, 12))]
        return [FaceDetection(bbox=(15, 15, 30, 30), confidence=0.85, landmarks=_lm(18, 18))]

    det = FakeDetector(fn)
    strat = FallbackStrategy("c", "confidence_fallback", "c", fallback_scale=1.5, confidence_threshold=0.75)
    res = detect_with_strategy(frame, detector=det, strategy=strat, frame_number=1, timestamp=0.1)
    assert res.fallback_triggered is True
    assert "baseline_max_conf_below" in (res.fallback_reason or "")
    assert len(res.final_detections) >= 1


def test_confidence_fallback_not_triggered_at_or_above_threshold():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeDetector(lambda w, h: [FaceDetection(bbox=(10, 10, 20, 20), confidence=0.8, landmarks=_lm(12, 12))])
    strat = FallbackStrategy("c", "confidence_fallback", "c", fallback_scale=1.5, confidence_threshold=0.75)
    res = detect_with_strategy(frame, detector=det, strategy=strat, frame_number=1, timestamp=0.1)
    assert res.fallback_triggered is False


def test_duplicate_suppression_and_coord_preservation():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    def fn(w, h):
        if w == 100:
            return [FaceDetection(bbox=(10, 10, 20, 20), confidence=0.7, landmarks=_lm(12, 12))]
        # same box in upscaled coords -> maps to same original
        return [FaceDetection(bbox=(15, 15, 30, 30), confidence=0.9, landmarks=_lm(18, 18))]

    det = FakeDetector(fn)
    strat = FallbackStrategy("full", "full_upscale", "full", fallback_scale=1.5)
    res = detect_with_strategy(frame, detector=det, strategy=strat, frame_number=1, timestamp=0.1, dedupe_iou=0.5)
    assert res.fallback_triggered is True
    assert len(res.baseline_detections) == 1
    assert len(res.fallback_detections) == 1
    assert len(res.final_detections) == 1
    assert res.final_detections[0].confidence == 0.9
    assert res.final_detections[0].bbox[0] == 10.0


def test_fallback_failure_preserves_baseline():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    class Det:
        def detect(self, image):
            w = image.shape[1]
            if w == 100:
                return [FaceDetection(bbox=(10, 10, 20, 20), confidence=0.6, landmarks=_lm(12, 12))]
            raise RuntimeError("boom")

    strat = FallbackStrategy("c", "confidence_fallback", "c", fallback_scale=1.5, confidence_threshold=0.75)
    res = detect_with_strategy(frame, detector=Det(), strategy=strat, frame_number=1, timestamp=0.1)
    assert res.fallback_triggered is True
    assert len(res.baseline_detections) == 1
    assert len(res.fallback_detections) == 0
    assert len(res.final_detections) == 1


def test_evaluate_fallback_strategies_deterministic(tmp_path: Path):
    import cv2

    ds = tmp_path / "ds"
    ds.mkdir()
    vw = cv2.VideoWriter(str(ds / "a.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    vw.write(np.zeros((32, 32, 3), dtype=np.uint8))
    vw.write(np.full((32, 32, 3), 120, dtype=np.uint8))
    vw.release()
    manifest = {"synthetic": True, "real_people": False, "notice": "s", "videos": {"clip_a": {"file": "a.mp4", "frame_count": 2, "description": "a", "labels": {"0": "SYN-A", "1": "none"}}}}
    (ds / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    class Det:
        def detect(self, image):
            if image.shape[1] > 32:
                return [FaceDetection(bbox=(1, 1, 10, 10), confidence=0.9, landmarks=_lm(2, 2))] if int(image[0, 0, 0]) == 0 else []
            return []

    strats = [FallbackStrategy("baseline_only", "baseline_only", "b"), FallbackStrategy("zero_detection_fallback_1_5x", "zero_detection_fallback", "z", 1.5)]
    r1 = evaluate_fallback_strategies(ds, strategies=strats, include_confidence_strategies=False, detector_factory=Det)
    r2 = evaluate_fallback_strategies(ds, strategies=strats, include_confidence_strategies=False, detector_factory=Det)
    s1 = r1["strategies"]["zero_detection_fallback_1_5x"]["clips"]["clip_a"]
    s2 = r2["strategies"]["zero_detection_fallback_1_5x"]["clips"]["clip_a"]
    assert s1["tp"] == s2["tp"] == 1
    assert s1["fp"] == s2["fp"] == 0
    assert s1["fallback_invocations"] == s2["fallback_invocations"]
