from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

OFFSET_TOLERANCE_SECONDS = 2.0


class TimestampError(ValueError):
    pass


def parse_timestamp(value: str | None, field: str = "timestamp") -> datetime:
    if not value or not str(value).strip():
        raise TimestampError(f"{field} is required")
    raw = str(value).strip().replace("Z", "+00:00")
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TimestampError(
            f"Invalid {field}: use ISO 8601, e.g. 2026-01-15T14:32:10+05:30"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
        warnings_note = True
    else:
        warnings_note = False
    parsed = parsed.astimezone(timezone.utc)
    if warnings_note:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_naive(value: str | None) -> bool:
    if not value:
        return False
    raw = str(value).strip().replace("Z", "+00:00")
    if " " in raw and "T" not in raw:
        raw = raw.replace(" ", "T", 1)
    try:
        return datetime.fromisoformat(raw).tzinfo is None
    except ValueError:
        return False


def compute_alignment(
    transaction_ts: str,
    cctv_ts: str,
    video_duration: float,
    video_start_ts: str | None = None,
    cctv_reference_video_time: float = 0.0,
    clock_offset_minutes: float | None = None,
) -> dict[str, Any]:
    """Map a transaction instant onto elapsed seconds in the video file.

    clock_offset = CCTV_clock - transaction_clock (positive means CCTV is ahead).
    If clock_offset_minutes is omitted it is derived from cctv_ts - transaction_ts.
    """
    tx = parse_timestamp(transaction_ts, "transaction timestamp")
    cctv = parse_timestamp(cctv_ts, "CCTV timestamp")
    derived_offset = (cctv - tx).total_seconds()

    if clock_offset_minutes is None:
        offset_seconds = derived_offset
        offset_source = "derived_from_transaction_and_cctv_timestamps"
    else:
        offset_seconds = float(clock_offset_minutes) * 60.0
        offset_source = "manual_clock_offset_minutes"

    if video_start_ts:
        start = parse_timestamp(video_start_ts, "video start timestamp")
    else:
        start = cctv - timedelta(seconds=float(cctv_reference_video_time))

    warnings: list[str] = []
    if is_naive(transaction_ts) or is_naive(cctv_ts) or (video_start_ts and is_naive(video_start_ts)):
        warnings.append("At least one timestamp had no timezone; UTC was assumed.")
    if clock_offset_minutes is not None and abs(offset_seconds - derived_offset) > OFFSET_TOLERANCE_SECONDS:
        warnings.append(
            "Manual clock offset differs from the offset implied by the two timestamps; verify before processing."
        )
    if derived_offset < 0:
        warnings.append("CCTV clock appears to be behind the transaction clock; verify the clock-offset sign.")

    transaction_in_cctv = tx + timedelta(seconds=offset_seconds)
    transaction_video_seconds = (transaction_in_cctv - start).total_seconds()

    return {
        "transaction_utc": tx.isoformat(),
        "cctv_utc": cctv.isoformat(),
        "transaction_clock": str(transaction_ts),
        "cctv_clock": str(cctv_ts),
        "derived_offset_seconds": round(derived_offset, 3),
        "offset_seconds": round(offset_seconds, 3),
        "offset_minutes": round(offset_seconds / 60.0, 4),
        "offset_source": offset_source,
        "video_start_utc": start.isoformat(),
        "transaction_cctv_utc": transaction_in_cctv.isoformat(),
        "transaction_video_seconds": round(transaction_video_seconds, 3),
        "video_duration": round(float(video_duration), 3),
        "warnings": warnings,
    }


def analyze_window(alignment: dict[str, Any], before_seconds: float, after_seconds: float) -> dict[str, Any]:
    try:
        before = float(before_seconds)
        after = float(after_seconds)
    except (TypeError, ValueError) as exc:
        raise TimestampError("Window before/after must be numeric seconds") from exc
    if before < 0 or after < 0:
        raise TimestampError("Analysis window values cannot be negative")
    if before + after < 1:
        raise TimestampError("Analysis window must span at least 1 second")

    center = float(alignment["transaction_video_seconds"])
    duration = float(alignment["video_duration"])
    raw_start = center - before
    raw_end = center + after
    clamped_start = max(0.0, min(raw_start, max(duration - 0.001, 0.0)))
    clamped_end = max(clamped_start + 0.001, min(raw_end, duration))

    warnings = list(alignment.get("warnings", []))
    if raw_start < 0:
        warnings.append(f"Requested window starts {abs(raw_start):.2f}s before the video; clamped to 0.")
    if raw_end > duration:
        warnings.append(f"Requested window ends {raw_end - duration:.2f}s after the video; clamped to duration.")
    if center < 0 or center > duration:
        warnings.append("Transaction maps outside the video duration; verify clock settings and video selection.")

    result = dict(alignment)
    result.update(
        {
            "window_before_seconds": round(before, 3),
            "window_after_seconds": round(after, 3),
            "window_start_raw": round(raw_start, 3),
            "window_end_raw": round(raw_end, 3),
            "window_start_seconds": round(clamped_start, 3),
            "window_end_seconds": round(clamped_end, 3),
            "analysis_span_seconds": round(clamped_end - clamped_start, 3),
            "warnings": warnings,
        }
    )
    return result
