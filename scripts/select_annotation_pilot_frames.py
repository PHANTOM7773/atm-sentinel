#!/usr/bin/env python3
"""Deterministically select ~48 pilot frames and extract derived PNGs.

Reads only existing synthetic manifest/videos. Writes only under
reports/ps04cctv-audit/annotations/. No production CV changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/datasets/synthetic/cv/manifest.json"
OUT_DIR = ROOT / "reports/ps04cctv-audit/annotations"
FRAMES_DIR = OUT_DIR / "frames"
SELECTION_PATH = OUT_DIR / "selected-frames-manifest.json"


# Deterministic, diverse selection. Indices manually chosen from known clip structure.
# challenges: 0-9 normal,10-19 blur,20-29 dark,30-39 occluded,40-54 no-face (manifest labels)
SELECTED = [
    # subject_a_front - frontal clear
    {"clip_id": "subject_a_front", "frame_index": 0, "target_conditions": ["front_facing", "clear"]},
    {"clip_id": "subject_a_front", "frame_index": 5, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 10, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 15, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 20, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 25, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 30, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_a_front", "frame_index": 39, "target_conditions": ["front_facing"]},
    # subject_a_side - side pose
    {"clip_id": "subject_a_side", "frame_index": 0, "target_conditions": ["side_pose"]},
    {"clip_id": "subject_a_side", "frame_index": 5, "target_conditions": ["side_pose"]},
    {"clip_id": "subject_a_side", "frame_index": 10, "target_conditions": ["side_pose"]},
    {"clip_id": "subject_a_side", "frame_index": 15, "target_conditions": ["side_pose"]},
    {"clip_id": "subject_a_side", "frame_index": 20, "target_conditions": ["side_pose"]},
    {"clip_id": "subject_a_side", "frame_index": 29, "target_conditions": ["side_pose"]},
    # subject_b_front - different identity frontal
    {"clip_id": "subject_b_front", "frame_index": 0, "target_conditions": ["front_facing", "different_subject"]},
    {"clip_id": "subject_b_front", "frame_index": 5, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 10, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 15, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 20, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 25, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 30, "target_conditions": ["front_facing"]},
    {"clip_id": "subject_b_front", "frame_index": 39, "target_conditions": ["front_facing"]},
    # multi_subject - multiple faces
    {"clip_id": "multi_subject", "frame_index": 0, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 5, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 10, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 15, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 20, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 25, "target_conditions": ["multiple_subjects"]},
    {"clip_id": "multi_subject", "frame_index": 34, "target_conditions": ["multiple_subjects"]},
    # challenges - difficult conditions
    {"clip_id": "challenges", "frame_index": 0, "target_conditions": ["challenging_clearish"]},
    {"clip_id": "challenges", "frame_index": 5, "target_conditions": ["challenging"]},
    {"clip_id": "challenges", "frame_index": 10, "target_conditions": ["blur"]},
    {"clip_id": "challenges", "frame_index": 15, "target_conditions": ["blur"]},
    {"clip_id": "challenges", "frame_index": 20, "target_conditions": ["dark_low_illumination"]},
    {"clip_id": "challenges", "frame_index": 25, "target_conditions": ["dark_low_illumination"]},
    {"clip_id": "challenges", "frame_index": 29, "target_conditions": ["small_face_candidate"]},
    {"clip_id": "challenges", "frame_index": 30, "target_conditions": ["occlusion"]},
    {"clip_id": "challenges", "frame_index": 35, "target_conditions": ["occlusion"]},
    {"clip_id": "challenges", "frame_index": 39, "target_conditions": ["occlusion_boundary"]},
    {"clip_id": "challenges", "frame_index": 40, "target_conditions": ["no_face_boundary"]},
    {"clip_id": "challenges", "frame_index": 45, "target_conditions": ["no_face"]},
    {"clip_id": "challenges", "frame_index": 50, "target_conditions": ["no_face"]},
    {"clip_id": "challenges", "frame_index": 54, "target_conditions": ["no_face"]},
    # no_face - negatives
    {"clip_id": "no_face", "frame_index": 0, "target_conditions": ["no_face"]},
    {"clip_id": "no_face", "frame_index": 5, "target_conditions": ["no_face"]},
    {"clip_id": "no_face", "frame_index": 10, "target_conditions": ["no_face"]},
    {"clip_id": "no_face", "frame_index": 15, "target_conditions": ["no_face"]},
    {"clip_id": "no_face", "frame_index": 19, "target_conditions": ["no_face"]},
]


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Overwrite selected-frames-manifest.json and extracted PNGs")
    args = ap.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    videos = manifest["videos"]
    fps_default = float(manifest.get("fps", 10))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    if SELECTION_PATH.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing {SELECTION_PATH}; use --force if intended.")
    entries = []
    for item in SELECTED:
        clip_id = item["clip_id"]
        frame_index = int(item["frame_index"])
        v = videos[clip_id]
        frame_count = int(v["frame_count"])
        if frame_index < 0 or frame_index >= frame_count:
            raise SystemExit(f"Invalid frame {clip_id}:{frame_index}")
        src = ROOT / "data/datasets/synthetic/cv" / v["file"]
        cap = cv2.VideoCapture(str(src))
        if not cap.isOpened():
            raise SystemExit(f"Cannot open {src}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None:
            raise SystemExit(f"Cannot read {clip_id}:{frame_index}")
        h, w = frame.shape[:2]
        filename = f"{clip_id}__frame_{frame_index:06d}.png"
        out_path = FRAMES_DIR / filename
        if out_path.exists() and not args.force:
            raise SystemExit(f"Refusing to overwrite {out_path}")
        ok_write = cv2.imwrite(str(out_path), frame)
        if not ok_write:
            raise SystemExit(f"Failed to write {out_path}")
        png_bytes = out_path.read_bytes()
        ts_ms = (frame_index / fps_default) * 1000.0
        entries.append({
            "clip_id": clip_id,
            "clip_file": v["file"],
            "frame_index": frame_index,
            "timestamp_ms": round(ts_ms, 3),
            "frame_count": frame_count,
            "image_width": w,
            "image_height": h,
            "derived_image_path": str(out_path.relative_to(ROOT)),
            "derived_image_sha256": sha256_bytes(png_bytes),
            "source_video_path": str(src.relative_to(ROOT)),
            "target_conditions": item["target_conditions"],
            "manifest_labels": (v.get("labels") or {}).get(str(frame_index)),
            "notes": "Derived reference frame only; original video untouched.",
        })
    doc = {
        "schema_version": "1.0-pilot-selection",
        "task": "TASK-09",
        "dataset_id": "synthetic-cv",
        "source_manifest": "data/datasets/synthetic/cv/manifest.json",
        "selection_policy": "Deterministic stratified sampling; no consecutive redundancy except condition boundaries.",
        "total_selected_frames": len(entries),
        "frames": entries,
        "unavailable_conditions": [
            "Real CCTV noise/compression artifacts not represented (synthetic only)",
            "True extreme profile/back-of-head may be limited; annotate actual observed pose",
            "Large-crowd density beyond 2 subjects not represented"
        ],
        "safety": {
            "original_videos_modified": False,
            "auto_ground_truth_generated": False,
            "derived_frames_directory": "reports/ps04cctv-audit/annotations/frames"
        }
    }
    SELECTION_PATH.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {SELECTION_PATH} with {len(entries)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
