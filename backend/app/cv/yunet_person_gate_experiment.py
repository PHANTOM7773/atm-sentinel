from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .baseline_benchmark import collect_environment, collect_model_provenance, compute_frame_presence_metrics, load_manifest, validate_manifest
from .detection import YOLOXPersonDetector, YuNetFaceDetector
from .face_detection_experiments import DetectionRecord, _iou, dedupe_detections, scale_detection_to_original

NOT_ASSESSABLE = "NOT_ASSESSABLE"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"


@dataclass(frozen=True)
class PersonGateStrategy:
    name: str
    mode: str  # baseline|zero_fallback|person_gated_zero_fallback|safety_fallback|person_region
    description: str
    fallback_scale: float = 1.5
    person_min_confidence: float = 0.0
    person_min_area: float = 0.0
    safety_on_no_person: str = "run_fallback"  # run_fallback|skip_fallback
    safety_on_person_error: str = "run_fallback"  # run_fallback|skip_fallback
    region_padding: float = 0.2


DEFAULT_STRATEGIES: tuple[PersonGateStrategy, ...] = (
    PersonGateStrategy("baseline_yunet", "baseline", "Original YuNet only"),
    PersonGateStrategy("zero_detection_fallback_1_5x", "zero_fallback", "TASK04-style zero-detection fallback"),
    PersonGateStrategy(
        "person_gated_zero_fallback_skip",
        "person_gated_zero_fallback",
        "Zero-detection fallback only when YOLOX person gate passes; skip fallback if no person",
        safety_on_no_person="skip_fallback",
    ),
    PersonGateStrategy(
        "person_gated_zero_fallback_safety_run",
        "safety_fallback",
        "Zero-detection fallback gated by YOLOX person; if no person/error, run fallback as safety",
        safety_on_no_person="run_fallback",
        safety_on_person_error="run_fallback",
    ),
    PersonGateStrategy(
        "person_region_1_5x_experimental",
        "person_region",
        "Run 1.5x YuNet on padded person regions when baseline has zero detections; merge with baseline",
        safety_on_no_person="skip_fallback",
        safety_on_person_error="run_fallback",
    ),
)


@dataclass
class FrameEval:
    frame_number: int
    timestamp: float | None
    strategy: str
    gt_label: str | None
    gt_has_face: bool | None
    baseline_detections: list[DetectionRecord]
    fallback_detections: list[DetectionRecord]
    final_detections: list[DetectionRecord]
    person_detections: list[dict[str, Any]]
    person_gate_passed: bool | None
    fallback_triggered: bool
    fallback_reason: str | None
    safety_policy_applied: str | None
    person_error: str | None
    baseline_latency_ms: float
    fallback_latency_ms: float
    person_latency_ms: float
    total_latency_ms: float
    yolox_calls: int
    yunet_calls: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_number": self.frame_number,
            "timestamp": self.timestamp,
            "strategy": self.strategy,
            "gt_label": self.gt_label,
            "gt_has_face": self.gt_has_face,
            "person_gate_passed": self.person_gate_passed,
            "fallback_triggered": self.fallback_triggered,
            "fallback_reason": self.fallback_reason,
            "safety_policy_applied": self.safety_policy_applied,
            "person_error": self.person_error,
            "baseline_latency_ms": round(self.baseline_latency_ms, 3),
            "fallback_latency_ms": round(self.fallback_latency_ms, 3),
            "person_latency_ms": round(self.person_latency_ms, 3),
            "total_latency_ms": round(self.total_latency_ms, 3),
            "yolox_calls": self.yolox_calls,
            "yunet_calls": self.yunet_calls,
            "person_detections": self.person_detections,
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
        frames.append((idx, (idx / fps) if fps > 0 else None, frame))
        idx += 1
    cap.release()
    return frames


def _detect_scale(frame: np.ndarray, *, detector: YuNetFaceDetector, scale: float, variant: str) -> tuple[list[DetectionRecord], float, int]:
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
        calls = 1
    except Exception:
        return [], (__import__("time").perf_counter() - t0) * 1000.0, 1
    latency = (__import__("time").perf_counter() - t0) * 1000.0
    out = []
    for det in dets:
        rec = scale_detection_to_original(det, s, orig_w, orig_h)
        if rec is None:
            continue
        out.append(DetectionRecord(**{**asdict(rec), "variant": variant}))
    return out, latency, calls


