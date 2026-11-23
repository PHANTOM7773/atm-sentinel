from __future__ import annotations

import json
import os
import platform
import resource
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np

from ..config import CV_OUTPUT_DIR, cv_limits
from .embeddings import EmbeddingStore
from .models import MODEL_SPECS, model_status
from .pipeline import CVPipeline
from .quality import LIMITATIONS as QUALITY_LIMITATIONS
from .runtime import RuntimeProfile

NOT_ASSESSABLE = "NOT_ASSESSABLE"
DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"
DEFAULT_HISTORICAL_JSON = Path(__file__).resolve().parents[3] / "data" / "cv" / "benchmark.json"


@dataclass(frozen=True)
class MetricResult:
    status: str  # MEASURED | NOT_ASSESSABLE | HEURISTIC | HISTORICAL | PUBLISHED_UPSTREAM
    value: Any
    reason: str = ""
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.details is None:
            payload.pop("details")
        return payload


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _label_set(value: Any) -> set[str]:
    if value is None:
        return set()
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _labels_match(a: Any, b: Any) -> bool:
    sa = _label_set(a) - {"none", "unlabelled"}
    sb = _label_set(b) - {"none", "unlabelled"}
    return bool(sa and sb and (sa & sb))


def _is_positive_label(value: Any) -> bool:
    labels = _label_set(value) - {"none", "unlabelled"}
    return bool(labels)


def load_manifest(dataset_dir: Path) -> dict[str, Any]:
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    videos = manifest.get("videos")
    if not isinstance(videos, dict) or not videos:
        raise ValueError("Manifest has no videos")
    return manifest


def validate_manifest(manifest: dict[str, Any], dataset_dir: Path) -> list[str]:
    errors: list[str] = []
    videos = manifest.get("videos")
    if not isinstance(videos, dict) or not videos:
        return ["manifest.videos must be a non-empty object"]
    for name, entry in videos.items():
        if not isinstance(entry, dict):
            errors.append(f"{name}: entry must be object")
            continue
        file_name = entry.get("file")
        if not isinstance(file_name, str) or not file_name:
            errors.append(f"{name}: missing file")
        else:
            path = dataset_dir / file_name
            if not path.exists():
                errors.append(f"{name}: missing asset {path}")
        frame_count = entry.get("frame_count")
        if not isinstance(frame_count, int) or frame_count < 0:
            errors.append(f"{name}: frame_count must be non-negative int")
        labels = entry.get("labels", {})
        if labels is not None and not isinstance(labels, dict):
            errors.append(f"{name}: labels must be object")
            continue
        for key, value in (labels or {}).items():
            try:
                idx = int(key)
            except Exception:
                errors.append(f"{name}: label key {key!r} not int-like")
                continue
            if idx < 0:
                errors.append(f"{name}: negative label index {idx}")
            if not isinstance(value, str):
                errors.append(f"{name}: label {key} must be string")
        if isinstance(frame_count, int):
            for idx in (int(k) for k in (labels or {}).keys() if str(k).lstrip("-").isdigit()):
                if idx >= frame_count:
                    errors.append(f"{name}: label index {idx} >= frame_count {frame_count}")
    return errors


