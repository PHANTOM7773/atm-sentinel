from __future__ import annotations

import math
from typing import Any, Sequence

from .types import Point


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _distance(first: Point, second: Point) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def landmark_visibility(landmarks: Sequence[Point] | None, crop_shape: tuple[int, ...]) -> float:
    if not landmarks:
        return 0.0
    height, width = crop_shape[:2]
    visible = 0
    for x, y in landmarks:
        if -0.05 * width <= x <= 1.05 * width and -0.05 * height <= y <= 1.05 * height:
            visible += 1
    return visible / len(landmarks)


def estimate_pose(landmarks: Sequence[Point] | None) -> dict[str, Any]:
    if not landmarks or len(landmarks) < 5:
        return {
            "roll_proxy_deg": None,
            "yaw_proxy": None,
            "pitch_proxy": None,
            "frontal_score": 0.0,
            "warnings": ["Landmarks unavailable; pose not estimated"],
        }

    right_eye, left_eye, nose, right_mouth, left_mouth = landmarks[:5]
    eye_distance = _distance(right_eye, left_eye)
    if eye_distance <= 1e-6:
        return {
            "roll_proxy_deg": None,
            "yaw_proxy": None,
            "pitch_proxy": None,
            "frontal_score": 0.0,
            "warnings": ["Landmark spacing invalid; pose not estimated"],
        }

    eye_mid_x = (right_eye[0] + left_eye[0]) / 2.0
    eye_mid_y = (right_eye[1] + left_eye[1]) / 2.0
    mouth_mid_y = (right_mouth[1] + left_mouth[1]) / 2.0

    roll = abs(math.degrees(math.atan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0])))
    yaw_proxy = abs(nose[0] - eye_mid_x) / eye_distance
    denominator = max(abs(mouth_mid_y - eye_mid_y), 1e-6)
    vertical_ratio = (nose[1] - eye_mid_y) / denominator
    pitch_proxy = abs(vertical_ratio - 0.5) / 0.5
    frontal_score = _clamp(1.0 - max(yaw_proxy / 0.5, roll / 30.0, pitch_proxy / 0.7))

    warnings: list[str] = []
    if yaw_proxy > 0.35:
        warnings.append("Yaw proxy suggests a turned face")
    if roll > 20.0:
        warnings.append("Roll proxy suggests a tilted face")
    if pitch_proxy > 0.5:
        warnings.append("Pitch proxy suggests an up/down tilted face")

    return {
        "roll_proxy_deg": round(roll, 2),
        "yaw_proxy": round(_clamp(yaw_proxy, 0.0, 2.0), 3),
        "pitch_proxy": round(_clamp(pitch_proxy, 0.0, 2.0), 3),
        "frontal_score": round(frontal_score, 3),
        "warnings": warnings,
        "method": "geometric proxies from five YuNet landmarks; not calibrated 3D pose",
    }


def occlusion_proxy(landmarks: Sequence[Point] | None, crop_shape: tuple[int, ...]) -> dict[str, Any]:
    visibility = landmark_visibility(landmarks, crop_shape)
    if visibility >= 0.99:
        status = "not_suspected"
    elif visibility >= 0.6:
        status = "review"
    else:
        status = "suspected"
    return {
        "status": status,
        "landmark_visibility": round(visibility, 3),
        "confidence": round(_clamp(1.0 - visibility), 3),
        "method": "landmark-boundary heuristic only; not a face-covering classifier",
    }


__all__ = ["estimate_pose", "landmark_visibility", "occlusion_proxy"]
