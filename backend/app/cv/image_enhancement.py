"""Isolated TASK 15 image enhancement for ATM CCTV face crops.

Never overwrites originals. Enhanced outputs are derived artifacts only.
No identity confirmation; no silent use in face matching/embeddings.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import DATA_DIR, PROJECT_ROOT
from .errors import CVError


ENHANCEMENT_VERSION = "task15-opencv-v1"
DERIVED_LABEL = "AI-enhanced derived image - not original evidence"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "reports" / "ps04cctv-audit" / "task15-enhancements"

PRESETS: dict[str, dict[str, Any]] = {
    "general_enhancement": {
        "label": "General enhancement",
        "description": "Mild denoise, CLAHE, gamma/contrast balance, conservative sharpen, optional upscale.",
        "params": {
            "clahe": True,
            "clahe_clip_limit": 2.0,
            "clahe_tile_grid": [8, 8],
            "gamma": 1.05,
            "brightness": 0,
            "contrast": 1.10,
            "denoise": True,
            "denoise_h": 5,
            "sharpen": True,
            "sharpen_amount": 0.35,
            "sharpen_sigma": 1.0,
            "upscale_factor": 1.5,
            "interpolation": "lanczos4",
        },
    },
    "low_light_correction": {
        "label": "Low-light correction",
        "description": "Brightens dark crops with CLAHE and gamma lift; conservative denoise/sharpen.",
        "params": {
            "clahe": True,
            "clahe_clip_limit": 2.8,
            "clahe_tile_grid": [8, 8],
            "gamma": 0.75,
            "brightness": 12,
            "contrast": 1.08,
            "denoise": True,
            "denoise_h": 6,
            "sharpen": True,
            "sharpen_amount": 0.25,
            "sharpen_sigma": 1.0,
            "upscale_factor": 1.5,
            "interpolation": "lanczos4",
        },
    },
    "low_contrast_correction": {
        "label": "Low-contrast correction",
        "description": "Improves local contrast with CLAHE and modest global contrast.",
        "params": {
            "clahe": True,
            "clahe_clip_limit": 3.0,
            "clahe_tile_grid": [8, 8],
            "gamma": 1.0,
            "brightness": 0,
            "contrast": 1.25,
            "denoise": True,
            "denoise_h": 4,
            "sharpen": True,
            "sharpen_amount": 0.20,
            "sharpen_sigma": 1.0,
            "upscale_factor": 1.5,
            "interpolation": "cubic",
        },
    },
    "noise_reduction": {
        "label": "Noise reduction",
        "description": "Prioritizes denoising with minimal sharpening.",
        "params": {
            "clahe": True,
            "clahe_clip_limit": 1.8,
            "clahe_tile_grid": [8, 8],
            "gamma": 1.0,
            "brightness": 0,
            "contrast": 1.05,
            "denoise": True,
            "denoise_h": 9,
            "sharpen": False,
            "sharpen_amount": 0.10,
            "sharpen_sigma": 1.0,
            "upscale_factor": 1.0,
            "interpolation": "cubic",
        },
    },
}

INTERPOLATIONS = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA,
    "lanczos4": cv2.INTER_LANCZOS4,
}


@dataclass
class EnhancementResult:
    original_path: str
    original_sha256: str
    enhanced_path: str
    enhanced_sha256: str
    preset: str
    preset_label: str
    params: dict[str, Any]
    method: str
    method_version: str
    derived_label: str
    original_width: int
    original_height: int
    enhanced_width: int
    enhanced_height: int
    processing_ms: float
    metadata_path: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_image(img: np.ndarray | None, path: Path) -> np.ndarray:
    if img is None or img.size == 0:
        raise CVError(f"Invalid or unreadable image: {path.name}")
    if img.ndim not in (2, 3):
        raise CVError(f"Unsupported image shape: {img.shape}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    if img.shape[2] != 3:
        raise CVError(f"Unsupported channel count: {img.shape}")
    return img


def apply_gamma(img: np.ndarray, gamma: float) -> np.ndarray:
    g = float(gamma)
    if g <= 0:
        raise CVError("gamma must be > 0")
    if abs(g - 1.0) < 1e-6:
        return img.copy()
    inv = 1.0 / g
    table = np.array([((i / 255.0) ** inv) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(img, table)


def apply_brightness_contrast(img: np.ndarray, brightness: float = 0, contrast: float = 1.0) -> np.ndarray:
    b = float(brightness)
    c = float(contrast)
    if c <= 0:
        raise CVError("contrast must be > 0")
    out = cv2.convertScaleAbs(img, alpha=c, beta=b)
    return out


def apply_clahe(img: np.ndarray, clip_limit: float = 2.0, tile_grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    clip = max(0.1, float(clip_limit))
    tg = (max(1, int(tile_grid[0])), max(1, int(tile_grid[1])))
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=tg)
    l2 = clahe.apply(l)
    merged = cv2.merge((l2, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def apply_denoise(img: np.ndarray, h: float = 5) -> np.ndarray:
    strength = max(1, int(round(float(h))))
    return cv2.fastNlMeansDenoisingColored(img, None, strength, strength, 7, 21)


def apply_sharpen(img: np.ndarray, amount: float = 0.3, sigma: float = 1.0) -> np.ndarray:
    amt = max(0.0, min(1.5, float(amount)))
    sig = max(0.1, float(sigma))
    if amt <= 0:
        return img.copy()
    blur = cv2.GaussianBlur(img, (0, 0), sig)
    # Unsharp mask: original*(1+amt) - blur*amt
    return cv2.addWeighted(img, 1.0 + amt, blur, -amt, 0)


def apply_upscale(img: np.ndarray, factor: float = 1.0, interpolation: str = "cubic") -> np.ndarray:
    f = float(factor)
    if f <= 0:
        raise CVError("upscale_factor must be > 0")
    if abs(f - 1.0) < 1e-6:
        return img.copy()
    h, w = img.shape[:2]
    new_w = max(1, int(round(w * f)))
    new_h = max(1, int(round(h * f)))
    # cap to avoid runaway memory
    max_dim = 4096
    if new_w > max_dim or new_h > max_dim:
        scale = min(max_dim / new_w, max_dim / new_h)
        new_w = max(1, int(new_w * scale))
        new_h = max(1, int(new_h * scale))
    interp = INTERPOLATIONS.get(str(interpolation).lower(), cv2.INTER_CUBIC)
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def normalize_params(preset: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    if preset not in PRESETS:
        raise CVError(f"Unknown preset: {preset}")
    params = dict(PRESETS[preset]["params"])
    if overrides:
        for k, v in overrides.items():
            if k in params:
                params[k] = v
    return params


def enhance_image(img: np.ndarray, params: dict[str, Any]) -> tuple[np.ndarray, list[str]]:
    warnings: list[str] = []
    out = _validate_image(img, Path("in-memory"))
    original_shape = out.shape

    if params.get("denoise", False):
        out = apply_denoise(out, params.get("denoise_h", 5))
    if params.get("clahe", False):
        tg = params.get("clahe_tile_grid", [8, 8])
        out = apply_clahe(out, params.get("clahe_clip_limit", 2.0), (int(tg[0]), int(tg[1])))
    if abs(float(params.get("gamma", 1.0)) - 1.0) > 1e-6:
        out = apply_gamma(out, float(params.get("gamma", 1.0)))
    bc_b = float(params.get("brightness", 0))
    bc_c = float(params.get("contrast", 1.0))
    if abs(bc_b) > 1e-6 or abs(bc_c - 1.0) > 1e-6:
        out = apply_brightness_contrast(out, bc_b, bc_c)
    if params.get("sharpen", False):
        out = apply_sharpen(out, params.get("sharpen_amount", 0.3), params.get("sharpen_sigma", 1.0))
    uf = float(params.get("upscale_factor", 1.0))
    if abs(uf - 1.0) > 1e-6:
        out = apply_upscale(out, uf, str(params.get("interpolation", "cubic")))

    if out.shape != original_shape:
        warnings.append("output_dimensions_changed_by_upscale")
    return out, warnings


def enhance_crop_file(
    *,
    input_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    preset: str = "general_enhancement",
    overrides: dict[str, Any] | None = None,
    case_id: str = "unknown",
    observation_id: str = "unknown",
    crop_id: str = "unknown",
    source_metadata: dict[str, Any] | None = None,
) -> EnhancementResult:
    if not input_path.exists() or not input_path.is_file():
        raise CVError(f"Original crop not found: {input_path.name}")
    original_sha = sha256_file(input_path)
    img = cv2.imread(str(input_path), cv2.IMREAD_UNCHANGED)
    img = _validate_image(img, input_path)
    params = normalize_params(preset, overrides)

    t0 = time.perf_counter()
    enhanced, warnings = enhance_image(img, params)
    processing_ms = (time.perf_counter() - t0) * 1000.0

    out_dir = output_root / preset
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{Path(crop_id).stem}_{preset}_enhanced"
    enhanced_path = out_dir / f"{base}.jpg"
    metadata_path = out_dir / f"{base}.json"

    ok = cv2.imwrite(str(enhanced_path), enhanced, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not ok or not enhanced_path.exists():
        raise CVError("Failed to write enhanced image")

    enhanced_sha = sha256_file(enhanced_path)
    result = EnhancementResult(
        original_path=str(input_path),
        original_sha256=original_sha,
        enhanced_path=str(enhanced_path),
        enhanced_sha256=enhanced_sha,
        preset=preset,
        preset_label=str(PRESETS[preset]["label"]),
        params=params,
        method="opencv_enhancement_pipeline",
        method_version=ENHANCEMENT_VERSION,
        derived_label=DERIVED_LABEL,
        original_width=int(img.shape[1]),
        original_height=int(img.shape[0]),
        enhanced_width=int(enhanced.shape[1]),
        enhanced_height=int(enhanced.shape[0]),
        processing_ms=round(processing_ms, 3),
        metadata_path=str(metadata_path),
        warnings=warnings,
    )

    meta = {
        **result.to_dict(),
        "case_id": case_id,
        "observation_id": observation_id,
        "crop_id": crop_id,
        "source_metadata": source_metadata or {},
        "forensic_notice": "Derived artifact. Original evidence unchanged. Not for silent face matching.",
    }
    metadata_path.write_text(json.dumps(meta, indent=2))
    return result


def list_presets() -> list[dict[str, Any]]:
    return [{"name": k, **v} for k, v in PRESETS.items()]
