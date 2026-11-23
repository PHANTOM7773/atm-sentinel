from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.cv.image_enhancement import (
    DERIVED_LABEL,
    enhance_crop_file,
    enhance_image,
    list_presets,
    normalize_params,
    sha256_file,
)


def _write_img(path: Path, img: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), img)


def test_presets_exist():
    names = {p["name"] for p in list_presets()}
    assert {"general_enhancement", "low_light_correction", "low_contrast_correction", "noise_reduction"} <= names


def test_enhance_image_changes_dark_image(tmp_path):
    img = np.full((80, 80, 3), 25, dtype=np.uint8)
    out, warnings = enhance_image(img, normalize_params("low_light_correction"))
    assert out.shape[0] >= img.shape[0]
    assert float(out.mean()) > float(img.mean())
    assert isinstance(warnings, list)


def test_enhance_crop_file_writes_derived_output_and_metadata(tmp_path):
    src = tmp_path / "orig.jpg"
    img = np.random.randint(0, 255, (60, 60, 3), dtype=np.uint8)
    _write_img(src, img)
    orig_sha = sha256_file(src)

    res = enhance_crop_file(
        input_path=src,
        output_root=tmp_path / "out",
        preset="general_enhancement",
        case_id="case1",
        observation_id="obs1",
        crop_id="crop1",
    )
    assert Path(res.enhanced_path).exists()
    assert Path(res.metadata_path).exists()
    assert res.original_sha256 == orig_sha
    assert sha256_file(src) == orig_sha  # original unchanged
    assert res.enhanced_sha256 != res.original_sha256 or res.enhanced_path != res.original_path
    assert res.derived_label == DERIVED_LABEL
    assert res.original_width == 60 and res.original_height == 60
    assert res.enhanced_width > 0 and res.enhanced_height > 0


def test_invalid_image_fails_gracefully(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not-an-image")
    with pytest.raises(Exception):
        enhance_crop_file(input_path=bad, output_root=tmp_path / "out", preset="general_enhancement")


def test_unknown_preset_rejected():
    with pytest.raises(Exception):
        normalize_params("nope")