def collect_environment() -> dict[str, Any]:
    ru_maxrss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes, Linux typically KiB
    peak_bytes = ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024
    return {
        "timestamp": _now_iso(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "opencv_version": cv2.__version__,
        "numpy_version": np.__version__,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "peak_rss_bytes_best_effort": peak_bytes,
        "peak_rss_note": "macOS ru_maxrss bytes; Linux ru_maxrss KiB*1024; best-effort process peak, includes test/runtime overhead.",
    }


def collect_model_provenance() -> dict[str, Any]:
    status = model_status()
    models = {}
    for key, spec in MODEL_SPECS.items():
        item = dict(status.get("models", {}).get(key, {}))
        item["expected_sha256"] = spec.sha256
        item["source_url"] = spec.source_url
        item["license"] = spec.license
        item["purpose"] = spec.purpose
        item["filename"] = spec.filename
        models[key] = item
    return {
        "directory": status.get("directory"),
        "all_usable": status.get("all_usable"),
        "models": models,
    }


def measure_model_load_times(profile: RuntimeProfile | None = None, repeats: int = 1) -> dict[str, Any]:
    from .detection import YOLOXPersonDetector, YuNetFaceDetector
    from .models import require_model
    from .runtime import create_with_fallback, facade_profile

    selected = facade_profile(profile or RuntimeProfile.from_env())
    results: dict[str, Any] = {}
    for key in ("yunet", "sface", "yolox"):
        timings_ms: list[float] = []
        error = None
        observed_runtime = None
        for _ in range(max(1, repeats)):
            started = time.perf_counter()
            try:
                if key == "yunet":
                    detector = YuNetFaceDetector(profile=selected)
                    observed_runtime = detector.profile.to_dict()
                elif key == "yolox":
                    detector = YOLOXPersonDetector(profile=selected)
                    observed_runtime = detector.profile.to_dict()
                else:
                    model_path = require_model("sface")

                    def factory(chosen: RuntimeProfile):
                        return cv2.FaceRecognizerSF.create(str(model_path), "", chosen.backend_id, chosen.target_id)

                    _, sf_profile = create_with_fallback(factory, selected)
                    observed_runtime = sf_profile.to_dict()
            except Exception as exc:
                error = str(exc)
                break
            timings_ms.append((time.perf_counter() - started) * 1000.0)
        if error:
            results[key] = {"status": NOT_ASSESSABLE, "reason": error, "timings_ms": timings_ms}
        else:
            results[key] = {
                "status": "MEASURED",
                "timings_ms": [round(t, 3) for t in timings_ms],
                "mean_ms": round(float(np.mean(timings_ms)), 3),
                "min_ms": round(float(np.min(timings_ms)), 3),
                "max_ms": round(float(np.max(timings_ms)), 3),
                "runtime_profile": observed_runtime,
            }
    return results


def _safe_div(num: float, den: float) -> float | None:
    if den == 0:
        return None
    return num / den


def compute_frame_presence_metrics(expected_by_frame: dict[int, bool], predicted_by_frame: dict[int, bool]) -> dict[str, Any]:
    keys = sorted(set(expected_by_frame) | set(predicted_by_frame))
    tp = fp = fn = tn = 0
    for k in keys:
        e = bool(expected_by_frame.get(k, False))
        p = bool(predicted_by_frame.get(k, False))
        if e and p:
            tp += 1
        elif (not e) and p:
            fp += 1
        elif e and (not p):
            fn += 1
        else:
            tn += 1
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * tp, 2 * tp + fp + fn) if (2 * tp + fp + fn) else None
    return {
        "frames_evaluated": len(keys),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": None if precision is None else round(precision, 4),
        "recall": None if recall is None else round(recall, 4),
        "f1": None if f1 is None else round(f1, 4),
    }


def compute_track_metrics(track_sequences: dict[str, list[int]] | None) -> MetricResult:
    if not track_sequences:
        return MetricResult(NOT_ASSESSABLE, None, "No valid ground-truth track annotations in manifest; cannot compute ID switches/fragmentation.")
    # Minimal generic computation when GT exists: sequence of GT track IDs per frame.
    total_switches = 0
    total_fragments = 0
    details = {}
    for gt_id, pred_ids in track_sequences.items():
        filtered = [p for p in pred_ids if p is not None]
        if not filtered:
            details[gt_id] = {"switches": 0, "fragments": 0, "observed": 0}
            continue
        switches = sum(1 for a, b in zip(filtered, filtered[1:]) if a != b)
        # Fragments: number of contiguous segments in observed timeline
        fragments = 0
        in_seg = False
        for p in pred_ids:
            if p is None and in_seg:
                in_seg = False
            elif p is not None and not in_seg:
                fragments += 1
                in_seg = True
        total_switches += switches
        total_fragments += fragments
        details[gt_id] = {"switches": switches, "fragments": fragments, "observed": len(filtered)}
    return MetricResult("MEASURED", {"id_switches": total_switches, "fragments": total_fragments}, details={"per_track": details})


