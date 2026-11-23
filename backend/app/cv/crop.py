from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from .errors import CVError
from .types import FaceDetection, Point


def safe_segment(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value)).strip("._-")
    return text[:80] or "unknown"


def crop_face(
    image: np.ndarray,
    detection: FaceDetection,
    padding: float = 0.15,
) -> tuple[np.ndarray, tuple[Point, Point, Point, Point, Point], tuple[float, float, float, float]]:
    if image is None or image.size == 0:
        raise CVError("Cannot crop from an empty frame")
    x, y, width, height = detection.bbox
    pad_x = width * padding
    pad_y = height * padding
    x1 = max(0, int(np.floor(x - pad_x)))
    y1 = max(0, int(np.floor(y - pad_y)))
    x2 = min(image.shape[1], int(np.ceil(x + width + pad_x)))
    y2 = min(image.shape[0], int(np.ceil(y + height + pad_y)))
    if x2 <= x1 or y2 <= y1:
        raise CVError("Face crop is outside the frame")
    crop = image[y1:y2, x1:x2]
    landmarks = tuple((float(px - x1), float(py - y1)) for px, py in detection.landmarks)
    return crop, landmarks, (float(x1), float(y1), float(x2 - x1), float(y2 - y1))


def save_crop(crop: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.jpg")
    try:
        try:
            written = cv2.imwrite(str(temporary), crop)
        except cv2.error as exc:
            raise CVError("Could not encode face crop") from exc
        if not written or not temporary.exists() or temporary.stat().st_size == 0:
            raise CVError("Could not encode face crop")
        with temporary.open("rb") as handle:
            if handle.read(3) != b"\xff\xd8\xff":
                raise CVError("Could not encode face crop")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def crop_signature(crop: np.ndarray) -> str:
    if crop is None or crop.size == 0:
        return ""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    resized = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
    threshold = float(np.median(resized))
    return "".join("1" if value > threshold else "0" for value in resized.flatten())


def face_sample_id(source_id: str, frame_number: int, track_id: int | None) -> str:
    return f"{safe_segment(source_id)}-f{frame_number:06d}-t{int(track_id or 0):03d}"


def prune_crops(directory: Path, max_files: int) -> int:
    if not directory.exists() or max_files < 0:
        return 0
    files = [
        path
        for path in directory.rglob("*.jpg")
        if path.is_file() and path.stat().st_size > 0 and not path.name.startswith(".")
    ]
    if len(files) <= max_files:
        return 0
    files.sort(key=lambda path: (path.stat().st_mtime_ns, str(path)))
    removed = 0
    for path in files[: len(files) - max_files]:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


__all__ = ["crop_face", "crop_signature", "face_sample_id", "prune_crops", "safe_segment", "save_crop"]
