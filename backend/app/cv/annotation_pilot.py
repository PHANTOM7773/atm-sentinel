"""TASK 09 annotation pilot contract/helpers.

Isolated from production CV pipeline. No auto ground-truth generation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PILOT_SCHEMA_VERSION = "1.0-pilot"
BBOX_FORMAT = "xywh_pixels_top_left"
VISIBILITY_VALUES = {"visible", "partially_occluded", "heavily_occluded"}
POSE_VALUES = {"front", "slight_profile", "profile", "unknown"}
FACE_SIZE_VALUES = {"small", "medium", "large"}
BLUR_VALUES = {"none", "mild", "severe"}
ILLUMINATION_VALUES = {"normal", "dark", "overexposed"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
ANNOTATION_STATUS_VALUES = {"not_annotated", "annotated", "needs_review"}
QA_STATUS_VALUES = {"NOT_REVIEWED", "REVIEW_REQUIRED", "QA_PASSED"}


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # error|warning
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "path": self.path, "message": self.message}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be object")
    return data


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_bbox(bbox: Any, *, width: int, height: int, path: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(bbox, list) or len(bbox) != 4 or not all(_is_num(x) for x in bbox):
        return [ValidationIssue("error", path, "bbox must be [x,y,w,h] numeric")]
    x, y, w, h = [float(v) for v in bbox]
    if w <= 0 or h <= 0:
        issues.append(ValidationIssue("error", path, "bbox width/height must be > 0"))
    if x < 0 or y < 0:
        issues.append(ValidationIssue("error", path, "bbox x/y must be >= 0"))
    if x + w > width + 1e-6 or y + h > height + 1e-6:
        issues.append(ValidationIssue("error", path, f"bbox exceeds image bounds {width}x{height}"))
    return issues


def validate_pilot_document(doc: dict[str, Any], *, manifest: dict[str, Any] | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    required = ["schema_version", "annotation_type", "dataset_id", "source_manifest", "frames"]
    for k in required:
        if k not in doc:
            issues.append(ValidationIssue("error", k, "required field missing"))
    if doc.get("annotation_type") != "face_bbox_ground_truth_pilot":
        issues.append(ValidationIssue("error", "annotation_type", "must be face_bbox_ground_truth_pilot"))
    if doc.get("bbox_format") not in {None, BBOX_FORMAT}:
        issues.append(ValidationIssue("error", "bbox_format", f"must be {BBOX_FORMAT}"))
    frames = doc.get("frames")
    if not isinstance(frames, list):
        return issues + [ValidationIssue("error", "frames", "frames must be list")]
    manifest_videos = (manifest or {}).get("videos", {})
    seen_frame_keys: set[tuple[str, int]] = set()
    seen_ann_ids: set[str] = set()
    for i, fr in enumerate(frames):
        fp = f"frames[{i}]"
        if not isinstance(fr, dict):
            issues.append(ValidationIssue("error", fp, "frame must be object"))
            continue
        clip_id = fr.get("clip_id")
        frame_index = fr.get("frame_index")
        if not isinstance(clip_id, str) or not clip_id:
            issues.append(ValidationIssue("error", f"{fp}.clip_id", "clip_id must be non-empty string"))
        if not _is_int(frame_index) or frame_index < 0:
            issues.append(ValidationIssue("error", f"{fp}.frame_index", "frame_index must be int >= 0"))
        key = (str(clip_id), int(frame_index) if _is_int(frame_index) else -1)
        if key in seen_frame_keys:
            issues.append(ValidationIssue("error", f"{fp}", f"duplicate frame entry {key}"))
        seen_frame_keys.add(key)
        mv = manifest_videos.get(clip_id) if isinstance(manifest_videos, dict) else None
        if manifest and mv is None:
            issues.append(ValidationIssue("error", f"{fp}.clip_id", f"clip_id {clip_id!r} not in manifest"))
        if isinstance(mv, dict):
            fc = mv.get("frame_count")
            if _is_int(frame_index) and isinstance(fc, int) and frame_index >= fc:
                issues.append(ValidationIssue("error", f"{fp}.frame_index", f"frame_index {frame_index} out of range for {clip_id} frame_count {fc}"))
        ts = fr.get("timestamp_ms")
        if ts is not None and (not _is_num(ts) or float(ts) < 0):
            issues.append(ValidationIssue("error", f"{fp}.timestamp_ms", "timestamp_ms must be non-negative number"))
        # optional expected timestamp check
        if isinstance(mv, dict) and _is_int(frame_index) and _is_num(ts):
            fps = float((manifest or {}).get("fps") or mv.get("fps") or 10)
            expected = (int(frame_index) / fps) * 1000.0
            if abs(float(ts) - expected) > 1.5:  # 1.5ms tolerance
                issues.append(ValidationIssue("warning", f"{fp}.timestamp_ms", f"timestamp_ms {ts} differs from expected {expected:.3f}"))
        status = fr.get("annotation_status", "not_annotated")
        if status not in ANNOTATION_STATUS_VALUES:
            issues.append(ValidationIssue("error", f"{fp}.annotation_status", f"invalid status {status!r}"))
        no_face = fr.get("no_face")
        if no_face is not None and not isinstance(no_face, bool):
            issues.append(ValidationIssue("error", f"{fp}.no_face", "no_face must be bool"))
        faces = fr.get("faces", [])
        if not isinstance(faces, list):
            issues.append(ValidationIssue("error", f"{fp}.faces", "faces must be list"))
            continue
        if no_face is True and len(faces) != 0:
            issues.append(ValidationIssue("error", f"{fp}.faces", "no_face=true but faces present"))
        for j, face in enumerate(faces):
            ap = f"{fp}.faces[{j}]"
            if not isinstance(face, dict):
                issues.append(ValidationIssue("error", ap, "face must be object"))
                continue
            ann_id = face.get("annotation_id")
            if not isinstance(ann_id, str) or not ann_id:
                issues.append(ValidationIssue("error", f"{ap}.annotation_id", "annotation_id must be non-empty string"))
            elif ann_id in seen_ann_ids:
                issues.append(ValidationIssue("error", f"{ap}.annotation_id", f"duplicate annotation_id {ann_id}"))
            else:
                seen_ann_ids.add(ann_id)
            w = fr.get("image_width") or (manifest or {}).get("width") or 640
            h = fr.get("image_height") or (manifest or {}).get("height") or 480
            issues.extend(validate_bbox(face.get("bbox"), width=int(w), height=int(h), path=f"{ap}.bbox"))
            checks = [
                ("visibility", VISIBILITY_VALUES),
                ("pose", POSE_VALUES),
                ("face_size", FACE_SIZE_VALUES),
                ("blur", BLUR_VALUES),
                ("illumination", ILLUMINATION_VALUES),
                ("annotation_confidence", CONFIDENCE_VALUES),
            ]
            for field, allowed in checks:
                val = face.get(field)
                if val not in allowed:
                    issues.append(ValidationIssue("error", f"{ap}.{field}", f"invalid {field}: {val!r}"))
            ig = face.get("ignore_difficult")
            if ig is not None and not isinstance(ig, bool):
                issues.append(ValidationIssue("error", f"{ap}.ignore_difficult", "ignore_difficult must be bool"))
        if status == "annotated":
            # annotated means either no_face true or at least one face; reviewed implied by human process but status captures it.
            if not no_face and len(faces) == 0:
                issues.append(ValidationIssue("warning", fp, "status annotated but no faces and no_face!=true"))
    return issues


def summarize_pilot(doc: dict[str, Any], issues: list[ValidationIssue] | None = None) -> dict[str, Any]:
    issues = issues if issues is not None else validate_pilot_document(doc)
    frames = doc.get("frames", []) if isinstance(doc.get("frames"), list) else []
    total = len(frames)
    annotated = sum(1 for f in frames if f.get("annotation_status") == "annotated")
    needs_review = sum(1 for f in frames if f.get("annotation_status") == "needs_review")
    not_annotated = sum(1 for f in frames if f.get("annotation_status", "not_annotated") == "not_annotated")
    face_boxes = 0
    no_face_frames = 0
    difficult = 0
    low_conf = 0
    cond = {"visibility": {}, "pose": {}, "face_size": {}, "blur": {}, "illumination": {}}
    for f in frames:
        faces = f.get("faces") if isinstance(f.get("faces"), list) else []
        if f.get("no_face") is True:
            no_face_frames += 1
        for face in faces:
            face_boxes += 1
            if face.get("ignore_difficult") is True:
                difficult += 1
            if face.get("annotation_confidence") == "low":
                low_conf += 1
            for k in cond:
                v = face.get(k)
                if isinstance(v, str):
                    cond[k][v] = cond[k].get(v, 0) + 1
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    return {
        "total_selected_frames": total,
        "annotated_frames": annotated,
        "unannotated_frames": not_annotated,
        "needs_review_frames": needs_review,
        "total_face_boxes": face_boxes,
        "no_face_frames": no_face_frames,
        "difficult_ignored_faces": difficult,
        "low_confidence_annotations": low_conf,
        "condition_coverage": cond,
        "validator_errors": [e.to_dict() for e in errors],
        "validator_warnings": [w.to_dict() for w in warnings],
        "qa_status": "NOT_REVIEWED",
        "benchmark_ready": False,
        "benchmark_ready_reason": "Human annotation/QA not complete; JSON validation alone is insufficient.",
    }