def _clip_bbox_to_frame(bbox: Sequence[float], w: int, h: int) -> tuple[int, int, int, int] | None:
    x, y, bw, bh = [float(v) for v in bbox]
    x1 = max(0, min(int(np.floor(x)), w - 1))
    y1 = max(0, min(int(np.floor(y)), h - 1))
    x2 = max(0, min(int(np.ceil(x + bw)), w))
    y2 = max(0, min(int(np.ceil(y + bh)), h))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _detect_person_regions(frame: np.ndarray, *, detector: YuNetFaceDetector, persons: list[dict[str, Any]], scale: float, padding: float, variant: str) -> tuple[list[DetectionRecord], float, int]:
    orig_h, orig_w = frame.shape[:2]
    out: list[DetectionRecord] = []
    total_latency = 0.0
    calls = 0
    for p in persons:
        bbox = p.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x, y, bw, bh = [float(v) for v in bbox]
        pad_x = bw * padding
        pad_y = bh * padding
        region = _clip_bbox_to_frame((x - pad_x, y - pad_y, bw + 2 * pad_x, bh + 2 * pad_y), orig_w, orig_h)
        if region is None:
            continue
        x1, y1, x2, y2 = region
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # upscale region if requested
        s = float(scale)
        if abs(s - 1.0) < 1e-9:
            work = crop
        else:
            interp = cv2.INTER_CUBIC if s > 1.0 else cv2.INTER_AREA
            work = cv2.resize(crop, (max(1, int(round(crop.shape[1] * s))), max(1, int(round(crop.shape[0] * s)))), interpolation=interp)
        t0 = __import__("time").perf_counter()
        try:
            dets = detector.detect(work)
            calls += 1
        except Exception:
            calls += 1
            total_latency += (__import__("time").perf_counter() - t0) * 1000.0
            continue
        total_latency += (__import__("time").perf_counter() - t0) * 1000.0
        inv = 1.0 / s
        for det in dets:
            # map crop-upscaled -> crop -> original
            mapped = FaceDetectionLike(det.bbox, det.confidence, det.landmarks)
            rec = scale_detection_to_original(mapped, s, crop.shape[1], crop.shape[0])
            if rec is None:
                continue
            bx, by, bw2, bh2 = rec.bbox
            rec2 = DetectionRecord(
                bbox=(bx + x1, by + y1, bw2, bh2),
                confidence=rec.confidence,
                landmarks=tuple((lx + x1, ly + y1) for lx, ly in rec.landmarks),  # type: ignore[assignment]
                scale=s,
                variant=variant,
                raw_bbox=tuple(float(v) for v in det.bbox),  # type: ignore[assignment]
                raw_landmarks=tuple((float(px), float(py)) for px, py in det.landmarks),  # type: ignore[assignment]
            )
            clipped = _clip_bbox_to_frame(rec2.bbox, orig_w, orig_h)
            if clipped is None:
                continue
            cx1, cy1, cx2, cy2 = clipped
            rec2.bbox = (float(cx1), float(cy1), float(cx2 - cx1), float(cy2 - cy1))
            out.append(rec2)
    return out, total_latency, calls


class FaceDetectionLike:
    def __init__(self, bbox, confidence, landmarks):
        self.bbox = bbox
        self.confidence = confidence
        self.landmarks = landmarks


def _person_gate(persons: list[dict[str, Any]], *, min_conf: float, min_area: float) -> tuple[bool, list[dict[str, Any]]]:
    usable = []
    for p in persons:
        conf = float(p.get("confidence", 0.0))
        bbox = p.get("bbox") or [0, 0, 0, 0]
        area = float(bbox[2]) * float(bbox[3])
        if conf >= min_conf and area >= min_area:
            usable.append(p)
    return len(usable) > 0, usable


