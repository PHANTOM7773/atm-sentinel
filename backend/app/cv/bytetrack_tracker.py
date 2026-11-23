"""Isolated ByteTrack-inspired person tracker for TASK 14.

Not wired into production pipeline. Keeps SimpleTracker untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, TypeVar

from .types import BoundingBox

T = TypeVar("T")


def iou(a: BoundingBox, b: BoundingBox) -> float:
    ax, ay, aw, ah = [float(v) for v in a]
    bx, by, bw, bh = [float(v) for v in b]
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    left, top = max(ax, bx), max(ay, by)
    right, bottom = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def centroid(box: BoundingBox) -> tuple[float, float]:
    x, y, w, h = [float(v) for v in box]
    return x + w / 2.0, y + h / 2.0


def _valid_bbox(box: Any) -> bool:
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        return False
    try:
        vals = [float(v) for v in box]
    except Exception:
        return False
    return all(math.isfinite(v) for v in vals) and vals[2] > 0 and vals[3] > 0


import math


@dataclass
class TrackState:
    track_id: int
    bbox: BoundingBox
    confidence: float
    hits: int = 1
    misses: int = 0
    age_frames: int = 0
    last_frame: int = -1
    last_timestamp: float = 0.0
    state: str = "tentative"  # tentative|active|lost|removed
    last_detection: Any = None
    velocity: tuple[float, float] = (0.0, 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "bbox": [float(v) for v in self.bbox],
            "confidence": self.confidence,
            "hits": self.hits,
            "misses": self.misses,
            "age_frames": self.age_frames,
            "last_frame": self.last_frame,
            "last_timestamp": self.last_timestamp,
            "state": self.state,
        }


class ByteTrackInspiredTracker:
    """Deterministic, clip-local tracker. Isolated; no production wiring."""

    def __init__(
        self,
        *,
        high_conf_threshold: float = 0.5,
        low_conf_threshold: float = 0.1,
        match_iou_threshold: float = 0.3,
        second_match_iou_threshold: float = 0.2,
        max_centroid_distance: float = 0.45,
        max_misses: int = 8,
        max_time_gap_seconds: float | None = None,
        min_hits: int = 2,
    ) -> None:
        self.high_conf_threshold = float(high_conf_threshold)
        self.low_conf_threshold = float(low_conf_threshold)
        self.match_iou_threshold = float(match_iou_threshold)
        self.second_match_iou_threshold = float(second_match_iou_threshold)
        self.max_centroid_distance = float(max_centroid_distance)
        self.max_misses = int(max_misses)
        self.max_time_gap_seconds = max_time_gap_seconds
        self.min_hits = max(1, int(min_hits))
        self._tracks: dict[int, TrackState] = {}
        self._next_id = 1
        self.confirmed_count = 0

    @property
    def tracks(self) -> dict[int, TrackState]:
        return self._tracks

    def _diag(self, frame_diag: float) -> float:
        return max(float(frame_diag), 1.0)

    def _score(self, track: TrackState, det: Any, diag: float) -> float:
        overlap = iou(track.bbox, det.bbox)
        tx, ty = centroid(track.bbox)
        dx, dy = centroid(det.bbox)
        dist = math.hypot(tx - dx, ty - dy)
        norm = dist / self._diag(diag)
        motion_ok = norm <= self.max_centroid_distance
        if overlap >= self.match_iou_threshold or motion_ok:
            # higher is better; combine IoU and motion consistency
            return overlap * 0.7 + max(0.0, 1.0 - norm / max(self.max_centroid_distance, 1e-6)) * 0.3
        return -1.0

    def _is_expired(self, track: TrackState, frame_number: int, timestamp: float) -> bool:
        if track.misses > self.max_misses:
            return True
        if self.max_time_gap_seconds is not None:
            gap = float(timestamp) - float(track.last_timestamp)
            if gap > float(self.max_time_gap_seconds) and track.last_frame != frame_number:
                return True
        return False

    def _ensure_state(self, track: TrackState) -> None:
        if track.state == "removed":
            return
        if track.hits >= self.min_hits and track.misses == 0:
            track.state = "active"
        elif track.misses > 0 and track.state in {"active", "tentative"}:
            track.state = "lost"
        elif track.hits < self.min_hits:
            track.state = "tentative"

    def _predicted_bbox(self, track: TrackState) -> BoundingBox:
        x, y, w, h = [float(v) for v in track.bbox]
        vx, vy = track.velocity
        # only predict for short gaps; avoids runaway drift
        if 0 < track.misses <= 2:
            return (x + vx * track.misses, y + vy * track.misses, w, h)
        return (x, y, w, h)

    def _assign(self, track: TrackState, det: Any, frame_number: int, timestamp: float) -> None:
        old_cx, old_cy = centroid(track.bbox)
        new_bbox = tuple(float(v) for v in det.bbox)  # type: ignore[assignment]
        new_cx, new_cy = centroid(new_bbox)
        dt_frames = max(1, int(frame_number) - int(track.last_frame)) if track.last_frame >= 0 else 1
        track.velocity = ((new_cx - old_cx) / dt_frames, (new_cy - old_cy) / dt_frames)
        track.bbox = new_bbox
        track.confidence = float(getattr(det, "confidence", 0.0))
        track.hits += 1
        track.misses = 0
        track.last_frame = frame_number
        track.last_timestamp = float(timestamp)
        track.last_detection = det
        self._ensure_state(track)
        setattr(det, "track_id", track.track_id)

    def _create_track(self, det: Any, frame_number: int, timestamp: float) -> TrackState:
        track = TrackState(
            track_id=self._next_id,
            bbox=tuple(float(v) for v in det.bbox),  # type: ignore[assignment]
            confidence=float(getattr(det, "confidence", 0.0)),
            hits=1,
            misses=0,
            age_frames=0,
            last_frame=frame_number,
            last_timestamp=float(timestamp),
            state="tentative" if self.min_hits > 1 else "active",
            last_detection=det,
        )
        self._next_id += 1
        self._tracks[track.track_id] = track
        setattr(det, "track_id", track.track_id)
        return track

    def _greedy_match(self, tracks: list[TrackState], dets: list[Any], diag: float, iou_thr: float) -> tuple[list[tuple[TrackState, Any]], list[TrackState], list[Any]]:
        candidates: list[tuple[float, int, int]] = []
        for ti, tr in enumerate(tracks):
            tb = self._predicted_bbox(tr)
            for di, det in enumerate(dets):
                overlap = iou(tb, det.bbox)
                tx, ty = centroid(tb)
                dx, dy = centroid(det.bbox)
                norm = math.hypot(tx - dx, ty - dy) / self._diag(diag)
                motion_ok = norm <= self.max_centroid_distance
                if overlap >= iou_thr or motion_ok:
                    score = overlap * 0.7 + max(0.0, 1.0 - norm / max(self.max_centroid_distance, 1e-6)) * 0.3
                    candidates.append((score, ti, di))
        candidates.sort(key=lambda x: (-x[0], tracks[x[1]].track_id, x[2]))
        used_t, used_d = set(), set()
        matches: list[tuple[TrackState, Any]] = []
        for _, ti, di in candidates:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti); used_d.add(di)
            matches.append((tracks[ti], dets[di]))
        unmatched_tracks = [t for i, t in enumerate(tracks) if i not in used_t]
        unmatched_dets = [d for i, d in enumerate(dets) if i not in used_d]
        return matches, unmatched_tracks, unmatched_dets

    def _sanitize_detections(self, detections: Iterable[Any]) -> list[Any]:
        clean: list[Any] = []
        for det in detections or []:
            bbox = getattr(det, "bbox", None)
            if not _valid_bbox(bbox):
                continue
            conf = getattr(det, "confidence", 0.0)
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = 0.0
            if not math.isfinite(conf_f) or conf_f < self.low_conf_threshold:
                continue
            # preserve original detection object/coords; only ensure floatability
            clean.append(det)
        return clean

    def update(self, detections: list[T], frame_number: int = 0, timestamp: float = 0.0) -> list[T]:
        ts = float(timestamp)
        fn = int(frame_number)
        for track in self._tracks.values():
            if track.state != "removed":
                track.age_frames += 1

        clean = self._sanitize_detections(detections)
        high = [d for d in clean if float(getattr(d, "confidence", 0.0)) >= self.high_conf_threshold]
        low = [d for d in clean if self.low_conf_threshold <= float(getattr(d, "confidence", 0.0)) < self.high_conf_threshold]

        diag = 1.0
        boxes = [getattr(d, "bbox") for d in clean] + [t.bbox for t in self._tracks.values() if t.state != "removed"]
        if boxes:
            diag = max(math.hypot(float(b[2]), float(b[3])) for b in boxes)

        # Stage 1: match high-conf detections to active/tentative/lost tracks
        pool = [t for t in self._tracks.values() if t.state != "removed"]
        matches1, unmatched_tracks1, unmatched_high = self._greedy_match(pool, high, diag, self.match_iou_threshold)
        for tr, det in matches1:
            self._assign(tr, det, fn, ts)

        # Stage 2: match remaining tracks (especially recently lost/active) with low-conf detections
        unmatched_tracks1 = [t for t in unmatched_tracks1 if t.state != "removed"]
        matches2, unmatched_tracks2, _unmatched_low = self._greedy_match(unmatched_tracks1, low, diag, self.second_match_iou_threshold)
        for tr, det in matches2:
            self._assign(tr, det, fn, ts)

        # New tracks only from unmatched high-conf detections
        for det in unmatched_high:
            self._create_track(det, fn, ts)

        # Mark unmatched tracks
        matched_ids = {tr.track_id for tr, _ in matches1} | {tr.track_id for tr, _ in matches2}
        for track in self._tracks.values():
            if track.track_id in matched_ids or track.state == "removed":
                continue
            if track.last_frame != fn:
                track.misses += 1
                self._ensure_state(track)
            if self._is_expired(track, fn, ts):
                track.state = "removed"

        # cleanup removed
        for tid in [tid for tid, t in self._tracks.items() if t.state == "removed"]:
            del self._tracks[tid]

        # ensure no duplicate active track IDs in outputs for this frame
        seen = set()
        for det in clean:
            tid = getattr(det, "track_id", None)
            if tid is None:
                continue
            if tid in seen:
                # should not happen; defensive: create a new track id
                replacement = self._create_track(det, fn, ts)
                setattr(det, "track_id", replacement.track_id)
                tid = replacement.track_id
            seen.add(tid)

        self.confirmed_count = sum(1 for t in self._tracks.values() if t.state == "active")
        return detections


__all__ = ["ByteTrackInspiredTracker", "TrackState", "centroid", "iou"]
