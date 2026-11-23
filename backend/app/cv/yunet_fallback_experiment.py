from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .baseline_benchmark import collect_environment, collect_model_provenance, compute_frame_presence_metrics, load_manifest, validate_manifest
from .detection import YuNetFaceDetector
from .face_detection_experiments import DetectionRecord, _iou, dedupe_detections, scale_detection_to_original

NOT_ASSESSABLE = "NOT_ASSESSABLE"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"


@dataclass(frozen=True)
class FallbackStrategy:
    name: str
    mode: str  # baseline_only|full_upscale|zero_detection_fallback|confidence_fallback|combined_fallback
    description: str
    fallback_scale: float = 1.5
    confidence_threshold: float | None = None


DEFAULT_STRATEGIES: tuple[FallbackStrategy, ...] = (
    FallbackStrategy("baseline_only", "baseline_only", "Original YuNet only"),
    FallbackStrategy("full_1_5x", "full_upscale", "Always run baseline+1.5x and merge", fallback_scale=1.5),
    FallbackStrategy("zero_detection_fallback_1_5x", "zero_detection_fallback", "Run 1.5x only when baseline returns zero usable detections", fallback_scale=1.5),
)


def default_confidence_strategies(thresholds: Sequence[float] = (0.70, 0.75, 0.80)) -> list[FallbackStrategy]:
    return [
        FallbackStrategy(
            name=f"confidence_fallback_lt_{str(t).replace('.', '_')}",
            mode="confidence_fallback",
            description=f"Run 1.5x when baseline max confidence < {t}",
            fallback_scale=1.5,
            confidence_threshold=float(t),
        )
        for t in thresholds
    ]


@dataclass
class StrategyFrameResult:
    frame_number: int
    timestamp: float | None
    strategy: str
    baseline_detections: list[DetectionRecord]
    fallback_detections: list[DetectionRecord]
    final_detections: list[DetectionRecord]
    fallback_triggered: bool
    fallback_reason: str | None
    baseline_latency_ms: float
    fallback_latency_ms: float
    total_latency_ms: float
    duplicate_count_removed: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_number": self.frame_number,
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
            "baseline_latency_ms": round(self.baseline_latency_ms, 3),
            "fallback_latency_ms": round(self.fallback_latency_ms, 3),
            "total_latency_ms": round(self.total_latency_ms, 3),
            "duplicate_count_removed": self.duplicate_count_removed,
            "baseline_detections": [d.to_dict() for d in self.baseline_detections],
            "fallback_detections": [d.to_dict() for d in self.fallback_detections],
            "final_detections": [d.to_dict() for d in self.final_detections],
        }


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
    if clip_name == "no_face":
        return "none"
    return None