def evaluate_frame(
    frame: np.ndarray,
    *,
    frame_number: int,
    timestamp: float | None,
    gt_label: str | None,
    detector: YuNetFaceDetector,
    person_detector: YOLOXPersonDetector | None,
    strategy: PersonGateStrategy,
    dedupe_iou: float = 0.5,
) -> FrameEval:
    gt_has_face = _is_positive_label(gt_label) if gt_label is not None else None
    if frame is None or frame.size == 0:
        return FrameEval(frame_number, timestamp, strategy.name, gt_label, gt_has_face, [], [], [], [], None, False, None, None, None, 0, 0, 0, 0, 0, 0)

    baseline, baseline_ms, yunet_calls = _detect_scale(frame, detector=detector, scale=1.0, variant=f"{strategy.name}:baseline")
    fallback: list[DetectionRecord] = []
    fallback_ms = 0.0
    person_ms = 0.0
    yolox_calls = 0
    person_detections: list[dict[str, Any]] = []
    person_gate_passed = None
    fallback_triggered = False
    fallback_reason = None
    safety_policy_applied = None
    person_error = None

    def run_full_fallback(reason: str):
        nonlocal fallback, fallback_ms, yunet_calls, fallback_triggered, fallback_reason
        dets, ms, calls = _detect_scale(frame, detector=detector, scale=strategy.fallback_scale, variant=f"{strategy.name}:fallback")
        fallback.extend(dets)
        fallback_ms += ms
        yunet_calls += calls
        fallback_triggered = True
        fallback_reason = reason

    def run_region_fallback(reason: str, usable_persons: list[dict[str, Any]]):
        nonlocal fallback, fallback_ms, yunet_calls, fallback_triggered, fallback_reason
        dets, ms, calls = _detect_person_regions(frame, detector=detector, persons=usable_persons, scale=strategy.fallback_scale, padding=strategy.region_padding, variant=f"{strategy.name}:person_region")
        fallback.extend(dets)
        fallback_ms += ms
        yunet_calls += calls
        fallback_triggered = True
        fallback_reason = reason

    if strategy.mode == "baseline":
        pass
    elif strategy.mode == "zero_fallback":
        if len(baseline) == 0:
            run_full_fallback("baseline_zero_detections")
    elif strategy.mode in {"person_gated_zero_fallback", "safety_fallback", "person_region"}:
        if len(baseline) == 0:
            if person_detector is None:
                person_error = "person_detector_unavailable"
                if strategy.safety_on_person_error == "run_fallback" and strategy.mode != "person_region":
                    safety_policy_applied = "run_fallback_on_person_error"
                    run_full_fallback("person_detector_unavailable")
                elif strategy.safety_on_person_error == "run_fallback" and strategy.mode == "person_region":
                    safety_policy_applied = "run_full_fallback_on_person_error"
                    run_full_fallback("person_detector_unavailable")
                else:
                    safety_policy_applied = "skip_fallback_on_person_error"
            else:
                t0 = __import__("time").perf_counter()
                try:
                    persons = person_detector.detect(frame)
                    yolox_calls += 1
                    person_ms += (__import__("time").perf_counter() - t0) * 1000.0
                    person_detections = [{"bbox": [float(x) for x in p.bbox], "confidence": float(p.confidence), "class_id": int(getattr(p, "class_id", 0))} for p in persons]
                except Exception as exc:
                    yolox_calls += 1
                    person_ms += (__import__("time").perf_counter() - t0) * 1000.0
                    person_error = str(exc)
                    person_detections = []
                    if strategy.safety_on_person_error == "run_fallback":
                        safety_policy_applied = "run_fallback_on_person_error"
                        run_full_fallback("person_detector_error")
                    else:
                        safety_policy_applied = "skip_fallback_on_person_error"
                    persons = []

                if person_error is None:
                    gate_passed, usable = _person_gate(person_detections, min_conf=strategy.person_min_confidence, min_area=strategy.person_min_area)
                    person_gate_passed = gate_passed
                    if gate_passed:
                        if strategy.mode == "person_region":
                            run_region_fallback("baseline_zero_person_gate_passed", usable)
                        else:
                            run_full_fallback("baseline_zero_person_gate_passed")
                    else:
                        if strategy.safety_on_no_person == "run_fallback":
                            safety_policy_applied = "run_fallback_on_no_person"
                            run_full_fallback("baseline_zero_no_person")
                        else:
                            safety_policy_applied = "skip_fallback_on_no_person"
    else:
        raise ValueError(f"Unknown strategy mode: {strategy.mode}")

    combined = list(baseline) + list(fallback)
    final = dedupe_detections(combined, iou_threshold=dedupe_iou) if combined else []
    total_ms = baseline_ms + fallback_ms + person_ms
    return FrameEval(frame_number, timestamp, strategy.name, gt_label, gt_has_face, baseline, fallback, final, person_detections, person_gate_passed, fallback_triggered, fallback_reason, safety_policy_applied, person_error, baseline_ms, fallback_ms, person_ms, total_ms, yolox_calls, yunet_calls)


