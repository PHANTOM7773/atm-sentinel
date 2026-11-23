import cv2
import numpy as np

from app.services.quality import LIMITATIONS, analyze_frame


def test_quality_metrics_range_and_breakdown():
    rng = np.random.default_rng(7)
    image = rng.integers(20, 230, size=(240, 320, 3), dtype=np.uint8)
    result = analyze_frame(image)
    assert 0 <= result["quality_score"] <= 100
    assert result["sharpness"] > 0
    assert 0 <= result["brightness"] <= 255
    assert result["contrast"] >= 0
    assert set(result["components"]) == {
        "sharpness_component",
        "illumination_component",
        "contrast_component",
        "resolution_component",
        "motion_component",
    }
    assert "not probabilities of identity" in LIMITATIONS


def test_blur_reduces_sharpness():
    rng = np.random.default_rng(11)
    sharp = rng.integers(0, 255, size=(200, 200, 3), dtype=np.uint8)
    blurred = cv2.GaussianBlur(sharp, (15, 15), 0)
    assert analyze_frame(blurred)["sharpness"] < analyze_frame(sharp)["sharpness"]


def test_exposure_warnings():
    dark = np.zeros((200, 200, 3), dtype=np.uint8)
    bright = np.full((200, 200, 3), 250, dtype=np.uint8)
    assert any("Underexposed" in warning for warning in analyze_frame(dark)["warnings"])
    assert any("Overexposed" in warning for warning in analyze_frame(bright)["warnings"])


def test_low_resolution_warning():
    image = np.full((80, 80, 3), 120, dtype=np.uint8)
    assert any("Low source resolution" in warning for warning in analyze_frame(image)["warnings"])


def test_empty_frame_rejected():
    import pytest

    with pytest.raises(ValueError):
        analyze_frame(None)
