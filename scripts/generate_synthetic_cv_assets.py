from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import CV_DATASET_DIR  # noqa: E402


WIDTH = 640
HEIGHT = 480
FPS = 10
SUBJECTS = {
    "SYN-A": {"skin": (176, 205, 226), "hair": (36, 28, 24), "shirt": (58, 92, 128)},
    "SYN-B": {"skin": (184, 204, 220), "hair": (72, 46, 28), "shirt": (132, 62, 72)},
    "SYN-C": {"skin": (198, 214, 224), "hair": (28, 30, 38), "shirt": (52, 120, 104)},
}


def _background(frame_index: int) -> np.ndarray:
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for y in range(HEIGHT):
        shade = int(72 + 34 * y / HEIGHT)
        frame[y, :] = (shade, shade + 8, shade + 16)
    cv2.rectangle(frame, (28, 28), (WIDTH - 28, HEIGHT - 28), (118, 124, 130), 2)
    cv2.rectangle(frame, (44, 44), (WIDTH - 44, 105), (92, 98, 104), -1)
    cv2.putText(
        frame,
        f"SYNTHETIC CV BENCHMARK  T+{frame_index / FPS:.1f}s",
        (54, 82),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (220, 226, 232),
        2,
    )
    cv2.rectangle(frame, (WIDTH - 150, 340), (WIDTH - 60, 430), (78, 84, 90), -1)
    cv2.putText(frame, "ATM", (WIDTH - 137, 390), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (210, 216, 222), 2)
    return frame


def _rotate_point(point: tuple[float, float], center: tuple[float, float], degrees: float) -> tuple[int, int]:
    angle = math.radians(degrees)
    px, py = point[0] - center[0], point[1] - center[1]
    rx = px * math.cos(angle) - py * math.sin(angle)
    ry = px * math.sin(angle) + py * math.cos(angle)
    return int(round(center[0] + rx)), int(round(center[1] + ry))


