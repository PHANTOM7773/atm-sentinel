from __future__ import annotations

from typing import Any

from ..schemas import CV_UNSUPPORTED_ATTRIBUTE_STATUS

RELIABILITY_STATUSES = ("usable", "limited", "poor", "not_assessed")
VISIBILITY_STATUSES = ("fully_visible", "mostly_visible", "partially_visible", "insufficient_visibility", "unknown")
OCCLUSION_STATUSES = ("not_suspected", "review_needed", "suspected", "unknown")
POSE_STATUSES = ("frontal_or_near_frontal", "turned_or_profile", "poor_pose", "unknown")
IMAGE_QUALITY_STATUSES = ("good", "limited", "poor", "unknown")
CONCEALMENT_STATUSES = ("not_assessed", "possible_obstruction")
ASSESSMENT_TYPES = ("measured", "heuristic", "not_assessed")

RELIABILITY_LIMITATION = (
    "Reliability and visibility indicators describe face-frame usability for human visual review only. "
    "They are not identity, biometric match, criminality, account ownership, or suspect-identification evidence. "
    "Mask, helmet, and cap classification are not assessed by the current implementation."
)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _as_bool(value: Any) -> bool | None:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    return None


def _indicator(
    *,
    name: str,
    status: str,
    evidence: list[str],
    limitation: str,
    assessment_type: str,
    measured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "evidence": evidence,
        "limitation": limitation,
        "assessment_type": assessment_type,
        "measured": measured or {},
    }


