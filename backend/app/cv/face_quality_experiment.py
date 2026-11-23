"""TASK 16 isolated face quality evaluator.

Builds on existing quality/landmark heuristics but stays isolated from
production best-face ranking and SFace embedding usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import cv2
import numpy as np

from .errors import CVError
from .landmarks import estimate_pose, landmark_visibility, occlusion_proxy
from .types import Point

QUALITY_DIMENSIONS = (
    "sharpness",
    "resolution",
    "exposure",
    "contrast",
    "noise",
    "pose",
    "occlusion_visibility",
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "sharpness": 0.28,
    "resolution": 0.15,
    "exposure": 0.15,
    "contrast": 0.12,
    "noise": 0.10,
    "pose": 0.10,
    "occlusion_visibility": 0.10,
}

DISCLAIMER = (
    "Quality score is an explainable image-usability heuristic (0-100). It is NOT a probability of identity, "
    "recognition accuracy, or biometric match."
)


@dataclass(frozen=True)
class DimensionResult:
    name: str
    score: float | None
    available: bool
    weight: float
    weighted_contribution: float
    reason_codes: list[str]
    warnings: list[str]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "available": self.available,
            "weight": round(self.weight, 6),
            "weighted_contribution": round(self.weighted_contribution, 4),
            "reason_codes": list(self.reason_codes),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
        }


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _normalize_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    raw = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in raw:
                try:
                    fv = float(v)
                except Exception:
                    continue
                if np.isfinite(fv) and fv >= 0:
                    raw[k] = fv
    active = {k: v for k, v in raw.items() if v > 0}
    total = sum(active.values())
    if total <= 0:
        # fallback to defaults
        active = dict(DEFAULT_WEIGHTS)
        total = sum(active.values())
    return {k: (active.get(k, 0.0) / total) for k in QUALITY_DIMENSIONS}


def _as_gray(crop: np.ndarray) -> np.ndarray:
    if crop.ndim == 2:
        return crop
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _noise_metric(gray: np.ndarray) -> dict[str, float]:
    # Robust noise proxy: MAD of Laplacian + high-frequency energy ratio.
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    med = float(np.median(lap))
    mad = float(np.median(np.abs(lap - med)))
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    hf = gray.astype(np.float32) - blur.astype(np.float32)
    hf_std = float(np.std(hf))
    return {"laplacian_mad": mad, "hf_std": hf_std}


def evaluate_face_quality(
    crop: np.ndarray,
    landmarks: Sequence[Point] | None = None,
    bbox: Sequence[float] | None = None,
    *,
    weights: Mapping[str, float] | None = None,
    expected_face_px: float = 80.0,
) -> dict[str, Any]:
    if crop is None or not isinstance(crop, np.ndarray) or crop.size == 0:
        raise CVError("Cannot score an empty/invalid face crop")
    if crop.ndim not in (2, 3):
        raise CVError(f"Unsupported crop shape: {crop.shape}")

    norm_weights = _normalize_weights(weights)
    gray = _as_gray(crop)
    h, w = gray.shape[:2]
    crop_min = float(min(h, w))
    face_w = face_h = None
    if bbox and len(bbox) >= 4:
        try:
            face_w = max(0.0, float(bbox[2]))
            face_h = max(0.0, float(bbox[3]))
        except Exception:
            face_w = face_h = None
    face_min = min(face_w, face_h) if face_w is not None and face_h is not None else crop_min

    dims: list[DimensionResult] = []
    reason_codes: list[str] = []
    warnings: list[str] = []

    # Sharpness / blur
    sharpness_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharp_score = _clamp(100.0 * (1.0 - np.exp(-sharpness_var / 120.0)))
    sharp_reasons = []
    sharp_warnings = []
    if sharpness_var < 50:
        sharp_reasons.append("low_sharpness")
        sharp_warnings.append("Low sharpness — possible blur/defocus")
    elif sharpness_var < 120:
        sharp_reasons.append("moderate_sharpness")
    else:
        sharp_reasons.append("sharpness_ok")
    dims.append(DimensionResult("sharpness", sharp_score, True, norm_weights["sharpness"], sharp_score * norm_weights["sharpness"], sharp_reasons, sharp_warnings, {"laplacian_variance": round(sharpness_var, 3)}))
    reason_codes += sharp_reasons; warnings += sharp_warnings

    # Resolution / usable pixel area
    usable_area = float(w * h)
    min_dim_score = _clamp(100.0 * min(1.0, face_min / max(1.0, expected_face_px)))
    area_score = _clamp(100.0 * min(1.0, usable_area / float(max(1.0, expected_face_px * expected_face_px))))
    res_score = _clamp(0.7 * min_dim_score + 0.3 * area_score)
    res_reasons = []
    res_warnings = []
    if face_min < expected_face_px * 0.5:
        res_reasons.append("tiny_face")
        res_warnings.append("Face/crop too small for reliable review")
    elif face_min < expected_face_px:
        res_reasons.append("small_face")
        res_warnings.append("Small face resolution")
    else:
        res_reasons.append("resolution_ok")
    dims.append(DimensionResult("resolution", res_score, True, norm_weights["resolution"], res_score * norm_weights["resolution"], res_reasons, res_warnings, {"crop_width": w, "crop_height": h, "face_min_px": round(face_min, 2), "usable_area_px": int(usable_area)}))
    reason_codes += res_reasons; warnings += res_warnings

    # Exposure / brightness
    brightness = float(np.mean(gray))
    exposure_score = _clamp(100.0 * (1.0 - abs(brightness - 128.0) / 128.0))
    exp_reasons = []
    exp_warnings = []
    if brightness < 35:
        exp_reasons.append("underexposed")
        exp_warnings.append("Underexposed crop")
    elif brightness > 225:
        exp_reasons.append("overexposed")
        exp_warnings.append("Overexposed crop")
    elif brightness < 60 or brightness > 190:
        exp_reasons.append("suboptimal_exposure")
    else:
        exp_reasons.append("exposure_ok")
    dims.append(DimensionResult("exposure", exposure_score, True, norm_weights["exposure"], exposure_score * norm_weights["exposure"], exp_reasons, exp_warnings, {"brightness_mean": round(brightness, 3)}))
    reason_codes += exp_reasons; warnings += exp_warnings

    # Contrast
    contrast = float(np.std(gray))
    contrast_score = _clamp(100.0 * min(1.0, contrast / 64.0))
    con_reasons = []
    con_warnings = []
    if contrast < 25:
        con_reasons.append("low_contrast")
        con_warnings.append("Low contrast")
    elif contrast < 40:
        con_reasons.append("moderate_contrast")
    else:
        con_reasons.append("contrast_ok")
    dims.append(DimensionResult("contrast", contrast_score, True, norm_weights["contrast"], contrast_score * norm_weights["contrast"], con_reasons, con_warnings, {"contrast_std": round(contrast, 3)}))
    reason_codes += con_reasons; warnings += con_warnings

    # Noise
    noise = _noise_metric(gray)
    mad = float(noise["laplacian_mad"])
    hf_std = float(noise["hf_std"])
    # Heuristic: combine robust Laplacian MAD and high-frequency residual.
    mad_score = 1.0 - min(1.0, max(0.0, (mad - 6.0) / 24.0))
    hf_score = 1.0 - min(1.0, max(0.0, (hf_std - 3.0) / 12.0))
    noise_score = _clamp(100.0 * (0.7 * mad_score + 0.3 * hf_score))
    noise_reasons = []
    noise_warnings = []
    if noise_score < 40:
        noise_reasons.append("high_noise")
        noise_warnings.append("High noise/compression artifact level")
    elif noise_score < 70:
        noise_reasons.append("moderate_noise")
    else:
        noise_reasons.append("noise_ok")
    dims.append(DimensionResult("noise", noise_score, True, norm_weights["noise"], noise_score * norm_weights["noise"], noise_reasons, noise_warnings, {"laplacian_mad": round(mad, 3), "hf_std": round(hf_std, 3)}))
    reason_codes += noise_reasons; warnings += noise_warnings

    # Pose / frontalness
    pose_available = landmarks is not None and len(list(landmarks)) >= 5
    if pose_available:
        pose = estimate_pose(landmarks)
        frontal = float(pose.get("frontal_score", 0.0))
        pose_score = _clamp(100.0 * max(0.0, min(1.0, frontal)))
        pose_reasons = []
        pose_warnings = []
        if frontal < 0.35:
            pose_reasons.append("poor_pose")
            pose_warnings.append("Face pose poor for review")
        elif frontal < 0.6:
            pose_reasons.append("turned_pose")
            pose_warnings.append("Face turned/profiled")
        else:
            pose_reasons.append("pose_ok")
        pose_warnings.extend([str(w) for w in pose.get("warnings", []) if str(w) not in pose_warnings])
        dims.append(DimensionResult("pose", pose_score, True, norm_weights["pose"], pose_score * norm_weights["pose"], pose_reasons, pose_warnings, {"frontal_score": round(frontal, 4), **{k: pose.get(k) for k in ["roll_proxy_deg","yaw_proxy","pitch_proxy"]}}))
        reason_codes += pose_reasons; warnings += pose_warnings
    else:
        dims.append(DimensionResult("pose", None, False, norm_weights["pose"], 0.0, ["pose_not_assessed"], ["Pose landmarks unavailable; pose not assessed"], {"landmarks_available": False}))
        reason_codes.append("pose_not_assessed")
        warnings.append("Pose landmarks unavailable; pose not assessed")

    # Occlusion / visibility
    occ_available = landmarks is not None and len(list(landmarks)) >= 5
    if occ_available:
        vis = float(landmark_visibility(landmarks, crop.shape))
        occ = occlusion_proxy(landmarks, crop.shape)
        status = str(occ.get("status", "unknown"))
        # visibility high is good; suspected occlusion reduces score
        occ_score = _clamp(100.0 * vis)
        if status == "suspected":
            occ_score = _clamp(min(occ_score, 35.0))
        elif status == "review":
            occ_score = _clamp(min(occ_score, 65.0))
        occ_reasons = []
        occ_warnings = []
        if status == "suspected":
            occ_reasons.append("occlusion_suspected")
            occ_warnings.append("Partial occlusion suspected")
        elif status == "review":
            occ_reasons.append("occlusion_review_needed")
            occ_warnings.append("Occlusion/visibility borderline; review needed")
        else:
            occ_reasons.append("visibility_ok")
        dims.append(DimensionResult("occlusion_visibility", occ_score, True, norm_weights["occlusion_visibility"], occ_score * norm_weights["occlusion_visibility"], occ_reasons, occ_warnings, {"landmark_visibility": round(vis, 4), "occlusion_status": status}))
        reason_codes += occ_reasons; warnings += occ_warnings
    else:
        dims.append(DimensionResult("occlusion_visibility", None, False, norm_weights["occlusion_visibility"], 0.0, ["occlusion_not_assessed"], ["Occlusion/visibility not assessed: landmarks unavailable"], {"landmarks_available": False}))
        reason_codes.append("occlusion_not_assessed")
        warnings.append("Occlusion/visibility not assessed: landmarks unavailable")

    available_dims = [d for d in dims if d.available and d.score is not None]
    missing_dims = [d.name for d in dims if not d.available]
    total_weight = sum(d.weight for d in available_dims)
    overall = sum(d.weighted_contribution for d in available_dims) / total_weight if total_weight > 0 else 0.0
    overall = _clamp(overall)

    # dedupe reason codes/warnings preserving order
    def dedupe(seq: list[str]) -> list[str]:
        seen=set(); out=[]
        for x in seq:
            if x not in seen:
                seen.add(x); out.append(x)
        return out

    return {
        "overall_score": round(float(overall), 2),
        "score_scale": "0-100",
        "score_meaning": DISCLAIMER,
        "dimensions": [d.to_dict() for d in dims],
        "available_dimensions": [d.name for d in available_dims],
        "missing_dimensions": missing_dims,
        "weights_used": {k: round(v, 6) for k, v in norm_weights.items()},
        "reason_codes": dedupe(reason_codes),
        "warnings": dedupe(warnings),
        "input": {
            "width": w,
            "height": h,
            "face_bbox": [float(x) for x in bbox] if bbox and len(bbox) >= 4 else None,
            "landmarks_count": len(list(landmarks)) if landmarks is not None else 0,
        },
    }
