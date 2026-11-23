from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.cv.types import FaceDetection
from app.cv.yunet_person_gate_experiment import PersonGateStrategy, evaluate_frame, evaluate_person_gate_strategies


def _lm(x, y):
    return tuple((float(x + i), float(y + i)) for i in range(5))


class FakeYuNet:
    def __init__(self, fn):
        self.fn = fn

    def detect(self, image):
        h, w = image.shape[:2]
        return self.fn(w, h, image)


class FakeYOLOX:
    def __init__(self, persons=None, exc=None):
        self.persons = persons or []
        self.exc = exc

    def detect(self, image):
        if self.exc:
            raise self.exc
        return self.persons


class P:
    def __init__(self, bbox, confidence=0.9, class_id=0):
        self.bbox = bbox
        self.confidence = confidence
        self.class_id = class_id


def test_person_gated_zero_fallback_skips_without_person():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeYuNet(lambda w, h, img: [] if w == 100 else [FaceDetection((10, 10, 20, 20), 0.9, _lm(10, 10))])
    strat = PersonGateStrategy("pg", "person_gated_zero_fallback", "pg", safety_on_no_person="skip_fallback")
    res = evaluate_frame(frame, frame_number=1, timestamp=0.1, gt_label="SYN-A", detector=det, person_detector=FakeYOLOX([]), strategy=strat)
    assert res.fallback_triggered is False
    assert res.safety_policy_applied == "skip_fallback_on_no_person"
    assert res.final_detections == []


def test_person_gated_zero_fallback_runs_with_person():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeYuNet(lambda w, h, img: [] if w == 100 else [FaceDetection((30, 30, 20, 20), 0.9, _lm(30, 30))])
    strat = PersonGateStrategy("pg", "person_gated_zero_fallback", "pg", safety_on_no_person="skip_fallback")
    res = evaluate_frame(frame, frame_number=1, timestamp=0.1, gt_label="SYN-A", detector=det, person_detector=FakeYOLOX([P((0, 0, 100, 100), 0.9)]), strategy=strat)
    assert res.fallback_triggered is True
    assert res.person_gate_passed is True
    assert len(res.final_detections) == 1


def test_safety_fallback_runs_when_no_person():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeYuNet(lambda w, h, img: [] if w == 100 else [FaceDetection((30, 30, 20, 20), 0.9, _lm(30, 30))])
    strat = PersonGateStrategy("sf", "safety_fallback", "sf", safety_on_no_person="run_fallback")
    res = evaluate_frame(frame, frame_number=1, timestamp=0.1, gt_label="SYN-A", detector=det, person_detector=FakeYOLOX([]), strategy=strat)
    assert res.fallback_triggered is True
    assert res.safety_policy_applied == "run_fallback_on_no_person"
    assert len(res.final_detections) == 1


def test_person_detector_error_safety_run_fallback():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = FakeYuNet(lambda w, h, img: [] if w == 100 else [FaceDetection((30, 30, 20, 20), 0.9, _lm(30, 30))])
    strat = PersonGateStrategy("sf", "safety_fallback", "sf", safety_on_person_error="run_fallback")
    res = evaluate_frame(frame, frame_number=1, timestamp=0.1, gt_label="SYN-A", detector=det, person_detector=FakeYOLOX(exc=RuntimeError("boom")), strategy=strat)
    assert res.person_error is not None
    assert res.fallback_triggered is True
    assert res.safety_policy_applied == "run_fallback_on_person_error"
    assert len(res.final_detections) == 1


def test_person_region_maps_coordinates_and_handles_multiple_persons():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    # When upscaled region is requested, detector returns a face in that upscaled region coords.
    def fn(w, h, img):
        # baseline full frame 100x100 -> no detection
        if w == 100 and h == 100:
            return []
        # upscaled person region crops will be larger than 50 in this test; return a face near (5,5) in region-local upscaled coords
        return [FaceDetection((10, 10, 20, 20), 0.9, _lm(10, 10))]
    det = FakeYuNet(fn)
    strat = PersonGateStrategy("pr", "person_region", "pr", fallback_scale=1.5, safety_on_no_person="skip_fallback", region_padding=0.0)
    persons = [FakeYOLOX.__class__]  # not used
    class P2:
        def __init__(self,b,c): self.bbox=b; self.confidence=c; self.class_id=0
    res = evaluate_frame(frame, frame_number=1, timestamp=0.5, gt_label="SYN-A", detector=det, person_detector=FakeYOLOX([P2((10,10,30,30),0.9), P2((60,60,30,30),0.9)]), strategy=strat)
    assert res.fallback_triggered is True
    assert res.timestamp == 0.5
    assert len(res.final_detections) >= 1
    for d in res.final_detections:
        x,y,w2,h2 = d.bbox
        assert 0 <= x < 100 and 0 <= y < 100


def test_deterministic_evaluation_and_no_face(tmp_path: Path):
    import cv2
    ds = tmp_path / "ds"
    ds.mkdir()
    vw = cv2.VideoWriter(str(ds / "nf.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    vw.write(np.full((32,32,3),120,dtype=np.uint8))
    vw.release()
    manifest = {"synthetic": True, "real_people": False, "notice": "s", "videos": {"no_face": {"file": "nf.mp4", "frame_count": 1, "description": "n", "labels": {}}}}
    (ds / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    class Det:
        def detect(self, image): return []
    class PDet:
        def detect(self, image): return []
    strats = [PersonGateStrategy("baseline_yunet","baseline","b"), PersonGateStrategy("zero_detection_fallback_1_5x","zero_fallback","z")]
    r1 = evaluate_person_gate_strategies(ds, strategies=strats, detector_factory=Det, person_detector_factory=PDet)
    r2 = evaluate_person_gate_strategies(ds, strategies=strats, detector_factory=Det, person_detector_factory=PDet)
    a=r1["strategies"]["zero_detection_fallback_1_5x"]["clips"]["no_face"]
    b=r2["strategies"]["zero_detection_fallback_1_5x"]["clips"]["no_face"]
    assert a["fp"] == b["fp"] == 0
    assert a["tn"] == b["tn"] == 1
