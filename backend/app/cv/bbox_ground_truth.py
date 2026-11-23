"""Isolated bbox ground-truth contract, validator, and evaluation helpers.

TASK 08: readiness/spec only. NOT wired into production CV pipeline.
No automatic labels are treated as ground truth; annotations must be explicit.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

BBOX_FORMAT = "xywh_pixels_top_left"
VISIBILITY = {"visible", "partial", "occluded", "unknown"}
POSE = {"frontal", "angled", "profile", "back", "unknown"}
FACE_SIZE = {"small", "medium", "large", "unknown"}
DIFFICULTY = {"easy", "medium", "hard", "ignore"}


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def load_annotation_file(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Annotation file must be a JSON object")
    return data


def validate_bbox(bbox: Any, *, frame_w: int | None = None, frame_h: int | None = None, path: str = "bbox") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(_is_number(x) for x in bbox):
        return [ValidationIssue(path, "bbox must be [x,y,w,h] numeric")]
    x, y, w, h = [float(v) for v in bbox]
    if w <= 0 or h <= 0:
        issues.append(ValidationIssue(path, "bbox width/height must be > 0"))
    if x < 0 or y < 0:
        issues.append(ValidationIssue(path, "bbox x/y must be >= 0"))
    if frame_w is not None and frame_h is not None:
        if x + w > frame_w + 1e-6 or y + h > frame_h + 1e-6:
            issues.append(ValidationIssue(path, f"bbox exceeds frame bounds {frame_w}x{frame_h}"))
    return issues


def validate_annotation_document(doc: dict[str, Any], *, known_clips: dict[str, dict[str, Any]] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in ["schema_version", "dataset_id", "annotation_type", "clips"]:
        if key not in doc:
            issues.append(ValidationIssue(key, "required field missing"))
    if doc.get("annotation_type") not in {None, "face_bbox_ground_truth"}:
        issues.append(ValidationIssue("annotation_type", "must be 'face_bbox_ground_truth'"))
    clips = doc.get("clips")
    if not isinstance(clips, list):
        return issues + [ValidationIssue("clips", "must be a list")]
    seen_ann_ids: set[str] = set()
    for i, clip in enumerate(clips):
        cp = f"clips[{i}]"
        if not isinstance(clip, dict):
            issues.append(ValidationIssue(cp, "clip entry must be object"))
            continue
        clip_id = clip.get("clip_id")
        if not isinstance(clip_id, str) or not clip_id:
            issues.append(ValidationIssue(f"{cp}.clip_id", "clip_id must be non-empty string"))
            continue
        ref = (known_clips or {}).get(clip_id)
        frame_count = clip.get("frame_count")
        if ref is not None:
            expected = ref.get("frame_count")
            if frame_count != expected:
                issues.append(ValidationIssue(f"{cp}.frame_count", f"must match manifest frame_count {expected}"))
        if not _is_int(frame_count) or frame_count <= 0:
            issues.append(ValidationIssue(f"{cp}.frame_count", "frame_count must be positive int"))
        frames = clip.get("frames")
        if not isinstance(frames, list):
            issues.append(ValidationIssue(f"{cp}.frames", "frames must be list"))
            continue
        seen_frames: set[int] = set()
        for j, fr in enumerate(frames):
            fp = f"{cp}.frames[{j}]"
            if not isinstance(fr, dict):
                issues.append(ValidationIssue(fp, "frame entry must be object"))
                continue
            fn = fr.get("frame_number")
            if not _is_int(fn) or fn < 0:
                issues.append(ValidationIssue(f"{fp}.frame_number", "frame_number must be int >= 0"))
                continue
            if _is_int(frame_count) and fn >= frame_count:
                issues.append(ValidationIssue(f"{fp}.frame_number", f"frame_number {fn} out of range for frame_count {frame_count}"))
            if fn in seen_frames:
                issues.append(ValidationIssue(f"{fp}.frame_number", f"duplicate frame_number {fn} in clip {clip_id}"))
            seen_frames.add(fn)
            faces = fr.get("faces", [])
            if not isinstance(faces, list):
                issues.append(ValidationIssue(f"{fp}.faces", "faces must be list"))
                continue
            for k, face in enumerate(faces):
                ap = f"{fp}.faces[{k}]"
                if not isinstance(face, dict):
                    issues.append(ValidationIssue(ap, "face annotation must be object"))
                    continue
                ann_id = face.get("annotation_id")
                if not isinstance(ann_id, str) or not ann_id:
                    issues.append(ValidationIssue(f"{ap}.annotation_id", "annotation_id must be non-empty string"))
                elif ann_id in seen_ann_ids:
                    issues.append(ValidationIssue(f"{ap}.annotation_id", f"duplicate annotation_id {ann_id}"))
                else:
                    seen_ann_ids.add(ann_id)
                issues.extend(validate_bbox(face.get("bbox"), frame_w=clip.get("width"), frame_h=clip.get("height"), path=f"{ap}.bbox"))
                for field, allowed in [("visibility", VISIBILITY), ("pose", POSE), ("face_size", FACE_SIZE), ("difficulty", DIFFICULTY)]:
                    val = face.get(field, "unknown")
                    if val not in allowed:
                        issues.append(ValidationIssue(f"{ap}.{field}", f"invalid {field}: {val!r}"))
                if "ignore" in face and not isinstance(face["ignore"], bool):
                    issues.append(ValidationIssue(f"{ap}.ignore", "ignore must be bool"))
                conf = face.get("annotator_confidence")
                if conf is not None and (not _is_number(conf) or not (0.0 <= float(conf) <= 1.0)):
                    issues.append(ValidationIssue(f"{ap}.annotator_confidence", "annotator_confidence must be 0..1"))
    return issues


def iou_xywh(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    ax, ay, aw, ah = [float(x) for x in a]
    bx, by, bw, bh = [float(x) for x in b]
    ax2, ay2, bx2, by2 = ax + aw, ay + ah, bx + bw, by + bh
    ix1, iy1, ix2, iy2 = max(ax, bx), max(ay, by), min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def match_detections(gts: list[dict[str, Any]], preds: list[dict[str, Any]], *, iou_threshold: float = 0.5) -> dict[str, Any]:
    # Greedy matching by IoU desc; ignores GTs marked ignore/difficult=ignore.
    active_gts = [(i, g) for i, g in enumerate(gts) if not g.get("ignore") and g.get("difficulty") != "ignore"]
    ignored_gts = [(i, g) for i, g in enumerate(gts) if g.get("ignore") or g.get("difficulty") == "ignore"]
    candidates = []
    for pi, p in enumerate(preds):
        for gi, g in active_gts:
            score = iou_xywh(p["bbox"], g["bbox"])
            if score >= iou_threshold:
                candidates.append((score, pi, gi))
    candidates.sort(key=lambda x: (-x[0], x[1], x[2]))
    matched_p, matched_g = set(), set()
    matches = []
    for score, pi, gi in candidates:
        if pi in matched_p or gi in matched_g:
            continue
        matched_p.add(pi); matched_g.add(gi)
        matches.append({"pred_index": pi, "gt_index": gi, "iou": score})
    # Predictions matching ignored GTs are excluded from FP count.
    ignored_matched_p = set()
    for pi, p in enumerate(preds):
        if pi in matched_p:
            continue
        if any(iou_xywh(p["bbox"], g["bbox"]) >= iou_threshold for _, g in ignored_gts):
            ignored_matched_p.add(pi)
    fps = [i for i in range(len(preds)) if i not in matched_p and i not in ignored_matched_p]
    fns = [gi for gi, _ in active_gts if gi not in matched_g]
    return {
        "matches": matches,
        "false_positive_pred_indices": fps,
        "false_negative_gt_indices": fns,
        "ignored_gt_indices": [gi for gi, _ in ignored_gts],
        "ignored_matched_pred_indices": sorted(ignored_matched_p),
    }


def summarize_eval(gts: list[dict[str, Any]], preds: list[dict[str, Any]], *, iou_threshold: float = 0.5) -> dict[str, Any]:
    m = match_detections(gts, preds, iou_threshold=iou_threshold)
    tp = len(m["matches"])
    fp = len(m["false_positive_pred_indices"])
    fn = len(m["false_negative_gt_indices"])
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall and (precision + recall) else (0.0 if precision is not None and recall is not None else None)
    ious = [x["iou"] for x in m["matches"]]
    return {
        "iou_threshold": iou_threshold,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "mean_matched_iou": (sum(ious) / len(ious)) if ious else None,
        "matched_ious": ious,
        "ignored_gt_count": len(m["ignored_gt_indices"]),
        "ignored_matched_pred_count": len(m["ignored_matched_pred_indices"]),
    }