def assess_face_reliability(observation: dict[str, Any] | None) -> dict[str, Any]:
    if not observation:
        return {
            "status": "not_assessed",
            "summary": "No face observation was available for reliability assessment.",
            "limitation": RELIABILITY_LIMITATION,
            "requires_human_verification": True,
            "indicators": [],
        }

    quality = observation.get("quality") if isinstance(observation.get("quality"), dict) else {}
    pose = observation.get("pose") if isinstance(observation.get("pose"), dict) else {}
    flags = observation.get("review_flags") if isinstance(observation.get("review_flags"), dict) else {}
    crop = observation.get("crop") if isinstance(observation.get("crop"), dict) else {}
    components = quality.get("components") if isinstance(quality.get("components"), dict) else {}

    quality_score = _as_float(quality.get("quality_score"))
    sharpness = _as_float(quality.get("sharpness"))
    brightness = _as_float(quality.get("brightness"))
    contrast = _as_float(quality.get("contrast"))
    face_size_px = _as_float(quality.get("face_size_px"))
    landmark_component = _as_float(components.get("landmark_component"))
    frontal_score = _as_float(pose.get("frontal_score"))
    if frontal_score is None:
        frontal_score = _as_float(components.get("frontal_component"))
    occlusion_status_raw = str(quality.get("occlusion_status") or "unknown")
    partial_occlusion = _as_bool(flags.get("partial_occlusion_suspected"))
    occlusion_review = _as_bool(flags.get("occlusion_review"))
    pose_away = _as_bool(flags.get("pose_away"))
    low_sharpness = _as_bool(flags.get("low_sharpness"))
    underexposed = _as_bool(flags.get("underexposed"))
    overexposed = _as_bool(flags.get("overexposed"))
    small_face = _as_bool(flags.get("small_face"))
    crop_retrieval = str(crop.get("retrieval_state") or "unknown")

    # Face visibility / occlusion
    visibility_evidence: list[str] = []
    if occlusion_status_raw != "unknown":
        visibility_evidence.append(f"occlusion_status={occlusion_status_raw}")
    if landmark_component is not None:
        visibility_evidence.append(f"landmark_component={landmark_component:.3f}")
    if partial_occlusion is not None:
        visibility_evidence.append(f"partial_occlusion_suspected={str(partial_occlusion).lower()}")
    if occlusion_review is not None:
        visibility_evidence.append(f"occlusion_review={str(occlusion_review).lower()}")

    if occlusion_status_raw == "suspected" or partial_occlusion is True:
        visibility_status = "partially_visible"
        occlusion_indicator_status = "suspected"
        visibility_summary = "Landmark-boundary evidence suggests partial face visibility."
    elif occlusion_status_raw == "review" or occlusion_review is True:
        visibility_status = "partially_visible"
        occlusion_indicator_status = "review_needed"
        visibility_summary = "Visibility is borderline and needs human review."
    elif occlusion_status_raw == "not_suspected" and landmark_component is not None:
        visibility_status = "fully_visible" if landmark_component >= 0.99 else "mostly_visible"
        occlusion_indicator_status = "not_suspected"
        visibility_summary = "Available landmark evidence does not suggest partial occlusion."
    elif occlusion_status_raw == "not_suspected":
        visibility_status = "mostly_visible"
        occlusion_indicator_status = "not_suspected"
        visibility_summary = "No occlusion was suspected, but landmark visibility details are incomplete."
    else:
        visibility_status = "unknown"
        occlusion_indicator_status = "unknown"
        visibility_summary = "Face visibility could not be assessed from available evidence."

    visibility_indicator = _indicator(
        name="face_visibility",
        status=visibility_status,
        evidence=visibility_evidence or ["no visibility evidence available"],
        limitation="Face visibility is inferred from landmark-boundary and occlusion heuristics, not a semantic obstruction classifier.",
        assessment_type="heuristic" if visibility_status != "unknown" else "not_assessed",
        measured={
            "occlusion_status": occlusion_status_raw,
            "landmark_component": landmark_component,
            "partial_occlusion_suspected": partial_occlusion,
            "occlusion_review": occlusion_review,
        },
    )
    occlusion_indicator = _indicator(
        name="occlusion",
        status=occlusion_indicator_status,
        evidence=visibility_evidence or ["no occlusion evidence available"],
        limitation="Occlusion is a landmark-boundary review signal; it does not identify the cause or object causing obstruction.",
        assessment_type="heuristic" if occlusion_indicator_status != "unknown" else "not_assessed",
        measured={
            "occlusion_status": occlusion_status_raw,
            "partial_occlusion_suspected": partial_occlusion,
            "occlusion_review": occlusion_review,
        },
    )

    # Pose
    pose_evidence: list[str] = []
    if frontal_score is not None:
        pose_evidence.append(f"frontal_score={frontal_score:.3f}")
    if pose_away is not None:
        pose_evidence.append(f"pose_away={str(pose_away).lower()}")
    pose_warnings = pose.get("warnings") if isinstance(pose.get("warnings"), list) else []
    for warning in pose_warnings[:3]:
        pose_evidence.append(f"warning={warning}")

    if frontal_score is None and pose_away is None:
        pose_status = "unknown"
        pose_summary = "Pose could not be assessed from available evidence."
        pose_type = "not_assessed"
    elif pose_away is True or (frontal_score is not None and frontal_score < 0.5):
        pose_status = "poor_pose" if (frontal_score is not None and frontal_score < 0.35) else "turned_or_profile"
        pose_summary = "Face pose limits visual review usability."
        pose_type = "heuristic"
    else:
        pose_status = "frontal_or_near_frontal"
        pose_summary = "Face pose appears suitable for visual review."
        pose_type = "heuristic"

    pose_indicator = _indicator(
        name="pose",
        status=pose_status,
        evidence=pose_evidence or ["no pose evidence available"],
        limitation="Pose uses uncalibrated geometric proxies from YuNet landmarks; it is not calibrated 3D pose or gaze estimation.",
        assessment_type=pose_type,
        measured={
            "frontal_score": frontal_score,
            "pose_away": pose_away,
            "roll_proxy_deg": _as_float(pose.get("roll_proxy_deg")),
            "yaw_proxy": _as_float(pose.get("yaw_proxy")),
            "pitch_proxy": _as_float(pose.get("pitch_proxy")),
        },
    )

    # Image quality
    quality_evidence: list[str] = []
    if quality_score is not None:
        quality_evidence.append(f"quality_score={quality_score:.1f}")
    if sharpness is not None:
        quality_evidence.append(f"sharpness={sharpness:.2f}")
    if brightness is not None:
        quality_evidence.append(f"brightness={brightness:.2f}")
    if face_size_px is not None:
        quality_evidence.append(f"face_size_px={int(face_size_px)}")
    if contrast is not None:
        quality_evidence.append(f"contrast={contrast:.2f}")
    for name, flag in (
        ("low_sharpness", low_sharpness),
        ("underexposed", underexposed),
        ("overexposed", overexposed),
        ("small_face", small_face),
    ):
        if flag is not None:
            quality_evidence.append(f"{name}={str(flag).lower()}")
    quality_evidence.append(f"crop_retrieval={crop_retrieval}")

    known_quality_flags = [f for f in (low_sharpness, underexposed, overexposed, small_face) if f is not None]
    poor_quality = bool(low_sharpness) or bool(underexposed) or bool(overexposed) or bool(small_face)
    quality_unknown = quality_score is None and sharpness is None and brightness is None and face_size_px is None and not known_quality_flags
    if crop_retrieval != "retrievable":
        image_quality_status = "poor"
        image_quality_summary = "The face crop is not retrievable for human visual review."
        image_quality_type = "measured"
    elif quality_unknown:
        image_quality_status = "unknown"
        image_quality_summary = "Image quality could not be assessed from available evidence."
        image_quality_type = "not_assessed"
    elif poor_quality or (quality_score is not None and quality_score < 55):
        image_quality_status = "poor"
        image_quality_summary = "Image quality limits reliable visual review."
        image_quality_type = "measured"
    elif (quality_score is not None and quality_score < 75) or (
        sharpness is not None and sharpness < 80
    ) or (face_size_px is not None and face_size_px < 100):
        image_quality_status = "limited"
        image_quality_summary = "Image quality is usable but has limitations."
        image_quality_type = "measured"
    else:
        image_quality_status = "good"
        image_quality_summary = "Image quality appears sufficient for visual review."
        image_quality_type = "measured"

    image_quality_indicator = _indicator(
        name="image_quality",
        status=image_quality_status,
        evidence=quality_evidence or ["no image quality evidence available"],
        limitation="Image quality metrics are usability proxies; they do not guarantee identity or event correctness.",
        assessment_type=image_quality_type,
        measured={
            "quality_score": quality_score,
            "sharpness": sharpness,
            "brightness": brightness,
            "contrast": contrast,
            "face_size_px": face_size_px,
            "crop_retrieval_state": crop_retrieval,
            "low_sharpness": low_sharpness,
            "underexposed": underexposed,
            "overexposed": overexposed,
            "small_face": small_face,
        },
    )

    # Potential concealment - never claim mask/helmet/cap detection
    concealment_evidence = [
        f"mask={CV_UNSUPPORTED_ATTRIBUTE_STATUS}",
        f"helmet={CV_UNSUPPORTED_ATTRIBUTE_STATUS}",
        f"cap={CV_UNSUPPORTED_ATTRIBUTE_STATUS}",
    ]
    concealment_measured = {
        "mask": CV_UNSUPPORTED_ATTRIBUTE_STATUS,
        "helmet": CV_UNSUPPORTED_ATTRIBUTE_STATUS,
        "cap": CV_UNSUPPORTED_ATTRIBUTE_STATUS,
        "occlusion_status": occlusion_status_raw,
    }
    concealment_status = "not_assessed"
    concealment_type = "not_assessed"
    concealment_summary = "Mask, helmet, cap, and other concealment types are not assessed by the current implementation."
    if occlusion_indicator_status in {"suspected", "review_needed"}:
        concealment_status = "possible_obstruction"
        concealment_type = "heuristic"
        concealment_evidence.append(f"occlusion_status={occlusion_status_raw}")
        concealment_summary = (
            "Occlusion heuristics suggest possible obstruction, but the obstruction type is not classified."
        )

    concealment_indicator = _indicator(
        name="potential_concealment",
        status=concealment_status,
        evidence=concealment_evidence,
        limitation=(
            "Current models do not classify mask, helmet, cap, or obstruction type. "
            "Possible obstruction, when present, is inferred only from occlusion heuristics and requires human review."
        ),
        assessment_type=concealment_type,
        measured=concealment_measured,
    )

    indicators = [visibility_indicator, occlusion_indicator, pose_indicator, image_quality_indicator, concealment_indicator]

    # Overall status
    poor_reasons: list[str] = []
    limited_reasons: list[str] = []
    unknown_reasons: list[str] = []
    if image_quality_status == "poor":
        poor_reasons.append(image_quality_summary)
    if visibility_status == "insufficient_visibility":
        poor_reasons.append(visibility_summary)
    if pose_status == "poor_pose":
        poor_reasons.append(pose_summary)

    if image_quality_status == "limited":
        limited_reasons.append(image_quality_summary)
    if visibility_status in {"partially_visible"}:
        limited_reasons.append(visibility_summary)
    if pose_status == "turned_or_profile":
        limited_reasons.append(pose_summary)
    if concealment_status == "possible_obstruction":
        limited_reasons.append(concealment_summary)

    if image_quality_status == "unknown":
        unknown_reasons.append("image quality unknown")
    if visibility_status == "unknown":
        unknown_reasons.append("visibility unknown")
    if pose_status == "unknown":
        unknown_reasons.append("pose unknown")

    if poor_reasons:
        overall = "poor"
        summary = "; ".join(dict.fromkeys(poor_reasons + limited_reasons))
    elif limited_reasons:
        overall = "limited"
        summary = "; ".join(dict.fromkeys(limited_reasons))
    elif unknown_reasons and len(unknown_reasons) >= 2:
        overall = "not_assessed"
        summary = "Insufficient evidence to assess face reliability: " + ", ".join(unknown_reasons) + "."
    elif unknown_reasons:
        overall = "limited"
        summary = "Reliability is partially assessed; " + ", ".join(unknown_reasons) + "."
    else:
        overall = "usable"
        summary = "Available heuristics indicate the face frame is usable for human visual review."

    return {
        "status": overall,
        "summary": summary,
        "limitation": RELIABILITY_LIMITATION,
        "requires_human_verification": True,
        "indicators": indicators,
    }
