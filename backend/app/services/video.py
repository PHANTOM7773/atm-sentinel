from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..config import FFMPEG, FFPROBE


class VideoError(ValueError):
    pass


def dependencies() -> dict[str, bool]:
    return {"ffmpeg": FFMPEG is not None, "ffprobe": FFPROBE is not None, "opencv": True}


def require_ffprobe() -> str:
    if not FFPROBE:
        raise VideoError(
            "ffprobe is not installed. Install FFmpeg (macOS: brew install ffmpeg) and restart the backend."
        )
    return FFPROBE


def require_ffmpeg() -> str:
    if not FFMPEG:
        raise VideoError(
            "FFmpeg is not installed. Install FFmpeg (macOS: brew install ffmpeg) and restart the backend."
        )
    return FFMPEG


def _rational(value: str | None) -> float:
    if not value or value in {"0/0", "N/A"}:
        return 0.0
    try:
        if "/" in value:
            top, bottom = value.split("/", 1)
            result = float(top) / float(bottom)
        else:
            result = float(value)
        return result if result > 0 else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_video(path: Path) -> dict[str, Any]:
    ffprobe = require_ffprobe()
    args = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise VideoError("ffprobe timed out while reading the video") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        last = detail[-1] if detail else "unknown ffprobe error"
        raise VideoError(f"ffprobe could not read this file: {last}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise VideoError("ffprobe returned an unreadable metadata response") from exc

    streams = payload.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    if not video_streams:
        raise VideoError("No video stream found. The file may be audio-only or corrupted.")
    stream = video_streams[0]
    fmt = payload.get("format", {})
    fps = _rational(stream.get("avg_frame_rate")) or _rational(stream.get("r_frame_rate"))
    duration_raw = fmt.get("duration") or stream.get("duration")
    try:
        duration = float(duration_raw) if duration_raw else 0.0
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "container": str(fmt.get("format_name", "")),
        "format_long_name": str(fmt.get("format_long_name", "")),
        "codec": str(stream.get("codec_name", "")),
        "codec_long_name": str(stream.get("codec_long_name", "")),
        "width": int(stream.get("width") or stream.get("coded_width") or 0),
        "height": int(stream.get("height") or stream.get("coded_height") or 0),
        "fps": round(fps, 4),
        "duration": round(duration, 3),
        "stream_count": len(streams),
        "bit_rate": int(fmt.get("bit_rate") or 0) if str(fmt.get("bit_rate", "")).isdigit() else 0,
        "streams": [
            {
                "index": s.get("index"),
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name"),
                "language": (s.get("tags") or {}).get("language", ""),
            }
            for s in streams
        ],
    }


def check_integrity(path: Path, timeout: int = 300) -> tuple[str, str]:
    ffmpeg = require_ffmpeg()
    args = [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"]
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise VideoError("Video integrity check timed out") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        return "failed", (detail[-1] if detail else "decode error")[:500]
    return "verified", "Full decode completed without reported errors"


def normalize_video(source: Path, destination: Path) -> None:
    ffmpeg = require_ffmpeg()
    args = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        str(destination),
    ]
    completed = subprocess.run(args, capture_output=True, text=True, timeout=900, check=False)
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        raise VideoError(f"Normalization failed: {detail[-1] if detail else 'unknown error'}")


def tool_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name, binary in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        if not binary:
            versions[name] = "not installed"
            continue
        try:
            result = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=10)
            versions[name] = result.stdout.splitlines()[0] if result.stdout else "unknown"
        except (OSError, subprocess.SubprocessError):
            versions[name] = "unknown"
    return versions


def copy_ffmpeg_placeholder() -> None:
    """Kept as a no-op so no code path ever shells out with a user filename."""
    return None


__all__ = [
    "VideoError",
    "check_integrity",
    "copy_ffmpeg_placeholder",
    "dependencies",
    "normalize_video",
    "probe_video",
    "require_ffmpeg",
    "require_ffprobe",
    "tool_versions",
]
