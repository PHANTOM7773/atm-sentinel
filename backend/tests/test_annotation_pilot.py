from __future__ import annotations

import json

from app.cv.annotation_pilot import summarize_pilot, validate_bbox, validate_pilot_document


def base_doc():
    return {
        "schema_version": "1.0-pilot",
        "annotation_type": "face_bbox_ground_truth_pilot",
        "dataset_id": "synthetic-cv",
        "source_manifest": "data/datasets/synthetic/cv/manifest.json",
        "bbox_format": "xywh_pixels_top_left",
        "frames": [
            {
                "clip_id": "subject_a_front",
                "frame_index": 0,
                "timestamp_ms": 0.0,
                "image_width": 640,
                "image_height": 480,
                "annotation_status": "annotated",
                "no_face": False,
                "faces": [
                    {
                        "annotation_id": "ann1",
                        "bbox": [10, 20, 30, 40],
                        "visibility": "visible",
                        "pose": "front",
                        "face_size": "medium",
                        "blur": "none",
                        "illumination": "normal",
                        "annotation_confidence": "high",
                        "ignore_difficult": False,
                    }
                ],
            }
        ],
    }


def test_validate_bbox_inside_bounds():
    assert validate_bbox([0, 0, 10, 10], width=100, height=100, path="b") == []
    assert any(i.severity == "error" for i in validate_bbox([95, 0, 10, 10], width=100, height=100, path="b"))


def test_validate_doc_ok():
    issues = validate_pilot_document(base_doc(), manifest={"videos": {"subject_a_front": {"frame_count": 40}}, "fps": 10})
    assert not [i for i in issues if i.severity == "error"]


def test_duplicate_annotation_id_and_invalid_box():
    doc = base_doc()
    doc["frames"].append({
        "clip_id": "subject_a_front", "frame_index": 1, "timestamp_ms": 100.0, "image_width": 640, "image_height": 480,
        "annotation_status": "annotated", "no_face": False,
        "faces": [{"annotation_id": "ann1", "bbox": [1, 2, -3, 4], "visibility": "visible", "pose": "front", "face_size": "small", "blur": "none", "illumination": "normal", "annotation_confidence": "low", "ignore_difficult": False}]
    })
    issues = validate_pilot_document(doc, manifest={"videos": {"subject_a_front": {"frame_count": 40}}, "fps": 10})
    msgs = [i.message for i in issues]
    assert any("duplicate annotation_id" in m for m in msgs)
    assert any("width/height" in m for m in msgs)


def test_no_face_frame_rules():
    doc = base_doc()
    doc["frames"][0]["no_face"] = True
    doc["frames"][0]["faces"] = [{"annotation_id": "x", "bbox": [1,1,2,2], "visibility":"visible","pose":"front","face_size":"small","blur":"none","illumination":"normal","annotation_confidence":"high","ignore_difficult":False}]
    issues = validate_pilot_document(doc)
    assert any("no_face=true" in i.message for i in issues)


def test_summary_counts():
    doc = base_doc()
    doc["frames"][0]["faces"].append({"annotation_id":"ann2","bbox":[1,1,2,2],"visibility":"partially_occluded","pose":"profile","face_size":"small","blur":"mild","illumination":"dark","annotation_confidence":"low","ignore_difficult":True})
    s = summarize_pilot(doc)
    assert s["total_face_boxes"] == 2
    assert s["difficult_ignored_faces"] == 1
    assert s["low_confidence_annotations"] == 1
    assert s["benchmark_ready"] is False
