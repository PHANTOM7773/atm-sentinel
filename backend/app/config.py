from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

APP_NAME = "ATM Sentinel"
APP_VERSION = "0.1.0"
SCHEMA_VERSION = 5

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("ATM_SENTINEL_DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
DB_PATH = DATA_DIR / "sentinel.db"
UPLOAD_DIR = DATA_DIR / "uploads"
FRAME_DIR = DATA_DIR / "frames"
EXPORT_DIR = DATA_DIR / "exports"

MAX_UPLOAD_BYTES = int(os.getenv("ATM_SENTINEL_MAX_UPLOAD_MB", "500")) * 1024 * 1024
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv"}
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

CV_MODEL_DIR = DATA_DIR / "models"
CV_OUTPUT_DIR = DATA_DIR / "cv"
CV_DATASET_DIR = DATA_DIR / "datasets"
CV_CROP_DIR = CV_OUTPUT_DIR / "crops"
CV_BACKEND = os.getenv("ATM_SENTINEL_CV_BACKEND", "cpu")
CV_TARGET = os.getenv("ATM_SENTINEL_CV_TARGET", "cpu")
CV_FACE_SCORE_THRESHOLD = float(os.getenv("ATM_SENTINEL_CV_FACE_SCORE", "0.6"))
CV_PERSON_SCORE_THRESHOLD = float(os.getenv("ATM_SENTINEL_CV_PERSON_SCORE", "0.45"))
CV_MIN_EMBED_QUALITY = float(os.getenv("ATM_SENTINEL_CV_MIN_EMBED_QUALITY", "20"))
CV_MAX_FRAMES = int(os.getenv("ATM_SENTINEL_CV_MAX_FRAMES", "300"))
CV_ANALYZE_MAX_FRAMES = int(os.getenv("ATM_SENTINEL_CV_ANALYZE_MAX_FRAMES", str(CV_MAX_FRAMES)))
CV_MAX_FRAME_STRIDE = int(os.getenv("ATM_SENTINEL_CV_MAX_FRAME_STRIDE", "20"))
CV_MAX_DECODED_FRAMES = int(os.getenv("ATM_SENTINEL_CV_MAX_DECODED_FRAMES", "3000"))
CV_MAX_CLIP_DURATION_SECONDS = float(os.getenv("ATM_SENTINEL_CV_MAX_CLIP_DURATION_SECONDS", "300"))
CV_ANALYZE_CONCURRENCY = max(1, int(os.getenv("ATM_SENTINEL_CV_ANALYZE_CONCURRENCY", "1")))
CV_MAX_CROPS_PER_ANALYSIS = int(os.getenv("ATM_SENTINEL_CV_MAX_CROPS_PER_ANALYSIS", "100"))
CV_MAX_CROP_FILES = int(os.getenv("ATM_SENTINEL_CV_MAX_CROP_FILES", "2000"))
CV_MAX_TOP_K = int(os.getenv("ATM_SENTINEL_CV_MAX_TOP_K", "25"))
CV_MAX_FACE_OBSERVATIONS_PER_FRAME = max(1, int(os.getenv("ATM_SENTINEL_CV_MAX_FACE_OBSERVATIONS_PER_FRAME", "8")))
CV_MAX_PERSON_OBSERVATIONS_PER_FRAME = max(1, int(os.getenv("ATM_SENTINEL_CV_MAX_PERSON_OBSERVATIONS_PER_FRAME", "12")))
CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS = max(
    CV_MAX_FACE_OBSERVATIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS", "120")),
)
CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS = max(
    CV_MAX_PERSON_OBSERVATIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS", "200")),
)
CV_MAX_FACE_DETECTIONS_PER_FRAME = max(
    CV_MAX_FACE_OBSERVATIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_FACE_DETECTIONS_PER_FRAME", "64")),
)
CV_MAX_PERSON_DETECTIONS_PER_FRAME = max(
    CV_MAX_PERSON_OBSERVATIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_PERSON_DETECTIONS_PER_FRAME", "128")),
)
CV_MAX_FACE_DETECTIONS_PER_ANALYSIS = max(
    CV_MAX_FACE_DETECTIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_FACE_DETECTIONS_PER_ANALYSIS", "6000")),
)
CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS = max(
    CV_MAX_PERSON_DETECTIONS_PER_FRAME,
    int(os.getenv("ATM_SENTINEL_CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS", "12000")),
)
CV_MAX_RANKED_CANDIDATES = max(1, int(os.getenv("ATM_SENTINEL_CV_MAX_RANKED_CANDIDATES", "100")))
CV_MAX_RESPONSE_BYTES = max(1024, int(os.getenv("ATM_SENTINEL_CV_MAX_RESPONSE_BYTES", "750000")))

DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
)


def _cors_origins() -> list[str]:
    configured = os.getenv("ATM_SENTINEL_CORS_ORIGINS", "").strip()
    if not configured:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


CORS_ORIGINS = _cors_origins()


def ensure_dirs() -> None:
    for path in (
        DATA_DIR,
        UPLOAD_DIR,
        FRAME_DIR,
        EXPORT_DIR,
        CV_MODEL_DIR,
        CV_OUTPUT_DIR,
        CV_DATASET_DIR,
        CV_CROP_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def relative_to_data(path: Path) -> str:
    return str(Path(path).resolve().relative_to(DATA_DIR))


def absolute_from_data(relative: str) -> Path:
    candidate = (DATA_DIR / relative).resolve()
    if DATA_DIR not in candidate.parents and candidate != DATA_DIR:
        raise ValueError("Resolved path escapes the data directory")
    return candidate


def cv_limits() -> dict[str, Any]:
    return {
        "max_analysis_frames": CV_ANALYZE_MAX_FRAMES,
        "max_frame_stride": CV_MAX_FRAME_STRIDE,
        "max_decoded_frames": CV_MAX_DECODED_FRAMES,
        "max_clip_duration_seconds": CV_MAX_CLIP_DURATION_SECONDS,
        "max_crops_per_analysis": CV_MAX_CROPS_PER_ANALYSIS,
        "max_retained_crop_files": CV_MAX_CROP_FILES,
        "max_top_k": CV_MAX_TOP_K,
        "max_face_observations_per_frame": CV_MAX_FACE_OBSERVATIONS_PER_FRAME,
        "max_person_observations_per_frame": CV_MAX_PERSON_OBSERVATIONS_PER_FRAME,
        "max_face_observations_per_analysis": CV_MAX_FACE_OBSERVATIONS_PER_ANALYSIS,
        "max_person_observations_per_analysis": CV_MAX_PERSON_OBSERVATIONS_PER_ANALYSIS,
        "max_face_detections_per_frame": CV_MAX_FACE_DETECTIONS_PER_FRAME,
        "max_person_detections_per_frame": CV_MAX_PERSON_DETECTIONS_PER_FRAME,
        "max_face_detections_per_analysis": CV_MAX_FACE_DETECTIONS_PER_ANALYSIS,
        "max_person_detections_per_analysis": CV_MAX_PERSON_DETECTIONS_PER_ANALYSIS,
        "max_ranked_candidates": CV_MAX_RANKED_CANDIDATES,
        "max_response_bytes": CV_MAX_RESPONSE_BYTES,
        "concurrent_analyses": CV_ANALYZE_CONCURRENCY,
        "synchronous": True,
    }
