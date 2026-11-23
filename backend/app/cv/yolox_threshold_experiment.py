from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .baseline_benchmark import collect_environment, collect_model_provenance, compute_frame_presence_metrics, load_manifest, validate_manifest
from .detection import YOLOXPersonDetector, YuNetFaceDetector
from .face_detection_experiments import dedupe_detections, scale_detection_to_original
from .yunet_fallback_experiment import FallbackStrategy, detect_with_strategy

NOT_ASSESSABLE = "NOT_ASSESSABLE"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"
DEFAULT_THRESHOLDS = (0.10, 0.20, 0.30, 0.40, 0.45, 0.50)


@dataclass
class RawPersonCandidate:
    bbox_xywh: tuple[float, float, float, float]
    confidence: float
    class_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"bbox_xywh": [float(x) for x in self.bbox_xywh], "confidence": float(self.confidence), "class_id": int(self.class_id)}


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
        frames.append((idx, (idx / fps) if fps > 0 else None, frame))
        idx += 1
    cap.release()
    return frames


def decode_yolox_raw(detector: YOLOXPersonDetector, image: np.ndarray) -> tuple[list[RawPersonCandidate], dict[str, Any]]:
    """Run YOLOX forward+decode once and return all person-class candidates before final threshold/NMS filtering.

    Uses the existing detector's preprocessing, forward, grid/stride decode, and class scoring.
    This is an isolated diagnostic helper; it does not modify production behavior.
    """
    diag: dict[str, Any] = {"ok": True}
    if image is None or image.size == 0:
        return [], {"ok": True, "empty_input": True}
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    padded, ratio = detector._letterbox(rgb)
    blob = np.expand_dims(np.transpose(padded, (2, 0, 1)), 0).astype(np.float32)
    detector.net.setInput(blob)
    t0 = time.perf_counter()
    outputs = detector._forward()
    forward_ms = (time.perf_counter() - t0) * 1000.0
    diag["forward_ms"] = round(forward_ms, 3)
    if not outputs:
        return [], {**diag, "no_outputs": True}
    dets = np.asarray(outputs[0], dtype=np.float32)
    diag["raw_output_shape"] = list(dets.shape)
    if dets.ndim == 3:
        dets = dets[0]
    if dets.ndim != 2 or dets.shape[1] < 85:
        return [], {**diag, "unexpected_shape": True}

    dets = dets.copy()
    dets[:, :2] = (dets[:, :2] + detector.grids) * detector.expanded_strides
    dets[:, 2:4] = np.exp(dets[:, 2:4]) * detector.expanded_strides
    boxes = dets[:, :4]
    boxes_xywh = np.ones_like(boxes)
    boxes_xywh[:, 0] = boxes[:, 0] - boxes[:, 2] / 2.0
    boxes_xywh[:, 1] = boxes[:, 1] - boxes[:, 3] / 2.0
    boxes_xywh[:, 2] = boxes[:, 2]
    boxes_xywh[:, 3] = boxes[:, 3]
    scores = dets[:, 4:5] * dets[:, 5:85]
    max_scores = np.amax(scores, axis=1)
    max_scores_idx = np.argmax(scores, axis=1)
    person_mask = max_scores_idx == detector.PERSON_CLASS_ID
    diag["total_candidates"] = int(len(dets))
    diag["person_class_candidates"] = int(np.sum(person_mask))
    diag["person_score_max"] = float(np.max(max_scores[person_mask])) if np.any(person_mask) else None
    diag["person_score_mean"] = float(np.mean(max_scores[person_mask])) if np.any(person_mask) else None

    cands: list[RawPersonCandidate] = []
    height, width = image.shape[:2]
    for i in np.where(person_mask)[0]:
        conf = float(max_scores[i])
        x, y, bw, bh = (float(v) / ratio for v in boxes_xywh[i])
        x1 = max(0.0, min(x, float(width - 1)))
        y1 = max(0.0, min(y, float(height - 1)))
        x2 = max(0.0, min(x + bw, float(width)))
        y2 = max(0.0, min(y + bh, float(height)))
        if x2 <= x1 or y2 <= y1:
            continue
        cands.append(RawPersonCandidate(bbox_xywh=(x1, y1, x2 - x1, y2 - y1), confidence=conf, class_id=int(max_scores_idx[i])))
    diag["person_candidates_after_geom"] = len(cands)
    return cands, diag