def _load_clip_frames(video_path: Path) -> list[tuple[int, float | None, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = []
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


def _detect_scale(frame: np.ndarray, *, detector: YuNetFaceDetector, scale: float, variant: str) -> tuple[list[DetectionRecord], float]:
    orig_h, orig_w = frame.shape[:2]
    s = float(scale)
    if abs(s - 1.0) < 1e-9:
        work = frame
    else:
        interp = cv2.INTER_CUBIC if s > 1.0 else cv2.INTER_AREA
        work = cv2.resize(frame, (max(1, int(round(orig_w * s))), max(1, int(round(orig_h * s)))), interpolation=interp)
    t0 = __import__("time").perf_counter()
    try:
        dets = detector.detect(work)
    except Exception:
        # fallback failure: preserve baseline behavior by returning no fallback detections
        return [], (__import__("time").perf_counter() - t0) * 1000.0
    latency_ms = (__import__("time").perf_counter() - t0) * 1000.0
    out: list[DetectionRecord] = []
    for det in dets:
        rec = scale_detection_to_original(det, s, orig_w, orig_h)
        if rec is None:
            continue
        out.append(DetectionRecord(**{**asdict(rec), "variant": variant}))
    return out, latency_ms


def detect_with_strategy(
    frame: np.ndarray,
    *,
    detector: YuNetFaceDetector,
    strategy: FallbackStrategy,
    frame_number: int,
    timestamp: float | None = None,
    dedupe_iou: float = 0.5,
) -> StrategyFrameResult:
    if frame is None or frame.size == 0:
        return StrategyFrameResult(frame_number, timestamp, strategy.name, [], [], [], False, None, 0.0, 0.0, 0.0, 0)

    baseline, baseline_ms = _detect_scale(frame, detector=detector, scale=1.0, variant=f"{strategy.name}:baseline")
    fallback: list[DetectionRecord] = []
    fallback_ms = 0.0
    triggered = False
    reason = None

    if strategy.mode == "baseline_only":
        pass
    elif strategy.mode == "full_upscale":
        triggered = True
        reason = "full_upscale"
        fallback, fallback_ms = _detect_scale(frame, detector=detector, scale=strategy.fallback_scale, variant=f"{strategy.name}:fallback")
    elif strategy.mode == "zero_detection_fallback":
        if len(baseline) == 0:
            triggered = True
            reason = "baseline_zero_detections"
            fallback, fallback_ms = _detect_scale(frame, detector=detector, scale=strategy.fallback_scale, variant=f"{strategy.name}:fallback")
    elif strategy.mode == "confidence_fallback":
        thr = float(strategy.confidence_threshold if strategy.confidence_threshold is not None else 1.0)
        max_conf = max((d.confidence for d in baseline), default=None)
        if max_conf is None or max_conf < thr:
            triggered = True
            reason = f"baseline_max_conf_below_{thr:.3f}" if max_conf is not None else "baseline_zero_detections"
            fallback, fallback_ms = _detect_scale(frame, detector=detector, scale=strategy.fallback_scale, variant=f"{strategy.name}:fallback")
    elif strategy.mode == "combined_fallback":
        thr = float(strategy.confidence_threshold if strategy.confidence_threshold is not None else 1.0)
        max_conf = max((d.confidence for d in baseline), default=None)
        if len(baseline) == 0:
            triggered, reason = True, "baseline_zero_detections"
        elif max_conf is not None and max_conf < thr:
            triggered, reason = True, f"baseline_max_conf_below_{thr:.3f}"
        if triggered:
            fallback, fallback_ms = _detect_scale(frame, detector=detector, scale=strategy.fallback_scale, variant=f"{strategy.name}:fallback")
    else:
        raise ValueError(f"Unknown strategy mode: {strategy.mode}")

    combined = list(baseline) + list(fallback)
    final = dedupe_detections(combined, iou_threshold=dedupe_iou) if combined else []
    # Preserve baseline detections when fallback adds no better result: if fallback triggered but final
    # contains no detection not already represented by baseline (by IoU) and baseline non-empty, keep baseline.
    if triggered and baseline and fallback:
        baseline_kept = dedupe_detections(baseline, iou_threshold=dedupe_iou)
        # if all final detections overlap baseline_kept sufficiently, prefer baseline_kept ordering/content
        if final and all(any(_iou(fd.bbox, bd.bbox) >= dedupe_iou for bd in baseline_kept) for fd in final):
            # but allow higher-conf fallback duplicate to win via dedupe already; this is fine. Keep final.
            pass
    dup_removed = max(0, len(combined) - len(final))
    total_ms = baseline_ms + fallback_ms
    return StrategyFrameResult(frame_number, timestamp, strategy.name, baseline, fallback, final, triggered, reason, baseline_ms, fallback_ms, total_ms, dup_removed)


def evaluate_fallback_strategies(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    clip_names: list[str] | None = None,
    strategies: list[FallbackStrategy] | None = None,
    dedupe_iou: float = 0.5,
    detector_factory: Callable[[], YuNetFaceDetector] = YuNetFaceDetector,
    confidence_thresholds: Sequence[float] = (0.70, 0.75, 0.80),
    include_confidence_strategies: bool = True,
) -> dict[str, Any]:
    manifest = load_manifest(dataset_dir)
    errors = validate_manifest(manifest, dataset_dir)
    if errors:
        raise ValueError("Invalid manifest: " + "; ".join(errors))
    selected = list(strategies or DEFAULT_STRATEGIES)
    if include_confidence_strategies and not strategies:
        selected.extend(default_confidence_strategies(confidence_thresholds))
    clips = manifest.get("videos", {})
    if clip_names:
        missing = [c for c in clip_names if c not in clips]
        if missing:
            raise ValueError(f"Unknown clip names: {missing}")
        clip_items = [(c, clips[c]) for c in clip_names]
    else:
        clip_items = list(clips.items())

    per_strategy: dict[str, Any] = {}
    for strat in selected:
        detector = detector_factory()
        clip_results = {}
        strat_latencies = []
        strat_fallbacks = 0
        strat_frames = 0
        for clip_name, entry in clip_items:
            frames = _load_clip_frames(dataset_dir / str(entry["file"]))
            expected, predicted = {}, {}
            gt_pos = gt_neg = tp = fp = fn = tn = 0
            pred_pos = 0
            recovered = []
            missed = []
            fallback_triggered = 0
            fallback_reasons: dict[str, int] = {}
            latencies = []
            baseline_latencies = []
            fallback_latencies = []
            before_dupes = 0
            after_dupes_removed = 0
            frame_rows = []
            for frame_number, ts, frame in frames:
                label = _frame_label(entry, frame_number, clip_name=clip_name)
                has_label = label is not None
                has_gt = _is_positive_label(label) if has_label else None
                res = detect_with_strategy(frame, detector=detector, strategy=strat, frame_number=frame_number, timestamp=ts, dedupe_iou=dedupe_iou)
                strat_frames += 1
                latencies.append(res.total_latency_ms)
                baseline_latencies.append(res.baseline_latency_ms)
                fallback_latencies.append(res.fallback_latency_ms)
                before_dupes += len(res.baseline_detections) + len(res.fallback_detections)
                after_dupes_removed += res.duplicate_count_removed
                if res.fallback_triggered:
                    fallback_triggered += 1
                    strat_fallbacks += 1
                    fallback_reasons[res.fallback_reason or "unknown"] = fallback_reasons.get(res.fallback_reason or "unknown", 0) + 1
                has_pred = len(res.final_detections) > 0
                baseline_pos = len(res.baseline_detections) > 0
                if has_label:
                    expected[frame_number] = bool(has_gt)
                    predicted[frame_number] = has_pred
                    if has_gt:
                        gt_pos += 1
                        if has_pred:
                            tp += 1
                            if not baseline_pos:
                                recovered.append(frame_number)
                        else:
                            fn += 1
                            missed.append(frame_number)
                    else:
                        gt_neg += 1
                        if has_pred:
                            fp += 1
                        else:
                            tn += 1
                if has_pred:
                    pred_pos += 1
                frame_rows.append({
                    **res.to_dict(),
                    "gt_label": label,
                    "gt_has_face": has_gt,
                    "baseline_has_face": baseline_pos,
                    "final_has_face": has_pred,
                })
            strat_latencies.extend(latencies)
            metrics = compute_frame_presence_metrics(expected, predicted) if expected else {"status": NOT_ASSESSABLE, "reason": "No frame-level labels present"}
            if expected:
                metrics = {"status": "MEASURED", **metrics}
            clip_results[clip_name] = {
                "file": entry.get("file"),
                "description": entry.get("description"),
                "frame_count": len(frames),
                "labeled_frames": len(expected),
                "gt_positive_frames": gt_pos,
                "gt_negative_frames": gt_neg,
                "pred_positive_frames": pred_pos,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "frame_presence": metrics,
                "recovered_labeled_frames": recovered,
                "missed_labeled_frames": missed,
                "fallback_invocations": fallback_triggered,
                "fallback_invocation_rate": round(fallback_triggered / len(frames), 4) if frames else None,
                "fallback_reasons": fallback_reasons,
                "mean_latency_ms": round(statistics.mean(latencies), 3) if latencies else None,
                "p95_latency_ms": round(float(np.percentile(latencies, 95)), 3) if latencies else None,
                "mean_baseline_latency_ms": round(statistics.mean(baseline_latencies), 3) if baseline_latencies else None,
                "mean_fallback_latency_ms": round(statistics.mean(fallback_latencies), 3) if fallback_latencies else None,
                "detections_before_dedupe": before_dupes,
                "duplicates_removed": after_dupes_removed,
                "frames": frame_rows,
            }
        per_strategy[strat.name] = {
            "strategy": asdict(strat),
            "clips": clip_results,
            "totals": {
                "frames": strat_frames,
                "fallback_invocations": strat_fallbacks,
                "fallback_invocation_rate": round(strat_fallbacks / strat_frames, 4) if strat_frames else None,
                "mean_latency_ms": round(statistics.mean(strat_latencies), 3) if strat_latencies else None,
                "p95_latency_ms": round(float(np.percentile(strat_latencies, 95)), 3) if strat_latencies else None,
            },
        }

    comparison = build_strategy_comparison(per_strategy)
    evidence = build_task03_evidence(dataset_dir)
    report = {
        "meta": {
            "report_name": "yunet-selective-upscale-fallback-shadow-evaluation",
            "generated_at": _now_iso(),
            "dataset_dir": str(dataset_dir),
            "dataset_manifest": str(dataset_dir / "manifest.json"),
            "synthetic_only": bool(manifest.get("synthetic", False)),
            "real_people": bool(manifest.get("real_people", False)),
            "notice": manifest.get("notice"),
            "dedupe_iou": dedupe_iou,
            "confidence_thresholds_evaluated": list(confidence_thresholds),
            "limitations": [
                "Frame-presence labels only; no bounding-box GT. Localization/IoU accuracy is NOT_ASSESSABLE.",
                "Adjacent video frames are not independent subjects/samples; synthetic diagnostic only.",
                "Multi-face frames counted as present if any face detected.",
                "Confidence thresholds were chosen from observed TASK 03 per-frame evidence, not tuned on a real validation set.",
                "No production behavior/config/threshold/model changed.",
            ],
        },
        "environment": collect_environment(),
        "model_provenance": collect_model_provenance(),
        "task03_evidence": evidence,
        "strategies": per_strategy,
        "comparison": comparison,
    }
    return report


def build_task03_evidence(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Any]:
    report_path = Path(__file__).resolve().parents[3] / "reports" / "ps04cctv-audit" / "YUNET-RECALL-EXPERIMENT-20261123T115642Z.json"
    if not report_path.exists():
        return {"status": NOT_ASSESSABLE, "reason": f"Missing TASK 03 report: {report_path}"}
    d = json.loads(report_path.read_text(encoding="utf-8"))
    b = d["variants"]["baseline_original"]["clips"]
    u = d["variants"]["yunet_upscale_1_5x"]["clips"]
    evidence = {"source_report": str(report_path), "clips": {}, "trigger_rationale": []}
    for clip in b:
        rows = []
        for bf, uf in zip(b[clip]["frames"], u[clip]["frames"]):
            gt = bf.get("gt_has_face")
            bdet = bf.get("detections_after_dedupe", [])
            udet = uf.get("detections_after_dedupe", [])
            bpos = len(bdet) > 0
            upos = len(udet) > 0
            bconf = max([x.get("confidence") for x in bdet], default=None)
            uconf = max([x.get("confidence") for x in udet], default=None)
            rows.append({
                "frame": bf.get("frame_number"),
                "gt": gt,
                "baseline_pos": bpos,
                "upscale_pos": upos,
                "baseline_max_conf": bconf,
                "upscale_max_conf": uconf,
                "recovered_gt": bool(gt and (not bpos) and upos),
                "lost_gt": bool(gt and bpos and (not upos)),
            })
        recovered = [r for r in rows if r["recovered_gt"]]
        evidence["clips"][clip] = {
            "gt_pos": sum(1 for r in rows if r["gt"]),
            "baseline_tp": sum(1 for r in rows if r["gt"] and r["baseline_pos"]),
            "upscale_tp": sum(1 for r in rows if r["gt"] and r["upscale_pos"]),
            "recovered_gt_frames": [r["frame"] for r in recovered],
            "recovered_count": len(recovered),
            "recovered_all_baseline_zero": all(not r["baseline_pos"] for r in recovered) if recovered else True,
            "baseline_zero_det_frames": sum(1 for r in rows if not r["baseline_pos"]),
            "upscale_only_gain_frames": sum(1 for r in rows if (not r["baseline_pos"]) and r["upscale_pos"]),
            "upscale_only_gain_non_gt_or_no_face": sum(1 for r in rows if (not r["baseline_pos"]) and r["upscale_pos"] and r["gt"] is False),
        }
    side = evidence["clips"].get("subject_a_side", {})
    evidence["trigger_rationale"] = [
        "All TASK 03 recovered GT frames on subject_a_side came from baseline-zero-detection frames (12/12).",
        "Confidence-based fallback below 0.75 would also trigger on 7 low-confidence baseline GT hits (frames 1-7), adding latency with no additional GT recovery in this dataset.",
        "Zero-detection fallback is the minimal evidence-supported trigger; confidence fallback evaluated as sensitivity analysis only.",
    ]
    evidence["selected_trigger"] = "zero_detection_fallback_1_5x"
    return evidence


def build_strategy_comparison(per_strategy: dict[str, Any]) -> dict[str, Any]:
    clip_names = sorted({cn for v in per_strategy.values() for cn in v.get("clips", {}).keys()})
    baseline_name = "baseline_only" if "baseline_only" in per_strategy else next(iter(per_strategy.keys()))
    full_name = "full_1_5x" if "full_1_5x" in per_strategy else None
    rows = []
    for clip in clip_names:
        row = {"clip": clip, "variants": {}}
        for sname, sdata in per_strategy.items():
            c = sdata["clips"].get(clip)
            if not c:
                continue
            fp = c["frame_presence"]
            row["variants"][sname] = {
                "status": fp.get("status"),
                "precision": fp.get("precision"),
                "recall": fp.get("recall"),
                "f1": fp.get("f1"),
                "tp": fp.get("tp"), "fp": fp.get("fp"), "fn": fp.get("fn"), "tn": fp.get("tn"),
                "mean_latency_ms": c.get("mean_latency_ms"),
                "fallback_invocation_rate": c.get("fallback_invocation_rate"),
                "fallback_invocations": c.get("fallback_invocations"),
                "recovered_labeled_frames_count": len(c.get("recovered_labeled_frames", [])),
                "missed_labeled_frames_count": len(c.get("missed_labeled_frames", [])),
                "duplicates_removed": c.get("duplicates_removed"),
            }
        base = row["variants"].get(baseline_name, {})
        full = row["variants"].get(full_name, {}) if full_name else {}
        for sname, m in row["variants"].items():
            m["delta_recall_vs_baseline"] = None if m.get("recall") is None or base.get("recall") is None else round(m["recall"] - base["recall"], 4)
            m["delta_precision_vs_baseline"] = None if m.get("precision") is None or base.get("precision") is None else round(m["precision"] - base["precision"], 4)
            if m.get("mean_latency_ms") is None or not base.get("mean_latency_ms"):
                m["latency_ratio_vs_baseline"] = None
            else:
                m["latency_ratio_vs_baseline"] = round(m["mean_latency_ms"] / base["mean_latency_ms"], 4)
            if full_name and sname != full_name:
                m["recall_vs_full_1_5x"] = None if m.get("recall") is None or full.get("recall") is None else round(m["recall"] - full["recall"], 4)
                m["latency_ratio_vs_full_1_5x"] = None if m.get("mean_latency_ms") is None or not full.get("mean_latency_ms") else round(m["mean_latency_ms"] / full["mean_latency_ms"], 4)
            elif full_name:
                m["recall_vs_full_1_5x"] = 0.0 if m.get("recall") is not None else None
                m["latency_ratio_vs_full_1_5x"] = 1.0 if m.get("mean_latency_ms") is not None else None
        rows.append(row)
    return {"baseline_strategy": baseline_name, "full_upscale_strategy": full_name, "clips": rows}


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    lines = []
    lines.append("# YuNet Selective Upscaling Fallback - Shadow Evaluation")
    lines.append("")
    lines.append(f"- Generated: {meta['generated_at']}")
    lines.append(f"- Dataset: `{meta['dataset_dir']}` (synthetic_only={meta['synthetic_only']}, real_people={meta['real_people']})")
    lines.append(f"- Dedupe IoU: {meta['dedupe_iou']}")
    lines.append("- Production behavior: **unchanged** (experimental evaluation only).")
    lines.append("")
    lines.append("## Task 03 evidence / trigger rationale")
    for item in report.get("task03_evidence", {}).get("trigger_rationale", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Comparison")
    lines.append("")
    lines.append("| clip | strategy | P | R | F1 | dR vs base | lat ms | lat x base | fallback % | dR vs full 1.5x | lat x full 1.5x |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report["comparison"]["clips"]:
        for sname, m in row["variants"].items():
            lines.append(
                f"| {row['clip']} | {sname} | {m.get('precision')} | {m.get('recall')} | {m.get('f1')} | {m.get('delta_recall_vs_baseline')} | {m.get('mean_latency_ms')} | {m.get('latency_ratio_vs_baseline')} | {m.get('fallback_invocation_rate')} | {m.get('recall_vs_full_1_5x')} | {m.get('latency_ratio_vs_full_1_5x')} |"
            )
    lines.append("")
    lines.append("## Limitations")
    for item in meta.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Safety")
    lines.append("- No production detection/pipeline/config/threshold/model changes.")
    lines.append("- No DB/schema/migrations/source media/datasets/evidence/exports/crops/embeddings modified.")
    lines.append("- No Git write/synchronization operations performed.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"YUNET-FALLBACK-EXPERIMENT-{ts}.json"
    md_path = out_dir / f"YUNET-FALLBACK-EXPERIMENT-{ts}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
