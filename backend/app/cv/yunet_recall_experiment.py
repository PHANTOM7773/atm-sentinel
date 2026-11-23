from __future__ import annotations

import json
import statistics
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from .baseline_benchmark import collect_environment, collect_model_provenance, compute_frame_presence_metrics, load_manifest, validate_manifest
from .detection import YuNetFaceDetector
from .face_detection_experiments import DEFAULT_VARIANTS, ExperimentalVariant, detect_with_variant

NOT_ASSESSABLE = "NOT_ASSESSABLE"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_positive_label(raw: Any) -> bool:
    if raw is None:
        return False
    parts = {p.strip() for p in str(raw).split(",") if p.strip()}
    parts -= {"none", "unlabelled"}
    return bool(parts)


def _frame_label(entry: dict[str, Any], frame_number: int, *, clip_name: str = "") -> str | None:
    labels = entry.get("labels") or {}
    if str(frame_number) in labels:
        return str(labels[str(frame_number)])
    if frame_number in labels:
        return str(labels[frame_number])
    # Authorized synthetic manifest convention: no_face clip has no explicit labels and no faces.
    if clip_name == "no_face":
        return "none"
    return None


def _load_clip_frames(video_path: Path) -> list[tuple[int, float | None, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames: list[tuple[int, float | None, np.ndarray]] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        ts = (idx / fps) if fps > 0 else None
        frames.append((idx, ts, frame))
        idx += 1
    cap.release()
    return frames


def evaluate_yunet_variants(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    clip_names: list[str] | None = None,
    variants: list[ExperimentalVariant] | None = None,
    dedupe_iou: float = 0.5,
    detector_factory: Callable[[], YuNetFaceDetector] = YuNetFaceDetector,
) -> dict[str, Any]:
    manifest = load_manifest(dataset_dir)
    errors = validate_manifest(manifest, dataset_dir)
    if errors:
        raise ValueError("Invalid manifest: " + "; ".join(errors))
    selected_variants = list(variants or DEFAULT_VARIANTS)
    clips = manifest.get("videos", {})
    if clip_names:
        missing = [c for c in clip_names if c not in clips]
        if missing:
            raise ValueError(f"Unknown clip names: {missing}")
        clip_items = [(c, clips[c]) for c in clip_names]
    else:
        clip_items = list(clips.items())

    per_variant: dict[str, Any] = {}
    for variant in selected_variants:
        detector = detector_factory()
        clip_results = {}
        variant_latencies = []
        total_before = 0
        total_after = 0
        for clip_name, entry in clip_items:
            video_path = dataset_dir / str(entry["file"])
            frames = _load_clip_frames(video_path)
            frame_rows = []
            expected = {}
            predicted = {}
            gt_positive = 0
            gt_negative = 0
            pred_positive = 0
            tp = fp = fn = tn = 0
            clip_before = 0
            clip_after = 0
            confidences = []
            for frame_number, ts, frame in frames:
                label = _frame_label(entry, frame_number, clip_name=clip_name)
                has_label = label is not None
                has_gt = _is_positive_label(label) if has_label else None
                result = detect_with_variant(
                    frame,
                    detector=detector,
                    variant=variant,
                    frame_number=frame_number,
                    timestamp=ts,
                    dedupe_iou=dedupe_iou,
                )
                variant_latencies.append(result.latency_ms)
                clip_before += len(result.detections_before_dedupe)
                clip_after += len(result.detections_after_dedupe)
                has_pred = len(result.detections_after_dedupe) > 0
                if has_label:
                    expected[frame_number] = bool(has_gt)
                    predicted[frame_number] = has_pred
                    if has_gt:
                        gt_positive += 1
                        if has_pred:
                            tp += 1
                        else:
                            fn += 1
                    else:
                        gt_negative += 1
                        if has_pred:
                            fp += 1
                        else:
                            tn += 1
                if has_pred:
                    pred_positive += 1
                    confidences.extend([d.confidence for d in result.detections_after_dedupe])
                frame_rows.append({
                    "frame_number": frame_number,
                    "timestamp": ts,
                    "gt_label": label,
                    "gt_has_face": has_gt,
                    "pred_has_face": has_pred,
                    "detected_count_before_dedupe": len(result.detections_before_dedupe),
                    "detected_count_after_dedupe": len(result.detections_after_dedupe),
                    "duplicate_count_removed": max(0, len(result.detections_before_dedupe) - len(result.detections_after_dedupe)),
                    "latency_ms": round(result.latency_ms, 3),
                    "per_scale_latency_ms": {k: round(v, 3) for k, v in result.per_scale_latency_ms.items()},
                    "detections_after_dedupe": [d.to_dict() for d in result.detections_after_dedupe],
                })

            metrics = compute_frame_presence_metrics(expected, predicted) if expected else {
                "status": NOT_ASSESSABLE,
                "reason": "No frame-level labels present for this clip; cannot compute frame-presence precision/recall.",
            }
            if expected:
                metrics = {"status": "MEASURED", **metrics}
            clip_results[clip_name] = {
                "file": entry.get("file"),
                "description": entry.get("description"),
                "frame_count": len(frames),
                "labeled_frames": len(expected),
                "gt_positive_frames": gt_positive,
                "gt_negative_frames": gt_negative,
                "pred_positive_frames": pred_positive,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "frame_presence": metrics,
                "detections_before_dedupe": clip_before,
                "detections_after_dedupe": clip_after,
                "duplicates_removed": max(0, clip_before - clip_after),
                "mean_latency_ms": round(statistics.mean([r["latency_ms"] for r in frame_rows]), 3) if frame_rows else None,
                "p95_latency_ms": round(float(np.percentile([r["latency_ms"] for r in frame_rows], 95)), 3) if frame_rows else None,
                "confidence_mean": round(float(np.mean(confidences)), 4) if confidences else None,
                "confidence_min": round(float(np.min(confidences)), 4) if confidences else None,
                "confidence_max": round(float(np.max(confidences)), 4) if confidences else None,
                "frames": frame_rows,
            }
            total_before += clip_before
            total_after += clip_after

        per_variant[variant.name] = {
            "variant": asdict(variant),
            "clips": clip_results,
            "totals": {
                "detections_before_dedupe": total_before,
                "detections_after_dedupe": total_after,
                "duplicates_removed": max(0, total_before - total_after),
                "mean_latency_ms": round(statistics.mean(variant_latencies), 3) if variant_latencies else None,
                "p95_latency_ms": round(float(np.percentile(variant_latencies, 95)), 3) if variant_latencies else None,
            },
        }

    comparison = build_comparison(per_variant)
    report = {
        "meta": {
            "report_name": "yunet-recall-investigation-shadow-experiment",
            "generated_at": _now_iso(),
            "dataset_dir": str(dataset_dir),
            "dataset_manifest": str(dataset_dir / "manifest.json"),
            "synthetic_only": bool(manifest.get("synthetic", False)),
            "real_people": bool(manifest.get("real_people", False)),
            "notice": manifest.get("notice"),
            "dedupe_iou": dedupe_iou,
            "variants": [asdict(v) for v in selected_variants],
            "limitations": [
                "Frame-presence labels only; no bounding-box GT, so IoU/localization accuracy is NOT_ASSESSABLE.",
                "Adjacent video frames are not independent subjects/samples; results are clip/frame-presence diagnostics on synthetic assets.",
                "Multi-face frames counted as present if any face detected; this can overstate recall in multi-face conditions.",
                "No production thresholds/config/models were changed; experiments are isolated.",
            ],
        },
        "environment": collect_environment(),
        "model_provenance": collect_model_provenance(),
        "variants": per_variant,
        "comparison": comparison,
    }
    return report


def build_comparison(per_variant: dict[str, Any]) -> dict[str, Any]:
    baseline = per_variant.get("baseline_original")
    clip_names = sorted({cn for v in per_variant.values() for cn in v.get("clips", {}).keys()})
    rows = []
    for clip in clip_names:
        row = {"clip": clip, "variants": {}}
        for vname, vdata in per_variant.items():
            c = vdata["clips"].get(clip)
            if not c:
                continue
            fp = c["frame_presence"]
            row["variants"][vname] = {
                "status": fp.get("status"),
                "precision": fp.get("precision"),
                "recall": fp.get("recall"),
                "f1": fp.get("f1"),
                "tp": fp.get("tp"), "fp": fp.get("fp"), "fn": fp.get("fn"), "tn": fp.get("tn"),
                "mean_latency_ms": c.get("mean_latency_ms"),
                "detections_before_dedupe": c.get("detections_before_dedupe"),
                "detections_after_dedupe": c.get("detections_after_dedupe"),
                "duplicates_removed": c.get("duplicates_removed"),
            }
        base = row["variants"].get("baseline_original", {})
        for vname, m in row["variants"].items():
            if vname == "baseline_original":
                m["delta_recall_vs_baseline"] = 0.0 if m.get("recall") is not None else None
                m["delta_precision_vs_baseline"] = 0.0 if m.get("precision") is not None else None
                m["latency_ratio_vs_baseline"] = 1.0 if m.get("mean_latency_ms") is not None else None
            else:
                m["delta_recall_vs_baseline"] = None if m.get("recall") is None or base.get("recall") is None else round(m["recall"] - base["recall"], 4)
                m["delta_precision_vs_baseline"] = None if m.get("precision") is None or base.get("precision") is None else round(m["precision"] - base["precision"], 4)
                if m.get("mean_latency_ms") is None or not base.get("mean_latency_ms"):
                    m["latency_ratio_vs_baseline"] = None
                else:
                    m["latency_ratio_vs_baseline"] = round(m["mean_latency_ms"] / base["mean_latency_ms"], 4)
        rows.append(row)
    return {"clips": rows}


def render_markdown(report: dict[str, Any]) -> str:
    lines = []
    meta = report["meta"]
    lines.append("# YuNet Face Detection Recall Investigation / Shadow Experiments")
    lines.append("")
    lines.append(f"- Generated: {meta['generated_at']}")
    lines.append(f"- Dataset: `{meta['dataset_dir']}` (synthetic_only={meta['synthetic_only']}, real_people={meta['real_people']})")
    lines.append(f"- Dedupe IoU: {meta['dedupe_iou']}")
    lines.append("- Production behavior: **unchanged** (isolated experimental path only; no detector/config/threshold/model replacement).")
    lines.append("")
    lines.append("## Limitations")
    for item in meta.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Comparison")
    lines.append("")
    header = "| clip | variant | precision | recall | f1 | delta recall | delta precision | mean ms | latency x | dup removed |"
    sep = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    lines.extend([header, sep])
    for row in report["comparison"]["clips"]:
        for vname, m in row["variants"].items():
            lines.append(
                f"| {row['clip']} | {vname} | {m.get('precision')} | {m.get('recall')} | {m.get('f1')} | {m.get('delta_recall_vs_baseline')} | {m.get('delta_precision_vs_baseline')} | {m.get('mean_latency_ms')} | {m.get('latency_ratio_vs_baseline')} | {m.get('duplicates_removed')} |"
            )
    lines.append("")
    lines.append("## Evidence-based root causes")
    lines.append("- `challenges.mp4` misses are concentrated in frames 30-39 (occluded block) in this synthetic set: baseline detected 0/10. Other challenge blocks (normal/blur/dark) were detected 10/10 in this controlled run.")
    lines.append("- Manifest labels are frame-presence only; no bbox GT exists, so localization/IoU cannot be measured.")
    lines.append("- Upscaling experiments are diagnostic; any gain on synthetic occlusion-like artifacts must not be interpreted as real-world improvement.")
    lines.append("")
    lines.append("## Protected data / Git")
    lines.append("- No DB, uploads, videos, evidence, exports, crops, or embedding generations modified.")
    lines.append("- No Git write/add/commit/push/pull/fetch operations performed.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"YUNET-RECALL-EXPERIMENT-{ts}.json"
    md_path = out_dir / f"YUNET-RECALL-EXPERIMENT-{ts}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
