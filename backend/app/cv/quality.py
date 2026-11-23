from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from .errors import CVError
from .landmarks import estimate_pose, landmark_visibility, occlusion_proxy
from .types import Point


def analyze_face_quality(
    crop: np.ndarray,
    landmarks: Sequence[Point] | None = None,
    bbox: Sequence[float] | None = None,
) -> dict[str, Any]:
    if crop is None or crop.size == 0:
        raise CVError("Cannot score an empty face crop")

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    height, width = gray.shape[:2]
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    crop_size = float(min(width, height))
    face_size = crop_size
    if bbox and len(bbox) >= 4:
        try:
            face_size = max(0.0, min(float(bbox[2]), float(bbox[3])))
        except (TypeError, ValueError):
            face_size = crop_size

    sharpness_norm = 1.0 - float(np.exp(-sharpness / 120.0))
    illumination_norm = _clamp(1.0 - abs(brightness - 128.0) / 128.0)
    contrast_norm = _clamp(contrast / 64.0)
    size_norm = _clamp(face_size / 80.0)
    landmark_norm = landmark_visibility(landmarks, crop.shape)
    pose = estimate_pose(landmarks)
    frontal_norm = float(pose["frontal_score"])

    overall = 100.0 * (
        0.28 * sharpness_norm
        + 0.18 * illumination_norm
        + 0.14 * contrast_norm
        + 0.15 * size_norm
        + 0.15 * landmark_norm
        + 0.10 * frontal_norm
    )

    occlusion = occlusion_proxy(landmarks, crop.shape)
    warnings: list[str] = list(pose["warnings"])
    if sharpness < 50:
        warnings.append("Low sharpness — possible defocus or blur")
    if brightness < 35:
        warnings.append("Underexposed crop")
    elif brightness > 225:
        warnings.append("Overexposed crop")
    if contrast < 25:
        warnings.append("Low contrast")
    if face_size < 80:
        warnings.append("Small detected face bbox")
    if occlusion["status"] == "review":
        warnings.append("Landmark visibility is borderline; review manually")
    if occlusion["status"] == "suspected":
        warnings.append("Landmark visibility suggests partial occlusion; review manually")

    flags = {
        "face_detected": True,
        "low_sharpness": sharpness < 50,
        "underexposed": brightness < 35,
        "overexposed": brightness > 225,
        "small_face": face_size < 80,
        "pose_away": frontal_norm < 0.5,
        "partial_occlusion_suspected": occlusion["status"] == "suspected",
        "occlusion_review": occlusion["status"] in {"review", "suspected"},
        "mask": "unknown",
        "helmet": "unknown",
        "cap": "unknown",
        "identity_confirmed": False,
    }

    return {
        "quality_score": round(_clamp(overall, 0.0, 100.0), 1),
        "sharpness": round(sharpness, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "face_size_px": int(face_size),
        "crop_size_px": int(crop_size),
        "occlusion_status": str(occlusion["status"]),
        "source_bbox": [round(float(value), 2) for value in bbox] if bbox else None,
        "components": {
            "sharpness_component": round(sharpness_norm, 3),
            "illumination_component": round(illumination_norm, 3),
            "contrast_component": round(contrast_norm, 3),
            "size_component": round(size_norm, 3),
            "landmark_component": round(landmark_norm, 3),
            "frontal_component": round(frontal_norm, 3),
        },
        "pose": pose,
        "occlusion": occlusion,
        "flags": flags,
        "warnings": warnings,
        "disclaimer": "Image usability only; not an identity, biometric or attribute-classification result.",
    }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


LIMITATIONS = (
    "Face-crop quality combines Laplacian variance, mean intensity, contrast, detected face bbox size, "
    "five-landmark visibility and uncalibrated geometric pose proxies. Occlusion is a review flag, not a "
    "mask/helmet/cap classifier. Scores measure crop usability only and are not probabilities of identity "
    "or correctness."
)


__all__ = ["LIMITATIONS", "analyze_face_quality"]
