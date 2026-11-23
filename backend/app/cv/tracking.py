from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from .types import BoundingBox

T = TypeVar("T")


def iou(a: BoundingBox, b: BoundingBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    overlap_w = max(0.0, right - left)
    overlap_h = max(0.0, bottom - top)
    overlap = overlap_w * overlap_h
    union = aw * ah + bw * bh - overlap
    return overlap / union if union > 0 else 0.0


def centroid(box: BoundingBox) -> tuple[float, float]:
    x, y, w, h = box
    return x + w / 2.0, y + h / 2.0


@dataclass
class _Track:
    track_id: int
    bbox: BoundingBox
    hits: int = 1
    misses: int = 0
    age: int = 0
    last_frame: int = -1
    last_detection: Any = None


class SimpleTracker:
    """Deterministic clip-local tracker.

    Track IDs are local to a single analysis run. Track ID 1 in one clip has no
    relationship to Track ID 1 in another clip.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_centroid_distance: float = 0.45,
        max_misses: int = 8,
        min_hits: int = 2,
    ) -> None:
        self.iou_threshold = float(iou_threshold)
        self.max_centroid_distance = float(max_centroid_distance)
        self.max_misses = int(max_misses)
        self.min_hits = int(min_hits)
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self.confirmed_count = 0

    def _match_score(self, track: _Track, detection: Any, diagonal: float) -> float:
        overlap = iou(track.bbox, detection.bbox)
        tx, ty = centroid(track.bbox)
        dx, dy = centroid(detection.bbox)
        distance = ((tx - dx) ** 2 + (ty - dy) ** 2) ** 0.5
        normalized = distance / max(diagonal, 1.0)
        if overlap >= self.iou_threshold or normalized <= self.max_centroid_distance:
            return overlap + max(0.0, 1.0 - normalized / self.max_centroid_distance)
        return -1.0

    def update(self, detections: list[T], frame_number: int = 0, timestamp: float = 0.0) -> list[T]:
        for track in self._tracks.values():
            track.age += 1

        diagonal = max(
            1.0,
            max(
                (detection.bbox[2] ** 2 + detection.bbox[3] ** 2) ** 0.5
                for detection in detections
            )
            if detections
            else 1.0,
        )

        candidates: list[tuple[float, int, int]] = []
        for detection_index, detection in enumerate(detections):
            for track_id, track in self._tracks.items():
                if track.misses >= self.max_misses:
                    continue
                score = self._match_score(track, detection, diagonal)
                if score >= 0.0:
                    candidates.append((score, track_id, detection_index))
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        for _, track_id, detection_index in candidates:
            if track_id in matched_tracks or detection_index in matched_detections:
                continue
            track = self._tracks[track_id]
            detection = detections[detection_index]
            matched_tracks.add(track_id)
            matched_detections.add(detection_index)
            track.bbox = detection.bbox
            track.hits += 1
            track.misses = 0
            track.last_frame = frame_number
            track.last_detection = detection
            setattr(detection, "track_id", track.track_id)

        for detection_index, detection in enumerate(detections):
            if detection_index in matched_detections:
                continue
            track = _Track(
                track_id=self._next_id,
                bbox=detection.bbox,
                last_frame=frame_number,
                last_detection=detection,
            )
            self._next_id += 1
            self._tracks[track.track_id] = track
            matched_tracks.add(track.track_id)
            setattr(detection, "track_id", track.track_id)

        for track_id in list(self._tracks):
            track = self._tracks[track_id]
            if track.last_frame != frame_number:
                track.misses += 1
            if track.misses >= self.max_misses:
                del self._tracks[track_id]

        self.confirmed_count = sum(1 for track in self._tracks.values() if track.hits >= self.min_hits)
        return detections


__all__ = ["SimpleTracker", "centroid", "iou"]