def filter_person_candidates(candidates: Sequence[RawPersonCandidate], *, score_threshold: float, nms_threshold: float) -> list[dict[str, Any]]:
    if not candidates:
        return []
    boxes = [list(c.bbox_xywh) for c in candidates]
    scores = [float(c.confidence) for c in candidates]
    class_ids = [int(c.class_id) for c in candidates]
    keep = cv2.dnn.NMSBoxesBatched(boxes, scores, class_ids, float(score_threshold), float(nms_threshold))
    if keep is None or len(keep) == 0:
        return []
    if isinstance(keep, tuple):
        keep = keep[0]
    indices = np.asarray(keep).reshape(-1).astype(int)
    out = []
    for idx in indices:
        if idx < 0 or idx >= len(candidates):
            continue
        c = candidates[idx]
        if c.confidence < score_threshold:
            continue
        out.append({"bbox": [float(x) for x in c.bbox_xywh], "confidence": float(c.confidence), "class_id": int(c.class_id)})
    return out


def evaluate_yolox_thresholds(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    clip_names: list[str] | None = None,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    dedupe_iou: float = 0.5,
    detector_factory: Callable[[], YOLOXPersonDetector] = YOLOXPersonDetector,
) -> dict[str, Any]:
    manifest = load_manifest(dataset_dir)
    errors = validate_manifest(manifest, dataset_dir)
    if errors:
        raise ValueError("Invalid manifest: " + "; ".join(errors))
    clips = manifest.get("videos", {})
    if clip_names:
        missing = [c for c in clip_names if c not in clips]
        if missing:
            raise ValueError(f"Unknown clip names: {missing}")
        clip_items = [(c, clips[c]) for c in clip_names]
    else:
        clip_items = list(clips.items())

    detector = detector_factory()
    thresholds = [float(t) for t in thresholds]
    per_threshold: dict[str, Any] = {}
    raw_frames = []

    for clip_name, entry in clip_items:
        frames = _load_clip_frames(dataset_dir / str(entry["file"]))
        for frame_number, ts, frame in frames:
            gt_label = _frame_label(entry, frame_number, clip_name=clip_name)
            gt_has_face = _is_positive_label(gt_label) if gt_label is not None else None
            t0 = time.perf_counter()
            cands, diag = decode_yolox_raw(detector, frame)
            decode_ms = (time.perf_counter() - t0) * 1000.0
            raw_frames.append({
                "clip": clip_name,
                "frame_number": frame_number,
                "timestamp": ts,
                "gt_label": gt_label,
                "gt_has_face": gt_has_face,
                "decode_ms": round(decode_ms, 3),
                "raw_diag": diag,
                "raw_candidates": [c.to_dict() for c in cands],
            })

    for thr in thresholds:
        clip_results = {}
        all_lat = []
        for clip_name, entry in clip_items:
            frame_rows = []
            gt_pos = 0
            person_on_gt = 0
            miss_on_gt = []
            fp_on_neg = []
            det_counts = []
            confs = []
            for rf in [r for r in raw_frames if r["clip"] == clip_name]:
                t0 = time.perf_counter()
                filtered = filter_person_candidates([RawPersonCandidate(tuple(c["bbox_xywh"]), c["confidence"], c["class_id"]) for c in rf["raw_candidates"]], score_threshold=thr, nms_threshold=detector.nms_threshold)
                filter_ms = (time.perf_counter() - t0) * 1000.0
                total_ms = rf["decode_ms"] + filter_ms
                all_lat.append(total_ms)
                det_counts.append(len(filtered))
                confs.extend([d["confidence"] for d in filtered])
                gt_has_face = rf["gt_has_face"]
                has_person = len(filtered) > 0
                if gt_has_face is True:
                    gt_pos += 1
                    if has_person:
                        person_on_gt += 1
                    else:
                        miss_on_gt.append(rf["frame_number"])
                if gt_has_face is False and has_person:
                    fp_on_neg.append(rf["frame_number"])
                frame_rows.append({
                    "frame_number": rf["frame_number"],
                    "timestamp": rf["timestamp"],
                    "gt_has_face": gt_has_face,
                    "person_count": len(filtered),
                    "persons": filtered,
                    "decode_ms": rf["decode_ms"],
                    "filter_ms": round(filter_ms, 3),
                    "total_ms": round(total_ms, 3),
                    "raw_person_candidates": len(rf["raw_candidates"]),
                })
            clip_results[clip_name] = {
                "frames": len(frame_rows),
                "gt_face_positive_frames": gt_pos,
                "frames_with_person_detection": sum(1 for r in frame_rows if r["person_count"] > 0),
                "person_on_gt_face_frames": person_on_gt,
                "face_positive_frame_coverage_proxy": round(person_on_gt / gt_pos, 4) if gt_pos else None,
                "miss_person_on_gt_face_frames": miss_on_gt,
                "person_on_gt_negative_frames": fp_on_neg,
                "person_conf_min": round(min(confs), 4) if confs else None,
                "person_conf_mean": round(float(np.mean(confs)), 4) if confs else None,
                "person_conf_max": round(max(confs), 4) if confs else None,
                "mean_total_ms": round(statistics.mean([r["total_ms"] for r in frame_rows]), 3) if frame_rows else None,
                "frames_detail": frame_rows,
            }
        per_threshold[str(thr)] = {
            "threshold": thr,
            "clips": clip_results,
            "totals": {
                "mean_total_ms": round(statistics.mean(all_lat), 3) if all_lat else None,
                "p95_total_ms": round(float(np.percentile(all_lat, 95)), 3) if all_lat else None,
            },
        }

    person_gating = evaluate_person_gating_at_thresholds(dataset_dir, clip_items, raw_frames, thresholds, detector.nms_threshold)
    report = {
        "meta": {
            "report_name": "yolox-threshold-sensitivity-reliability",
            "generated_at": _now_iso(),
            "dataset_dir": str(dataset_dir),
            "manifest": str(dataset_dir / "manifest.json"),
            "synthetic_only": bool(manifest.get("synthetic", False)),
            "real_people": bool(manifest.get("real_people", False)),
            "thresholds": thresholds,
            "limitations": [
                "Manifest has face-presence labels, not person bounding-box GT. Face-positive-frame coverage is a PROXY only, not person recall/precision/mAP/localization.",
                "Adjacent frames are not independent subjects/samples; synthetic diagnostic only.",
                "No production threshold selected or changed.",
            ],
        },
        "environment": collect_environment(),
        "model_provenance": collect_model_provenance(),
        "threshold_results": per_threshold,
        "person_gating_re_evaluation": person_gating,
    }
    return report


