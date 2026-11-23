from __future__ import annotations

import copy
import json

from app.db import get_db, utc_now
from app.services import cv_integration
from app.services.best_face import select_from_observations
from app.services.face_reliability import assess_face_reliability


def _quality(
    *,
    score: float = 85.0,
    sharpness: float = 150.0,
    brightness: float = 120.0,
    contrast: float = 45.0,
    face_size_px: int = 120,
    landmark: float = 1.0,
    frontal: float = 0.9,
    occlusion_status: str = "not_suspected",
):
    return {
        "quality_score": score,
        "sharpness": sharpness,
        "brightness": brightness,
        "contrast": contrast,
        "face_size_px": face_size_px,
        "crop_size_px": 160,
        "occlusion_status": occlusion_status,
        "components": {
            "sharpness_component": 0.8,
            "illumination_component": 0.8,
            "contrast_component": 0.8,
            "size_component": 0.8,
            "landmark_component": landmark,
            "frontal_component": frontal,
        },
        "warnings": [],
        "disclaimer": "Image usability only; not an identity, biometric or attribute-classification result.",
    }


def _flags(
    *,
    low_sharpness: bool = False,
    underexposed: bool = False,
    overexposed: bool = False,
    small_face: bool = False,
    pose_away: bool = False,
    partial_occlusion_suspected: bool = False,
    occlusion_review: bool = False,
):
    return {
        "low_sharpness": low_sharpness,
        "underexposed": underexposed,
        "overexposed": overexposed,
        "small_face": small_face,
        "pose_away": pose_away,
        "partial_occlusion_suspected": partial_occlusion_suspected,
        "occlusion_review": occlusion_review,
        "mask": "not_assessed",
        "helmet": "not_assessed",
        "cap": "not_assessed",
        "identity_confirmed": False,
    }


def _observation(
    *,
    quality=None,
    flags=None,
    pose=None,
    crop=None,
):
    quality = quality or _quality()
    flags = flags or _flags()
    pose = pose if pose is not None else {"frontal_score": 0.9, "warnings": [], "method": "proxy"}
    crop = crop or {"crop_id": "c1", "available": True, "status": "available", "retrieval_state": "retrievable"}
    return {
        "observation_id": "obs-1",
        "original_frame_number": 10,
        "original_video_timestamp_seconds": 1.0,
        "bbox": [10, 10, 40, 40],
        "detector_confidence": 0.9,
        "quality": quality,
        "pose": pose,
        "review_flags": flags,
        "crop": crop,
    }


def _indicator(payload, name):
    for indicator in payload["indicators"]:
        if indicator["name"] == name:
            return indicator
    raise AssertionError(name)


def test_high_quality_unobstructed_face_is_usable():
    payload = assess_face_reliability(_observation())
    assert payload["status"] == "usable"
    assert payload["requires_human_verification"] is True
    assert _indicator(payload, "face_visibility")["status"] in {"fully_visible", "mostly_visible"}
    assert _indicator(payload, "image_quality")["status"] == "good"
    assert _indicator(payload, "pose")["status"] == "frontal_or_near_frontal"
    assert _indicator(payload, "potential_concealment")["status"] == "not_assessed"
    assert "not identity" in payload["limitation"].lower()


def test_low_sharpness_reports_poor_image_quality():
    payload = assess_face_reliability(_observation(flags=_flags(low_sharpness=True), quality=_quality(sharpness=20.0, score=40.0)))
    image = _indicator(payload, "image_quality")
    assert payload["status"] == "poor"
    assert image["status"] == "poor"
    assert any("low_sharpness=true" in e for e in image["evidence"])


def test_poor_illumination_reports_limitation():
    under = assess_face_reliability(_observation(flags=_flags(underexposed=True), quality=_quality(brightness=20.0, score=45.0)))
    over = assess_face_reliability(_observation(flags=_flags(overexposed=True), quality=_quality(brightness=240.0, score=45.0)))
    assert _indicator(under, "image_quality")["status"] == "poor"
    assert any("underexposed=true" in e for e in _indicator(under, "image_quality")["evidence"])
    assert _indicator(over, "image_quality")["status"] == "poor"
    assert any("overexposed=true" in e for e in _indicator(over, "image_quality")["evidence"])


