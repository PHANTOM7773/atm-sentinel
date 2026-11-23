from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def analyze_frame(image: Any) -> dict[str, Any]:
    """Explainable image-quality metrics. Not an identity or biometric score."""
    if image is None or getattr(image, "size", 0) == 0:
        raise ValueError("Cannot analyze an empty frame")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    height, width = gray.shape[:2]

    blur = cv2.Laplacian(gray, cv2.CV_64F)
    sharpness = float(blur.var())

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gx_energy = float(np.mean(np.abs(gx)))
    gy_energy = float(np.mean(np.abs(gy)))
    directional = 1.0 - min(gx_energy, gy_energy) / (max(gx_energy, gy_energy) + 1e-6)

    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    sharpness_norm = 1.0 - float(np.exp(-sharpness / 120.0))
    illumination_norm = max(0.0, 1.0 - abs(brightness - 128.0) / 128.0)
    contrast_norm = min(contrast / 64.0, 1.0)
    resolution_norm = min(float(min(width, height)) / 480.0, 1.0)
    motion_norm = 1.0 - min(directional / 0.75, 1.0)

    overall = 100.0 * (
        0.38 * sharpness_norm
        + 0.20 * illumination_norm
        + 0.18 * contrast_norm
        + 0.10 * resolution_norm
        + 0.14 * motion_norm
    )

    warnings: list[str] = []
    if sharpness < 50:
        warnings.append("Low sharpness — possible defocus or blur")
    if brightness < 35:
        warnings.append("Underexposed frame")
    elif brightness > 225:
        warnings.append("Overexposed frame")
    if contrast < 25:
        warnings.append("Low contrast")
    if min(width, height) < 480:
        warnings.append("Low source resolution")
    if directional > 0.68:
        warnings.append("Directional blur suspected")

    return {
        "sharpness": round(sharpness, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "quality_score": round(max(0.0, min(100.0, overall)), 1),
        "width": int(width),
        "height": int(height),
        "motion_blur_indicator": round(float(directional), 3),
        "components": {
            "sharpness_component": round(sharpness_norm, 3),
            "illumination_component": round(illumination_norm, 3),
            "contrast_component": round(contrast_norm, 3),
            "resolution_component": round(resolution_norm, 3),
            "motion_component": round(motion_norm, 3),
        },
        "warnings": warnings,
    }


LIMITATIONS = (
    "Quality scores use Laplacian variance, mean intensity, standard deviation, source resolution and "
    "a directional-gradient heuristic. They are affected by scene content, compression and lighting. "
    "They measure image usability only and are not probabilities of identity or correctness."
)