def compute_pair_metrics(pairs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    same = [p for p in pairs if p.get("same_subject") is True]
    diff = [p for p in pairs if p.get("same_subject") is False]
    thresholds = [round(x, 2) for x in np.linspace(0.0, 1.0, 101)]
    sweep = []
    for t in thresholds:
        tp = sum(1 for p in same if float(p["score"]) >= t)
        fn = len(same) - tp
        fp = sum(1 for p in diff if float(p["score"]) >= t)
        tn = len(diff) - fp
        tar = _safe_div(tp, tp + fn)
        far = _safe_div(fp, fp + tn)
        sweep.append({"threshold": t, "tar": tar, "far": far, "tp": tp, "fp": fp, "tn": tn, "fn": fn})
    # Equal error rate approximation
    eer = None
    eer_threshold = None
    for row in sweep:
        tar, far = row["tar"], row["far"]
        if tar is None or far is None:
            continue
        err = abs(tar - (1.0 - far))
        if eer is None or err < eer:
            eer = err
            eer_threshold = row["threshold"]
    same_scores = [float(p["score"]) for p in same]
    diff_scores = [float(p["score"]) for p in diff]
    has_pairs = bool(same or diff)
    result = {
        "status": "MEASURED" if has_pairs else NOT_ASSESSABLE,
        "same_subject_pairs": len(same),
        "different_subject_pairs": len(diff),
        "same_score_mean": round(float(np.mean(same_scores)), 6) if same_scores else None,
        "same_score_std": round(float(np.std(same_scores)), 6) if same_scores else None,
        "diff_score_mean": round(float(np.mean(diff_scores)), 6) if diff_scores else None,
        "diff_score_std": round(float(np.std(diff_scores)), 6) if diff_scores else None,
        "eer_proxy_threshold": eer_threshold,
        "eer_proxy_abs_gap": None if eer is None else round(float(eer), 6),
        "threshold_sweep": sweep,
    }
    if not has_pairs:
        result["reason"] = "No same/different labeled pair samples produced"
    return result


def compute_rank_metrics(ranking_rows: Sequence[dict[str, Any]], ks: Sequence[int] = (1, 5)) -> dict[str, Any]:
    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in ranking_rows:
        by_query.setdefault(str(row.get("query_sample_id")), []).append(row)
    for rows in by_query.values():
        rows.sort(key=lambda r: int(r.get("rank", 10**9)))
    assessed = 0
    hits = {k: 0 for k in ks}
    false_match_top1 = 0
    false_match_topk = {k: 0 for k in ks}
    query_details = []
    for qid, rows in by_query.items():
        if not rows:
            continue
        assessed += 1
        qlabel = rows[0].get("query_label")
        top1 = rows[0]
        top1_match = bool(_labels_match(qlabel, top1.get("candidate_label")))
        if not top1_match:
            false_match_top1 += 1
        for k in ks:
            k_rows = rows[:k]
            k_hit = any(_labels_match(qlabel, r.get("candidate_label")) for r in k_rows)
            if k_hit:
                hits[k] += 1
            if any(not _labels_match(qlabel, r.get("candidate_label")) and str(r.get("candidate_label")) not in {"none", "", "unlabelled"} for r in k_rows):
                false_match_topk[k] += 1
        query_details.append({"query_sample_id": qid, "query_label": qlabel, "top1_match": top1_match, "candidate_count": len(rows)})
    status = "MEASURED" if assessed else NOT_ASSESSABLE
    result = {
        "status": status,
        "queries_assessed": assessed,
        "rank_at_k": {str(k): {"hits": hits[k], "rate": round(hits[k] / assessed, 4) if assessed else None} for k in ks},
        "false_match_top1_count": false_match_top1,
        "false_match_top1_rate": round(false_match_top1 / assessed, 4) if assessed else None,
        "queries_with_any_hard_negative_in_topk": {str(k): false_match_topk[k] for k in ks},
        "query_details": query_details,
    }
    if not assessed:
        result["reason"] = "No ranking queries assessed"
    return result


def compute_best_face_stats(analyses: Sequence[dict[str, Any]]) -> dict[str, Any]:
    # Heuristic/operational stats only; no GT best-face agreement.
    selected_scores = []
    quality_scores = []
    by_clip = {}
    for clip in analyses:
        faces = []
        for frame in clip.get("frames", []):
            for face in frame.get("faces", []):
                q = (face.get("quality") or {}).get("quality_score")
                if q is not None:
                    quality_scores.append(float(q))
                    faces.append(face)
        if not faces:
            by_clip[clip.get("source_id")] = {"face_count": 0, "selected": None}
            continue
        faces_sorted = sorted(faces, key=lambda f: (-float((f.get("quality") or {}).get("quality_score") or 0.0), int(f.get("frame_number", 0)), str(f.get("sample_id"))))
        best = faces_sorted[0]
        score = float((best.get("quality") or {}).get("quality_score") or 0.0)
        selected_scores.append(score)
        by_clip[clip.get("source_id")] = {
            "face_count": len(faces),
            "selected_sample_id": best.get("sample_id"),
            "selected_frame_number": best.get("frame_number"),
            "selected_quality_score": score,
        }
    def _stats(vals):
        if not vals:
            return None
        arr = np.asarray(vals, dtype=np.float32)
        return {"count": int(arr.size), "mean": round(float(arr.mean()), 3), "std": round(float(arr.std()), 3), "min": round(float(arr.min()), 3), "p50": round(float(np.median(arr)), 3), "max": round(float(arr.max()), 3)}
    return {
        "status": "HEURISTIC",
        "reason": "No ground-truth best-face annotations; reports existing quality/best-face selection outcomes only.",
        "all_face_quality": _stats(quality_scores),
        "selected_best_face_quality": _stats(selected_scores),
        "by_clip": by_clip,
    }


def _frame_label(entry: dict[str, Any], frame_number: int) -> str | None:
    labels = entry.get("labels") or {}
    raw = labels.get(str(frame_number))
    if raw is None:
        raw = labels.get(frame_number)
    return str(raw) if raw is not None else None


def evaluate_dataset(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    max_frames: int | None = None,
    frame_stride: int = 1,
    top_k: int = 5,
    warmup_runs: int = 0,
    measurement_runs: int = 1,
    include_load_timing: bool = True,
    load_timing_repeats: int = 1,
    pipeline_factory=CVPipeline,
) -> dict[str, Any]:
    started = time.perf_counter()
    manifest = load_manifest(dataset_dir)
    validation_errors = validate_manifest(manifest, dataset_dir)
    if validation_errors:
        raise ValueError("Invalid manifest: " + "; ".join(validation_errors))

    env = collect_environment()
    models = collect_model_provenance()
    limits = cv_limits()
    run_meta = {
        "benchmark_name": "atm-sentinel-cv-baseline",
        "benchmark_version": "task02-v1",
        "generated_at": _now_iso(),
        "dataset_dir": str(dataset_dir),
        "dataset_manifest": str(dataset_dir / "manifest.json"),
        "dataset_notice": manifest.get("notice"),
        "synthetic_only": bool(manifest.get("synthetic", False)),
        "real_people": bool(manifest.get("real_people", False)),
        "config": {
            "max_frames": max_frames,
            "frame_stride": frame_stride,
            "top_k": top_k,
            "warmup_runs": warmup_runs,
            "measurement_runs": measurement_runs,
            "include_load_timing": include_load_timing,
            "load_timing_repeats": load_timing_repeats,
        },
        "cv_limits": limits,
        "quality_limitations": QUALITY_LIMITATIONS,
        "disclaimer": "Candidate-only CV benchmark on synthetic/sample assets. No identity confirmation. Not real-world accuracy evidence.",
    }

    load_timing = measure_model_load_times(repeats=load_timing_repeats) if include_load_timing else {"status": NOT_ASSESSABLE, "reason": "disabled"}

    # warmup
    warmup = {"runs": warmup_runs, "status": "SKIPPED" if warmup_runs <= 0 else "MEASURED", "clips": []}
    for wi in range(max(0, warmup_runs)):
        with tempfile.TemporaryDirectory(prefix=f"cv-bench-warmup-{wi}-") as td:
            p = pipeline_factory(output_dir=Path(td))
            for name, entry in manifest["videos"].items():
                labels = {int(k): v for k, v in (entry.get("labels") or {}).items()}
                p.reset_trackers()
                p.analyze_video(
                    dataset_dir / entry["file"],
                    case_id=f"bench-warmup-{wi}",
                    source_id=name,
                    max_frames=max_frames or entry.get("frame_count"),
                    frame_stride=frame_stride,
                    save_crops=False,
                    add_to_index=False,
                    labels=labels,
                )
                warmup["clips"].append({"run": wi, "source_id": name})

    clip_runs: list[dict[str, Any]] = []
    ranking_rows: list[dict[str, Any]] = []
    pair_samples: list[dict[str, Any]] = []

    for run_idx in range(max(1, measurement_runs)):
        with tempfile.TemporaryDirectory(prefix=f"cv-bench-run-{run_idx}-") as td:
            run_dir = Path(td)
            pipeline = pipeline_factory(output_dir=run_dir)
            query_analyses = {}
            for name, entry in manifest["videos"].items():
                labels = {int(k): v for k, v in (entry.get("labels") or {}).items()}
                pipeline.reset_trackers()
                t0 = time.perf_counter()
                analysis = pipeline.analyze_video(
                    dataset_dir / entry["file"],
                    case_id=f"bench-run-{run_idx}",
                    source_id=name,
                    max_frames=max_frames or entry.get("frame_count"),
                    frame_stride=frame_stride,
                    save_crops=False,
                    add_to_index=False,
                    labels=labels,
                )
                wall_ms = (time.perf_counter() - t0) * 1000.0
                clip_runs.append({
                    "run": run_idx,
                    "source_id": name,
                    "file": entry.get("file"),
                    "frame_count": entry.get("frame_count"),
                    "description": entry.get("description"),
                    "analysis": analysis.to_dict(),
                    "wall_ms": round(wall_ms, 3),
                })
                # indexing for ranking/pairs: exclude no_face; keep other synthetic clips
                if name != "no_face":
                    pipeline.reset_trackers()
                    gallery_analysis = pipeline.analyze_video(
                        dataset_dir / entry["file"],
                        case_id=f"bench-rank-{run_idx}",
                        source_id=name,
                        max_frames=max_frames or entry.get("frame_count"),
                        frame_stride=frame_stride,
                        save_crops=False,
                        add_to_index=True,
                        labels=labels,
                        cv_run_id=f"bench-rank-{run_idx}-{name}",
                        video_id=name,
                    )
                    staged = pipeline.staged_embeddings()
                    if staged:
                        pipeline.store.publish_staged_records(staged)
                    pipeline._staged_embeddings = []  # benchmark-only: prevent cross-analysis duplicate staging in same temp pipeline
                    if name == "subject_a_side":
                        query_analyses[name] = gallery_analysis

            # Ranking: query clips against isolated gallery excluding query clip
            for qname, qanalysis in query_analyses.items():
                for frame in qanalysis.frames:
                    for face in frame.faces:
                        vector = face.get("embedding")
                        if not vector:
                            continue
                        results = pipeline.store.search(
                            np.asarray(vector, dtype=np.float32),
                            case_id=f"bench-rank-{run_idx}",
                            top_k=top_k,
                            exclude_sample_id=face.get("sample_id"),
                            exclude_source_id=qname,
                        )
                        for rank, item in enumerate(results, start=1):
                            md = item.get("metadata") or {}
                            ranking_rows.append({
                                "run": run_idx,
                                "query_source_id": qname,
                                "query_sample_id": face.get("sample_id"),
                                "query_label": face.get("synthetic_label"),
                                "rank": rank,
                                "candidate_sample_id": md.get("sample_id"),
                                "candidate_source_id": md.get("source_id"),
                                "candidate_label": md.get("synthetic_label"),
                                "similarity": item.get("cosine_similarity"),
                            })
                        qlabel = face.get("synthetic_label")
                        for item in results:
                            md = item.get("metadata") or {}
                            clabel = md.get("synthetic_label")
                            if not _is_positive_label(qlabel) or not _is_positive_label(clabel):
                                continue
                            pair_samples.append({
                                "run": run_idx,
                                "query_sample_id": face.get("sample_id"),
                                "candidate_sample_id": md.get("sample_id"),
                                "query_label": qlabel,
                                "candidate_label": clabel,
                                "score": float(item.get("cosine_similarity")),
                                "same_subject": bool(_labels_match(qlabel, clabel)),
                            })

    # Aggregate per-clip metrics across runs
    by_clip: dict[str, list[dict[str, Any]]] = {}
    for row in clip_runs:
        by_clip.setdefault(row["source_id"], []).append(row)

    clip_metrics = {}
    for name, rows in by_clip.items():
        entry = manifest["videos"][name]
        labels = {int(k): v for k, v in (entry.get("labels") or {}).items()}
        frame_count = int(entry.get("frame_count", 0))
        # face frame presence ground truth exists for these synthetic manifest labels
        expected_face_presence = {i: _is_positive_label(labels.get(i)) for i in range(frame_count)}
        # predicted presence from first run is representative for deterministic pipeline; also aggregate
        run_presence = []
        person_expected = {i: _is_positive_label(labels.get(i)) for i in range(frame_count)}
        person_run_presence = []
        recall_runs = []
        person_recall_runs = []
        latency_runs = []
        fps_runs = []
        quality_means = []
        track_stability = []
        for row in rows:
            analysis = row["analysis"]
            pred_face = {int(f["frame_number"]): bool(f.get("faces")) for f in analysis.get("frames", [])}
            pred_person = {int(f["frame_number"]): bool(f.get("persons")) for f in analysis.get("frames", [])}
            # fill missing frames as false (not analyzed in stride/max cases) only if within analyzed range
            for i in range(frame_count):
                pred_face.setdefault(i, False)
                pred_person.setdefault(i, False)
            m_face = compute_frame_presence_metrics(expected_face_presence, pred_face)
            m_person = compute_frame_presence_metrics(person_expected, pred_person)
            run_presence.append(m_face)
            person_run_presence.append(m_person)
            # recall by labeled-positive frames only
            pos_frames = [i for i, v in expected_face_presence.items() if v]
            if pos_frames:
                hit = sum(1 for i in pos_frames if pred_face.get(i))
                recall_runs.append(hit / len(pos_frames))
            person_pos = [i for i, v in person_expected.items() if v]
            if person_pos:
                phit = sum(1 for i in person_pos if pred_person.get(i))
                person_recall_runs.append(phit / len(person_pos))
            summary = analysis.get("summary", {})
            if summary.get("average_frame_ms") is not None:
                latency_runs.append(float(summary["average_frame_ms"]))
            if summary.get("estimated_fps") is not None:
                fps_runs.append(float(summary["estimated_fps"]))
            if summary.get("average_face_quality") is not None:
                quality_means.append(float(summary["average_face_quality"]))
            track_stability.append({
                "unique_face_tracks": summary.get("unique_face_tracks"),
                "unique_person_tracks": summary.get("unique_person_tracks"),
                "face_detections": summary.get("face_detections"),
                "person_detections": summary.get("person_detections"),
            })

        def agg_metric(dicts, key):
            vals = [d.get(key) for d in dicts if d.get(key) is not None]
            return round(float(np.mean(vals)), 4) if vals else None

        clip_metrics[name] = {
            "runs": len(rows),
            "ground_truth": {
                "face_frame_presence_labels": "present_in_manifest_labels" if labels else NOT_ASSESSABLE,
                "person_bbox_or_track_gt": NOT_ASSESSABLE,
                "identity_labels": "synthetic_labels_present" if any(_is_positive_label(v) for v in labels.values()) else NOT_ASSESSABLE,
            },
            "face_detection_frame_presence": {
                "status": "MEASURED" if labels else NOT_ASSESSABLE,
                "precision_mean": agg_metric(run_presence, "precision"),
                "recall_mean": agg_metric(run_presence, "recall"),
                "f1_mean": agg_metric(run_presence, "f1"),
                "tp_mean": agg_metric(run_presence, "tp"),
                "fp_mean": agg_metric(run_presence, "fp"),
                "fn_mean": agg_metric(run_presence, "fn"),
                "tn_mean": agg_metric(run_presence, "tn"),
                "note": "Frame-presence metric using manifest labels; not box-level IoU mAP. Multi-face frame counted as present if any face detected.",
            } if labels else MetricResult(NOT_ASSESSABLE, None, "No frame labels").to_dict(),
            "person_detection_frame_presence": {
                "status": "HEURISTIC" if labels else NOT_ASSESSABLE,
                "precision_mean": agg_metric(person_run_presence, "precision"),
                "recall_mean": agg_metric(person_run_presence, "recall"),
                "f1_mean": agg_metric(person_run_presence, "f1"),
                "note": "Uses manifest face-presence labels as weak proxy for person presence in synthetic clips; YOLOX person GT boxes/tracks unavailable. Treat as heuristic, not person detector accuracy.",
            } if labels else MetricResult(NOT_ASSESSABLE, None, "No labels").to_dict(),
            "latency": {
                "status": "MEASURED",
                "avg_frame_ms_mean": round(float(np.mean(latency_runs)), 3) if latency_runs else None,
                "avg_frame_ms_std": round(float(np.std(latency_runs)), 3) if latency_runs else None,
                "estimated_fps_mean": round(float(np.mean(fps_runs)), 3) if fps_runs else None,
            },
            "quality": {
                "status": "HEURISTIC",
                "average_face_quality_mean": round(float(np.mean(quality_means)), 3) if quality_means else None,
                "note": "Existing heuristic quality score; not calibrated ground truth.",
            },
            "track_stability": {
                "status": "MEASURED",
                "runs": track_stability,
                "note": "Unique track counts/detections are measured; ID switches/fragmentation vs GT are NOT_ASSESSABLE because manifest has no track GT.",
            },
        }

    tracking_gt = compute_track_metrics(None)
    ranking_metrics = compute_rank_metrics(ranking_rows, ks=(1, 5)) if ranking_rows else {"status": NOT_ASSESSABLE, "reason": "No ranking rows produced"}
    pair_metrics = compute_pair_metrics(pair_samples) if pair_samples else {"status": NOT_ASSESSABLE, "reason": "No same/different pair samples produced"}

    # Best-face stats from measurement analyses
    best_face = compute_best_face_stats([r["analysis"] for r in clip_runs if r["run"] == 0])

    report = {
        "meta": run_meta,
        "environment": env,
        "model_provenance": models,
        "model_load_timing": load_timing,
        "warmup": warmup,
        "dataset": {
            "manifest_path": str(dataset_dir / "manifest.json"),
            "videos": {k: {"file": v.get("file"), "frame_count": v.get("frame_count"), "description": v.get("description"), "has_labels": bool(v.get("labels"))} for k, v in manifest["videos"].items()},
            "validation_errors": [],
        },
        "metrics": {
            "detection": {
                "face_frame_presence": {name: m["face_detection_frame_presence"] for name, m in clip_metrics.items()},
                "person_frame_presence_proxy": {name: m["person_detection_frame_presence"] for name, m in clip_metrics.items()},
                "notes": [
                    "Box-level precision/recall/mAP NOT_ASSESSABLE: manifest provides frame labels, not bounding boxes.",
                    "Person metrics are heuristic proxies only where synthetic labels are used as presence proxy.",
                ],
            },
            "tracking": {
                "id_switches_fragmentation": tracking_gt.to_dict(),
                "track_stability": {name: m["track_stability"] for name, m in clip_metrics.items()},
            },
            "recognition_ranking": {
                "status": "MEASURED" if ranking_rows else NOT_ASSESSABLE,
                "rank_metrics": ranking_metrics,
                "pair_metrics": pair_metrics,
                "rows": ranking_rows,
                "notes": [
                    "Uses existing synthetic manifest labels and current SFace+EmbeddingStore.search behavior.",
                    "Synthetic-only; not real-world accuracy or identity evidence.",
                    "Only clips with labels and embeddings contribute; missing labels/pairs are excluded and reported.",
                ],
            },
            "quality_best_face": best_face,
            "runtime_resources": {
                "status": "MEASURED",
                "per_clip_latency": {name: m["latency"] for name, m in clip_metrics.items()},
                "process_peak_rss_bytes_best_effort": env["peak_rss_bytes_best_effort"],
                "note": env["peak_rss_note"],
            },
        },
        "historical_reference": _load_historical_reference(),
        "published_upstream_claims": {
            "status": "PUBLISHED_UPSTREAM",
            "note": "Not measured locally in this run. See docs/CV_MODEL_SELECTION.md and model cards/papers for upstream claims; treat as non-local evidence.",
        },
        "raw_runs": clip_runs,
        "completed_at": _now_iso(),
        "duration_ms": round((time.perf_counter() - started) * 1000.0, 3),
    }
    return report


def _load_historical_reference() -> dict[str, Any]:
    if not DEFAULT_HISTORICAL_JSON.exists():
        return {"status": NOT_ASSESSABLE, "reason": f"Missing {DEFAULT_HISTORICAL_JSON}"}
    try:
        data = json.loads(DEFAULT_HISTORICAL_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": NOT_ASSESSABLE, "reason": f"Failed reading historical benchmark: {exc}"}
    return {
        "status": "HISTORICAL",
        "path": str(DEFAULT_HISTORICAL_JSON),
        "generated_at": data.get("generated_at"),
        "opencv_version": data.get("opencv_version"),
        "ranking_methodology": data.get("ranking_methodology"),
        "note": "Historical artifact from previous benchmark script run; not regenerated in this task.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    env = report["environment"]
    prov = report["model_provenance"]
    lines = []
    lines.append(f"# ATM Sentinel CV Baseline Benchmark (Task 02)")
    lines.append("")
    lines.append(f"Generated: `{meta['generated_at']}`")
    lines.append("")
    lines.append("> Synthetic/sample-only baseline. Candidate-only outputs. No identity confirmation. No real CCTV/R4C validation.")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append(f"- Dataset: `{meta['dataset_dir']}` (manifest `{meta['dataset_manifest']}`)")
    lines.append(f"- Runs: warmup={meta['config']['warmup_runs']}, measurement={meta['config']['measurement_runs']}, stride={meta['config']['frame_stride']}, top_k={meta['config']['top_k']}")
    lines.append("- Pipeline: existing `CVPipeline` with current YOLOX/YuNet/SimpleTracker/SFace/quality/best-face behavior; no model/config threshold changes.")
    lines.append("- No prohibited scripts run. No source assets, DB, evidence, exports, or embedding generations modified.")
    lines.append("")
    lines.append("## Environment")
    lines.append("")
    lines.append(f"- Platform: {env['platform']} / {env['machine']}")
    lines.append(f"- Python: {env['python_version']} ({env['python_implementation']})")
    lines.append(f"- OpenCV: {env['opencv_version']} | NumPy: {env['numpy_version']}")
    lines.append(f"- Peak RSS (best effort): {env['peak_rss_bytes_best_effort']} bytes ({env['peak_rss_note']})")
    lines.append("")
    lines.append("## Model Provenance")
    lines.append("")
    lines.append("| Model | File | SHA256 | Expected | Verification | License |")
    lines.append("|---|---|---|---|---|---|")
    for k, m in prov.get("models", {}).items():
        lines.append(f"| {k} | `{m.get('filename','')}` | `{m.get('sha256','')}` | `{m.get('expected_sha256','')}` | {m.get('verification','')} | {m.get('license','')} |")
    lines.append("")
    lines.append("## Measured / Heuristic / Not Assessable")
    lines.append("")
    det = report["metrics"]["detection"]
    lines.append("### Detection (frame presence)")
    lines.append("")
    lines.append("| Clip | Face P | Face R | Face F1 | Person P (heuristic proxy) | Person R (heuristic proxy) |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for clip in report["dataset"]["videos"].keys():
        f = det["face_frame_presence"].get(clip, {})
        p = det["person_frame_presence_proxy"].get(clip, {})
        lines.append(f"| {clip} | {f.get('precision_mean')} | {f.get('recall_mean')} | {f.get('f1_mean')} | {p.get('precision_mean')} | {p.get('recall_mean')} |")
    lines.append("")
    lines.append("> Box-level detection mAP/IoU: **NOT_ASSESSABLE** (manifest has no bounding-box GT). Person proxy uses face-presence labels only; heuristic.")
    lines.append("")
    tr = report["metrics"]["tracking"]["id_switches_fragmentation"]
    lines.append("### Tracking")
    lines.append("")
    lines.append(f"- ID switches/fragmentation vs GT: **{tr.get('status')}** — {tr.get('reason','')}")
    lines.append("- Track stability counts measured per clip; see JSON for details.")
    lines.append("")
    rk = report["metrics"]["recognition_ranking"]
    lines.append("### Recognition / Ranking")
    lines.append("")
    lines.append(f"- Status: **{rk.get('status')}**")
    rm = rk.get("rank_metrics", {})
    if isinstance(rm, dict) and rm.get("queries_assessed") is not None:
        for k, v in (rm.get("rank_at_k") or {}).items():
            lines.append(f"- Rank@{k}: {v.get('hits')}/{rm.get('queries_assessed')} ({v.get('rate')})")
        lines.append(f"- False-match top1: {rm.get('false_match_top1_count')}/{rm.get('queries_assessed')} ({rm.get('false_match_top1_rate')})")
    pm = rk.get("pair_metrics", {})
    if isinstance(pm, dict) and pm.get("same_subject_pairs") is not None:
        lines.append(f"- Same-subject pairs: {pm.get('same_subject_pairs')}, different-subject pairs: {pm.get('different_subject_pairs')}")
        lines.append(f"- Same-score mean±std: {pm.get('same_score_mean')} ± {pm.get('same_score_std')}")
        lines.append(f"- Diff-score mean±std: {pm.get('diff_score_mean')} ± {pm.get('diff_score_std')}")
    lines.append("")
    q = report["metrics"]["quality_best_face"]
    lines.append("### Quality / Best-face")
    lines.append("")
    lines.append(f"- Status: **{q.get('status')}** — {q.get('reason','')}")
    if q.get("all_face_quality"):
        lines.append(f"- All face quality: {q['all_face_quality']}")
    if q.get("selected_best_face_quality"):
        lines.append(f"- Selected best-face quality: {q['selected_best_face_quality']}")
    lines.append("")
    lines.append("## Historical / Published")
    lines.append("")
    hist = report.get("historical_reference", {})
    lines.append(f"- Historical artifact: **{hist.get('status')}** `{hist.get('path','')}` {hist.get('note','')}")
    lines.append(f"- Published upstream claims: **{report['published_upstream_claims']['status']}** — {report['published_upstream_claims']['note']}")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for n in [
        "Synthetic-only dataset; no real CCTV, no R4C validation.",
        "Box-level GT unavailable; detection precision/recall reported as frame-presence where labels exist.",
        "Person frame-presence uses face-label proxy; heuristic only.",
        "No GT track IDs in manifest; ID switches/fragmentation NOT_ASSESSABLE.",
        "Recognition/ranking uses synthetic labels and should not be interpreted as identity accuracy.",
        "Peak RSS is best-effort process peak.",
    ]:
        lines.append(f"- {n}")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"CV-BASELINE-BENCHMARK-{ts}.json"
    md_path = out_dir / f"CV-BASELINE-BENCHMARK-{ts}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}