def evaluate_person_gating_at_thresholds(dataset_dir: Path, clip_items, raw_frames, thresholds: Sequence[float], nms_threshold: float) -> dict[str, Any]:
    # Re-evaluate TASK 05-style zero-detection fallback with YOLOX-gated skip at each threshold.
    # This uses actual YuNet baseline/fallback behavior but gates fallback by YOLOX person detections filtered at threshold.
    from .yunet_person_gate_experiment import PersonGateStrategy, evaluate_frame

    yunet = YuNetFaceDetector()
    class FixedYOLOX:
        def __init__(self, persons):
            self._persons = persons
        def detect(self, image):
            return self._persons
    class P:
        def __init__(self, bbox, confidence, class_id=0):
            self.bbox = tuple(bbox); self.confidence = float(confidence); self.class_id = int(class_id)

    strategies = [
        ("zero_detection_fallback_1_5x", PersonGateStrategy("zero_detection_fallback_1_5x", "zero_fallback", "ref")),
        ("person_gated_skip", PersonGateStrategy("person_gated_skip", "person_gated_zero_fallback", "pg", safety_on_no_person="skip_fallback")),
        ("person_gated_safety_run", PersonGateStrategy("person_gated_safety_run", "safety_fallback", "sf", safety_on_no_person="run_fallback", safety_on_person_error="run_fallback")),
    ]
    out = {}
    for thr in thresholds:
        thr_key = str(float(thr))
        per_strategy = {}
        for sname, strat in strategies:
            clip_results = {}
            for clip_name, entry in clip_items:
                frames = _load_clip_frames(dataset_dir / str(entry["file"]))
                expected, predicted = {}, {}
                tp=fp=fn=tn=0
                fallback_invocations=0
                yolox_calls=0
                yunet_calls=0
                lats=[]
                for frame_number, ts, frame in frames:
                    gt_label = _frame_label(entry, frame_number, clip_name=clip_name)
                    gt_has_face = _is_positive_label(gt_label) if gt_label is not None else None
                    rf = next(r for r in raw_frames if r["clip"]==clip_name and r["frame_number"]==frame_number)
                    filtered = filter_person_candidates([RawPersonCandidate(tuple(c["bbox_xywh"]), c["confidence"], c["class_id"]) for c in rf["raw_candidates"]], score_threshold=float(thr), nms_threshold=nms_threshold)
                    person_detector = FixedYOLOX([P(f["bbox"], f["confidence"], f["class_id"]) for f in filtered]) if strat.mode in {"person_gated_zero_fallback","safety_fallback","person_region"} else None
                    res = evaluate_frame(frame, frame_number=frame_number, timestamp=ts, gt_label=gt_label, detector=yunet, person_detector=person_detector, strategy=strat)
                    # yolox call counted if gating used
                    if strat.mode in {"person_gated_zero_fallback","safety_fallback","person_region"} and len(res.baseline_detections)==0:
                        yolox_calls += 1
                    yunet_calls += res.yunet_calls
                    if res.fallback_triggered:
                        fallback_invocations += 1
                    lats.append(res.total_latency_ms)
                    if gt_label is not None:
                        expected[frame_number]=bool(gt_has_face)
                        has_pred=len(res.final_detections)>0
                        predicted[frame_number]=has_pred
                        if gt_has_face:
                            if has_pred: tp+=1
                            else: fn+=1
                        else:
                            if has_pred: fp+=1
                            else: tn+=1
                metrics = compute_frame_presence_metrics(expected,predicted) if expected else {"status":NOT_ASSESSABLE}
                if expected: metrics = {"status":"MEASURED", **metrics}
                clip_results[clip_name]={
                    "face_precision": metrics.get("precision"), "face_recall": metrics.get("recall"), "face_f1": metrics.get("f1"),
                    "tp":tp,"fp":fp,"fn":fn,"tn":tn,
                    "fallback_invocations": fallback_invocations,
                    "fallback_invocation_rate": round(fallback_invocations/len(frames),4) if frames else None,
                    "yolox_calls": yolox_calls, "yunet_calls": yunet_calls,
                    "mean_latency_ms": round(statistics.mean(lats),3) if lats else None,
                }
            per_strategy[sname]=clip_results
        out[thr_key]=per_strategy
    return out


