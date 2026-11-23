from __future__ import annotations

from dataclasses import dataclass

from app.cv.bytetrack_tracker import ByteTrackInspiredTracker
from app.cv.tracking import SimpleTracker
from app.cv.types import PersonDetection


@dataclass
class Det:
    bbox: tuple[float, float, float, float]
    confidence: float
    track_id: int | None = None


def ids(dets):
    return [d.track_id for d in dets]


def test_two_stage_high_low_association_preserves_id():
    tracker = ByteTrackInspiredTracker(high_conf_threshold=0.6, low_conf_threshold=0.1, max_misses=3, min_hits=1)
    d1 = Det((0, 0, 20, 20), 0.9)
    tracker.update([d1], frame_number=0, timestamp=0.0)
    assert d1.track_id == 1
    # low-confidence occlusion-like detection should be matched in second stage
    d2 = Det((1, 1, 20, 20), 0.3)
    tracker.update([d2], frame_number=1, timestamp=0.1)
    assert d2.track_id == 1
    assert tracker.tracks[1].state in {"active", "lost", "tentative"}


def test_max_misses_and_time_gap_lifecycle():
    tracker = ByteTrackInspiredTracker(max_misses=1, max_time_gap_seconds=0.2, min_hits=1)
    d1 = Det((0, 0, 10, 10), 0.9)
    tracker.update([d1], 0, 0.0)
    tracker.update([], 1, 0.1)
    assert 1 in tracker.tracks and tracker.tracks[1].state == "lost"
    tracker.update([], 2, 0.2)
    assert 1 not in tracker.tracks

    tracker2 = ByteTrackInspiredTracker(max_misses=10, max_time_gap_seconds=0.05, min_hits=1)
    d = Det((0, 0, 10, 10), 0.9)
    tracker2.update([d], 0, 0.0)
    tracker2.update([], 1, 0.1)  # gap > 0.05
    assert 1 not in tracker2.tracks


def test_stable_clip_local_ids_no_reuse():
    tracker = ByteTrackInspiredTracker(max_misses=0, min_hits=1)
    a = Det((0, 0, 10, 10), 0.9)
    tracker.update([a], 0, 0.0)
    tracker.update([], 1, 0.1)  # removed
    b = Det((0, 0, 10, 10), 0.9)
    tracker.update([b], 2, 0.2)
    assert a.track_id == 1
    assert b.track_id == 2


def test_no_duplicate_active_track_ids():
    tracker = ByteTrackInspiredTracker(min_hits=1)
    dets = [Det((0, 0, 10, 10), 0.9), Det((1, 1, 10, 10), 0.9), Det((200, 200, 10, 10), 0.8)]
    out = tracker.update(dets, 0, 0.0)
    tids = [d.track_id for d in out]
    assert len(tids) == len(set(tids))
    assert None not in tids


def test_invalid_empty_detection_handling():
    tracker = ByteTrackInspiredTracker(min_hits=1)
    dets = [
        Det((0, 0, 10, 10), 0.9),
        Det((0, 0, -1, 10), 0.9),
        Det((0, 0, 10, float('nan')), 0.9),
    ]
    out = tracker.update(dets, 0, 0.0)
    assert out[0].track_id == 1
    assert out[1].track_id is None
    assert out[2].track_id is None
    assert tracker.update([], 1, 0.1) == []


def test_multi_person_crossing_deterministic():
    def run(Tracker):
        t = Tracker(min_hits=1)
        seq = [
            [Det((0, 50, 20, 20), 0.9), Det((100, 50, 20, 20), 0.9)],
            [Det((40, 50, 20, 20), 0.9), Det((60, 50, 20, 20), 0.9)],  # crossing/overlap
            [Det((100, 50, 20, 20), 0.9), Det((0, 50, 20, 20), 0.9)],
        ]
        out = []
        for i, dets in enumerate(seq):
            t.update(dets, i, i * 0.1)
            out.append(sorted((d.track_id, tuple(d.bbox)) for d in dets))
        return out

    a = run(ByteTrackInspiredTracker)
    b = run(ByteTrackInspiredTracker)
    assert a == b
    # deterministic, no duplicate IDs within frame; crossing may swap identities but should not explode IDs
    for frame in a:
        tids = [tid for tid, _ in frame]
        assert len(tids) == len(set(tids))
    flat = [tid for frame in a for tid, _ in frame]
    assert max(flat) <= 4
    assert min(flat) >= 1


def test_preserves_original_coordinates():
    tracker = ByteTrackInspiredTracker(min_hits=1)
    det = PersonDetection((10.5, 20.25, 30.0, 40.0), 0.95)
    tracker.update([det], 0, 0.0)
    assert det.bbox == (10.5, 20.25, 30.0, 40.0)
    assert det.confidence == 0.95


def test_simpletracker_compatibility_shape():
    # Both should accept PersonDetection-like objects and set track_id
    for Tracker in (SimpleTracker, ByteTrackInspiredTracker):
        t = Tracker() if Tracker is SimpleTracker else Tracker(min_hits=1)
        det = PersonDetection((0, 0, 10, 10), 0.9)
        out = t.update([det], frame_number=0)
        assert out[0].track_id is not None
