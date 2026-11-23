import pytest

from app.services.timestamp import (
    TimestampError,
    analyze_window,
    compute_alignment,
    is_naive,
    parse_timestamp,
)


def test_parse_timezone_and_naive_detection():
    aware = parse_timestamp("2026-01-15T14:32:10+05:30")
    assert aware.isoformat() == "2026-01-15T09:02:10+00:00"
    assert is_naive("2026-01-15T14:32:10")
    assert not is_naive("2026-01-15T14:32:10+05:30")


def test_invalid_timestamp_rejected():
    with pytest.raises(TimestampError):
        parse_timestamp("not-a-date")


def test_offset_derived_from_transaction_and_cctv():
    result = compute_alignment(
        "2026-01-15T09:00:00+00:00",
        "2026-01-15T09:02:30+00:00",
        60,
        video_start_ts="2026-01-15T09:02:25+00:00",
    )
    assert result["offset_seconds"] == 150
    assert result["offset_minutes"] == 2.5
    assert result["offset_source"] == "derived_from_transaction_and_cctv_timestamps"
    assert result["transaction_video_seconds"] == 5


def test_manual_offset_override_and_mismatch_warning():
    result = compute_alignment(
        "2026-01-15T09:00:00+00:00",
        "2026-01-15T09:02:30+00:00",
        60,
        video_start_ts="2026-01-15T09:02:00+00:00",
        clock_offset_minutes=2,
    )
    assert result["offset_seconds"] == 120
    assert any("differs" in warning for warning in result["warnings"])


def test_cctv_reference_point_anchor():
    result = compute_alignment(
        "2026-01-15T09:00:00+00:00",
        "2026-01-15T09:02:00+00:00",
        30,
        cctv_reference_video_time=10,
    )
    assert result["transaction_video_seconds"] == 10


def test_window_boundaries_and_clamping():
    alignment = compute_alignment(
        "2026-01-15T09:00:00+00:00",
        "2026-01-15T09:00:10+00:00",
        20,
        cctv_reference_video_time=10,
    )
    window = analyze_window(alignment, 5, 30)
    assert window["window_start_seconds"] == 5
    assert window["window_end_seconds"] == 20
    assert any("after the video" in warning for warning in window["warnings"])
    assert window["analysis_span_seconds"] == 15


def test_negative_or_tiny_window_rejected():
    alignment = compute_alignment("2026-01-15T09:00:00+00:00", "2026-01-15T09:00:00+00:00", 20)
    with pytest.raises(TimestampError):
        analyze_window(alignment, -1, 1)
    with pytest.raises(TimestampError):
        analyze_window(alignment, 0.2, 0.2)


def test_transaction_outside_video_warns():
    alignment = compute_alignment(
        "2026-01-15T09:00:00+00:00",
        "2026-01-15T09:00:00+00:00",
        20,
        cctv_reference_video_time=-5,
    )
    window = analyze_window(alignment, 2, 2)
    assert any("outside the video" in warning for warning in window["warnings"])
