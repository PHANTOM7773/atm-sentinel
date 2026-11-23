from __future__ import annotations

import numpy as np

from app.cv.face_retrieval_experiment import (
    build_pairs,
    pair_stats,
    retrieval_metrics,
    roc_metrics,
    threshold_analysis,
    FaceSample,
)


def _s(label, clip, i, vec):
    crop = np.zeros((32,32,3), dtype=np.uint8)
    v = np.array(vec, dtype=np.float32)
    v = v / np.linalg.norm(v)
    return FaceSample(f"{clip}:{i}", label, clip, i, None, (0,0,10,10), 0.9, 50.0, 100.0, 100.0, 40.0, crop, v)


def test_build_pairs_and_stats():
    samples = [
        _s('A','c1',0,[1,0,0,0]),
        _s('A','c2',1,[0.99,0.01,0,0]),
        _s('B','c1',2,[0,1,0,0]),
    ]
    pairs = build_pairs(samples)
    assert len(pairs) == 3
    pos = [p for p in pairs if p['same_subject']]
    neg = [p for p in pairs if not p['same_subject']]
    assert len(pos) == 1 and len(neg) == 2
    st = pair_stats(pairs)
    assert st['genuine']['count'] == 1
    assert st['impostor']['count'] == 2


def test_retrieval_cross_clip_excludes_same_clip():
    samples = [
        _s('A','c1',0,[1,0,0,0]),
        _s('A','c1',1,[0.95,0.05,0,0]), # same clip - should be excluded
        _s('A','c2',2,[0.9,0.1,0,0]),
        _s('B','c2',3,[0,1,0,0]),
    ]
    m = retrieval_metrics(samples, exclude_same_clip=True)
    assert m['status'] == 'MEASURED'
    # query c1:0 should find c2:2 as relevant cross-clip
    q = [d for d in m['details'] if d['query']=='c1:0'][0]
    assert q['rank1'] == 1


def test_roc_and_threshold_not_assessable_on_tiny():
    pairs = [{'same_subject': True, 'cosine_similarity': 0.9}]
    r = roc_metrics(pairs)
    assert r['status'] == 'NOT_ASSESSABLE'
    ta = threshold_analysis(pairs, production_threshold=0.0)
    assert ta['status'] == 'NOT_ASSESSABLE' or 'rows' in ta
