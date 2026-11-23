"""Isolated experimental face-detector adapter interface for TASK 07.

This module is NOT wired into production CV pipeline/config defaults.
It provides a normalized contract for benchmarking/evaluating detectors when
legally approved model weights are available locally.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Protocol

import numpy as np

from .detection import YuNetFaceDetector
from .errors import CVError
from .models import model_path, verify_model


@dataclass(frozen=True)
class NormalizedFaceDetection:
    bbox: tuple[int, int, int, int]  # original frame coordinates: x, y, w, h
    confidence: float
    landmarks: list[tuple[float, float]] | None = None
    frame_number: int | None = None
    timestamp_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DetectorMetadata:
    name: str
    variant: str
    version: str
    backend: str
    source: str = ""
    sha256: str = ""
    license: str = ""
    weights_present: bool = False


@dataclass
class DetectionResult:
    model: DetectorMetadata
    input_width: int
    input_height: int
    latency_ms: float
    detections: list[NormalizedFaceDetection] = field(default_factory=list)
    available: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": asdict(self.model),
            "input_width": self.input_width,
            "input_height": self.input_height,
            "latency_ms": self.latency_ms,
            "detections": [d.to_dict() for d in self.detections],
            "available": self.available,
            "error": self.error,
        }


class FaceDetectorAdapter(Protocol):
    metadata: DetectorMetadata

    def detect(self, frame: np.ndarray, *, frame_number: int | None = None, timestamp_ms: float | None = None) -> DetectionResult:
        ...


class UnavailableFaceDetectorAdapter:
    def __init__(self, metadata: DetectorMetadata, reason: str):
        self.metadata = metadata
        self.reason = reason

    def detect(self, frame: np.ndarray, *, frame_number: int | None = None, timestamp_ms: float | None = None) -> DetectionResult:
        h, w = frame.shape[:2]
        return DetectionResult(
            model=self.metadata,
            input_width=int(w),
            input_height=int(h),
            latency_ms=0.0,
            detections=[],
            available=False,
            error=self.reason,
        )


class YuNetExperimentalAdapter:
    """Wraps existing YuNet detector without changing production defaults."""

    def __init__(self, detector: YuNetFaceDetector | None = None):
        self._detector = detector
        ok, state = verify_model("yunet")
        path = model_path("yunet")
        self.metadata = DetectorMetadata(
            name="yunet",
            variant="face_detection_yunet_2026may",
            version="2026may",
            backend="opencv.FaceDetectorYN",
            source=str(path),
            sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
            license="MIT weights; OpenCV Zoo Apache-2.0 repository",
            weights_present=ok and path.exists(),
        )
        self._init_error = None if self.metadata.weights_present else f"yunet unavailable: {state}"

    def _get_detector(self) -> YuNetFaceDetector:
        if self._detector is None:
            self._detector = YuNetFaceDetector()
        return self._detector

    def detect(self, frame: np.ndarray, *, frame_number: int | None = None, timestamp_ms: float | None = None) -> DetectionResult:
        h, w = frame.shape[:2]
        if self._init_error:
            return DetectionResult(self.metadata, w, h, 0.0, [], available=False, error=self._init_error)
        start = perf_counter()
        try:
            dets = self._get_detector().detect(frame)
            normalized = [
                NormalizedFaceDetection(
                    bbox=(int(d.bbox[0]), int(d.bbox[1]), int(d.bbox[2]), int(d.bbox[3])),
                    confidence=float(d.confidence),
                    landmarks=[(float(x), float(y)) for x, y in (d.landmarks or [])] or None,
                    frame_number=frame_number,
                    timestamp_ms=timestamp_ms,
                )
                for d in dets
            ]
            return DetectionResult(self.metadata, w, h, (perf_counter() - start) * 1000.0, normalized, available=True)
        except Exception as exc:  # noqa: BLE001 - adapter must surface structured error
            return DetectionResult(self.metadata, w, h, (perf_counter() - start) * 1000.0, [], available=False, error=str(exc))


def get_face_detector_adapter(name: str) -> FaceDetectorAdapter:
    key = (name or "").strip().lower()
    if key in {"yunet", "baseline"}:
        return YuNetExperimentalAdapter()
    # No other models are locally available/approved. Do not fabricate.
    return UnavailableFaceDetectorAdapter(
        DetectorMetadata(name=key or "unknown", variant="unavailable", version="unknown", backend="none"),
        reason=f"Detector '{name}' is not locally available/approved; no weights downloaded.",
    )


__all__ = [
    "DetectionResult",
    "DetectorMetadata",
    "FaceDetectorAdapter",
    "NormalizedFaceDetection",
    "UnavailableFaceDetectorAdapter",
    "YuNetExperimentalAdapter",
    "get_face_detector_adapter",
]