def test_small_face_reports_limitation():
    payload = assess_face_reliability(_observation(flags=_flags(small_face=True), quality=_quality(face_size_px=40, score=45.0)))
    image = _indicator(payload, "image_quality")
    assert image["status"] == "poor"
    assert any("small_face=true" in e for e in image["evidence"])


def test_pose_limitation_reported():
    payload = assess_face_reliability(_observation(flags=_flags(pose_away=True), pose={"frontal_score": 0.2, "warnings": ["turned"], "method": "proxy"}))
    pose = _indicator(payload, "pose")
    assert pose["status"] in {"turned_or_profile", "poor_pose"}
    assert payload["status"] in {"limited", "poor"}
    assert any("frontal_score=" in e for e in pose["evidence"])


def test_occlusion_suspected_reported_conservatively():
    payload = assess_face_reliability(
        _observation(
            quality=_quality(occlusion_status="suspected", landmark=0.4),
            flags=_flags(partial_occlusion_suspected=True),
        )
    )
    assert _indicator(payload, "face_visibility")["status"] == "partially_visible"
    assert _indicator(payload, "occlusion")["status"] == "suspected"
    concealment = _indicator(payload, "potential_concealment")
    assert concealment["status"] == "possible_obstruction"
    assert concealment["assessment_type"] == "heuristic"
    assert all("no mask" not in e.lower() for e in concealment["evidence"])


def test_missing_metric_is_unknown_not_fabricated():
    payload = assess_face_reliability({
        "observation_id": "obs-missing",
        "quality": {},
        "review_flags": {},
        "pose": {},
        "crop": {"retrieval_state": "retrievable"},
    })
    assert payload["status"] in {"not_assessed", "limited"}
    assert _indicator(payload, "image_quality")["status"] == "unknown"
    assert _indicator(payload, "pose")["status"] == "unknown"
    assert _indicator(payload, "face_visibility")["status"] == "unknown"
    concealment = _indicator(payload, "potential_concealment")
    assert concealment["status"] == "not_assessed"
    assert concealment["measured"]["mask"] == "not_assessed"
    assert concealment["measured"]["helmet"] == "not_assessed"
    assert concealment["measured"]["cap"] == "not_assessed"


def test_mask_helmet_cap_unsupported_are_explicitly_not_assessed():
    payload = assess_face_reliability(_observation())
    concealment = _indicator(payload, "potential_concealment")
    assert concealment["status"] == "not_assessed"
    assert concealment["assessment_type"] == "not_assessed"
    assert concealment["measured"]["mask"] == "not_assessed"
    assert concealment["measured"]["helmet"] == "not_assessed"
    assert concealment["measured"]["cap"] == "not_assessed"
    assert "do not classify mask" in concealment["limitation"].lower() or "not assessed" in concealment["limitation"].lower()


def test_best_face_selected_reliability_matches_underlying_observation():
    face = _observation()
    face["observation_id"] = "face-1"
    person = {"observation_id": "person-1", "track_id": 7, "frame_number": 10, "timestamp": 1.0, "bbox": [0, 0, 100, 100], "detector_confidence": 0.8}
    payload = select_from_observations(
        {"association_id": "assoc-1", "case_id": "case", "cv_run_id": "run", "person_track_id": 7, "review_state": "proposed"},
        [face],
        [person],
    )
    selected = payload["selected"]
    assert selected is not None
    assert selected["reliability"] == assess_face_reliability(selected["observation"])
    assert payload["ranked_frames"][0]["reliability"]["status"] in {"usable", "limited", "poor", "not_assessed"}


