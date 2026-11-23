from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.cv.detection import YuNetFaceDetector
from app.cv.face_detection_experiments import (
    ExperimentalVariant,
    dedupe_detections,
    detect_with_variant,
    scale_detection_to_original,
)
from app.cv.types import FaceDetection
from app.cv.yunet_recall_experiment import NOT_ASSESSABLE, evaluate_yunet_variants


class FakeYuNet:
    def __init__(self, responses_by_scale):
        self.responses_by_scale = responses_by_scale
        self.calls = []

    def detect(self, image):
        h, w = image.shape[:2]
        self.calls.append((w, h))
        # infer scale by width relative to original 100 for tests
        scale = w / 100.0
        key = round(scale, 3)
        dets = self.responses_by_scale.get(key, [])
        return [FaceDetection(bbox=d["bbox"], confidence=d["confidence"], landmarks=d["landmarks"]) for d in dets]


def _lm(x, y):
    return tuple((float(x + i), float(y + i)) for i in range(5))


def test_scale_detection_to_original_maps_bbox_and_landmarks():
    det = FaceDetection(bbox=(20, 10, 40, 50), confidence=0.9, landmarks=_lm(30, 20))
    rec = scale_detection_to_original(det, scale=2.0, orig_w=100, orig_h=100)
    assert rec is not None
    assert rec.bbox == (10.0, 5.0, 20.0, 25.0)
    assert rec.landmarks[0] == (15.0, 10.0)
    assert rec.scale == 2.0


def test_dedupe_detections_removes_overlapping_lower_confidence():
    a = scale_detection_to_original(FaceDetection(bbox=(10, 10, 20, 20), confidence=0.9, landmarks=_lm(10, 10)), 1.0, 100, 100)
    b = scale_detection_to_original(FaceDetection(bbox=(11, 11, 20, 20), confidence=0.8, landmarks=_lm(11, 11)), 1.0, 100, 100)
    c = scale_detection_to_original(FaceDetection(bbox=(60, 60, 20, 20), confidence=0.7, landmarks=_lm(60, 60)), 1.0, 100, 100)
    kept = dedupe_detections([a, b, c], iou_threshold=0.5)
    assert len(kept) == 2
    assert kept[0].confidence == 0.9


def test_detect_with_variant_preserves_timestamp_and_reports_duplicates():
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    det = {"bbox": (20, 20, 20, 20), "confidence": 0.9, "landmarks": _lm(25, 25)}
    fake = FakeYuNet({1.0: [det], 2.0: [ {"bbox": (40, 40, 40, 40), "confidence": 0.8, "landmarks": _lm(50, 50)} ]})
    variant = ExperimentalVariant("v", (1.0, 2.0), "test")
    res = detect_with_variant(frame, detector=fake, variant=variant, frame_number=7, timestamp=1.75, dedupe_iou=0.5)
    assert res.frame_number == 7
    assert res.timestamp == 1.75
    assert len(res.detections_before_dedupe) == 2
    assert len(res.detections_after_dedupe) == 1
    assert res.detections_after_dedupe[0].bbox == (20.0, 20.0, 20.0, 20.0)


def test_detect_with_variant_handles_empty_invalid_frames():
    fake = FakeYuNet({1.0: []})
    variant = ExperimentalVariant("baseline_original", (1.0,), "test")
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    res = detect_with_variant(empty, detector=fake, variant=variant, frame_number=0, timestamp=0.0)
    assert res.detections_after_dedupe == []
    assert res.latency_ms == 0.0


def test_evaluate_yunet_variants_with_synthetic_manifest(tmp_path: Path):
    import cv2

    ds = tmp_path / "ds"
    ds.mkdir()
    # clip a: frame0 black (detect), frame1 gray (no detect)
    vw = cv2.VideoWriter(str(ds / "a.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    vw.write(np.zeros((32, 32, 3), dtype=np.uint8))
    vw.write(np.full((32, 32, 3), 120, dtype=np.uint8))
    vw.release()
    vw = cv2.VideoWriter(str(ds / "b.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    vw.write(np.full((32, 32, 3), 120, dtype=np.uint8))
    vw.write(np.full((32, 32, 3), 120, dtype=np.uint8))
    vw.release()
    manifest = {
        "synthetic": True,
        "real_people": False,
        "notice": "synthetic",
        "videos": {
            "clip_a": {"file": "a.mp4", "frame_count": 2, "description": "a", "labels": {"0": "SYN-A", "1": "none"}},
            "clip_b": {"file": "b.mp4", "frame_count": 2, "description": "b", "labels": {}},
        },
    }
    (ds / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    class Det:
        def detect(self, image):
            if int(image[0, 0, 0]) == 0:
                return [FaceDetection(bbox=(1, 1, 10, 10), confidence=0.9, landmarks=_lm(2, 2))]
            return []

    report = evaluate_yunet_variants(ds, variants=[ExperimentalVariant("baseline_original", (1.0,), "base")], detector_factory=Det)
    ca = report["variants"]["baseline_original"]["clips"]["clip_a"]
    assert ca["frame_presence"]["status"] == "MEASURED"
    assert ca["tp"] == 1 and ca["tn"] == 1
    cb = report["variants"]["baseline_original"]["clips"]["clip_b"]
    assert cb["frame_presence"]["status"] == NOT_ASSESSABLE


def test_real_baseline_detector_unchanged_api():
    from app.cv.models import model_status

    status = model_status().get("models", {}).get("yunet", {})
    if not status.get("usable"):
        import pytest

        pytest.skip("YuNet model not available in this environment")
    det = YuNetFaceDetector()
    assert hasattr(det, "detect")
    assert det.score_threshold > 0
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    out = det.detect(frame)
    assert isinstance(out, list)


def test_no_face_clip_name_treated_as_negative_labels(tmp_path: Path):
    import cv2
    ds = tmp_path / "ds"
    ds.mkdir()
    vw = cv2.VideoWriter(str(ds / "nf.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    vw.write(np.full((32,32,3),120,dtype=np.uint8))
    vw.release()
    manifest = {"synthetic": True, "real_people": False, "notice": "s", "videos": {"no_face": {"file": "nf.mp4", "frame_count": 1, "description":"n","labels": {}}}}
    (ds/"manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    class Det:
        def detect(self, image): return []
    report = evaluate_yunet_variants(ds, variants=[ExperimentalVariant("baseline_original",(1.0,),"b")], detector_factory=Det)
    c = report["variants"]["baseline_original"]["clips"]["no_face"]
    assert c["frame_presence"]["status"] == "MEASURED"
    assert c["tn"] == 1 and c["fp"] == 0