def evaluate_person_gate_strategies(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    clip_names: list[str] | None = None,
    strategies: list[PersonGateStrategy] | None = None,
    dedupe_iou: float = 0.5,
    detector_factory: Callable[[], YuNetFaceDetector] = YuNetFaceDetector,
    person_detector_factory: Callable[[], YOLOXPersonDetector] | None = YOLOXPersonDetector,
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

    selected = list(strategies or DEFAULT_STRATEGIES)
    # Precompute YOLOX per frame once for fair comparison/cost accounting baseline? No: measure actual calls per strategy.
    # But we still gather evidence for all clips with a separate pass.
    evidence = collect_yolox_evidence(dataset_dir, clip_items, person_detector_factory)

    per_strategy = {}
    for strat in selected:
        detector = detector_factory()
        person_detector = person_detector_factory() if (person_detector_factory and strat.mode in {"person_gated_zero_fallback", "safety_fallback", "person_region"}) else None
        clip_results = {}
        total_lat = []
        total_fb = 0
        total_frames = 0
        for clip_name, entry in clip_items:
            frames = _load_clip_frames(dataset_dir / str(entry["file"]))
            expected, predicted = {}, {}
            tp = fp = fn = tn = 0
            recovered, missed = [], []
            fallback_invocations = 0
            fallback_reasons: dict[str, int] = {}
            yolox_calls = yunet_calls = 0
            person_errors = 0
            safety_applied: dict[str, int] = {}
            rows = []
            for frame_number, ts, frame in frames:
                gt_label = _frame_label(entry, frame_number, clip_name=clip_name)
                gt_has_face = _is_positive_label(gt_label) if gt_label is not None else None
                res = evaluate_frame(frame, frame_number=frame_number, timestamp=ts, gt_label=gt_label, detector=detector, person_detector=person_detector, strategy=strat, dedupe_iou=dedupe_iou)
                total_frames += 1
                yolox_calls += res.yolox_calls
                yunet_calls += res.yunet_calls
                if res.person_error:
                    person_errors += 1
                if res.safety_policy_applied:
                    safety_applied[res.safety_policy_applied] = safety_applied.get(res.safety_policy_applied, 0) + 1
                if res.fallback_triggered:
                    fallback_invocations += 1
                    total_fb += 1
                    fallback_reasons[res.fallback_reason or "unknown"] = fallback_reasons.get(res.fallback_reason or "unknown", 0) + 1
                has_pred = len(res.final_detections) > 0
                baseline_pos = len(res.baseline_detections) > 0
                if gt_label is not None:
                    expected[frame_number] = bool(gt_has_face)
                    predicted[frame_number] = has_pred
                    if gt_has_face:
                        if has_pred:
                            tp += 1
                            if not baseline_pos:
                                recovered.append(frame_number)
                        else:
                            fn += 1
                            missed.append(frame_number)
                    else:
                        if has_pred:
                            fp += 1
                        else:
                            tn += 1
                rows.append(res.to_dict())
                total_lat.append(res.total_latency_ms)
            metrics = compute_frame_presence_metrics(expected, predicted) if expected else {"status": NOT_ASSESSABLE, "reason": "No frame-level labels"}
            if expected:
                metrics = {"status": "MEASURED", **metrics}
            clip_results[clip_name] = {
                "file": entry.get("file"),
                "description": entry.get("description"),
                "frame_count": len(frames),
                "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "frame_presence": metrics,
                "recovered_labeled_frames": recovered,
                "missed_labeled_frames": missed,
                "fallback_invocations": fallback_invocations,
                "fallback_invocation_rate": round(fallback_invocations / len(frames), 4) if frames else None,
                "fallback_reasons": fallback_reasons,
                "yolox_calls": yolox_calls,
                "yunet_calls": yunet_calls,
                "person_errors": person_errors,
                "safety_policy_applied": safety_applied,
                "mean_latency_ms": round(statistics.mean([r["total_latency_ms"] for r in rows]), 3) if rows else None,
                "p95_latency_ms": round(float(np.percentile([r["total_latency_ms"] for r in rows], 95)), 3) if rows else None,
                "frames": rows,
            }
        per_strategy[strat.name] = {
            "strategy": asdict(strat),
            "clips": clip_results,
            "totals": {
                "frames": total_frames,
                "fallback_invocations": total_fb,
                "fallback_invocation_rate": round(total_fb / total_frames, 4) if total_frames else None,
                "mean_latency_ms": round(statistics.mean(total_lat), 3) if total_lat else None,
                "p95_latency_ms": round(float(np.percentile(total_lat, 95)), 3) if total_lat else None,
            },
        }
    comparison = build_comparison(per_strategy)
    report = {
        "meta": {
            "report_name": "yunet-person-gated-fallback-shadow-evaluation",
            "generated_at": _now_iso(),
            "dataset_dir": str(dataset_dir),
            "manifest": str(dataset_dir / "manifest.json"),
            "synthetic_only": bool(manifest.get("synthetic", False)),
            "real_people": bool(manifest.get("real_people", False)),
            "dedupe_iou": dedupe_iou,
            "limitations": [
                "Frame-presence labels only; bbox GT absent so localization/IoU NOT_ASSESSABLE.",
                "Synthetic diagnostic only; adjacent frames are not independent subjects/samples.",
                "YOLOX person labels are not present in manifest; person-gate evidence is observational on this synthetic set.",
                "No production behavior/config/model/threshold changes.",
            ],
        },
        "environment": collect_environment(),
        "model_provenance": collect_model_provenance(),
        "yolox_evidence": evidence,
        "strategies": per_strategy,
        "comparison": comparison,
    }
    return report


def collect_yolox_evidence(dataset_dir: Path, clip_items: list[tuple[str, dict[str, Any]]], person_detector_factory: Callable[[], YOLOXPersonDetector] | None) -> dict[str, Any]:
    if person_detector_factory is None:
        return {"status": NOT_ASSESSABLE, "reason": "No person detector factory provided"}
    try:
        det = person_detector_factory()
    except Exception as exc:
        return {"status": NOT_ASSESSABLE, "reason": f"Person detector unavailable: {exc}"}
    clip_summaries = {}
    for clip_name, entry in clip_items:
        frames = _load_clip_frames(dataset_dir / str(entry["file"]))
        gt_pos = 0
        person_on_gt = 0
        miss_person_on_gt = []
        fp_person_on_neg = []
        person_counts = []
        confs = []
        areas = []
        for frame_number, _ts, frame in frames:
            gt_label = _frame_label(entry, frame_number, clip_name=clip_name)
            gt_has_face = _is_positive_label(gt_label) if gt_label is not None else None
            try:
                persons = det.detect(frame)
            except Exception:
                persons = []
            person_counts.append(len(persons))
            for p in persons:
                confs.append(float(p.confidence))
                areas.append(float(p.bbox[2] * p.bbox[3]))
            has_person = len(persons) > 0
            if gt_has_face is True:
                gt_pos += 1
                if has_person:
                    person_on_gt += 1
                else:
                    miss_person_on_gt.append(frame_number)
            if gt_has_face is False and has_person:
                fp_person_on_neg.append(frame_number)
        clip_summaries[clip_name] = {
            "frames": len(frames),
            "gt_face_positive_frames": gt_pos,
            "frames_with_person_detection": sum(1 for c in person_counts if c > 0),
            "person_on_gt_face_frames": person_on_gt,
            "person_recall_on_gt_face_frames": round(person_on_gt / gt_pos, 4) if gt_pos else None,
            "miss_person_on_gt_face_frames": miss_person_on_gt,
            "fp_person_on_gt_negative_frames": fp_person_on_neg,
            "person_conf_min": round(min(confs), 4) if confs else None,
            "person_conf_mean": round(float(np.mean(confs)), 4) if confs else None,
            "person_conf_max": round(max(confs), 4) if confs else None,
            "person_area_min": round(min(areas), 2) if areas else None,
            "person_area_mean": round(float(np.mean(areas)), 2) if areas else None,
            "person_area_max": round(max(areas), 2) if areas else None,
        }
    return {
        "status": "MEASURED",
        "note": "Observational person detection on synthetic clips; manifest has no person bbox GT. Person recall here is vs face-presence labels only (proxy, not person GT).",
        "clips": clip_summaries,
    }


def build_comparison(per_strategy: dict[str, Any]) -> dict[str, Any]:
    clip_names = sorted({cn for v in per_strategy.values() for cn in v.get("clips", {}).keys()})
    base_name = "baseline_yunet" if "baseline_yunet" in per_strategy else next(iter(per_strategy))
    ref_name = "zero_detection_fallback_1_5x" if "zero_detection_fallback_1_5x" in per_strategy else None
    rows = []
    for clip in clip_names:
        row = {"clip": clip, "variants": {}}
        for sname, sdata in per_strategy.items():
            c = sdata["clips"].get(clip)
            if not c:
                continue
            fp = c["frame_presence"]
            row["variants"][sname] = {
                "status": fp.get("status"), "precision": fp.get("precision"), "recall": fp.get("recall"), "f1": fp.get("f1"),
                "tp": fp.get("tp"), "fp": fp.get("fp"), "fn": fp.get("fn"), "tn": fp.get("tn"),
                "mean_latency_ms": c.get("mean_latency_ms"), "fallback_invocation_rate": c.get("fallback_invocation_rate"),
                "yolox_calls": c.get("yolox_calls"), "yunet_calls": c.get("yunet_calls"),
                "recovered_labeled_frames": len(c.get("recovered_labeled_frames", [])),
                "missed_labeled_frames": len(c.get("missed_labeled_frames", [])),
                "person_errors": c.get("person_errors"),
            }
        base = row["variants"].get(base_name, {})
        ref = row["variants"].get(ref_name, {}) if ref_name else {}
        for sname, m in row["variants"].items():
            m["delta_recall_vs_baseline"] = None if m.get("recall") is None or base.get("recall") is None else round(m["recall"] - base["recall"], 4)
            m["latency_ratio_vs_baseline"] = None if m.get("mean_latency_ms") is None or not base.get("mean_latency_ms") else round(m["mean_latency_ms"] / base["mean_latency_ms"], 4)
            if ref_name:
                m["delta_recall_vs_zero_fallback"] = None if m.get("recall") is None or ref.get("recall") is None else round(m["recall"] - ref["recall"], 4)
                m["latency_ratio_vs_zero_fallback"] = None if m.get("mean_latency_ms") is None or not ref.get("mean_latency_ms") else round(m["mean_latency_ms"] / ref["mean_latency_ms"], 4)
        rows.append(row)
    return {"baseline": base_name, "reference_zero_fallback": ref_name, "clips": rows}


def render_markdown(report: dict[str, Any]) -> str:
    m = report["meta"]
    lines = [
        "# YuNet Person-Gated Fallback - Shadow Evaluation",
        "",
        f"- Generated: {m['generated_at']}",
        f"- Dataset: `{m['dataset_dir']}` (synthetic_only={m['synthetic_only']}, real_people={m['real_people']})",
        "- Production behavior: **unchanged** (experimental only).",
        "",
        "## YOLOX evidence (observational; no person bbox GT in manifest)",
    ]
    ev = report.get("yolox_evidence", {})
    if ev.get("status") == "MEASURED":
        lines.append("| clip | gt face+ frames | person on gt-face frames | person recall proxy | miss person on gt-face | fp person on gt-face-neg |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for clip, c in ev.get("clips", {}).items():
            lines.append(f"| {clip} | {c['gt_face_positive_frames']} | {c['person_on_gt_face_frames']} | {c['person_recall_on_gt_face_frames']} | {len(c['miss_person_on_gt_face_frames'])} | {len(c['fp_person_on_gt_negative_frames'])} |")
    else:
        lines.append(f"- {ev.get('status')}: {ev.get('reason')}")
    lines.append("")
    lines.append("## Comparison")
    lines.append("| clip | strategy | P | R | F1 | dR base | lat ms | lat x base | fb% | yolox | yunet | dR vs zero-fb | lat x zero-fb |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in report["comparison"]["clips"]:
        for sname, v in row["variants"].items():
            lines.append(f"| {row['clip']} | {sname} | {v.get('precision')} | {v.get('recall')} | {v.get('f1')} | {v.get('delta_recall_vs_baseline')} | {v.get('mean_latency_ms')} | {v.get('latency_ratio_vs_baseline')} | {v.get('fallback_invocation_rate')} | {v.get('yolox_calls')} | {v.get('yunet_calls')} | {v.get('delta_recall_vs_zero_fallback')} | {v.get('latency_ratio_vs_zero_fallback')} |")
    lines.append("")
    lines.append("## Limitations")
    for item in m.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Safety")
    lines.append("- No production code/config/model/threshold changes. No DB/media/evidence/crops/embeddings changed.")
    lines.append("- No Git write/synchronization operations performed.")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"YUNET-PERSON-GATE-EXPERIMENT-{ts}.json"
    md_path = out_dir / f"YUNET-PERSON-GATE-EXPERIMENT-{ts}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
