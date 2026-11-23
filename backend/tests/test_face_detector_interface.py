from __future__ import annotations

import numpy as np

from app.cv.face_detector_interface import (
    DetectorMetadata,
    NormalizedFaceDetection,
    UnavailableFaceDetectorAdapter,
    get_face_detector_adapter,
)


def test_unavailable_adapter_returns_structured_error():
    adapter = get_face_detector_adapter("scrfd_500m")
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    res = adapter.detect(frame, frame_number=7, timestamp_ms=123.4)
    assert res.available is False
    assert res.detections == []
    assert "not locally available/approved" in (res.error or "")
    assert res.input_width == 64 and res.input_height == 64


def test_explicit_unavailable_adapter_class():
    meta = DetectorMetadata(name="retinaface", variant="r50", version="x", backend="none")
    adapter = UnavailableFaceDetectorAdapter(meta, "missing weights")
    res = adapter.detect(np.zeros((32, 16, 3), dtype=np.uint8))
    assert not res.available
    assert res.error == "missing weights"
    assert res.model.name == "retinaface"


def test_normalized_detection_to_dict():
    det = NormalizedFaceDetection(bbox=(1, 2, 3, 4), confidence=0.9, landmarks=[(1.0, 2.0)], frame_number=1, timestamp_ms=10.0)
    d = det.to_dict()
    assert d["bbox"] == (1, 2, 3, 4)
    assert d["confidence"] == 0.9
    assert d["frame_number"] == 1


def test_yunet_adapter_unavailable_when_missing(monkeypatch):
    import app.cv.face_detector_interface as mod

    monkeypatch.setattr(mod, "verify_model", lambda key: (False, "not_downloaded"))
    class P:
        def exists(self):
            return False
        def __str__(self):
            return "/tmp/missing.onnx"
    monkeypatch.setattr(mod, "model_path", lambda key: P())
    adapter = mod.YuNetExperimentalAdapter(detector=None)
    res = adapter.detect(np.zeros((64, 64, 3), dtype=np.uint8), frame_number=3)
    assert res.available is False
    assert "unavailable" in (res.error or "").lower()
    assert res.detections == []
