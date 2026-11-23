from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import CV_MODEL_DIR, ensure_dirs
from .errors import CVError


@dataclass(frozen=True)
class ModelSpec:
    key: str
    filename: str
    source_url: str
    sha256: str | None
    license: str
    purpose: str
    notes: str


MODEL_SPECS: dict[str, ModelSpec] = {
    "yunet": ModelSpec(
        key="yunet",
        filename="face_detection_yunet_2026may.onnx",
        source_url=(
            "https://huggingface.co/pollen-robotics/face_detection_yunet_2026may/resolve/"
            "2b8e922362946a0db67e861bae0f77826980effd/face_detection_yunet_2026may.onnx"
        ),
        sha256="ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
        license="MIT weights; OpenCV Zoo Apache-2.0 repository",
        purpose="Face detection and five facial landmarks",
        notes=(
            "Dynamic input shape, compatible with OpenCV 5.x DNN ONNX loading. "
            "Upstream GitHub file revision: 26cc381e4d2594bb9f47a26eb8fd96c94a13660d."
        ),
    ),
    "sface": ModelSpec(
        key="sface",
        filename="face_recognition_sface_2021dec.onnx",
        source_url=(
            "https://huggingface.co/opencv/face_recognition_sface/resolve/"
            "3d7082438a6e4551e840c9b2bb60b71e8da4b524/face_recognition_sface_2021dec.onnx"
        ),
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        license="Apache-2.0",
        purpose="128-dimensional face descriptors for candidate ranking only",
        notes=(
            "Descriptors are L2-normalized before storage and comparison. "
            "Pinned Hugging Face revision: 3d7082438a6e4551e840c9b2bb60b71e8da4b524."
        ),
    ),
    "yolox": ModelSpec(
        key="yolox",
        filename="object_detection_yolox_2022nov.onnx",
        source_url=(
            "https://huggingface.co/opencv/object_detection_yolox/resolve/"
            "78c368f74ce73ee28fc7a1be418a598c71b58b52/object_detection_yolox_2022nov.onnx"
        ),
        sha256="c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
        license="Apache-2.0",
        purpose="COCO person detection",
        notes=(
            "YOLOX-s variant with 640x640 letterboxed input; only class 0 is retained. "
            "Pinned Hugging Face revision: 78c368f74ce73ee28fc7a1be418a598c71b58b52."
        ),
    ),
}


def model_path(key: str) -> Path:
    spec = MODEL_SPECS.get(key)
    if not spec:
        raise CVError(f"Unknown model: {key}")
    ensure_dirs()
    return CV_MODEL_DIR / spec.filename


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(key: str) -> tuple[bool, str]:
    spec = MODEL_SPECS[key]
    path = model_path(key)
    if not path.exists():
        return False, "not_downloaded"
    actual = sha256_file(path)
    if not spec.sha256:
        return True, "unpinned"
    return (actual == spec.sha256), ("verified" if actual == spec.sha256 else "mismatch")


def require_model(key: str) -> Path:
    path = model_path(key)
    if not path.exists():
        spec = MODEL_SPECS[key]
        raise CVError(f"Missing model {key}; run scripts/download_cv_models.py to fetch {spec.filename}")
    ok, state = verify_model(key)
    if not ok:
        raise CVError(f"Model {key} failed SHA256 verification ({state})")
    return path


def model_status() -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    for key, spec in MODEL_SPECS.items():
        path = model_path(key)
        ok, state = verify_model(key)
        statuses[key] = {
            "filename": spec.filename,
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "sha256": sha256_file(path) if path.exists() else "",
            "expected_sha256": spec.sha256,
            "verification": state,
            "usable": ok,
            "license": spec.license,
            "purpose": spec.purpose,
            "source_url": spec.source_url,
            "notes": spec.notes,
        }
    return {
        "directory": str(CV_MODEL_DIR),
        "models": statuses,
        "all_usable": all(item["usable"] for item in statuses.values()),
    }


__all__ = ["MODEL_SPECS", "model_path", "model_status", "require_model", "sha256_file", "verify_model"]
