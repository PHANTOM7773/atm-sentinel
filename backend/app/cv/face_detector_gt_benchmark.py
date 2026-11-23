"""TASK 17 - Face detector ground-truth benchmark (isolated).

Uses manual bbox annotations (exploratory, NOT_REVIEWED) to evaluate existing
YuNet strategies. Does not modify production detector behavior.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from .detection import YuNetFaceDetector
from .face_detection_experiments import DetectionRecord, dedupe_detections, scale_detection_to_original

ANNOTATION_PATH = Path("reports/ps04cctv-audit/annotations/human-annotations.status-fixed.json")
DEFAULT_IOU_THRESHOLDS = (0.5,)
DEFAULT_CONF_THRESHOLDS = (0.0, 0.5, 0.7)


@dataclass(frozen=True)
class StrategySpec:
    name: str
    mode: str  # baseline|full_1_5x|zero_fallback|confidence_fallback
    fallback_scale: float = 1.5
    confidence_threshold: float | None = None
    description: str = ""


DEFAULT_STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec("yunet_baseline", "baseline", description="Existing YuNet on original resolution"),
    StrategySpec("yunet_full_1_5x", "full_1_5x", fallback_scale=1.5, description="Always run baseline + 1.5x upscale and merge"),
    StrategySpec("yunet_zero_detection_fallback_1_5x", "zero_fallback", fallback_scale=1.5, description="Run 1.5x only when baseline has zero detections"),
    StrategySpec("yunet_conf_fallback_lt_0_7", "confidence_fallback", fallback_scale=1.5, confidence_threshold=0.7, description="Run 1.5x when baseline max confidence < 0.7"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_annotations(path: Path = ANNOTATION_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text())
    return data


def validate_annotations(data: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    frames = data.get("frames")
    if not isinstance(frames, list):
        return {"ok": False, "errors": ["frames must be a list"], "warnings": warnings, "summary": {}}
    required = {
        "clip_id","clip_file","frame_index","timestamp_ms","image_width","image_height",
        "derived_image_path","derived_image_sha256","source_video_path","annotation_status","no_face","needs_review","frame_notes","faces"
    }
    total_boxes = 0
    no_face_frames = 0
    for i, f in enumerate(frames):
        if not isinstance(f, dict):
            errors.append(f"frame[{i}] not object")
            continue
        miss = required - set(f.keys())
        if miss:
            errors.append(f"frame[{i}] missing keys: {sorted(miss)}")
        w = int(f.get("image_width", 0)); h = int(f.get("image_height", 0))
        if w <= 0 or h <= 0:
            errors.append(f"frame[{i}] invalid dimensions")
        for pkey in ("derived_image_path", "source_video_path"):
            p = base_dir / str(f.get(pkey, ""))
            if not p.exists():
                errors.append(f"missing {pkey}: {p}")
        faces = f.get("faces") or []
        if f.get("no_face"):
            no_face_frames += 1
            if faces:
                errors.append(f"frame[{i}] no_face=true but has faces")
        for j, box in enumerate(faces):
            bbox = box.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4):
                errors.append(f"frame[{i}].faces[{j}] invalid bbox")
                continue
            x, y, bw, bh = [float(v) for v in bbox]
            if bw <= 0 or bh <= 0:
                errors.append(f"frame[{i}].faces[{j}] non-positive bbox")
            if x < -1 or y < -1 or x + bw > w + 1 or y + bh > h + 1:
                errors.append(f"frame[{i}].faces[{j}] out of bounds")
            total_boxes += 1
        if f.get("annotation_status") != "annotated":
            warnings.append(f"frame[{i}] annotation_status={f.get('annotation_status')}")
        if f.get("needs_review"):
            warnings.append(f"frame[{i}] needs_review=true")
    summary = {
        "frames": len(frames),
        "total_boxes": total_boxes,
        "no_face_frames": no_face_frames,
        "clips": sorted({str(f.get("clip_id")) for f in frames if isinstance(f, dict)}),
        "qa_status": "NOT_REVIEWED",
    }
    # task expectations
    if summary["frames"] != 48:
        warnings.append(f"expected 48 frames, got {summary['frames']}")
    if summary["total_boxes"] != 46:
        warnings.append(f"expected 46 face boxes, got {summary['total_boxes']}")
    if summary["no_face_frames"] != 9:
        warnings.append(f"expected 9 no-face frames, got {summary['no_face_frames']}")
    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings, "summary": summary}


def iou_xywh(a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay, aw, ah = [float(x) for x in a]
    bx, by, bw, bh = [float(x) for x in b]
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def match_one_to_one(gt_boxes: list[list[float]], pred_boxes: list[list[float]], iou_thr: float) -> dict[str, Any]:
    # Greedy by IoU desc, deterministic tie-breakers. Each GT and pred used once.
    candidates = []
    for gi, g in enumerate(gt_boxes):
        for pi, p in enumerate(pred_boxes):
            i = iou_xywh(g, p)
            if i >= iou_thr:
                candidates.append((i, gi, pi))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    used_g, used_p = set(), set()
    matches = []
    for i, gi, pi in candidates:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi); used_p.add(pi)
        matches.append({"gt_index": gi, "pred_index": pi, "iou": i})
    unmatched_gt = [i for i in range(len(gt_boxes)) if i not in used_g]
    unmatched_pred = [i for i in range(len(pred_boxes)) if i not in used_p]
    return {"matches": matches, "unmatched_gt": unmatched_gt, "unmatched_pred": unmatched_pred}


def compute_prf(tp: int, fp: int, fn: int) -> dict[str, float | None]:
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def voc_ap(recalls: list[float], precisions: list[float]) -> float | None:
    if not recalls or not precisions or len(recalls) != len(precisions):
        return None
    # VOC 2010+ all-point interpolation
    mrec = np.concatenate(([0.0], np.array(recalls, dtype=float), [1.0]))
    mpre = np.concatenate(([0.0], np.array(precisions, dtype=float), [0.0]))
    for i in range(mpre.size - 1, 0, -1):
        mpre[i - 1] = max(mpre[i - 1], mpre[i])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    ap = float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))
    return ap


def _detect_scaled(frame: np.ndarray, detector: YuNetFaceDetector, scale: float, tag: str) -> tuple[list[DetectionRecord], float]:
    h, w = frame.shape[:2]
    if abs(scale - 1.0) < 1e-9:
        work = frame
    else:
        interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
        work = cv2.resize(frame, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))), interpolation=interp)
    t0 = time.perf_counter()
    dets = detector.detect(work)
    ms = (time.perf_counter() - t0) * 1000.0
    out = []
    for d in dets:
        rec = scale_detection_to_original(d, scale, w, h)
        if rec is not None:
            out.append(DetectionRecord(**{**rec.__dict__, "variant": tag}))
    return out, ms


def run_strategy(frame: np.ndarray, detector: YuNetFaceDetector, spec: StrategySpec, *, dedupe_iou: float = 0.5) -> dict[str, Any]:
    baseline, base_ms = _detect_scaled(frame, detector, 1.0, f"{spec.name}:baseline")
    fallback, fb_ms = [], 0.0
    triggered = False
    reason = None
    if spec.mode == "baseline":
        pass
    elif spec.mode == "full_1_5x":
        triggered, reason = True, "full_upscale"
        fallback, fb_ms = _detect_scaled(frame, detector, spec.fallback_scale, f"{spec.name}:fallback")
    elif spec.mode == "zero_fallback":
        if len(baseline) == 0:
            triggered, reason = True, "baseline_zero_detections"
            fallback, fb_ms = _detect_scaled(frame, detector, spec.fallback_scale, f"{spec.name}:fallback")
    elif spec.mode == "confidence_fallback":
        thr = float(spec.confidence_threshold if spec.confidence_threshold is not None else 1.0)
        max_conf = max((d.confidence for d in baseline), default=None)
        if max_conf is None or max_conf < thr:
            triggered = True
            reason = "baseline_zero_detections" if max_conf is None else f"baseline_max_conf_below_{thr:.3f}"
            fallback, fb_ms = _detect_scaled(frame, detector, spec.fallback_scale, f"{spec.name}:fallback")
    else:
        raise ValueError(f"unknown mode {spec.mode}")
    combined = baseline + fallback
    final = dedupe_detections(combined, iou_threshold=dedupe_iou) if combined else []
    return {
        "baseline": baseline,
        "fallback": fallback,
        "final": final,
        "fallback_triggered": triggered,
        "fallback_reason": reason,
        "baseline_ms": base_ms,
        "fallback_ms": fb_ms,
        "total_ms": base_ms + fb_ms,
    }


def evaluate_strategy_on_annotations(
    *,
    annotations_path: Path = ANNOTATION_PATH,
    base_dir: Path = Path("."),
    strategies: Sequence[StrategySpec] = DEFAULT_STRATEGIES,
    iou_thresholds: Sequence[float] = DEFAULT_IOU_THRESHOLDS,
    conf_thresholds: Sequence[float] = DEFAULT_CONF_THRESHOLDS,
    dedupe_iou: float = 0.5,
    detector_factory: Callable[[], YuNetFaceDetector] = YuNetFaceDetector,
) -> dict[str, Any]:
    data = load_annotations(annotations_path)
    validation = validate_annotations(data, base_dir=base_dir)
    if not validation["ok"]:
        raise ValueError("Annotation validation failed: " + "; ".join(validation["errors"][:10]))

    frames = data.get("frames", [])
    out: dict[str, Any] = {
        "meta": {
            "task": "TASK-17",
            "generated_at_utc": _now_iso(),
            "annotations_path": str(annotations_path),
            "qa_status": "NOT_REVIEWED",
            "exploratory_only": True,
            "warning": "Exploratory benchmark on synthetic NOT_REVIEWED annotations. Do not treat as production/real-CCTV accuracy.",
            "iou_thresholds": list(iou_thresholds),
            "confidence_thresholds": list(conf_thresholds),
            "dedupe_iou": dedupe_iou,
            "strategies": [s.__dict__ for s in strategies],
        },
        "validation": validation,
        "strategies": {},
    }

    for spec in strategies:
        detector = detector_factory()
        strat_res: dict[str, Any] = {
            "description": spec.description,
            "by_confidence": {},
        }
        # AP calculation at IoU=0.50 across all GT boxes, using prediction confidence ranking
        ap_rows = []
        total_gt = 0
        for frame in frames:
            img_path = (base_dir / frame["derived_image_path"]).resolve()
            img = cv2.imread(str(img_path))
            if img is None:
                raise RuntimeError(f"Could not read {img_path}")
            run = run_strategy(img, detector, spec, dedupe_iou=dedupe_iou)
            gts = [list(map(float, b["bbox"])) for b in frame.get("faces", [])]
            preds = [list(map(float, d.bbox)) for d in run["final"]]
            confs = [float(d.confidence) for d in run["final"]]
            total_gt += len(gts)
            # for AP@0.5
            m = match_one_to_one(gts, preds, 0.5)
            matched_pred = {mm["pred_index"]: mm["iou"] for mm in m["matches"]}
            for pi, conf in enumerate(confs):
                ap_rows.append({"confidence": conf, "is_tp": pi in matched_pred, "frame": frame["clip_id"] + ":" + str(frame["frame_index"])})
            # store per-frame for later per-conf aggregation
            frame["_cache_"+spec.name] = {
                "gts": gts, "preds": preds, "confs": confs, "run": run,
                "clip_id": frame["clip_id"], "frame_index": frame["frame_index"], "no_face": bool(frame.get("no_face")),
            }

        # compute AP@0.5
        ap_rows.sort(key=lambda r: (-r["confidence"], r["frame"]))
        tp_cum = fp_cum = 0
        recalls, precisions = [], []
        for r in ap_rows:
            if r["is_tp"]:
                tp_cum += 1
            else:
                fp_cum += 1
            recalls.append(tp_cum / total_gt if total_gt else 0.0)
            precisions.append(tp_cum / (tp_cum + fp_cum) if (tp_cum + fp_cum) else 0.0)
        ap50 = voc_ap(recalls, precisions) if total_gt > 0 else None
        strat_res["ap50"] = ap50
        strat_res["ap50_note"] = "VOC-style all-point AP at IoU=0.50 over annotated boxes; exploratory/NOT_REVIEWED synthetic GT."

        for conf_thr in conf_thresholds:
            by_iou = {}
            for iou_thr in iou_thresholds:
                accum = {
                    "tp": 0, "fp": 0, "fn": 0,
                    "gt_boxes": 0, "pred_boxes": 0,
                    "matched_ious": [],
                    "no_face_frames": 0, "no_face_fp_frames": 0, "no_face_fp_boxes": 0,
                    "latencies_ms": [], "fallback_triggered": 0, "frames": 0,
                    "per_clip": {},
                    "per_frame": [],
                }
                for frame in frames:
                    cache = frame["_cache_"+spec.name]
                    gts = cache["gts"]
                    preds_all = cache["preds"]
                    confs_all = cache["confs"]
                    keep = [i for i, c in enumerate(confs_all) if c >= conf_thr]
                    preds = [preds_all[i] for i in keep]
                    confs = [confs_all[i] for i in keep]
                    m = match_one_to_one(gts, preds, iou_thr)
                    tp = len(m["matches"]); fp = len(m["unmatched_pred"]); fn = len(m["unmatched_gt"])
                    accum["tp"] += tp; accum["fp"] += fp; accum["fn"] += fn
                    accum["gt_boxes"] += len(gts); accum["pred_boxes"] += len(preds)
                    accum["matched_ious"].extend([mm["iou"] for mm in m["matches"]])
                    accum["latencies_ms"].append(cache["run"]["total_ms"])
                    accum["fallback_triggered"] += 1 if cache["run"]["fallback_triggered"] else 0
                    accum["frames"] += 1
                    is_no_face = bool(frame.get("no_face"))
                    if is_no_face:
                        accum["no_face_frames"] += 1
                        if len(preds) > 0:
                            accum["no_face_fp_frames"] += 1
                            accum["no_face_fp_boxes"] += len(preds)
                    clip = cache["clip_id"]
                    pc = accum["per_clip"].setdefault(clip, {"tp":0,"fp":0,"fn":0,"gt_boxes":0,"pred_boxes":0,"frames":0,"no_face_frames":0,"no_face_fp_frames":0,"no_face_fp_boxes":0,"latencies_ms":[],"fallback_triggered":0})
                    pc["tp"]+=tp; pc["fp"]+=fp; pc["fn"]+=fn; pc["gt_boxes"]+=len(gts); pc["pred_boxes"]+=len(preds); pc["frames"]+=1
                    pc["latencies_ms"].append(cache["run"]["total_ms"]); pc["fallback_triggered"] += 1 if cache["run"]["fallback_triggered"] else 0
                    if is_no_face:
                        pc["no_face_frames"] += 1
                        if len(preds)>0: pc["no_face_fp_frames"]+=1; pc["no_face_fp_boxes"]+=len(preds)
                    accum["per_frame"].append({
                        "clip_id": clip, "frame_index": cache["frame_index"], "no_face": is_no_face,
                        "gt_boxes": len(gts), "pred_boxes": len(preds), "tp": tp, "fp": fp, "fn": fn,
                        "mean_iou_matched": float(np.mean([mm["iou"] for mm in m["matches"]])) if m["matches"] else None,
                        "fallback_triggered": cache["run"]["fallback_triggered"], "fallback_reason": cache["run"]["fallback_reason"],
                        "latency_ms": cache["run"]["total_ms"],
                    })

                prf = compute_prf(accum["tp"], accum["fp"], accum["fn"])
                by_iou[str(iou_thr)] = {
                    "iou_threshold": iou_thr,
                    "box_level": {
                        **prf,
                        "tp": accum["tp"], "fp": accum["fp"], "fn": accum["fn"],
                        "gt_boxes": accum["gt_boxes"], "pred_boxes": accum["pred_boxes"],
                        "mean_matched_iou": float(np.mean(accum["matched_ious"])) if accum["matched_ious"] else None,
                    },
                    "no_face": {
                        "frames": accum["no_face_frames"],
                        "fp_frames": accum["no_face_fp_frames"],
                        "fp_boxes": accum["no_face_fp_boxes"],
                        "false_positive_frame_rate": (accum["no_face_fp_frames"]/accum["no_face_frames"]) if accum["no_face_frames"] else None,
                    },
                    "latency": {
                        "mean_ms": float(np.mean(accum["latencies_ms"])) if accum["latencies_ms"] else None,
                        "p95_ms": float(np.percentile(accum["latencies_ms"],95)) if accum["latencies_ms"] else None,
                    },
                    "fallback_rate": (accum["fallback_triggered"]/accum["frames"]) if accum["frames"] else None,
                    "per_clip": {
                        c: {
                            **compute_prf(pc["tp"],pc["fp"],pc["fn"]),
                            "tp":pc["tp"],"fp":pc["fp"],"fn":pc["fn"],"gt_boxes":pc["gt_boxes"],"pred_boxes":pc["pred_boxes"],
                            "frames":pc["frames"],"no_face_frames":pc["no_face_frames"],"no_face_fp_frames":pc["no_face_fp_frames"],"no_face_fp_boxes":pc["no_face_fp_boxes"],
                            "mean_latency_ms": float(np.mean(pc["latencies_ms"])) if pc["latencies_ms"] else None,
                            "fallback_rate": (pc["fallback_triggered"]/pc["frames"]) if pc["frames"] else None,
                        } for c,pc in accum["per_clip"].items()
                    },
                    "per_frame": accum["per_frame"],
                }
            strat_res["by_confidence"][str(conf_thr)] = by_iou

        # cleanup frame cache for this strategy
        for frame in frames:
            frame.pop("_cache_"+spec.name, None)

        out["strategies"][spec.name] = strat_res

    out["comparison"] = build_comparison(out)
    return out


def build_comparison(report: dict[str, Any]) -> dict[str, Any]:
    # compare at conf=0.5, iou=0.5 if present
    conf = "0.5" if "0.5" in next(iter(report["strategies"].values()))["by_confidence"] else next(iter(next(iter(report["strategies"].values()))["by_confidence"].keys()))
    iou = "0.5"
    rows = []
    for name, s in report["strategies"].items():
        m = s["by_confidence"].get(conf, {}).get(iou)
        if not m: continue
        b = m["box_level"]
        rows.append({
            "strategy": name,
            "conf_threshold": float(conf),
            "iou_threshold": float(iou),
            "precision": b["precision"], "recall": b["recall"], "f1": b["f1"],
            "mean_matched_iou": b["mean_matched_iou"],
            "no_face_fp_frame_rate": m["no_face"]["false_positive_frame_rate"],
            "mean_latency_ms": m["latency"]["mean_ms"],
            "fallback_rate": m["fallback_rate"],
            "ap50": s.get("ap50"),
        })
    rows.sort(key=lambda r: (-(r["f1"] or -1), -(r["recall"] or -1), r["mean_latency_ms"] or 1e9))
    return {"primary_thresholds": {"confidence": float(conf), "iou": float(iou)}, "rows": rows}