def render_markdown(report: dict[str, Any]) -> str:
    m = report["meta"]
    lines = ["# YOLOX Person Detection Threshold Sensitivity & Reliability Evaluation", ""]
    lines.append(f"- Generated: {m['generated_at']}")
    lines.append(f"- Dataset: `{m['dataset_dir']}` (synthetic_only={m['synthetic_only']}, real_people={m['real_people']})")
    lines.append("- Production behavior: **unchanged**. No threshold selected.")
    lines.append("")
    lines.append("## Threshold sensitivity (face-positive-frame coverage is PROXY only; no person GT)")
    lines.append("| thr | clip | gt face+ | person on gt-face+ | coverage proxy | person on gt-face-neg | mean ms |")
    lines.append("|---:|---|---:|---:|---:|---:|---:|")
    for thr, data in report["threshold_results"].items():
        for clip, c in data["clips"].items():
            lines.append(f"| {thr} | {clip} | {c['gt_face_positive_frames']} | {c['person_on_gt_face_frames']} | {c['face_positive_frame_coverage_proxy']} | {len(c['person_on_gt_negative_frames'])} | {c['mean_total_ms']} |")
    lines.append("")
    lines.append("## Limitations")
    for item in m["limitations"]:
        lines.append(f"- {item}")
    lines.append("- No Git write/synchronization operations performed.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"YOLOX-THRESHOLD-EXPERIMENT-{ts}.json"
    md_path = out_dir / f"YOLOX-THRESHOLD-EXPERIMENT-{ts}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