def test_reliability_does_not_alter_selection_or_similarity_scores():
    from app.services.best_face import select_from_observations as select_with_reliability

    face_a = _observation()
    face_a["observation_id"] = "a"
    face_a["original_frame_number"] = 1
    face_a["quality"] = _quality(score=90.0, sharpness=180.0)
    face_a["quality"]["components"]["sharpness_component"] = 0.98
    face_b = _observation()
    face_b["observation_id"] = "b"
    face_b["original_frame_number"] = 2
    face_b["quality"] = _quality(score=80.0, sharpness=20.0)
    face_b["quality"]["components"]["sharpness_component"] = 0.30
    face_b["review_flags"] = _flags(low_sharpness=True)
    persons = [
        {"observation_id": "p1", "track_id": 7, "frame_number": 1, "timestamp": 0.1, "bbox": [0, 0, 100, 100], "detector_confidence": 0.8},
        {"observation_id": "p2", "track_id": 7, "frame_number": 2, "timestamp": 0.2, "bbox": [0, 0, 100, 100], "detector_confidence": 0.8},
    ]
    assoc = {"association_id": "assoc-1", "case_id": "case", "cv_run_id": "run", "person_track_id": 7, "review_state": "proposed"}
    base_a = copy.deepcopy(face_a)
    base_b = copy.deepcopy(face_b)
    payload = select_with_reliability(assoc, [face_a, face_b], persons)
    assert payload["selected"]["observation"]["observation_id"] == "a"
    assert payload["ranked_frames"][0]["selection_score"] > payload["rejected_frames"][0]["selection_score"]
    assert payload["rejected_frames"][0]["reliability"]["status"] == "poor"
    baseline = select_with_reliability(assoc, [base_a, base_b], persons)
    assert payload["selected"]["observation"]["observation_id"] == baseline["selected"]["observation"]["observation_id"]
    assert payload["ranked_frames"][0]["selection_score"] == baseline["ranked_frames"][0]["selection_score"]


def _seed_case_tx_video(client, suffix):
    case = client.post("/api/cases", json={"case_number": f"REL-{suffix}", "title": "Rel", "location": "Test"}).json()
    tx = client.post(f"/api/cases/{case['id']}/transactions", json={
        "reference": f"TX-{suffix}", "atm_id": "ATM-1", "transaction_ts": "2026-01-15T09:00:05+00:00", "transaction_type": "withdrawal", "amount": "100"
    }).json()
    now = utc_now()
    with get_db() as conn:
        video_id = "rel-video-" + suffix.lower()
        conn.execute(
            "INSERT INTO videos (id, case_id, original_filename, stored_path, content_type, size_bytes, sha256, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
            (video_id, case["id"], f"{suffix}.mp4", "uploads/missing.mp4", "video/mp4", 1, "1" * 64, now),
        )
        conn.commit()
    return case, tx, {"id": video_id}


