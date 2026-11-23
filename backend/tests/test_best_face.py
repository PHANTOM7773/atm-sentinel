from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.db import get_db, utc_now
from app.services import cv_integration
from app.services.best_face import select_from_observations
from app.services.security import new_id


def _quality(
    *,
    sharpness: float = 0.9,
    size: float = 0.8,
    frontal: float = 0.9,
    illumination: float = 0.9,
    contrast: float = 0.9,
    landmark: float = 0.9,
    score: float | None = None,
    occlusion_status: str = "not_suspected",
) -> dict[str, Any]:
    if score is None:
        score = round(
            100.0
            * (
                0.28 * sharpness
                + 0.18 * illumination
                + 0.14 * contrast
                + 0.15 * size
                + 0.15 * landmark
                + 0.1 * frontal
            ),
            1,
        )
    return {
        "quality_score": score,
        "sharpness": round(sharpness * 100.0, 2),
        "brightness": 128.0,
        "contrast": round(contrast * 64.0, 2),
        "face_size_px": int(size * 120),
        "crop_size_px": 160,
        "occlusion_status": occlusion_status,
        "components": {
            "sharpness_component": round(sharpness, 3),
            "illumination_component": round(illumination, 3),
            "contrast_component": round(contrast, 3),
            "size_component": round(size, 3),
            "landmark_component": round(landmark, 3),
            "frontal_component": round(frontal, 3),
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
) -> dict[str, Any]:
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


def _face(
    observation_id: str,
    frame_number: int,
    track_id: int,
    *,
    quality: dict[str, Any] | None = None,
    flags: dict[str, Any] | None = None,
    frontal_score: float | None = None,
    detector_confidence: float = 0.9,
    crop_state: str = "retrievable",
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    quality = quality or _quality()
    flags = flags or _flags()
    return {
        "observation_id": observation_id,
        "cv_sample_id": f"sample-{observation_id}",
        "cv_run_id": "run",
        "case_id": "case",
        "original_frame_number": frame_number,
        "original_video_timestamp_seconds": round(frame_number / 10.0, 4),
        "bbox": bbox or [120.0, 20.0, 40.0, 40.0],
        "detector_confidence": detector_confidence,
        "track_id": track_id,
        "quality": quality,
        "pose": {
            "frontal_score": frontal_score if frontal_score is not None else quality["components"]["frontal_component"],
            "warnings": [],
        },
        "review_flags": flags,
        "crop": {
            "crop_id": f"crop-{observation_id}",
            "available": crop_state == "retrievable",
            "status": "available" if crop_state == "retrievable" else "unavailable",
            "retrieval_state": crop_state,
        },
    }


def _person(observation_id: str, frame_number: int, track_id: int, bbox: list[float] | None = None) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "track_id": track_id,
        "frame_number": frame_number,
        "timestamp": round(frame_number / 10.0, 4),
        "bbox": bbox or [80.0, 0.0, 220.0, 220.0],
        "detector_confidence": 0.8,
    }


def _association(track_id: int | None = 7, review_state: str = "proposed") -> dict[str, Any]:
    return {
        "association_id": "assoc-1",
        "case_id": "case",
        "cv_run_id": "run",
        "person_track_id": track_id,
        "review_state": review_state,
    }


def _selected_id(payload: dict[str, Any]) -> str | None:
    selected = payload["selected"]
    return selected["observation"]["observation_id"] if selected else None


def test_clear_sharp_face_outranks_lower_sharpness_face() -> None:
    sharp = _face("sharp", 1, 31, quality=_quality(sharpness=0.98))
    lower = _face("lower", 2, 32, quality=_quality(sharpness=0.42))
    persons = [_person("person-1", 1, 7), _person("person-2", 2, 7)]
    payload = select_from_observations(_association(), [sharp, lower], persons)

    assert _selected_id(payload) == "sharp"
    assert [item["observation"]["observation_id"] for item in payload["ranked_frames"]] == ["sharp", "lower"]
    assert payload["ranked_frames"][0]["selection_score"] > payload["ranked_frames"][1]["selection_score"]
    assert "sharpness_contribution" in payload["ranked_frames"][0]["quality_indicators"]


def test_better_usable_resolution_influences_selection() -> None:
    larger = _face("larger", 1, 31, quality=_quality(size=0.95, score=80.0))
    smaller = _face("smaller", 2, 32, quality=_quality(size=0.35, score=80.0))
    persons = [_person("person-1", 1, 7), _person("person-2", 2, 7)]
    payload = select_from_observations(_association(), [larger, smaller], persons)

    assert _selected_id(payload) == "larger"
    assert payload["ranked_frames"][0]["quality_indicators"]["usable_resolution_contribution"] > (
        payload["ranked_frames"][1]["quality_indicators"]["usable_resolution_contribution"]
    )


def test_pose_illumination_and_occlusion_indicators_affect_selection() -> None:
    clear = _face("clear", 1, 31, quality=_quality(frontal=0.95, illumination=0.95))
    pose_away = _face(
        "pose-away",
        2,
        32,
        quality=_quality(frontal=0.2, illumination=0.95),
        flags=_flags(pose_away=True),
        frontal_score=0.2,
    )
    underexposed = _face(
        "underexposed",
        3,
        33,
        quality=_quality(illumination=0.15, score=45.0),
        flags=_flags(underexposed=True),
    )
    occlusion_review = _face(
        "occlusion-review",
        4,
        34,
        quality=_quality(frontal=0.9, illumination=0.9, occlusion_status="review"),
        flags=_flags(occlusion_review=True),
    )
    occlusion_suspected = _face(
        "occlusion-suspected",
        5,
        35,
        quality=_quality(frontal=0.9, occlusion_status="suspected"),
        flags=_flags(partial_occlusion_suspected=True),
    )
    persons = [_person(f"person-{index}", index, 7) for index in range(1, 6)]
    payload = select_from_observations(
        _association(),
        [pose_away, underexposed, occlusion_suspected, occlusion_review, clear],
        persons,
    )

    assert _selected_id(payload) == "clear"
    assert any(item["observation"]["observation_id"] == "occlusion-review" for item in payload["ranked_frames"])
    rejected = {item["observation"]["observation_id"]: item for item in payload["rejected_frames"]}
    assert set(rejected) == {"pose-away", "underexposed", "occlusion-suspected"}
    assert "pose_away" in rejected["pose-away"]["reason_codes"]
    assert "underexposed" in rejected["underexposed"]["reason_codes"]
    assert "occlusion_suspected" in rejected["occlusion-suspected"]["reason_codes"]


def test_deterministic_tie_break_uses_frame_then_observation_id() -> None:
    later = _face("a-later", 7, 31)
    earlier = _face("z-earlier", 3, 32)
    persons = [_person("person-a", 7, 7), _person("person-b", 3, 7)]
    payload = select_from_observations(_association(), [later, earlier], persons)
    assert _selected_id(payload) == "z-earlier"

    first = _face("z-same-frame", 3, 31)
    second = _face("a-same-frame", 3, 32)
    tied_persons = [_person("person-c", 3, 7), _person("person-d", 3, 7)]
    tied = select_from_observations(_association(), [first, second], tied_persons)
    assert _selected_id(tied) == "a-same-frame"


def test_no_usable_faces_returns_explicit_no_selection() -> None:
    payload = select_from_observations(_association(), [], [_person("person-1", 1, 7)])
    assert payload["selected"] is None
    assert payload["no_selection_reason"] == "no_face_observations_in_run"
    assert payload["ranked_frames"] == []
    assert payload["requires_human_verification"] is True
    assert payload["original_evidence_preserved"] is True


def test_low_quality_only_frame_is_not_selected() -> None:
    low_quality = _face(
        "low-quality",
        1,
        31,
        quality=_quality(sharpness=0.1, size=0.15, frontal=0.2, score=22.0),
        flags=_flags(low_sharpness=True, small_face=True, pose_away=True),
        frontal_score=0.2,
    )
    payload = select_from_observations(_association(), [low_quality], [_person("person-1", 1, 7)])

    assert payload["selected"] is None
    assert payload["no_selection_reason"] == "no_eligible_face_for_person"
    assert len(payload["rejected_frames"]) == 1
    assert set(payload["rejected_frames"][0]["reason_codes"]) >= {
        "low_sharpness",
        "small_face",
        "pose_away",
    }


def test_crop_not_retrievable_frame_is_rejected() -> None:
    expired = _face("expired", 1, 31, crop_state="expired")
    payload = select_from_observations(_association(), [expired], [_person("person-1", 1, 7)])

    assert payload["selected"] is None
    assert "crop_not_retrievable" in payload["rejected_frames"][0]["reason_codes"]


def test_faces_from_different_people_are_not_mixed() -> None:
    target = _face("target", 1, 31)
    other = _face("other", 2, 41)
    persons = [_person("person-target", 1, 7), _person("person-other", 2, 8)]
    payload = select_from_observations(_association(7), [target, other], persons)

    assert _selected_id(payload) == "target"
    assert [item["observation"]["observation_id"] for item in payload["ranked_frames"]] == ["target"]
    assert [item["observation"]["observation_id"] for item in payload["other_person_frames"]] == ["other"]
    assert payload["other_person_frames"][0]["reason_codes"] == ["different_person_track"]


def test_ambiguous_person_link_is_kept_out_of_ranked_frames() -> None:
    overlapping = _face("ambiguous", 1, 31, bbox=[150.0, 20.0, 40.0, 40.0])
    persons = [
        _person("person-a", 1, 7, bbox=[120.0, 0.0, 60.0, 200.0]),
        _person("person-b", 1, 8, bbox=[160.0, 0.0, 60.0, 200.0]),
    ]
    payload = select_from_observations(_association(7), [overlapping], persons)

    assert payload["selected"] is None
    assert payload["no_selection_reason"] == "no_face_observations_linked_to_person"
    assert payload["other_person_frames"][0]["reason_codes"] == ["ambiguous_person_track_link", "person_track_link_unusable"]


def test_rejected_association_has_no_selection() -> None:
    face = _face("face", 1, 31)
    payload = select_from_observations(_association(review_state="rejected"), [face], [_person("person-1", 1, 7)])
    assert payload["selected"] is None
    assert payload["no_selection_reason"] == "association_review_rejected"


def test_original_observations_are_not_mutated() -> None:
    faces = [_face("face", 1, 31), _face("face-2", 2, 32)]
    persons = [_person("person-1", 1, 7), _person("person-2", 2, 7)]
    faces_before = copy.deepcopy(faces)
    persons_before = copy.deepcopy(persons)

    select_from_observations(_association(), faces, persons)

    assert faces == faces_before
    assert persons == persons_before


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _seed_case_run(client: Any, case_number: str, monkeypatch: Any) -> dict[str, Any]:
    monkeypatch.setattr(cv_integration, "_crop_retrieval_state", lambda row: "retrievable")
    now = utc_now()
    case_id = new_id()
    video_id = new_id()
    run_id = new_id()
    association_id = new_id()
    sha256 = "a" * 64
    with get_db() as conn:
        conn.execute(
            "INSERT INTO cases(id, case_number, title, location, created_at, updated_at) VALUES(?,?,?,?,?,?)",
            (case_id, case_number, case_number, "Test", now, now),
        )
        conn.execute(
            """
            INSERT INTO videos(
                id, case_id, original_filename, stored_path, content_type, size_bytes, sha256,
                width, height, fps, duration, uploaded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                video_id,
                case_id,
                "test.mp4",
                "unused.mp4",
                "video/mp4",
                100,
                sha256,
                640,
                480,
                10.0,
                1.0,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO cv_runs(
                id, case_id, video_id, source_video_sha256, status, window_mode,
                analysis_run_id, created_at, window_start_seconds, window_end_seconds
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (run_id, case_id, video_id, sha256, "completed", "full_video", f"analysis-{run_id}", now, 0.0, 1.0),
        )
        conn.execute(
            """
            INSERT INTO transaction_person_associations(
                association_id, case_id, cv_run_id, video_id, candidate_key, source_video_sha256,
                analysis_run_id, zone_id, person_track_id, review_state, evidence_strength,
                heuristic_score, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                association_id,
                case_id,
                run_id,
                video_id,
                "track-7",
                sha256,
                f"analysis-{run_id}",
                "zone-1",
                7,
                "proposed",
                "strong",
                0.9,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO cv_person_observations(
                id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds, bbox_json,
                detector_confidence, track_id, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_id(),
                run_id,
                case_id,
                video_id,
                f"{run_id}-person-1",
                sha256,
                1,
                0.1,
                _json([80.0, 0.0, 220.0, 220.0]),
                0.8,
                7,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO cv_observations(
                id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds, bbox_json, detector_confidence,
                track_id, quality_json, pose_json, review_flags_json, crop_id, crop_available,
                crop_status, crop_retrieval_state, verification_status, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "face-observation-1",
                run_id,
                case_id,
                video_id,
                f"{run_id}-face-1",
                sha256,
                1,
                0.1,
                _json([120.0, 20.0, 40.0, 40.0]),
                0.95,
                31,
                _json(_quality()),
                _json({"frontal_score": 0.9, "warnings": []}),
                _json(_flags()),
                "crop-face-observation-1",
                1,
                "available",
                "retrievable",
                "candidate_only",
                now,
            ),
        )
    return {"case_id": case_id, "run_id": run_id, "association_id": association_id, "sha256": sha256}


def test_best_face_endpoint_is_case_and_run_scoped(client: Any, monkeypatch: Any) -> None:
    seeded = _seed_case_run(client, "BEST-FACE-API", monkeypatch)
    other_case = client.post(
        "/api/cases",
        json={"case_number": "BEST-FACE-OTHER", "title": "Other", "location": "Test"},
    ).json()

    url = (
        f"/api/cv/runs/{seeded['run_id']}/person-associations/{seeded['association_id']}/best-face"
    )
    response = client.get(url, params={"case_id": seeded["case_id"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected"]["observation"]["observation_id"] == "face-observation-1"
    assert body["selected"]["rank"] == 1
    assert body["score_meaning"].startswith("Heuristic quality-ranking score")
    assert body["requires_human_verification"] is True

    wrong_case = client.get(url, params={"case_id": other_case["id"]})
    assert wrong_case.status_code == 404

    wrong_run = client.get(
        f"/api/cv/runs/unknown-run/person-associations/{seeded['association_id']}/best-face",
        params={"case_id": seeded["case_id"]},
    )
    assert wrong_run.status_code == 404


def test_association_list_contains_read_only_best_face_summary(client: Any, monkeypatch: Any) -> None:
    seeded = _seed_case_run(client, "BEST-FACE-LIST", monkeypatch)
    response = client.get(
        f"/api/cv/runs/{seeded['run_id']}/person-associations",
        params={"case_id": seeded["case_id"]},
    )
    assert response.status_code == 200, response.text
    association = response.json()["items"][0]
    summary = association["best_face"]
    assert summary["status"] == "selected"
    assert summary["selected_observation_id"] == "face-observation-1"
    assert summary["selected_frame_number"] == 1
    assert summary["ranked_frame_count"] == 1
    assert summary["limitation"].startswith("Best-face selection is a deterministic review aid")

    with get_db() as conn:
        row = conn.execute(
            "SELECT quality_json FROM cv_observations WHERE id=?",
            ("face-observation-1",),
        ).fetchone()
    assert json.loads(row["quality_json"])["quality_score"] == _quality()["quality_score"]
