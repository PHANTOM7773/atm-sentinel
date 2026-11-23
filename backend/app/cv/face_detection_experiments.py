from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .detection import YuNetFaceDetector
from .types import BoundingBox, FaceDetection, Point


@dataclass(frozen=True)
class ExperimentalVariant:
    name: str
    scales: tuple[float, ...]
    description: str


DEFAULT_VARIANTS: tuple[ExperimentalVariant, ...] = (
    ExperimentalVariant("baseline_original", (1.0,), "Existing YuNet on original resolution"),
    ExperimentalVariant("yunet_upscale_1_5x", (1.0, 1.5), "YuNet on original + 1.5x upscale, merged"),
    ExperimentalVariant("yunet_upscale_2x", (1.0, 2.0), "YuNet on original + 2x upscale, merged"),
)


@dataclass
class DetectionRecord:
    bbox: BoundingBox
    confidence: float
    landmarks: tuple[Point, Point, Point, Point, Point]
    scale: float
    variant: str
    raw_bbox: BoundingBox
    raw_landmarks: tuple[Point, Point, Point, Point, Point]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bbox": [float(x) for x in self.bbox],
            "confidence": float(self.confidence),
            "landmarks": [[float(x), float(y)] for x, y in self.landmarks],
            "scale": float(self.scale),
            "variant": self.variant,
        }


@dataclass
class FrameExperimentResult:
    frame_number: int
    timestamp: float | None
    variant: str
    detections_before_dedupe: list[DetectionRecord]
    detections_after_dedupe: list[DetectionRecord]
    latency_ms: float
    per_scale_latency_ms: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_number": self.frame_number,
            "timestamp": self.timestamp,
            "variant": self.variant,
            "latency_ms": round(self.latency_ms, 3),
            "per_scale_latency_ms": {k: round(v, 3) for k, v in self.per_scale_latency_ms.items()},
            "detections_before_dedupe": [d.to_dict() for d in self.detections_before_dedupe],
            "detections_after_dedupe": [d.to_dict() for d in self.detections_after_dedupe],
            "duplicate_count_removed": max(0, len(self.detections_before_dedupe) - len(self.detections_after_dedupe)),
        }


def _clip_bbox(bbox: BoundingBox, width: int, height: int) -> BoundingBox | None:
    x, y, w, h = [float(v) for v in bbox]
    x1 = max(0.0, min(x, float(width - 1)))
    y1 = max(0.0, min(y, float(height - 1)))
    x2 = max(0.0, min(x + w, float(width)))
    y2 = max(0.0, min(y + h, float(height)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2 - x1, y2 - y1)


def scale_detection_to_original(det: FaceDetection, scale: float, orig_w: int, orig_h: int) -> DetectionRecord | None:
    if scale <= 0:
        return None
    inv = 1.0 / float(scale)
    mapped_bbox = (det.bbox[0] * inv, det.bbox[1] * inv, det.bbox[2] * inv, det.bbox[3] * inv)
    clipped = _clip_bbox(mapped_bbox, orig_w, orig_h)
    if clipped is None:
        return None
    mapped_landmarks = tuple((float(p[0]) * inv, float(p[1]) * inv) for p in det.landmarks)
    mapped_landmarks = tuple((min(max(x, 0.0), float(orig_w - 1)), min(max(y, 0.0), float(orig_h - 1))) for x, y in mapped_landmarks)
    return DetectionRecord(
        bbox=clipped,
        confidence=float(det.confidence),
        landmarks=mapped_landmarks,  # type: ignore[assignment]
        scale=float(scale),
        variant="",
        raw_bbox=tuple(float(v) for v in det.bbox),  # type: ignore[assignment]
        raw_landmarks=tuple((float(x), float(y)) for x, y in det.landmarks),  # type: ignore[assignment]
    )


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def dedupe_detections(records: Sequence[DetectionRecord], iou_threshold: float = 0.5) -> list[DetectionRecord]:
    # Deterministic NMS-like suppression in original coordinates.
    ordered = sorted(
        list(records),
        key=lambda r: (-float(r.confidence), float(r.bbox[0]), float(r.bbox[1]), float(r.bbox[2]), float(r.bbox[3]), float(r.scale)),
    )
    kept: list[DetectionRecord] = []
    for cand in ordered:
        if any(_iou(cand.bbox, k.bbox) >= iou_threshold for k in kept):
            continue
        kept.append(cand)
    return kept


def detect_with_variant(
    frame: np.ndarray,
    *,
    detector: YuNetFaceDetector,
    variant: ExperimentalVariant,
    frame_number: int,
    timestamp: float | None = None,
    dedupe_iou: float = 0.5,
) -> FrameExperimentResult:
    if frame is None or frame.size == 0:
        return FrameExperimentResult(frame_number, timestamp, variant.name, [], [], 0.0, {})
    orig_h, orig_w = frame.shape[:2]
    before: list[DetectionRecord] = []
    per_scale_latency: dict[str, float] = {}
    t0 = time.perf_counter()
    for scale in variant.scales:
        s = float(scale)
        if s <= 0:
            continue
        if abs(s - 1.0) < 1e-9:
            work = frame
        else:
            interp = cv2.INTER_CUBIC if s > 1.0 else cv2.INTER_AREA
            work = cv2.resize(frame, (max(1, int(round(orig_w * s))), max(1, int(round(orig_h * s)))), interpolation=interp)
        st = time.perf_counter()
        detections = detector.detect(work)
        per_scale_latency[f"{s:g}x"] = (time.perf_counter() - st) * 1000.0
        for det in detections:
            rec = scale_detection_to_original(det, s, orig_w, orig_h)
            if rec is None:
                continue
            before.append(DetectionRecord(**{**asdict(rec), "variant": variant.name}))
    latency_ms = (time.perf_counter() - t0) * 1000.0
    after = dedupe_detections(before, iou_threshold=dedupe_iou)
    return FrameExperimentResult(frame_number, timestamp, variant.name, before, after, latency_ms, per_scale_latency)


def run_variant_on_frames(
    frames: Sequence[tuple[int, float | None, np.ndarray]],
    *,
    detector_factory: Callable[[], YuNetFaceDetector],
    variant: ExperimentalVariant,
    dedupe_iou: float = 0.5,
) -> list[FrameExperimentResult]:
    detector = detector_factory()
    results: list[FrameExperimentResult] = []
    for frame_number, timestamp, frame in frames:
        results.append(
            detect_with_variant(
                frame,
                detector=detector,
                variant=variant,
                frame_number=frame_number,
                timestamp=timestamp,
                dedupe_iou=dedupe_iou,
            )
        )
    return results