def _seed_cv(client, case_id, tx_id, video_id, monkeypatch):
    now = utc_now()
    run_id = "rel-run"
    sha256 = "1" * 64
    with get_db() as conn:
        conn.execute(
            """INSERT INTO cv_runs (id, case_id, video_id, transaction_id, source_video_sha256, status, window_mode, window_start_seconds, window_end_seconds, analysis_run_id, request_json, window_json, timestamp_provenance_json, model_provenance_json, budget_json, truncation_json, warnings_json, disclaimer, message, created_at, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, case_id, video_id, tx_id, sha256, "completed", "full_video", 0.0, 1.0, "analysis-rel", "{}", "{}", "{}", "[]", "{}", "{}", "[]", "d", "ok", now, now, now),
        )
        conn.commit()
    return run_id


def test_best_face_endpoint_includes_reliability(client, monkeypatch):
    case = client.post("/api/cases", json={"case_number": "REL-ENDPOINT", "title": "Rel", "location": "Test"}).json()
    tx = client.post(f"/api/cases/{case['id']}/transactions", json={
        "reference": "TX-REL-ENDPOINT", "atm_id": "ATM-1", "transaction_ts": "2026-01-15T09:00:05+00:00", "transaction_type": "withdrawal", "amount": "100"
    }).json()
    now = utc_now()
    run_id = "rel-endpoint-run"
    video_id = "rel-video"
    sha256 = "2" * 64
    with get_db() as conn:
        conn.execute("INSERT INTO videos (id, case_id, original_filename, stored_path, content_type, size_bytes, sha256, uploaded_at) VALUES (?,?,?,?,?,?,?,?)", (video_id, case['id'], 'v.mp4', 'uploads/missing.mp4', 'video/mp4', 1, sha256, now))
        conn.execute(
            """INSERT INTO cv_runs (id, case_id, video_id, transaction_id, source_video_sha256, status, window_mode, window_start_seconds, window_end_seconds, analysis_run_id, request_json, window_json, timestamp_provenance_json, model_provenance_json, budget_json, truncation_json, warnings_json, disclaimer, message, created_at, started_at, finished_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, case['id'], video_id, tx['id'], sha256, 'completed', 'full_video', 0.0, 1.0, 'analysis-rel-endpoint', '{}', '{}', '{}', '[]', '{}', '{}', '[]', 'd', 'ok', now, now, now),
        )
        conn.execute(
            "INSERT INTO cv_person_observations (id, cv_run_id, case_id, video_id, sample_id, source_video_sha256, original_frame_number, original_video_timestamp_seconds, analysis_relative_timestamp_seconds, bbox_json, detector_confidence, track_id, zone_overlap_ratio, zone_iou, in_zone, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ('person-1', run_id, case['id'], video_id, 'sample-person-1', sha256, 1, 0.1, 0.1, json.dumps([0,0,100,100]), 0.8, 7, 1.0, 1.0, 1, now),
        )
        conn.execute(
            """INSERT INTO cv_observations (id, cv_run_id, case_id, video_id, sample_id, source_video_sha256, original_frame_number, original_video_timestamp_seconds, analysis_relative_timestamp_seconds, extracted_frame_id, bbox_json, detector_confidence, track_id, quality_json, pose_json, review_flags_json, crop_id, crop_available, crop_status, crop_retrieval_state, verification_status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('face-1', run_id, case['id'], video_id, 'sample-face-1', sha256, 1, 0.1, 0.1, None, json.dumps([10,10,40,40]), 0.95, 31, json.dumps(_quality()), json.dumps({"frontal_score":0.9,"warnings":[],"method":"proxy"}), json.dumps(_flags()), 'crop-face-1', 1, 'available', 'retrievable', 'candidate_only', now),
        )
        conn.execute(
            """INSERT INTO transaction_person_associations (association_id, case_id, transaction_id, cv_run_id, video_id, candidate_key, source_video_sha256, analysis_run_id, zone_id, person_track_id, review_state, evidence_strength, heuristic_score, dwell_seconds, zone_frame_count, transaction_window_overlap_seconds, first_video_timestamp_seconds, last_video_timestamp_seconds, transaction_video_seconds, window_start_seconds, window_end_seconds, evidence_json, reviewer_note, reviewed_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            ('assoc-1', case['id'], tx['id'], run_id, video_id, 'case:tx:run:track7', sha256, 'analysis-rel-endpoint', 'zone-1', 7, 'proposed', 'strong', 0.9, 1.0, 1, 1.0, 0.1, 0.1, 0.1, 0.0, 1.0, json.dumps({"eligibility":{"reasons":[]}}), None, None, now, now),
        )
        conn.commit()
    monkeypatch.setattr(cv_integration, "_observation_from_row", lambda row, vid, h: {
        "observation_id": str(row["id"]), "cv_sample_id": "s1", "cv_run_id": str(row["cv_run_id"]), "case_id": str(row["case_id"]),
        "video_provenance": {"source_video_id": vid, "source_video_sha256": h, "derivative_kind": "none"},
        "original_frame_number": int(row["original_frame_number"]), "original_video_timestamp_seconds": float(row["original_video_timestamp_seconds"]),
        "bbox": json.loads(row["bbox_json"]), "detector_confidence": float(row["detector_confidence"]), "track_id": row["track_id"],
        "quality": json.loads(row["quality_json"]), "pose": json.loads(row["pose_json"]), "review_flags": json.loads(row["review_flags_json"]),
        "crop": {"crop_id": row["crop_id"], "available": True, "status": "available", "retrieval_state": "retrievable"},
        "verification_status": "candidate_only", "requires_human_verification": True, "candidate_disclaimer": "candidate",
    })
    res = client.get(f"/api/cv/runs/{run_id}/person-associations/assoc-1/best-face", params={"case_id": case['id']})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["selected"]["reliability"]["status"] in {"usable", "limited", "poor", "not_assessed"}
    assert body["selected"]["reliability"]["requires_human_verification"] is True
