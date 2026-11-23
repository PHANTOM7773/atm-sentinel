from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from app.services.quality import LIMITATIONS


def generate(path: Path, seconds: int = 12, fps: int = 10, start_utc: datetime | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 640, 480
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not create synthetic video")
    start = start_utc or datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone.utc)
    try:
        for index in range(seconds * fps):
            t = index / fps
            frame = np.full((height, width, 3), 38, dtype=np.uint8)
            cv2.rectangle(frame, (40, 40), (600, 440), (78, 96, 118), 2)
            cv2.putText(frame, "SYNTHETIC DEMO - NO PERSON", (56, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (210, 220, 235), 2)
            cv2.putText(frame, "ATM CCTV SIMULATION", (56, 112), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 175, 205), 1)
            clock = (start + timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S UTC")
            cv2.putText(frame, clock, (56, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (235, 235, 235), 2)
            cv2.putText(frame, f"T+{t:05.1f}s", (56, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 200, 240), 2)
            drift = int(220 + 40 * np.sin(t * 0.9))
            cv2.rectangle(frame, (60, drift), (580, drift + 90), (60, 70, 85), -1)
            cv2.putText(frame, "CARD SLOT / DEMO", (85, drift + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 210, 225), 2)
            cv2.putText(frame, "Quality scores are image-only: " + LIMITATIONS[:42], (52, 430), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (140, 155, 175), 1)
            writer.write(frame)
    finally:
        writer.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a clearly labelled synthetic CCTV-style demo clip")
    parser.add_argument("--output", default="data/demo/synthetic_atm.mp4")
    parser.add_argument("--seconds", type=int, default=12)
    parser.add_argument("--fps", type=int, default=10)
    args = parser.parse_args()
    output = Path(args.output)
    generate(output, args.seconds, args.fps)
    print(f"Created {output} ({output.stat().st_size} bytes)")
