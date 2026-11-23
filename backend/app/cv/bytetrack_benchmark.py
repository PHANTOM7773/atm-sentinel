"""Isolated TASK 14 benchmark: ByteTrack-inspired tracker vs SimpleTracker.

No production wiring. Uses existing synthetic clips and YOLOX person detector in
temporary isolated output dirs. Does not persist embeddings/crops/DB rows.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2

from ..config import DATA_DIR
from .bytetrack_tracker import ByteTrackInspiredTracker
from .detection import YOLOXPersonDetector
from .tracking import SimpleTracker
from .types import PersonDetection

DEFAULT_SYNTHETIC_MANIFEST = DATA_DIR / "datasets" / "synthetic" / "cv" / "manifest.json"


@dataclass
class SeqMetrics:
    id_switches: int
    fragmentations: int
    track_count: int
    duplicate_active_ids: int
    frames: int


def _tracker_factory(name: str, **kwargs: Any) -> Any:
    if name == "simple":
        return SimpleTracker(
            iou_threshold=float(kwargs.get("iou_threshold", 0.3)),
            max_misses=int(kwargs.get("max_misses", 8)),
            min_hits=int(kwargs.get("min_hits", 2)),
        )
    if name == "bytetrack":
        return ByteTrackInspiredTracker(
            high_conf_threshold=float(kwargs.get("high_conf_threshold", 0.5)),
            low_conf_threshold=float(kwargs.get("low_conf_threshold", 0.1)),
            match_iou_threshold=float(kwargs.get("match_iou_threshold", 0.3)),
            second_match_iou_threshold=float(kwargs.get("second_match_iou_threshold", 0.2)),
            max_centroid_distance=float(kwargs.get("max_centroid_distance", 0.45)),
            max_misses=int(kwargs.get("max_misses", 8)),
            max_time_gap_seconds=kwargs.get("max_time_gap_seconds"),
            min_hits=int(kwargs.get("min_hits", 2)),
        )
    raise ValueError(f"unknown tracker {name}")


def evaluate_deterministic_sequence(sequence: list[list[PersonDetection]], tracker_name: str, **kwargs: Any) -> dict[str, Any]:
    tr = _tracker_factory(tracker_name, **kwargs)
    active_prev: dict[int, tuple[float, float, float, float]] = {}
    last_seen: dict[int, int] = {}
    id_switches = 0
    fragmentations = 0
    duplicate_active_ids = 0
    all_ids: set[int] = set()

    # id_switch proxy: if a detection near previous center gets different id in next frame
    prev_centers: dict[tuple[int, int], int] = {}
    for frame_idx, dets in enumerate(sequence):
        out = tr.update([PersonDetection(d.bbox, d.confidence) for d in dets], frame_number=frame_idx, timestamp=frame_idx * 0.1)
        tids = [int(d.track_id) for d in out if d.track_id is not None]
        duplicate_active_ids += max(0, len(tids) - len(set(tids)))
        curr_centers: dict[tuple[int, int], int] = {}
        for d in out:
            if d.track_id is None:
                continue
            tid = int(d.track_id)
            all_ids.add(tid)
            if tid in last_seen and frame_idx - last_seen[tid] > 1:
                fragmentations += 1
            last_seen[tid] = frame_idx
            cx = int((d.bbox[0] + d.bbox[2] / 2) // 20)
            cy = int((d.bbox[1] + d.bbox[3] / 2) // 20)
            key = (cx, cy)
            curr_centers[key] = tid
            if key in prev_centers and prev_centers[key] != tid:
                id_switches += 1
        prev_centers = curr_centers

    return {
        "tracker": tracker_name,
        "frames": len(sequence),
        "id_switches_proxy": id_switches,
        "fragmentations": fragmentations,
        "unique_track_ids": len(all_ids),
        "duplicate_active_ids": duplicate_active_ids,
    }


def deterministic_sequences() -> dict[str, list[list[PersonDetection]]]:
    # Synthetic in-memory sequences; not ground-truth CCTV.
    linear = [[PersonDetection((10 + i * 5, 20, 30, 60), 0.9)] for i in range(12)]
    occlusion = []
    for i in range(12):
        if 4 <= i <= 6:
            occlusion.append([PersonDetection((10 + i * 5, 20, 30, 60), 0.25)])  # low conf during occlusion
        else:
            occlusion.append([PersonDetection((10 + i * 5, 20, 30, 60), 0.9)])
    crossing = []
    for i in range(12):
        crossing.append([
            PersonDetection((10 + i * 8, 50, 30, 60), 0.9),
            PersonDetection((110 - i * 8, 55, 30, 60), 0.9),
        ])
    absent = [[PersonDetection((10 + i * 5, 20, 30, 60), 0.9)] for i in range(4)] + [[] for _ in range(3)] + [[PersonDetection((35, 20, 30, 60), 0.9)] for _ in range(4)]
    return {
        "linear_single_person": linear,
        "occlusion_low_conf": occlusion,
        "crossing_two_persons": crossing,
        "temporary_absence": absent,
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    videos = manifest.get("videos")
    entries: list[dict[str, Any]] = []
    if isinstance(videos, dict):
        for name, meta in videos.items():
            if not isinstance(meta, dict):
                continue
            # include challenge clips as separate entries
            if name == "challenges" and isinstance(meta, dict):
                for c in meta.get("clips", []) or []:
                    if isinstance(c, dict):
                        entries.append({
                            "name": str(c.get("name") or Path(str(c.get("file",""))).stem),
                            "file": c.get("file"),
                            "category": "challenges",
                            **c,
                        })
                continue
            entries.append({
                "name": str(meta.get("name") or name),
                "file": meta.get("file") or f"{name}.mp4",
                "category": str(meta.get("category") or name),
                **meta,
            })
    elif isinstance(videos, list):
        for meta in videos:
            if isinstance(meta, dict):
                entries.append(meta)
    elif isinstance(manifest.get("clips"), list):
        entries = [e for e in manifest["clips"] if isinstance(e, dict)]
    return entries


def _clip_path(entry: dict[str, Any]) -> Path:
    rel = entry.get("relative_path") or entry.get("path") or entry.get("file")
    if not rel:
        raise ValueError("manifest entry missing path")
    p = Path(str(rel))
    if p.is_absolute():
        return p
    # synthetic manifest stores files relative to synthetic CV dir
    candidate = DATA_DIR / "datasets" / "synthetic" / "cv" / p
    if candidate.exists():
        return candidate
    return (DATA_DIR / p)


def benchmark_synthetic_clips(
    *,
    manifest_path: Path = DEFAULT_SYNTHETIC_MANIFEST,
    clip_names: list[str] | None = None,
    max_frames: int = 30,
    frame_stride: int = 1,
) -> dict[str, Any]:
    manifest = _load_manifest(manifest_path)
    entries = _manifest_entries(manifest)
    if not entries:
        raise ValueError("unsupported manifest format")
    selected = []
    for e in entries:
        name = str(e.get("name") or e.get("clip_name") or Path(str(e.get("file", ""))).stem)
        if clip_names and name not in clip_names:
            continue
        selected.append(e)
    if clip_names is None:
        # bounded, reproducible default - existing synthetic clips
        want = {"subject_a_front", "subject_b_front", "subject_a_side", "subject_b_side"}
        selected = [e for e in entries if str(e.get("name")) in want]
    if not selected:
        raise ValueError("no clips selected")

    detector = YOLOXPersonDetector()
    results = []
    for entry in selected:
        clip = _clip_path(entry)
        cap = cv2.VideoCapture(str(clip))
        if not cap.isOpened():
            results.append({"clip": str(clip), "error": "open_failed"})
            continue
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 10.0
        trackers = {
            "simple": _tracker_factory("simple"),
            "bytetrack": _tracker_factory("bytetrack"),
        }
        stats = {
            k: {"frames": 0, "detections": 0, "id_switches_proxy": 0, "fragmentations": 0, "unique_ids": set(), "last_seen": {}, "prev_centers": {}, "runtime_ms": 0.0}
            for k in trackers
        }
        frame_idx = 0
        analyzed = 0
        while analyzed < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if frame_idx % max(1, frame_stride) != 0:
                frame_idx += 1
                continue
            dets = detector.detect(frame)
            ts = frame_idx / fps
            for name, tr in trackers.items():
                t0 = time.perf_counter()
                out = tr.update([PersonDetection(d.bbox, d.confidence) for d in dets], frame_number=frame_idx, timestamp=ts)
                stats[name]["runtime_ms"] += (time.perf_counter() - t0) * 1000
                stats[name]["frames"] += 1
                stats[name]["detections"] += len(out)
                curr = {}
                for d in out:
                    if d.track_id is None:
                        continue
                    tid = int(d.track_id)
                    stats[name]["unique_ids"].add(tid)
                    ls = stats[name]["last_seen"].get(tid)
                    if ls is not None and frame_idx - ls > 1:
                        stats[name]["fragmentations"] += 1
                    stats[name]["last_seen"][tid] = frame_idx
                    key = (int((d.bbox[0] + d.bbox[2] / 2) // 20), int((d.bbox[1] + d.bbox[3] / 2) // 20))
                    curr[key] = tid
                    prev = stats[name]["prev_centers"].get(key)
                    if prev is not None and prev != tid:
                        stats[name]["id_switches_proxy"] += 1
                stats[name]["prev_centers"] = curr
            analyzed += 1
            frame_idx += 1
        cap.release()
        clip_result = {
            "clip": str(entry.get("name")),
            "path": str(clip.relative_to(DATA_DIR)) if str(clip).startswith(str(DATA_DIR)) else str(clip),
            "analyzed_frames": analyzed,
            "fps": fps,
            "trackers": {},
        }
        for name, s in stats.items():
            clip_result["trackers"][name] = {
                "frames": s["frames"],
                "detections": s["detections"],
                "unique_track_ids": len(s["unique_ids"]),
                "id_switches_proxy": s["id_switches_proxy"],
                "fragmentations": s["fragmentations"],
                "tracker_runtime_ms": round(s["runtime_ms"], 3),
            }
        results.append(clip_result)
    return {
        "manifest": str(manifest_path.relative_to(DATA_DIR)) if str(manifest_path).startswith(str(DATA_DIR)) else str(manifest_path),
        "max_frames": max_frames,
        "frame_stride": frame_stride,
        "clips": results,
        "notes": [
            "Synthetic clip benchmark; no person/track ground truth.",
            "id_switches_proxy and fragmentations are proxy metrics based on spatial bins and track continuity, not annotated ID switches.",
            "YOLOX person detector reused from existing local model/runtime.",
        ],
    }


def run_task14_benchmark() -> dict[str, Any]:
    seqs = deterministic_sequences()
    deterministic = {}
    for name, seq in seqs.items():
        deterministic[name] = {
            "simple": evaluate_deterministic_sequence(seq, "simple"),
            "bytetrack": evaluate_deterministic_sequence(seq, "bytetrack"),
        }
    synthetic = benchmark_synthetic_clips()
    return {
        "task": "TASK-14",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "deterministic_sequences": deterministic,
        "synthetic_clip_benchmark": synthetic,
        "limitations": [
            "No person bounding-box or identity ground truth exists; IDF1/MOTA/HOTA are NOT_ASSESSABLE.",
            "Synthetic clips are not representative of real CCTV; no real-world generalization claim.",
            "Crossing identity preservation on synthetic detections is a stress proxy, not annotated ground truth.",
        ],
    }
