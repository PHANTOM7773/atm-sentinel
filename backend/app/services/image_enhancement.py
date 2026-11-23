from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import CV_CROP_DIR, DATA_DIR
from ..cv.image_enhancement import DEFAULT_OUTPUT_ROOT, DERIVED_LABEL, ENHANCEMENT_VERSION, enhance_crop_file, list_presets
from ..db import get_db
from . import cv_integration


class ImageEnhancementError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def presets() -> list[dict[str, Any]]:
    return list_presets()


def _derived_root() -> Path:
    root = DEFAULT_OUTPUT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    return root


def _meta_path(case_id: str, cv_run_id: str, observation_id: str, crop_id: str, preset: str) -> Path:
    safe = [cv_integration._validated_crop_identifier(x, 422) for x in [case_id, cv_run_id, observation_id, crop_id, preset]]
    return _derived_root() / safe[0] / safe[1] / safe[2] / safe[3] / f"{safe[4]}.json"


def _read_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def enhance_observation_crop(
    *,
    case_id: str,
    cv_run_id: str,
    observation_id: str,
    crop_id: str,
    preset: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # resolve original crop through existing scoped/retrievable checks
    original_path = cv_integration.resolve_observation_crop(case_id, cv_run_id, observation_id, crop_id)
    meta_out = _meta_path(case_id, cv_run_id, observation_id, crop_id, preset)
    meta_out.parent.mkdir(parents=True, exist_ok=True)

    # source metadata/provenance
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cv_observations WHERE id=? AND cv_run_id=? AND case_id=?",
            (observation_id, cv_run_id, case_id),
        ).fetchone()
    if not row:
        raise ImageEnhancementError("Observation not found", 404)

    source_metadata = {
        "case_id": case_id,
        "cv_run_id": cv_run_id,
        "observation_id": observation_id,
        "crop_id": crop_id,
        "sample_id": str(row["sample_id"]),
        "original_frame_number": int(row["original_frame_number"]),
        "original_video_timestamp_seconds": float(row["original_video_timestamp_seconds"]),
        "source_video_sha256": str(row["source_video_sha256"]),
        "bbox": json.loads(row["bbox_json"] or "[]"),
        "detector_confidence": float(row["detector_confidence"]),
        "quality": json.loads(row["quality_json"] or "{}"),
    }

    result = enhance_crop_file(
        input_path=original_path,
        output_root=meta_out.parent,  # write alongside metadata dir; preset subdir managed below
        preset=preset,
        overrides=overrides,
        case_id=case_id,
        observation_id=observation_id,
        crop_id=crop_id,
        source_metadata=source_metadata,
    )

    # move/normalize into deterministic location for this observation+crop+preset
    target_img = meta_out.with_suffix(".jpg")
    target_meta = meta_out
    src_img = Path(result.enhanced_path)
    src_meta = Path(result.metadata_path)
    if src_img.resolve() != target_img.resolve():
        target_img.write_bytes(src_img.read_bytes())
        try:
            src_img.unlink()
        except Exception:
            pass
    if src_meta.resolve() != target_meta.resolve():
        try:
            src_meta.unlink()
        except Exception:
            pass

    # recompute hash for final file
    from ..cv.image_enhancement import sha256_file

    enhanced_sha = sha256_file(target_img)
    payload = {
        **result.to_dict(),
        "enhanced_path": str(target_img),
        "enhanced_sha256": enhanced_sha,
        "metadata_path": str(target_meta),
        "case_id": case_id,
        "cv_run_id": cv_run_id,
        "observation_id": observation_id,
        "crop_id": crop_id,
        "source_metadata": source_metadata,
        "derived_label": DERIVED_LABEL,
        "method_version": ENHANCEMENT_VERSION,
        "forensic_notice": "Derived artifact. Original evidence unchanged. Never use for face matching/embeddings.",
    }
    target_meta.write_text(json.dumps(payload, indent=2))
    return payload


def get_enhancement_meta(case_id: str, cv_run_id: str, observation_id: str, crop_id: str, preset: str) -> dict[str, Any]:
    # ensure scoped access to original observation/crop
    cv_integration.resolve_observation_crop(case_id, cv_run_id, observation_id, crop_id)
    meta = _read_meta(_meta_path(case_id, cv_run_id, observation_id, crop_id, preset))
    if not meta:
        raise ImageEnhancementError("Enhanced crop not found", 404)
    return meta


def resolve_enhanced_crop(case_id: str, cv_run_id: str, observation_id: str, crop_id: str, preset: str) -> Path:
    meta = get_enhancement_meta(case_id, cv_run_id, observation_id, crop_id, preset)
    path = Path(str(meta.get("enhanced_path", ""))).resolve()
    root = _derived_root().resolve()
    if root != path and root not in path.parents:
        raise ImageEnhancementError("Enhanced crop not available", 404)
    if not path.exists() or not path.is_file():
        raise ImageEnhancementError("Enhanced crop not available", 404)
    return path
