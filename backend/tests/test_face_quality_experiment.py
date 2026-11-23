from __future__ import annotations

import numpy as np
import pytest

from app.cv.face_quality_experiment import evaluate_face_quality


def _base_img(value=120, size=96):
    img = np.full((size, size, 3), value, dtype=np.uint8)
    # add some texture so sharpness/noise aren't pathological
    rng = np.random.default_rng(1)
    noise = rng.integers(-5, 6, size=img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def test_normal_crop_scores_in_bounds_and_has_reason_codes():
    img = _base_img()
    r = evaluate_face_quality(img, bbox=[10, 10, 70, 70])
    assert 0 <= r["overall_score"] <= 100
    assert r["score_scale"] == "0-100"
    assert "NOT a probability" in r["score_meaning"]
    assert isinstance(r["reason_codes"], list) and r["reason_codes"]
    assert set(r["weights_used"]).issuperset({"sharpness", "resolution", "exposure", "contrast", "noise", "pose", "occlusion_visibility"})


def test_deterministic_for_same_input():
    img = _base_img()
    a = evaluate_face_quality(img, bbox=[0, 0, 96, 96])
    b = evaluate_face_quality(img, bbox=[0, 0, 96, 96])
    assert a == b


def test_blurry_scores_lower_sharpness_than_normal():
    img = _base_img()
    blur = cv2_blur(img)
    n = evaluate_face_quality(img)
    b = evaluate_face_quality(blur)
    sharp_n = dim(n, "sharpness")["score"]
    sharp_b = dim(b, "sharpness")["score"]
    assert sharp_b < sharp_n


def test_dark_and_low_contrast_degrade_expected_dimensions():
    img = _base_img(value=120)
    dark = np.full_like(img, 15)
    low_contrast = np.full_like(img, 120)
    d = evaluate_face_quality(dark)
    lc = evaluate_face_quality(low_contrast)
    assert dim(d, "exposure")["score"] < dim(evaluate_face_quality(img), "exposure")["score"]
    assert dim(lc, "contrast")["score"] < dim(evaluate_face_quality(img), "contrast")["score"]


def test_noisy_crop_degrades_noise_dimension():
    img = _base_img()
    rng = np.random.default_rng(2)
    noisy = np.clip(img.astype(np.int16) + rng.integers(-60, 61, size=img.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    n = evaluate_face_quality(img)
    noisy_r = evaluate_face_quality(noisy)
    assert dim(noisy_r, "noise")["score"] < dim(n, "noise")["score"]
    assert "high_noise" in noisy_r["reason_codes"] or "moderate_noise" in noisy_r["reason_codes"]


def test_tiny_crop_flags_resolution():
    img = _base_img(size=24)
    r = evaluate_face_quality(img, bbox=[0, 0, 20, 20])
    assert dim(r, "resolution")["score"] < 60
    assert "tiny_face" in r["reason_codes"] or "small_face" in r["reason_codes"]


def test_missing_landmarks_marks_pose_occlusion_unavailable():
    img = _base_img()
    r = evaluate_face_quality(img)
    assert "pose" in r["missing_dimensions"]
    assert "occlusion_visibility" in r["missing_dimensions"]
    assert dim(r, "pose")["available"] is False
    assert dim(r, "pose")["score"] is None
    assert "pose_not_assessed" in r["reason_codes"]


def test_invalid_input_raises():
    with pytest.raises(Exception):
        evaluate_face_quality(None)  # type: ignore
    with pytest.raises(Exception):
        evaluate_face_quality(np.array([]))


def dim(result, name):
    return next(d for d in result["dimensions"] if d["name"] == name)


def cv2_blur(img):
    import cv2
    return cv2.GaussianBlur(img, (21, 21), 8)
