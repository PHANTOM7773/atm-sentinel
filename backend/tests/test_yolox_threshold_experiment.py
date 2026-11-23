from __future__ import annotations

import numpy as np

from app.cv.yolox_threshold_experiment import RawPersonCandidate, filter_person_candidates


def test_filter_person_candidates_threshold_and_nms():
    cands = [
        RawPersonCandidate((10, 10, 20, 20), 0.9, 0),
        RawPersonCandidate((11, 11, 20, 20), 0.8, 0),  # overlaps, should be suppressed
        RawPersonCandidate((50, 50, 20, 20), 0.2, 0),  # below threshold
        RawPersonCandidate((70, 70, 20, 20), 0.6, 0),
    ]
    out = filter_person_candidates(cands, score_threshold=0.45, nms_threshold=0.45)
    assert len(out) == 2
    confs = sorted([o["confidence"] for o in out], reverse=True)
    assert confs == [0.9, 0.6]


def test_filter_person_candidates_empty():
    assert filter_person_candidates([], score_threshold=0.45, nms_threshold=0.45) == []


def test_deterministic_filtering():
    cands = [RawPersonCandidate((10, 10, 20, 20), 0.5, 0), RawPersonCandidate((40, 40, 10, 10), 0.7, 0)]
    a = filter_person_candidates(cands, score_threshold=0.3, nms_threshold=0.45)
    b = filter_person_candidates(cands, score_threshold=0.3, nms_threshold=0.45)
    assert a == b


def test_threshold_monotonicity_on_counts():
    cands = [RawPersonCandidate((i*30, 10, 20, 20), conf, 0) for i, conf in enumerate([0.05,0.15,0.25,0.35,0.45,0.55])]
    counts = [len(filter_person_candidates(cands, score_threshold=t, nms_threshold=0.45)) for t in [0.1,0.2,0.3,0.4,0.5]]
    assert all(counts[i] >= counts[i+1] for i in range(len(counts)-1))
