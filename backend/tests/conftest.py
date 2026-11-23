import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="atm-sentinel-tests-"))
os.environ["ATM_SENTINEL_DATA_DIR"] = str(TEST_DATA_DIR)

from app.config import DATA_DIR, ensure_dirs  # noqa: E402
from app.db import init_db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_data_dir():
    ensure_dirs()
    init_db()
    yield
    for directory in ("uploads", "frames", "exports", "tmp", "demo"):
        target = DATA_DIR / directory
        if not target.exists():
            continue
        for child in target.iterdir():
            if child.is_file():
                child.unlink()
    db_file = DATA_DIR / "sentinel.db"
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_file) + suffix)
        if path.exists():
            path.unlink()
    init_db()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def synthetic_video(tmp_path):
    import cv2

    path = tmp_path / "synthetic_test.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for index in range(60):
        frame = np.full((240, 320, 3), 90, dtype=np.uint8)
        cv2.rectangle(frame, (20, 20), (300, 220), (150, 170, 190), 2)
        cv2.putText(frame, f"T+{index / 10:.1f}s  SYNTHETIC", (25, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)
        writer.write(frame)
    writer.release()
    assert path.exists() and path.stat().st_size > 0
    return path


@pytest.fixture
def ffmpeg_synthetic_video_factory(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are required for format compatibility coverage")

    def build(extension: str):
        path = tmp_path / f"synthetic_format_test.{extension}"
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=160x120:rate=10",
                "-t",
                "1",
                "-an",
                "-c:v",
                "mpeg4",
                str(path),
            ],
            check=True,
        )
        assert path.exists() and path.stat().st_size > 0
        return path

    return build


@pytest.fixture
def case_and_transaction(client):
    case = client.post("/api/cases", json={"case_number": "TEST-0001", "title": "Synthetic test case", "location": "Test"}).json()
    tx = client.post(
        f"/api/cases/{case['id']}/transactions",
        json={
            "reference": "TEST-TX-001",
            "atm_id": "ATM-TEST",
            "transaction_ts": "2026-01-15T09:00:05+00:00",
            "cctv_ts": "2026-01-15T09:00:35+00:00",
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "test",
        },
    ).json()
    return case, tx