def draw_face(
    frame: np.ndarray,
    center: tuple[int, int],
    size: int,
    subject: str,
    turn: float = 0.0,
    tilt: float = 0.0,
    visible: bool = True,
) -> None:
    palette = SUBJECTS[subject]
    skin = palette["skin"]
    hair = palette["hair"]
    shirt = palette["shirt"]
    cx, cy = center
    face_w = int(size * 0.74)
    face_h = int(size)
    center_point = (float(cx), float(cy))

    torso_top = int(cy + face_h * 0.55)
    torso_bottom = int(min(HEIGHT - 80, cy + face_h * 1.25))
    neck_top = int(cy + face_h * 0.40)
    cv2.rectangle(
        frame,
        (int(cx - face_w * 0.17), neck_top),
        (int(cx + face_w * 0.17), torso_top + 8),
        skin,
        -1,
    )
    torso = [
        (int(cx - face_w * 0.58), torso_top),
        (int(cx + face_w * 0.58), torso_top),
        (int(cx + face_w * 0.72), torso_bottom),
        (int(cx - face_w * 0.72), torso_bottom),
    ]
    cv2.fillPoly(frame, [np.asarray(torso, dtype=np.int32)], shirt)

    for side in (-1, 1):
        shoulder = (int(cx + side * face_w * 0.60), torso_top + 8)
        elbow = (int(cx + side * face_w * 0.95), torso_bottom - 18)
        hand = (int(cx + side * face_w * 1.02), torso_bottom + 8)
        cv2.line(frame, shoulder, elbow, shirt, max(10, size // 10), cv2.LINE_AA)
        cv2.line(frame, elbow, hand, skin, max(8, size // 14), cv2.LINE_AA)
        cv2.circle(frame, hand, max(7, size // 17), skin, -1, cv2.LINE_AA)

    for side in (-1, 1):
        hip = (int(cx + side * face_w * 0.30), torso_bottom)
        ankle = (int(cx + side * face_w * 0.36), HEIGHT - 28)
        cv2.line(frame, hip, ankle, (44, 49, 57), max(14, size // 8), cv2.LINE_AA)
        cv2.ellipse(frame, (ankle[0] + side * 5, HEIGHT - 20), (18, 8), 0, 0, 360, (28, 30, 34), -1)

    head_center = _rotate_point((cx, cy), center_point, tilt)
    cv2.ellipse(frame, head_center, (face_w // 2, face_h // 2), tilt, 0, 360, skin, -1, cv2.LINE_AA)
    ear_left = _rotate_point((cx - face_w // 2, cy), center_point, tilt)
    ear_right = _rotate_point((cx + face_w // 2, cy), center_point, tilt)
    cv2.ellipse(frame, ear_left, (max(4, size // 18), max(7, size // 10)), tilt, 0, 360, skin, -1)
    cv2.ellipse(frame, ear_right, (max(4, size // 18), max(7, size // 10)), tilt, 0, 360, skin, -1)

    hair_top = _rotate_point((cx, cy - face_h * 0.42), center_point, tilt)
    cv2.ellipse(frame, hair_top, (face_w // 2 + 3, face_h // 4), tilt, 0, 360, hair, -1, cv2.LINE_AA)

    if not visible:
        return

    shift = int(turn * face_w * 0.12)
    eye_y = cy - int(face_h * 0.10)
    eye_dx = max(8, int(face_w * 0.19))
    for side in (-1, 1):
        eye_center = _rotate_point((cx + side * eye_dx + shift, eye_y), center_point, tilt)
        cv2.ellipse(frame, eye_center, (max(6, size // 13), max(4, size // 20)), tilt, 0, 360, (242, 244, 246), -1)
        pupil_center = _rotate_point((cx + side * eye_dx + shift + int(turn * 2), eye_y), center_point, tilt)
        cv2.circle(frame, pupil_center, max(3, size // 28), (34, 40, 46), -1)
        brow_start = _rotate_point((cx + side * eye_dx - eye_dx // 2 + shift, eye_y - size // 16), center_point, tilt)
        brow_end = _rotate_point((cx + side * eye_dx + eye_dx // 2 + shift, eye_y - size // 18), center_point, tilt)
        cv2.line(frame, brow_start, brow_end, hair, max(2, size // 28), cv2.LINE_AA)

    nose_tip = _rotate_point((cx + int(shift * 1.4), cy + int(face_h * 0.07)), center_point, tilt)
    cv2.ellipse(frame, nose_tip, (max(3, size // 26), max(5, size // 16)), tilt, 0, 360, (146, 158, 168), -1)
    mouth_y = cy + int(face_h * 0.26)
    mouth_left = _rotate_point((cx + shift // 2 - int(face_w * 0.13), mouth_y), center_point, tilt)
    mouth_right = _rotate_point((cx + shift // 2 + int(face_w * 0.13), mouth_y), center_point, tilt)
    cv2.line(frame, mouth_left, mouth_right, (92, 62, 66), max(2, size // 28), cv2.LINE_AA)
    cv2.ellipse(
        frame,
        _rotate_point((cx + shift // 2, mouth_y + size // 40), center_point, tilt),
        (max(5, size // 14), max(2, size // 45)),
        tilt,
        0,
        360,
        (176, 112, 116),
        -1,
    )


def _write_video(path: Path, frames: list[np.ndarray]) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"Could not create video: {path}")
    for frame in frames:
        writer.write(frame)
    writer.release()


def build_assets(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "generated_by": "scripts/generate_synthetic_cv_assets.py",
        "synthetic": True,
        "real_people": False,
        "notice": "Fictional procedural faces and scenes for pipeline-functionality testing only.",
        "fps": FPS,
        "width": WIDTH,
        "height": HEIGHT,
        "videos": {},
    }

    def add(name: str, frames: list[np.ndarray], labels: dict[int, str], description: str) -> None:
        path = output_dir / f"{name}.mp4"
        _write_video(path, frames)
        manifest["videos"][name] = {
            "file": path.name,
            "frame_count": len(frames),
            "description": description,
            "labels": {str(key): value for key, value in labels.items()},
        }

    clear_frames: list[np.ndarray] = []
    clear_labels: dict[int, str] = {}
    for index in range(40):
        frame = _background(index)
        draw_face(frame, (320, 175), 155, "SYN-A", turn=math.sin(index / 8) * 0.25, tilt=math.sin(index / 11) * 3)
        clear_frames.append(frame)
        clear_labels[index] = "SYN-A"
    add("subject_a_front", clear_frames, clear_labels, "One clearly visible synthetic subject across 40 frames")

    side_frames: list[np.ndarray] = []
    side_labels: dict[int, str] = {}
    for index in range(30):
        frame = _background(index)
        draw_face(frame, (320, 175), 150, "SYN-A", turn=0.9 + math.sin(index / 9) * 0.1, tilt=-4)
        side_frames.append(frame)
        side_labels[index] = "SYN-A"
    add("subject_a_side", side_frames, side_labels, "Same synthetic subject with turned-face pose variation")

    other_frames: list[np.ndarray] = []
    other_labels: dict[int, str] = {}
    for index in range(40):
        frame = _background(index)
        draw_face(frame, (320, 175), 155, "SYN-B", turn=math.sin(index / 10) * 0.2, tilt=math.cos(index / 12) * 3)
        other_frames.append(frame)
        other_labels[index] = "SYN-B"
    add("subject_b_front", other_frames, other_labels, "Different synthetic subject in the same scene")

    multi_frames: list[np.ndarray] = []
    multi_labels: dict[int, str] = {}
    for index in range(35):
        frame = _background(index)
        draw_face(frame, (205, 175), 145, "SYN-A", turn=-0.2, tilt=2)
        draw_face(frame, (450, 175), 145, "SYN-B", turn=0.2, tilt=-2)
        multi_frames.append(frame)
        multi_labels[index] = "SYN-A,SYN-B"
    add("multi_subject", multi_frames, multi_labels, "Two synthetic subjects in the same frame")

    challenge_frames: list[np.ndarray] = []
    challenge_labels: dict[int, str] = {}
    for index in range(55):
        frame = _background(index)
        if index < 40:
            draw_face(frame, (320, 175), 155 if index < 10 else (105 if index < 20 else 150), "SYN-C", turn=math.sin(index / 7) * 0.4)
            if 10 <= index < 20:
                frame = cv2.GaussianBlur(frame, (17, 17), 0)
            elif 20 <= index < 30:
                frame = cv2.convertScaleAbs(frame, alpha=0.34, beta=0)
            elif 30 <= index < 40:
                cv2.rectangle(frame, (250, 185), (390, 245), (52, 58, 64), -1)
            challenge_labels[index] = "SYN-C"
        else:
            challenge_labels[index] = "none"
        challenge_frames.append(frame)
    add("challenges", challenge_frames, challenge_labels, "Blur, darkness, small face, partial occlusion and no-face frames")

    no_face_frames = [_background(index) for index in range(20)]
    add("no_face", no_face_frames, {}, "ATM scene without any synthetic face")

    (output_dir / "README.txt").write_text(
        "SYNTHETIC DATASET NOTICE\n\n"
        "All faces and scenes in this directory are procedurally generated fictional assets. "
        "No real people or real footage are present. Results from these clips validate pipeline mechanics only.\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic CV benchmark clips")
    parser.add_argument(
        "--output-dir",
        default=str(CV_DATASET_DIR / "synthetic" / "cv"),
        help="Directory for generated clips and manifest",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    manifest = build_assets(output_dir)
    print(f"Generated {len(manifest['videos'])} synthetic clips in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
