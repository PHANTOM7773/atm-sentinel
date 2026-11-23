from __future__ import annotations

from app.cv.bbox_ground_truth import iou_xywh, match_detections, summarize_eval, validate_annotation_document


def _doc():
    return {
        "schema_version": "1.0-draft",
        "dataset_id": "synthetic-cv",
        "annotation_type": "face_bbox_ground_truth",
        "clips": [
            {
                "clip_id": "subject_a_front",
                "frame_count": 40,
                "width": 640,
                "height": 480,
                "frames": [
                    {
                        "frame_number": 0,
                        "faces": [
                            {
                                "annotation_id": "a0f0",
                                "bbox": [10, 20, 30, 40],
                                "visibility": "visible",
                                "pose": "frontal",
                                "face_size": "medium",
                                "difficulty": "easy",
                                "annotator_confidence": 0.9,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def test_valid_minimal_doc():
    issues = validate_annotation_document(_doc(), known_clips={"subject_a_front": {"frame_count": 40}})
    assert issues == []


def test_invalid_bbox_and_frame():
    doc = _doc()
    doc["clips"][0]["frames"][0]["frame_number"] = 99
    doc["clips"][0]["frames"][0]["faces"][0]["bbox"] = [700, 10, 30, 40]
    issues = validate_annotation_document(doc, known_clips={"subject_a_front": {"frame_count": 40}})
    msgs = [i.message for i in issues]
    assert any("out of range" in m for m in msgs)
    assert any("exceeds frame bounds" in m for m in msgs)


def test_duplicate_annotation_id():
    doc = _doc()
    face = dict(doc["clips"][0]["frames"][0]["faces"][0])
    doc["clips"][0]["frames"].append({"frame_number": 1, "faces": [face]})
    issues = validate_annotation_document(doc, known_clips={"subject_a_front": {"frame_count": 40}})
    assert any("duplicate annotation_id" in i.message for i in issues)


def test_iou_and_matching_with_ignore():
    assert iou_xywh([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    gts = [
        {"bbox": [10, 10, 20, 20], "ignore": False},
        {"bbox": [100, 100, 20, 20], "ignore": True},
    ]
    preds = [{"bbox": [10, 10, 20, 20]}, {"bbox": [100, 100, 20, 20]}, {"bbox": [200, 200, 20, 20]}]
    m = match_detections(gts, preds, iou_threshold=0.5)
    assert len(m["matches"]) == 1
    assert m["false_negative_gt_indices"] == []
    assert m["ignored_matched_pred_indices"] == [1]
    assert m["false_positive_pred_indices"] == [2]
    s = summarize_eval(gts, preds, iou_threshold=0.5)
    assert s["tp"] == 1 and s["fp"] == 1 and s["fn"] == 0
