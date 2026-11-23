"""TASK 18 - Isolated face embedding/retrieval benchmark.

Uses existing local SFace model and authorized synthetic clips only.
Does not modify production matching, DB, or protected data.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import cv2
import numpy as np

from ..config import CV_FACE_SCORE_THRESHOLD
from .crop import crop_face
from .detection import YuNetFaceDetector
from .embeddings import normalize_vector
from .models import require_model
from .runtime import RuntimeProfile, create_with_fallback, facade_profile

DEFAULT_DATASET_DIR = Path(__file__).resolve().parents[3] / "data" / "datasets" / "synthetic" / "cv"
DEFAULT_PROD_THRESHOLD = 0.0  # no explicit cosine threshold found in production candidate search; report actual behavior


@dataclass(frozen=True)
class FaceSample:
    sample_id: str
    subject_label: str
    clip_name: str
    frame_number: int
    timestamp: float | None
    bbox: tuple[float, float, float, float]
    confidence: float
    quality_score: float | None
    sharpness: float | None
    brightness: float | None
    face_size: float
    crop: np.ndarray
    embedding: np.ndarray


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Any]:
    p = dataset_dir / "manifest.json"
    return json.loads(p.read_text())


def _label_for_frame(entry: dict[str, Any], frame_number: int) -> str | None:
    labels = entry.get("labels") or {}
    raw = labels.get(str(frame_number), labels.get(frame_number))
    if raw is None:
        return None
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    parts = [p for p in parts if p not in {"none", "unlabelled"}]
    if not parts:
        return None
    if len(parts) != 1:
        # Ambiguous multi-subject frame label - cannot reliably assign to a single detection without GT bbox mapping.
        return "__AMBIGUOUS__"
    return parts[0]


def _clip_frames(dataset_dir: Path, clip_name: str, entry: dict[str, Any]) -> list[tuple[int, float | None, np.ndarray]]:
    cap = cv2.VideoCapture(str(dataset_dir / entry["file"]))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open {entry['file']}")
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


def _quality_metrics(crop: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    return {"sharpness": sharpness, "brightness": brightness, "contrast": contrast}


def create_sface(profile: RuntimeProfile | None = None):
    selected = facade_profile(profile or RuntimeProfile.from_env())
    model_path = require_model("sface")

    def factory(chosen: RuntimeProfile):
        return cv2.FaceRecognizerSF.create(str(model_path), "", chosen.backend_id, chosen.target_id)

    embedder, prof = create_with_fallback(factory, selected)
    return embedder, prof


def extract_samples(
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    *,
    clip_names: Sequence[str] | None = None,
    detector: YuNetFaceDetector | None = None,
    embedder=None,
    min_quality_score: float | None = None,
) -> tuple[list[FaceSample], dict[str, Any]]:
    manifest = load_manifest(dataset_dir)
    clips = manifest.get("videos", {})
    selected = list(clip_names) if clip_names else list(clips.keys())
    det = detector or YuNetFaceDetector()
    emb = embedder
    if emb is None:
        emb, _ = create_sface()
    samples: list[FaceSample] = []
    audit: dict[str, Any] = {"clips": {}, "excluded": [], "ambiguous_frames": 0, "no_label_frames": 0}

    for clip_name in selected:
        entry = clips[clip_name]
        frames = _clip_frames(dataset_dir, clip_name, entry)
        clip_info = {"frames": len(frames), "samples": 0, "subjects": set(), "excluded_ambiguous": 0, "excluded_no_label": 0, "excluded_no_detection": 0}
        for frame_number, ts, frame in frames:
            label = _label_for_frame(entry, frame_number)
            if label == "__AMBIGUOUS__":
                audit["ambiguous_frames"] += 1
                clip_info["excluded_ambiguous"] += 1
                continue
            if label is None:
                # no-face/unknown label - not usable for identity pairs
                audit["no_label_frames"] += 1
                clip_info["excluded_no_label"] += 1
                continue
            dets = det.detect(frame)
            if not dets:
                clip_info["excluded_no_detection"] += 1
                continue
            # For single-subject labeled frames, if multiple detections exist we cannot reliably map; exclude frame to avoid fabricated identity.
            if len(dets) != 1:
                audit["excluded"].append({"clip": clip_name, "frame": frame_number, "reason": "multiple_detections_single_label_ambiguous", "detections": len(dets)})
                continue
            d = dets[0]
            try:
                crop, _, _ = crop_face(frame, d)
            except Exception:
                continue
            qm = _quality_metrics(crop)
            qscore = None
            try:
                from .quality import analyze_face_quality
                qscore = float(analyze_face_quality(crop, d.landmarks, d.bbox)["quality_score"])
            except Exception:
                qscore = None
            if min_quality_score is not None and (qscore is None or qscore < min_quality_score):
                continue
            try:
                aligned = emb.alignCrop(frame, np.asarray(d.landmarks, dtype=np.float32))
                feat = emb.feature(aligned)
                vec = normalize_vector(np.asarray(feat, dtype=np.float32).reshape(-1))
            except Exception:
                continue
            sid = f"{clip_name}:{frame_number}:{len(samples)}"
            samples.append(FaceSample(
                sample_id=sid, subject_label=label, clip_name=clip_name, frame_number=frame_number,
                timestamp=ts, bbox=tuple(float(x) for x in d.bbox), confidence=float(d.confidence),
                quality_score=qscore, sharpness=qm["sharpness"], brightness=qm["brightness"],
                face_size=float(min(d.bbox[2], d.bbox[3])), crop=crop, embedding=vec,
            ))
            clip_info["samples"] += 1
            clip_info["subjects"].add(label)
        clip_info["subjects"] = sorted(clip_info["subjects"])
        audit["clips"][clip_name] = clip_info

    audit["total_samples"] = len(samples)
    audit["unique_subjects"] = sorted({s.subject_label for s in samples})
    audit["clips_with_samples"] = sorted({s.clip_name for s in samples})
    return samples, audit


def build_pairs(samples: Sequence[FaceSample], *, cross_clip_only: bool = False, include_same_clip_negatives: bool = True) -> list[dict[str, Any]]:
    pairs = []
    for i in range(len(samples)):
        a = samples[i]
        for j in range(i + 1, len(samples)):
            b = samples[j]
            same_subject = a.subject_label == b.subject_label
            same_clip = a.clip_name == b.clip_name
            if cross_clip_only and same_clip:
                continue
            if not same_subject and not include_same_clip_negatives and same_clip:
                continue
            score = float(np.dot(a.embedding, b.embedding))
            pairs.append({
                "a": a.sample_id, "b": b.sample_id,
                "a_subject": a.subject_label, "b_subject": b.subject_label,
                "a_clip": a.clip_name, "b_clip": b.clip_name,
                "same_subject": same_subject,
                "same_clip": same_clip,
                "cross_clip": not same_clip,
                "cosine_similarity": score,
            })
    return pairs


def pair_stats(pairs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    pos = [p["cosine_similarity"] for p in pairs if p["same_subject"]]
    neg = [p["cosine_similarity"] for p in pairs if not p["same_subject"]]
    def stats(xs):
        if not xs: return {"count": 0}
        arr = np.array(xs, dtype=float)
        return {
            "count": int(arr.size),
            "mean": float(arr.mean()), "std": float(arr.std()),
            "min": float(arr.min()), "max": float(arr.max()),
            "p05": float(np.percentile(arr,5)), "p50": float(np.percentile(arr,50)), "p95": float(np.percentile(arr,95)),
        }
    return {"genuine": stats(pos), "impostor": stats(neg)}


def roc_metrics(pairs: Sequence[dict[str, Any]], *, far_targets: Sequence[float] = (0.01, 0.05, 0.1)) -> dict[str, Any]:
    pos = [p for p in pairs if p["same_subject"]]
    neg = [p for p in pairs if not p["same_subject"]]
    if len(pos) < 2 or len(neg) < 2:
        return {"status": "NOT_ASSESSABLE", "reason": "insufficient pairs for meaningful ROC/AUC", "positive_pairs": len(pos), "negative_pairs": len(neg)}
    thresholds = sorted({float(p["cosine_similarity"]) for p in pairs}, reverse=True)
    # include extremes
    thresholds = [1.000001] + thresholds + [-1.000001]
    rows = []
    for t in thresholds:
        tp = sum(1 for p in pos if p["cosine_similarity"] >= t)
        fn = len(pos) - tp
        fp = sum(1 for p in neg if p["cosine_similarity"] >= t)
        tn = len(neg) - fp
        tar = tp / len(pos)
        far = fp / len(neg)
        rows.append({"threshold": float(t), "tar": tar, "far": far, "tp": tp, "fp": fp, "tn": tn, "fn": fn})
    # AUC by trapezoid over FAR sorted ascending
    pts = sorted([(r["far"], r["tar"]) for r in rows], key=lambda x: (x[0], x[1]))
    auc = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        auc += (x2 - x1) * (y1 + y2) / 2.0
    # TAR@FAR
    tar_at_far = {}
    for target in far_targets:
        eligible = [r for r in rows if r["far"] <= target]
        if eligible:
            best = max(eligible, key=lambda r: (r["tar"], -r["far"], r["threshold"]))
            tar_at_far[str(target)] = {"tar": best["tar"], "far": best["far"], "threshold": best["threshold"]}
        else:
            tar_at_far[str(target)] = {"tar": None, "far": None, "threshold": None, "reason": "no threshold meets FAR target"}
    # EER proxy
    eer = min(rows, key=lambda r: abs(r["tar"] - (1 - r["far"])))
    return {
        "status": "MEASURED", "positive_pairs": len(pos), "negative_pairs": len(neg),
        "auc": float(auc),
        "eer_proxy": {"threshold": eer["threshold"], "tar": eer["tar"], "far": eer["far"], "abs_gap": abs(eer["tar"] - (1-eer["far"]))},
        "tar_at_far": tar_at_far,
    }


def retrieval_metrics(samples: Sequence[FaceSample], *, exclude_same_clip: bool) -> dict[str, Any]:
    by_id = {s.sample_id: s for s in samples}
    ranks = []
    rr = []
    recall_at = {1:0,5:0}
    details = []
    for q in samples:
        candidates = []
        for c in samples:
            if c.sample_id == q.sample_id:
                continue
            if exclude_same_clip and c.clip_name == q.clip_name:
                continue
            score = float(np.dot(q.embedding, c.embedding))
            candidates.append((score, c))
        candidates.sort(key=lambda x: (-x[0], x[1].sample_id))
        if not candidates:
            continue
        relevant = [i for i, (_, c) in enumerate(candidates, start=1) if c.subject_label == q.subject_label]
        if not relevant:
            # no genuine candidate available; cannot assess retrieval for this query
            details.append({"query": q.sample_id, "status": "NOT_ASSESSABLE", "reason": "no_relevant_candidates"})
            continue
        rank = relevant[0]
        ranks.append(rank)
        rr.append(1.0 / rank)
        for k in recall_at:
            if rank <= k:
                recall_at[k] += 1
        details.append({"query": q.sample_id, "query_subject": q.subject_label, "query_clip": q.clip_name, "rank1": rank, "top1_subject": candidates[0][1].subject_label, "top1_score": candidates[0][0]})
    assessed = len(ranks)
    if assessed == 0:
        return {"status": "NOT_ASSESSABLE", "reason": "no queries with relevant candidates", "assessed_queries": 0}
    return {
        "status": "MEASURED",
        "assessed_queries": assessed,
        "rank1": recall_at[1] / assessed,
        "rank5": recall_at[5] / assessed,
        "mrr": float(np.mean(rr)),
        "recall_at_k": {str(k): recall_at[k]/assessed for k in recall_at},
        "details": details,
    }


def degrade_crop(crop: np.ndarray) -> dict[str, np.ndarray]:
    h, w = crop.shape[:2]
    blur = cv2.GaussianBlur(crop, (11, 11), 3)
    down = cv2.resize(cv2.resize(crop, (max(8, w//3), max(8, h//3)), interpolation=cv2.INTER_AREA), (w, h), interpolation=cv2.INTER_LINEAR)
    low_light = cv2.convertScaleAbs(crop, alpha=0.45, beta=-15)
    low_contrast = cv2.convertScaleAbs(crop, alpha=0.55, beta=45)
    rng = np.random.default_rng(7)
    noise = np.clip(crop.astype(np.int16) + rng.integers(-30, 31, size=crop.shape, dtype=np.int16), 0, 255).astype(np.uint8)
    return {"original": crop, "blur": blur, "downscale": down, "low_light": low_light, "low_contrast": low_contrast, "moderate_noise": noise}


def robustness_experiment(samples: Sequence[FaceSample], embedder, *, max_samples: int = 80) -> dict[str, Any]:
    # Use controlled in-memory crop variants; re-embed using SFace.feature on crop directly is not ideal,
    # but SFace expects aligned face; we keep landmark-aligned original embedding and for degraded variants
    # embed degraded crop through a simple detect+align fallback: if landmarks unavailable, use resize to 112x112
    # and feature() on normalized crop as proxy? No - that would be unsupported. Instead, apply degradations to
    # original full-frame-aligned crop by creating synthetic BGR crop and using embedder.feature after resize to input.
    # SFace.feature can operate on aligned 112x112 face; we approximate by resizing crop to 112x112.
    selected = list(samples[:max_samples])
    variants = ["original", "blur", "downscale", "low_light", "low_contrast", "moderate_noise"]
    by_variant: dict[str, list[np.ndarray]] = {v: [] for v in variants}
    kept = []
    for s in selected:
        deg = degrade_crop(s.crop)
        ok = True
        vecs = {}
        for v, img in deg.items():
            try:
                face112 = cv2.resize(img, (112, 112), interpolation=cv2.INTER_LINEAR)
                feat = embedder.feature(face112)
                vecs[v] = normalize_vector(np.asarray(feat, dtype=np.float32).reshape(-1))
            except Exception:
                ok = False
                break
        if not ok:
            continue
        kept.append(s)
        for v in variants:
            by_variant[v].append(vecs[v])
    if len(kept) < 4:
        return {"status": "NOT_ASSESSABLE", "reason": "insufficient samples for robustness", "samples": len(kept)}

    def rank1(vectors: list[np.ndarray]) -> dict[str, Any]:
        correct = 0; total = 0
        for i, q in enumerate(kept):
            best_j, best_score = None, -1e9
            for j, c in enumerate(kept):
                if i == j or kept[i].clip_name == kept[j].clip_name:
                    continue
                score = float(np.dot(vectors[i], vectors[j]))
                if score > best_score:
                    best_score, best_j = score, j
            if best_j is None:
                continue
            total += 1
            if kept[best_j].subject_label == q.subject_label:
                correct += 1
        if total == 0:
            return {"status": "NOT_ASSESSABLE", "reason": "no cross-clip candidates in robustness subset", "assessed_queries": 0}
        return {"status": "MEASURED", "rank1": correct / total, "assessed_queries": total}

    summary = {}
    orig_v = by_variant["original"]
    for v in variants:
        vecs = by_variant[v]
        sims_to_orig = [float(np.dot(o, x)) for o, x in zip(orig_v, vecs)]
        summary[v] = {
            "samples": len(kept),
            "rank1_cross_clip": rank1(vecs),
            "mean_cosine_to_original": float(np.mean(sims_to_orig)),
            "min_cosine_to_original": float(np.min(sims_to_orig)),
        }
    return {
        "status": "MEASURED",
        "method": "Controlled in-memory crop degradations; embeddings computed via SFace.feature on resized 112x112 crop (proxy for degraded crop embedding, not production alignCrop path). Original retrieval benchmark uses alignCrop on original frames.",
        "samples": len(kept),
        "variants": summary,
        "limitations": [
            "Degraded variants use resized-crop SFace.feature proxy, not full-frame alignCrop; absolute scores may differ from production path.",
            "No enhanced TASK 15 outputs used as matching inputs.",
        ],
    }


def threshold_analysis(pairs: Sequence[dict[str, Any]], *, production_threshold: float | None = None) -> dict[str, Any]:
    thresholds = [round(x, 2) for x in np.linspace(-1.0, 1.0, 401)]
    rows = []
    pos = [p for p in pairs if p["same_subject"]]
    neg = [p for p in pairs if not p["same_subject"]]
    for t in thresholds:
        fp = sum(1 for p in neg if p["cosine_similarity"] >= t)
        fn = sum(1 for p in pos if p["cosine_similarity"] < t)
        tp = len(pos) - fn
        tn = len(neg) - fp
        rows.append({
            "threshold": t,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "tar": (tp/len(pos)) if pos else None,
            "far": (fp/len(neg)) if neg else None,
            "false_match_rate": (fp/len(neg)) if neg else None,
            "missed_match_rate": (fn/len(pos)) if pos else None,
        })
    # best balanced by min(FAR+miss)
    valid = [r for r in rows if r["far"] is not None and r["missed_match_rate"] is not None]
    best = min(valid, key=lambda r: (r["far"] + r["missed_match_rate"], abs(r["threshold"]))) if valid else None
    prod = None
    if production_threshold is not None:
        for r in rows:
            if abs(r["threshold"] - production_threshold) < 1e-9:
                prod = r
                break
    return {
        "status": "MEASURED" if valid else "NOT_ASSESSABLE",
        "production_threshold_observed": production_threshold,
        "production_threshold_note": "No explicit cosine similarity acceptance threshold found in production candidate search; search ranks by cosine and returns top_k. 0.0 used as reporting baseline only.",
        "best_balanced_offline": best,
        "rows": rows,
        "change_recommended": False,
        "change_reason": "Offline-only exploratory analysis on small synthetic labeled set; no production threshold change justified without larger NOT_REVIEWED-cleared/real-world evidence.",
    }


def run_benchmark(dataset_dir: Path = DEFAULT_DATASET_DIR) -> dict[str, Any]:
    t0 = time.perf_counter()
    det = YuNetFaceDetector()
    emb, emb_profile = create_sface()
    samples, audit = extract_samples(dataset_dir, detector=det, embedder=emb)
    pairs_all = build_pairs(samples, cross_clip_only=False, include_same_clip_negatives=True)
    pairs_cross = build_pairs(samples, cross_clip_only=True, include_same_clip_negatives=True)

    # condition metrics where labels support it
    def bucket(sample: FaceSample) -> dict[str, str]:
        size = 'small' if sample.face_size < 80 else 'medium' if sample.face_size < 140 else 'large'
        blur = 'blurry' if (sample.sharpness or 0) < 80 else 'ok'
        light = 'dark' if (sample.brightness or 0) < 60 else 'bright' if (sample.brightness or 0) > 180 else 'normal'
        return {'size': size, 'blur': blur, 'illumination': light}

    buckets = {s.sample_id: bucket(s) for s in samples}

    def by_condition(condition: str) -> dict[str, Any]:
        out = {}
        for val in sorted({buckets[s.sample_id][condition] for s in samples}):
            subset = [s for s in samples if buckets[s.sample_id][condition] == val]
            ids = {s.sample_id for s in subset}
            spairs = [p for p in pairs_all if p['a'] in ids and p['b'] in ids]
            if len(subset) < 2:
                out[val] = {'status': 'NOT_ASSESSABLE', 'samples': len(subset)}
                continue
            out[val] = {
                'status': 'MEASURED', 'samples': len(subset),
                'pair_stats': pair_stats(spairs),
                'retrieval_cross_clip': retrieval_metrics(subset, exclude_same_clip=True),
            }
        return out

    report = {
        'meta': {
            'task': 'TASK-18',
            'generated_at_utc': _now_iso(),
            'dataset_dir': str(dataset_dir),
            'synthetic_only': True,
            'real_people': False,
            'model': 'SFace existing local model only',
            'model_runtime': emb_profile.to_dict() if hasattr(emb_profile, 'to_dict') else str(emb_profile),
            'production_threshold_note': 'No explicit cosine acceptance threshold found in production candidate search; production ranks/returns top_k. Offline threshold analysis is exploratory only.',
        },
        'dataset_audit': audit,
        'pairs': {
            'all': {'count': len(pairs_all), 'positive': sum(1 for p in pairs_all if p['same_subject']), 'negative': sum(1 for p in pairs_all if not p['same_subject']), 'stats': pair_stats(pairs_all)},
            'cross_clip': {'count': len(pairs_cross), 'positive': sum(1 for p in pairs_cross if p['same_subject']), 'negative': sum(1 for p in pairs_cross if not p['same_subject']), 'stats': pair_stats(pairs_cross)},
        },
        'retrieval': {
            'source_clip_excluded': retrieval_metrics(samples, exclude_same_clip=True),
            'including_same_clip': retrieval_metrics(samples, exclude_same_clip=False),
        },
        'roc_auc': {
            'all_pairs': roc_metrics(pairs_all),
            'cross_clip_pairs': roc_metrics(pairs_cross),
        },
        'condition_breakdown': {
            'face_size': by_condition('size'),
            'blur': by_condition('blur'),
            'illumination': by_condition('illumination'),
            'pose': {'status': 'NOT_ASSESSABLE', 'reason': 'No reliable per-sample pose labels in synthetic manifest; pose not inferred from visual similarity.'},
        },
        'robustness': robustness_experiment(samples, emb),
        'threshold_analysis': threshold_analysis(pairs_all, production_threshold=0.0),
        'limitations': [
            'Synthetic authorized dataset only; no real CCTV, no real identities.',
            'Subject labels come from synthetic manifest only; no identity inferred from visual similarity.',
            'Multi-subject/no-face/ambiguous frames excluded from identity pairs.',
            'Small subject count (3 labeled subjects: SYN-A/SYN-B/SYN-C) limits ROC/AUC and threshold generality.',
            'Cross-clip genuine pairs exist only where same synthetic label appears in multiple clips (SYN-A front/side).',
            'Robustness uses resized-crop SFace.feature proxy; not identical to production alignCrop path.',
            'No production threshold/model/matching behavior changed.',
        ],
        'elapsed_seconds': round(time.perf_counter() - t0, 3),
    }
    return report
