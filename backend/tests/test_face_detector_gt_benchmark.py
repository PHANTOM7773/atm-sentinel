from __future__ import annotations

from app.cv.face_detector_gt_benchmark import compute_prf, iou_xywh, match_one_to_one, validate_annotations, voc_ap


def test_iou_xywh_basic():
    assert iou_xywh([0,0,10,10],[0,0,10,10]) == 1.0
    assert iou_xywh([0,0,10,10],[10,0,10,10]) == 0.0
    i = iou_xywh([0,0,10,10],[5,0,10,10])
    assert 0.33 < i < 0.34


def test_one_to_one_matching_prevents_double_count():
    gt = [[0,0,10,10]]
    preds = [[0,0,10,10],[1,1,10,10]]  # both overlap same GT
    m = match_one_to_one(gt, preds, 0.5)
    assert len(m["matches"]) == 1
    assert len(m["unmatched_pred"]) == 1
    assert len(m["unmatched_gt"]) == 0


def test_prf_and_ap():
    prf = compute_prf(tp=2, fp=1, fn=1)
    assert prf["precision"] == 2/3
    assert prf["recall"] == 2/3
    assert prf["f1"] == 2/3
    ap = voc_ap([0.5, 1.0], [1.0, 0.5])
    assert ap is not None and 0.75 <= ap <= 1.0


def test_validate_annotations_catches_bad_box():
    data = {
        "frames": [{
            "clip_id":"c","clip_file":"c.mp4","frame_index":0,"timestamp_ms":0,
            "image_width":100,"image_height":100,
            "derived_image_path":"missing.png","source_video_path":"missing.mp4",
            "annotation_status":"annotated","no_face":False,"needs_review":False,"frame_notes":"",
            "faces":[{"bbox":[90,90,20,20]}]
        }]
    }
    res = validate_annotations(data, base_dir=__import__('pathlib').Path('.'))
    assert not res["ok"]
    assert any('out of bounds' in e for e in res['errors'])
