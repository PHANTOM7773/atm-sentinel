from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from ..config import CV_FACE_SCORE_THRESHOLD
from ..db import get_db, parse_json
from ..schemas import CV_BEST_FACE_LIMITATION, CV_BEST_FACE_SCORE_MEANING
from . import cv_integration
from .atm_association import association_from_row
from .face_reliability import assess_face_reliability


class BestFaceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


LINK_METHOD = "same_frame_face_bbox_contained_in_person_bbox"
MIN_FACE_BBOX_CONTAINMENT = 0.6
SELECTION_WEIGHTS = {
    "sharpness": 0.3,
    "usable_resolution": 0.15,
    "frontalness": 0.15,
    "illumination": 0.15,
    "contrast": 0.1,
    "landmark_visibility": 0.1,
    "detector_confidence": 0.05,
}
METHODOLOGY = {
    "method": "deterministic_quality_ranking_of_existing_face_observations",
    "link_method": LINK_METHOD,
    "minimum_face_bbox_containment": MIN_FACE_BBOX_CONTAINMENT,
    "crop_requirement": "retrievable",
    "detector_confidence_threshold": CV_FACE_SCORE_THRESHOLD,
    "hard_rejection_flags": [
        "low_sharpness",
        "underexposed",
        "overexposed",
        "small_face",
        "pose_away",
        "occlusion_suspected",
        "quality_components_missing",
        "crop_not_retrievable",
        "face_detector_confidence_below_threshold",
    ],
    "occlusion_review_factor": 0.75,
    "tie_break": "earlier_original_frame_number_then_observation_id",
    "score_meaning": CV_BEST_FACE_SCORE_MEANING,
    "limitation": CV_BEST_FACE_LIMITATION,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _as_bool(value: Any) -> bool:
    return value is True or value == 1


def _bbox_xyxy(bbox: Any) -> tuple[float, float, float, float]:
    values = list(bbox) if isinstance(bbox, (list, tuple)) else []
    padded = [_as_float(value) for value in values[:4]]
    while len(padded) < 4:
        padded.append(0.0)
    x, y, width, height = padded
    if width < 0:
        x, width = x + width, -width
    if height < 0:
        y, height = y + height, -height
    return x, y, x + width, y + height


def _face_person_containment(face_bbox: Any, person_bbox: Any) -> tuple[float, bool]:
    fx1, fy1, fx2, fy2 = _bbox_xyxy(face_bbox)
    px1, py1, px2, py2 = _bbox_xyxy(person_bbox)
    face_area = max(0.0, fx2 - fx1) * max(0.0, fy2 - fy1)
    if face_area <= 0 or px2 <= px1 or py2 <= py1:
        return 0.0, False
    intersection_x = max(0.0, min(fx2, px2) - max(fx1, px1))
    intersection_y = max(0.0, min(fy2, py2) - max(fy1, py1))
    ratio = (intersection_x * intersection_y) / face_area
    center_x = (fx1 + fx2) / 2.0
    center_y = (fy1 + fy2) / 2.0
    center_inside = px1 <= center_x <= px2 and py1 <= center_y <= py2
    return min(1.0, max(0.0, ratio)), center_inside


def _link_faces_to_persons(
    faces: list[dict[str, Any]], persons: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    persons_by_frame: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for person in persons:
        try:
            frame_number = int(person["frame_number"])
        except (KeyError, TypeError, ValueError):
            continue
        if person.get("track_id") is None:
            continue
        persons_by_frame[frame_number].append(person)

    linked: list[dict[str, Any]] = []
    for face in faces:
        frame_number = int(face["original_frame_number"])
        candidates: list[tuple[float, int, str, dict[str, Any]]] = []
        for person in persons_by_frame.get(frame_number, []):
            ratio, center_inside = _face_person_containment(face.get("bbox"), person.get("bbox"))
            if not center_inside or ratio < MIN_FACE_BBOX_CONTAINMENT:
                continue
            candidates.append(
                (
                    round(ratio, 6),
                    int(person["track_id"]),
                    str(person["observation_id"]),
                )
            )
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        if not candidates:
            link = {
                "link_state": "missing",
                "reason_codes": ["no_same_frame_person_bbox_link"],
            }
        else:
            top_ratio = candidates[0][0]
            competing_tracks = {item[1] for item in candidates if item[0] == top_ratio}
            if len(competing_tracks) > 1:
                link = {
                    "link_state": "ambiguous",
                    "reason_codes": ["ambiguous_person_track_link"],
                }
            else:
                ratio, track_id, person_observation_id = candidates[0]
                link = {
                    "link_state": "linked",
                    "person_track_id": track_id,
                    "face_track_id": face.get("track_id"),
                    "person_observation_id": person_observation_id,
                    "original_frame_number": frame_number,
                    "original_video_timestamp_seconds": _as_float(face.get("original_video_timestamp_seconds")),
                    "bbox_containment_ratio": round(ratio, 4),
                    "method": LINK_METHOD,
                    "limitations": [
                        "Run-local bbox containment is not identity evidence.",
                        "Track IDs may be reused across runs and are not identities.",
                        "Occlusion and pose are heuristic indicators, not calibrated measurements.",
                    ],
                    "reason_codes": [],
                }
        linked.append({"face": face, "link": link})
    return linked


def _component_values(face: dict[str, Any]) -> dict[str, float]:
    quality = face.get("quality") or {}
    components = quality.get("components") or {}
    pose = face.get("pose") or {}
    return {
        "sharpness": _as_float(components.get("sharpness_component")),
        "usable_resolution": _as_float(components.get("size_component")),
        "frontalness": _as_float(components.get("frontal_component", pose.get("frontal_score"))),
        "illumination": _as_float(components.get("illumination_component")),
        "contrast": _as_float(components.get("contrast_component")),
        "landmark_visibility": _as_float(components.get("landmark_component")),
        "detector_confidence": min(1.0, max(0.0, _as_float(face.get("detector_confidence")))),
    }


def _score_face(face: dict[str, Any], link: dict[str, Any]) -> dict[str, Any]:
    quality = face.get("quality") or {}
    pose = face.get("pose") or {}
    flags = face.get("review_flags") or {}
    crop = face.get("crop") or {}
    components = quality.get("components") or {}
    reason_codes: list[str] = list(link.get("reason_codes") or [])
    rationale: list[str] = []

    if link.get("link_state") != "linked":
        reason_codes.append("person_track_link_unusable")
    if crop.get("retrieval_state") != "retrievable":
        reason_codes.append("crop_not_retrievable")
    if _as_float(face.get("detector_confidence")) < CV_FACE_SCORE_THRESHOLD:
        reason_codes.append("face_detector_confidence_below_threshold")
    if _as_bool(flags.get("low_sharpness")):
        reason_codes.append("low_sharpness")
    if _as_bool(flags.get("underexposed")):
        reason_codes.append("underexposed")
    if _as_bool(flags.get("overexposed")):
        reason_codes.append("overexposed")
    if _as_bool(flags.get("small_face")):
        reason_codes.append("small_face")
    if _as_bool(flags.get("pose_away")) or _as_float(pose.get("frontal_score"), 1.0) < 0.5:
        reason_codes.append("pose_away")
    if not components:
        reason_codes.append("quality_components_missing")

    occlusion_status = str(quality.get("occlusion_status") or "unknown")
    if _as_bool(flags.get("partial_occlusion_suspected")) or occlusion_status == "suspected":
        reason_codes.append("occlusion_suspected")
    occlusion_factor = 1.0
    if _as_bool(flags.get("occlusion_review")) or occlusion_status == "review":
        occlusion_factor = METHODOLOGY["occlusion_review_factor"]
        rationale.append("Occlusion review flag reduced the ranking weight.")

    values = _component_values(face)
    contributions = {name: round(values[name] * weight, 4) for name, weight in SELECTION_WEIGHTS.items()}
    raw_score = sum(values[name] * weight for name, weight in SELECTION_WEIGHTS.items()) * occlusion_factor
    selection_score = round(min(1.0, max(0.0, raw_score)), 4)

    ranked_signals = sorted(contributions.items(), key=lambda item: (-item[1], item[0]))[:3]
    for name, contribution in ranked_signals:
        rationale.append(f"{name} contributed {contribution:.4f} to the quality-ranking score.")
    if link.get("link_state") == "linked":
        rationale.append(
            "Face bbox was contained in person-track bbox "
            f"{float(link.get('bbox_containment_ratio') or 0.0):.3f} in the same frame."
        )

    indicators = {
        "quality_score": _as_float(quality.get("quality_score")),
        **{f"{name}_component": round(value, 4) for name, value in values.items()},
        **{f"{name}_contribution": contribution for name, contribution in contributions.items()},
        "occlusion_factor": occlusion_factor,
    }
    if link.get("bbox_containment_ratio") is not None:
        indicators["bbox_containment_ratio"] = _as_float(link.get("bbox_containment_ratio"))

    return {
        "selection_score": selection_score,
        "eligible": not reason_codes,
        "reason_codes": sorted(set(reason_codes)),
        "rationale": rationale,
        "quality_indicators": indicators,
    }


def _ranked_frame(
    face: dict[str, Any],
    link: dict[str, Any],
    scoring: dict[str, Any],
    *,
    rank: int | None = None,
    extra_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    reason_codes = list(scoring["reason_codes"])
    if extra_reason_codes:
        reason_codes.extend(extra_reason_codes)
    link_summary = None
    if link.get("link_state") == "linked":
        link_summary = {
            "method": link["method"],
            "person_track_id": link["person_track_id"],
            "face_track_id": link.get("face_track_id"),
            "person_observation_id": link["person_observation_id"],
            "original_frame_number": link["original_frame_number"],
            "original_video_timestamp_seconds": link["original_video_timestamp_seconds"],
            "bbox_containment_ratio": link["bbox_containment_ratio"],
            "limitations": link["limitations"],
        }
    return {
        "observation": face,
        "rank": rank,
        "selection_score": scoring["selection_score"],
        "eligible": scoring["eligible"] and not extra_reason_codes,
        "reason_codes": sorted(set(reason_codes)),
        "rationale": scoring["rationale"],
        "quality_indicators": scoring["quality_indicators"],
        "reliability": assess_face_reliability(face),
        "link": link_summary,
    }


def _sort_key(item: dict[str, Any]) -> tuple[float, int, str]:
    observation = item["observation"]
    return (
        -_as_float(item.get("selection_score")),
        int(observation.get("original_frame_number", 0)),
        str(observation.get("observation_id", "")),
    )


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    selected = payload.get("selected")
    reliability = selected.get("reliability") if isinstance(selected, dict) else None
    return {
        "status": "selected" if selected else "no_selection",
        "selected_observation_id": selected["observation"]["observation_id"] if selected else None,
        "selected_frame_number": selected["observation"]["original_frame_number"] if selected else None,
        "selected_timestamp_seconds": (
            selected["observation"]["original_video_timestamp_seconds"] if selected else None
        ),
        "selected_selection_score": selected["selection_score"] if selected else None,
        "selected_reliability_status": reliability.get("status") if isinstance(reliability, dict) else None,
        "selected_reliability_summary": reliability.get("summary") if isinstance(reliability, dict) else None,
        "ranked_frame_count": len(payload["ranked_frames"]),
        "rejected_frame_count": len(payload["rejected_frames"]),
        "other_person_frame_count": len(payload["other_person_frames"]),
        "no_selection_reason": payload.get("no_selection_reason"),
        "score_meaning": CV_BEST_FACE_SCORE_MEANING,
        "limitation": CV_BEST_FACE_LIMITATION,
    }


def _selection_payload(
    association: dict[str, Any],
    faces: list[dict[str, Any]],
    persons: list[dict[str, Any]],
) -> dict[str, Any]:
    base = {
        "case_id": association["case_id"],
        "cv_run_id": association["cv_run_id"],
        "association_id": association["association_id"],
        "person_track_id": association.get("person_track_id"),
        "association_review_state": association["review_state"],
        "selected": None,
        "ranked_frames": [],
        "rejected_frames": [],
        "other_person_frames": [],
        "no_selection_reason": None,
        "methodology": dict(METHODOLOGY),
        "score_meaning": CV_BEST_FACE_SCORE_MEANING,
        "limitation": CV_BEST_FACE_LIMITATION,
        "requires_human_verification": True,
        "original_evidence_preserved": True,
    }
    if association.get("review_state") == "rejected":
        base["no_selection_reason"] = "association_review_rejected"
        return base
    if association.get("person_track_id") is None:
        base["no_selection_reason"] = "no_person_track_in_association"
        return base

    target_track = int(association["person_track_id"])
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    for linked_face in _link_faces_to_persons(faces, persons):
        face = linked_face["face"]
        link = linked_face["link"]
        scoring = _score_face(face, link)
        target = link.get("person_track_id")
        if target == target_track:
            item = _ranked_frame(face, link, scoring)
            if scoring["eligible"]:
                eligible.append(item)
            else:
                rejected.append(item)
        else:
            extra = ["different_person_track"] if link.get("link_state") == "linked" else []
            other.append(_ranked_frame(face, link, scoring, extra_reason_codes=extra))

    eligible.sort(key=_sort_key)
    rejected.sort(key=_sort_key)
    other.sort(key=_sort_key)
    for index, item in enumerate(eligible, start=1):
        item["rank"] = index

    base["ranked_frames"] = eligible
    base["rejected_frames"] = rejected
    base["other_person_frames"] = other
    if eligible:
        base["selected"] = eligible[0]
    elif not faces:
        base["no_selection_reason"] = "no_face_observations_in_run"
    elif not rejected:
        base["no_selection_reason"] = "no_face_observations_linked_to_person"
    else:
        base["no_selection_reason"] = "no_eligible_face_for_person"
    return base


def _load_context(case_id: str, cv_run_id: str, association_id: str | None = None) -> dict[str, Any]:
    with get_db() as conn:
        run = conn.execute("SELECT * FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
        if not run or str(run["case_id"]) != case_id:
            raise BestFaceError("CV run not found", 404)
        association_clause = ""
        association_values: list[Any] = [cv_run_id, case_id]
        if association_id:
            association_clause = " AND association_id=?"
            association_values.append(association_id)
        association_rows = conn.execute(
            f"""
            SELECT * FROM transaction_person_associations
            WHERE cv_run_id=? AND case_id=?{association_clause}
            ORDER BY heuristic_score DESC, person_track_id ASC, association_id ASC
            """,
            association_values,
        ).fetchall()
        if association_id and not association_rows:
            raise BestFaceError("Transaction-person association not found", 404)
        video_id = str(run["video_id"])
        sha256 = str(run["source_video_sha256"])
        face_rows = conn.execute(
            """
            SELECT * FROM cv_observations
            WHERE case_id=? AND cv_run_id=? AND video_id=? AND source_video_sha256=?
            ORDER BY original_frame_number, id
            """,
            (case_id, cv_run_id, video_id, sha256),
        ).fetchall()
        person_rows = conn.execute(
            """
            SELECT * FROM cv_person_observations
            WHERE case_id=? AND cv_run_id=? AND video_id=? AND source_video_sha256=?
            ORDER BY original_frame_number, id
            """,
            (case_id, cv_run_id, video_id, sha256),
        ).fetchall()

    faces = [
        cv_integration._observation_from_row(row, video_id, sha256)
        for row in face_rows[: cv_integration.CV_MAX_OBSERVATIONS]
    ]
    persons = []
    for row in person_rows:
        persons.append(
            {
                "observation_id": str(row["id"]),
                "track_id": row["track_id"],
                "frame_number": int(row["original_frame_number"]),
                "timestamp": float(row["original_video_timestamp_seconds"]),
                "bbox": parse_json(row["bbox_json"], []),
                "detector_confidence": float(row["detector_confidence"]),
            }
        )
    return {
        "associations": [association_from_row(row) for row in association_rows],
        "faces": faces,
        "persons": persons,
    }


def get_selection(case_id: str, cv_run_id: str, association_id: str) -> dict[str, Any]:
    context = _load_context(case_id, cv_run_id, association_id)
    return _selection_payload(context["associations"][0], context["faces"], context["persons"])


def build_summaries(case_id: str, cv_run_id: str, associations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not associations:
        return {}
    context = _load_context(case_id, cv_run_id)
    summaries: dict[str, dict[str, Any]] = {}
    for association in associations:
        payload = _selection_payload(association, context["faces"], context["persons"])
        summaries[str(association["association_id"])] = _summary(payload)
    return summaries


def select_from_observations(
    association: dict[str, Any],
    faces: list[dict[str, Any]],
    persons: list[dict[str, Any]],
) -> dict[str, Any]:
    return _selection_payload(association, faces, persons)
