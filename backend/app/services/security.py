from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from ..config import ALLOWED_EXTENSIONS, DATA_DIR

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._() -]{0,190}$")
MAGIC = {
    "mp4": [(4, b"ftyp")],
    "mov": [(4, b"ftyp")],
    "avi": [(0, b"RIFF"), (8, b"AVI ")],
    "mkv": [(0, b"\x1a\x45\xdf\xa3")],
}


class ValidationError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


def safe_original_name(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise ValidationError("A filename is required")
    name = filename.strip().replace("\\", "/").split("/")[-1]
    if name in {"", ".", ".."} or CONTROL_CHARS.search(name):
        raise ValidationError("Unsafe filename")
    if not SAFE_NAME.match(name):
        raise ValidationError("Filename contains unsupported characters")
    return name


def file_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '.{ext or 'none'}'. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}. "
            "Convert with: ffmpeg -i input -c:v libx264 -preset veryfast -c:a aac output.mp4"
        )
    return ext


def check_magic(header: bytes, ext: str) -> None:
    for offset, expected in MAGIC[ext]:
        if len(header) < offset + len(expected) or header[offset : offset + len(expected)] != expected:
            raise ValidationError(
                f"File content does not match the .{ext} extension. "
                "Use FFmpeg to normalize the file before upload."
            )


def validate_upload(filename: str, size: int, header: bytes, max_bytes: int) -> tuple[str, str]:
    if size <= 0:
        raise ValidationError("Empty upload: the file has no bytes")
    if size > max_bytes:
        raise ValidationError(f"File is too large ({size} bytes). Limit is {max_bytes} bytes")
    safe_name = safe_original_name(filename)
    ext = file_extension(safe_name)
    check_magic(header, ext)
    return safe_name, ext


def internal_video_name(video_id: str, ext: str) -> str:
    return f"{video_id}.{ext}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def within_data(path: Path) -> Path:
    resolved = path.resolve()
    if DATA_DIR not in resolved.parents and resolved != DATA_DIR:
        raise ValidationError("Path escapes the project data directory")
    return resolved


def session_token(passphrase: str, issued: str) -> str:
    import hmac

    return hmac.new(passphrase.encode(), issued.encode(), hashlib.sha256).hexdigest()


def env_passphrase() -> str:
    return os.getenv("ATM_SENTINEL_PASSPHRASE", "")
