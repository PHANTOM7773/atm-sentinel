from __future__ import annotations

import json
import os
import resource
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("ATM_SENTINEL_CV_PERSON_SCORE", "0.1")
os.environ.setdefault("ATM_SENTINEL_CV_BACKEND", "cpu")
os.environ.setdefault("ATM_SENTINEL_CV_TARGET", "cpu")
sys.path.insert(0, str(ROOT / "backend"))

import cv2  # noqa: E402

from app.config import CV_OUTPUT_DIR  # noqa: E402
from app.cv import CVPipeline, model_status  # noqa: E402
from app.cv.embeddings import EmbeddingStore  # noqa: E402
from app.cv.quality import LIMITATIONS  # noqa: E402

DATASET_DIR = ROOT / "data" / "datasets" / "synthetic" / "cv"
OUTPUT_JSON = ROOT / "data" / "cv" / "benchmark.json"
OUTPUT_MD = ROOT / "docs" / "CV_PHASE1_BENCHMARK.md"
OUTPUT_RANKING = ROOT / "data" / "cv" / "benchmark_ranking_evidence.json"
BENCHMARK_METHODOLOGY_VERSION = "phase1.2-ranking-evidence-v1"
ORDER = [
    "subject_a_front",
    "subject_a_side",
    "subject_b_front",
    "multi_subject",
    "challenges",
    "no_face",
]
GALLERY_CLIPS = ["subject_a_front", "subject_b_front", "multi_subject", "challenges"]
QUERY_CLIPS = ["subject_a_side"]
HARD_NEGATIVE_CLIPS = ["subject_b_front", "challenges"]


def _label_set(value: Any) -> set[str]:
    if not value:
        return set()
    return {part.strip() for part in str(value).split(",") if part.strip()}


def _labels_match(query_label: Any, candidate_label: Any) -> bool:
    query = _label_set(query_label)
    candidate = _label_set(candidate_label)
    return bool(query & candidate)


def _rank_metrics(
    ranking: dict[str, Any] | None,
    gallery_hard_negative_samples: int,
) -> dict[str, Any]:
    if not ranking:
        return {"ranked_samples": 0}
    rank_one = 0
    top_five = 0
    hard_negative_candidates = 0
    hard_negative_top_five = 0
    hard_negative_queries_returned = 0
    scored = 0
    for candidates in ranking["candidates"].values():
        if not candidates:
            continue
        scored += 1
        query_label = candidates[0]["metadata"].get("query_label")
        first_label = candidates[0]["metadata"].get("synthetic_label")
        if _labels_match(query_label, first_label):
            rank_one += 1
        query_hard_negatives = 0
        for candidate in candidates[:5]:
            candidate_label = candidate["metadata"].get("synthetic_label")
            if _labels_match(query_label, candidate_label):
                top_five += 1
            elif candidate_label and candidate_label != "none":
                hard_negative_top_five += 1
                query_hard_negatives += 1
        hard_negative_candidates += sum(
            1
            for candidate in candidates
            if candidate["metadata"].get("synthetic_label")
            and candidate["metadata"].get("synthetic_label") != "none"
            and not _labels_match(query_label, candidate["metadata"].get("synthetic_label"))
        )
        if query_hard_negatives:
            hard_negative_queries_returned += 1
    return {
        "ranked_samples": scored,
        "same_label_rank1": rank_one,
        "same_label_top5": top_five,
        "hard_negative_candidates": hard_negative_candidates,
        "hard_negative_top5": hard_negative_top_five,
        "hard_negative_queries_returned": hard_negative_queries_returned,
        "hard_negative_query_count": scored if gallery_hard_negative_samples else 0,
        "hard_negative_discrimination_established": hard_negative_candidates > 0,
        "same_label_rank1_rate": round(rank_one / scored, 3) if scored else 0.0,
        "same_label_top5_rate": round(top_five / scored, 3) if scored else 0.0,
    }


def _add_query_labels(ranking: dict[str, Any], analysis: Any) -> dict[str, str]:
    query_labels: dict[str, str] = {}
    for frame in analysis.frames:
        for face in frame.faces:
            query_labels[face["sample_id"]] = face.get("synthetic_label", "unlabelled")
    for sample_id, candidates in ranking["candidates"].items():
        for candidate in candidates:
            candidate["metadata"]["query_label"] = query_labels.get(sample_id, "unlabelled")
    return query_labels


def _entry_label_set(entry: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for value in entry.get("labels", {}).values():
        labels.update(_label_set(value))
    return labels - {"none"}


def _expected_samples(entry: dict[str, Any]) -> int:
    return sum(len(_label_set(value) - {"none"}) for value in entry.get("labels", {}).values())


def _hard_negative_samples(entry: dict[str, Any], query_labels: set[str]) -> int:
    return sum(
        len(labels - {"none"})
        for labels in (_label_set(value) for value in entry.get("labels", {}).values())
        if labels and not ((labels - {"none"}) & query_labels)
    )


def _ranking_rows(
    ranking: dict[str, Any],
    query_labels: dict[str, str],
    query_clip: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample_id, candidates in ranking["candidates"].items():
        query_label = query_labels.get(sample_id, "unlabelled")
        for rank, candidate in enumerate(candidates, start=1):
            metadata = candidate.get("metadata", {})
            candidate_label = str(metadata.get("synthetic_label", ""))
            outcome = (
                "same_label"
                if _labels_match(query_label, candidate_label)
                else "hard_negative"
                if candidate_label and candidate_label != "none"
                else "unlabelled"
            )
            rows.append(
                {
                    "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
                    "query_clip": query_clip,
                    "query_sample_id": sample_id,
                    "excluded_query_clip": query_clip,
                    "rank": rank,
                    "candidate_sample_id": str(metadata.get("sample_id", "")),
                    "candidate_source_id": str(metadata.get("source_id", "")),
                    "candidate_track_id": metadata.get("track_id"),
                    "similarity": candidate.get("cosine_similarity"),
                    "query_label": query_label,
                    "candidate_label": candidate_label,
                    "evaluation_outcome": outcome,
                    "synthetic_only": True,
                }
            )
    return rows


def build_report() -> dict[str, Any]:
    manifest = json.loads((DATASET_DIR / "manifest.json").read_text(encoding="utf-8"))
    query_labels = set()
    for clip in QUERY_CLIPS:
        query_labels.update(_entry_label_set(manifest["videos"][clip]))
    gallery_hard_negative_samples = sum(
        _hard_negative_samples(manifest["videos"][clip], query_labels) for clip in GALLERY_CLIPS
    )
    expected_query_samples = sum(_expected_samples(manifest["videos"][clip]) for clip in QUERY_CLIPS)
    with tempfile.TemporaryDirectory(prefix="benchmark-", dir=CV_OUTPUT_DIR) as temporary:
        pipeline = CVPipeline(output_dir=Path(temporary))
        clips: dict[str, Any] = {}
        rankings: dict[str, Any] = {}
        ranking_rows: list[dict[str, Any]] = []

        for name in ORDER:
            entry = manifest["videos"][name]
            labels = {int(key): value for key, value in entry["labels"].items()}
            should_rank = name in QUERY_CLIPS
            pipeline.reset_trackers()
            analysis = pipeline.analyze_video(
                DATASET_DIR / entry["file"],
                case_id="synthetic",
                source_id=name,
                max_frames=entry["frame_count"],
                frame_stride=1,
                save_crops=False,
                add_to_index=name in GALLERY_CLIPS,
                labels=labels,
            )
            expected_positive_frames = sum(1 for value in labels.values() if value and value != "none")
            frames_with_face = sum(1 for frame in analysis.frames if frame.faces)
            expected_faces = sum(
                len(value.split(",")) for value in labels.values() if value and value != "none"
            )
            ranking = pipeline.rank_faces(analysis, "synthetic", top_k=5) if should_rank else None
            if ranking:
                sample_query_labels = _add_query_labels(ranking, analysis)
                rankings[name] = _rank_metrics(ranking, gallery_hard_negative_samples)
                ranking_rows.extend(_ranking_rows(ranking, sample_query_labels, name))
            clips[name] = {
                "description": entry["description"],
                "expected_positive_frames": expected_positive_frames,
                "frames_with_face": frames_with_face,
                "face_detection_recall_by_frame": round(frames_with_face / expected_positive_frames, 3)
                if expected_positive_frames
                else None,
                "expected_face_observations": expected_faces,
                "observed_face_observations": analysis.summary["face_detections"],
                "expected_person_observations": expected_positive_frames,
                "observed_person_observations": analysis.summary["person_detections"],
                "summary": analysis.summary,
                "ranking": rankings.get(name),
                "indexed_for_ranking": name in GALLERY_CLIPS,
            }

        status = model_status()
        memory_bytes = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        runtime = pipeline.runtime
        store_status = pipeline.store.status()
        ranked_query_count = len({row["query_sample_id"] for row in ranking_rows})
        ranking_methodology = {
            "version": BENCHMARK_METHODOLOGY_VERSION,
            "gallery_clips": GALLERY_CLIPS,
            "query_clips": QUERY_CLIPS,
            "hard_negative_clips": HARD_NEGATIVE_CLIPS,
            "query_clip_excluded": True,
            "isolated_index_per_run": True,
            "label_matching": "set intersection across comma-separated synthetic labels",
            "gallery_hard_negative_samples": gallery_hard_negative_samples,
            "expected_query_samples": expected_query_samples,
            "ranked_query_samples": ranked_query_count,
            "hard_negative_query_count": ranked_query_count if gallery_hard_negative_samples else 0,
            "note": (
                "Query-clip embeddings and all samples from the query clip are excluded from the gallery. "
                "This is a cross-pose synthetic smoke test, not a real-world accuracy estimate. "
                "Labels are applied only after ranking for post-ranking evaluation."
            ),
        }
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": {
                "synthetic": True,
                "real_people": False,
                "notice": manifest["notice"],
                "directory": str(DATASET_DIR),
            },
            "models": {
                key: {
                    "filename": item["filename"],
                    "sha256": item["sha256"],
                    "license": item["license"],
                    "verification": item["verification"],
                }
                for key, item in status["models"].items()
            },
            "runtime": runtime,
            "opencv_version": cv2.__version__,
            "thresholds": {
                "person_score": float(os.environ["ATM_SENTINEL_CV_PERSON_SCORE"]),
                "note": (
                    "Lower than the application default because procedural bodies are not photorealistic; "
                    "the application default remains unvalidated."
                ),
            },
            "ranking_methodology": ranking_methodology,
            "ranking_evidence": {
                "path": str(OUTPUT_RANKING.relative_to(ROOT)),
                "row_count": len(ranking_rows),
                "query_count": ranked_query_count,
                "gallery_count": store_status["record_count"],
                "synthetic_only": True,
            },
            "embedding_store": store_status,
            "clips": clips,
            "peak_memory": {
                "ru_maxrss": memory_bytes,
                "platform": sys.platform,
                "note": "macOS reports bytes; this is a single-process peak including Python and OpenCV.",
            },
            "limitations": LIMITATIONS,
            "disclaimer": (
                "Synthetic pipeline-functionality benchmark only. Candidate rankings are not identity "
                "confirmations and do not establish real-world accuracy."
            ),
        }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    for row in ranking_rows:
        row["query_count"] = ranked_query_count
        row["gallery_count"] = store_status["record_count"]
    ranking_evidence = {
        "methodology_version": BENCHMARK_METHODOLOGY_VERSION,
        "methodology": ranking_methodology,
        "synthetic_only": True,
        "scope": "Synthetic cross-pose smoke test only; not real-world accuracy or identity evidence.",
        "query_count": ranked_query_count,
        "gallery_count": store_status["record_count"],
        "excluded_query_clips": QUERY_CLIPS,
        "rows": ranking_rows,
        "disclaimer": report["disclaimer"],
    }
    OUTPUT_RANKING.write_text(json.dumps(ranking_evidence, indent=2) + "\n", encoding="utf-8")
    OUTPUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    OUTPUT_MD.write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: dict[str, Any]) -> str:
    runtime = report["runtime"]
    configured = runtime.get("configured", {})
    models = runtime.get("models", {})
    lines = [
        "# ATM Sentinel CV Phase 1 Benchmark",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "Synthetic/fictional assets only. This validates pipeline mechanics, not real-world accuracy or identity claims.",
        "",
        "## Runtime",
        "",
        f"- OpenCV: {report['opencv_version']}",
    ]
    for key in ("yunet", "sface", "yolox"):
        profile = models.get(key, configured.get(key, {}))
        lines.append(
            f"- {key}: `{profile.get('effective_backend', 'unknown')}` / "
            f"`{profile.get('effective_target', 'unknown')}` "
            f"(fallback: {profile.get('fallback', 'unknown')})"
        )
    lines.extend(
        [
            f"- Person score threshold: `{report['thresholds']['person_score']}`",
            f"- Peak process memory: `{report['peak_memory']['ru_maxrss']}` bytes (macOS `ru_maxrss`)",
            f"- Candidate records: `{report['embedding_store']['record_count']}`",
            "",
            "## Ranking methodology",
            "",
            f"- Gallery clips: `{', '.join(report['ranking_methodology']['gallery_clips'])}`",
            f"- Query clips: `{', '.join(report['ranking_methodology']['query_clips'])}`",
            f"- Hard negatives: `{', '.join(report['ranking_methodology']['hard_negative_clips'])}`",
            f"- Gallery hard-negative samples: `{report['ranking_methodology']['gallery_hard_negative_samples']}`",
            f"- Expected query samples: `{report['ranking_methodology']['expected_query_samples']}`",
            f"- Ranked query samples: `{report['ranking_methodology']['ranked_query_samples']}`",
            f"- Hard-negative queries evaluated: `{report['ranking_methodology']['hard_negative_query_count']}`",
            "- Query-clip embeddings are excluded; the index is isolated for each benchmark run.",
            "- Cross-pose synthetic smoke test only; not a real-world accuracy estimate.",
            f"- Ranking evidence artifact: `{report['ranking_evidence']['path']}` ({report['ranking_evidence']['row_count']} rows).",
            "",
            "## Timing terminology",
            "",
            "Frame timings are single-pass synthetic smoke timings from one run, not a repeated benchmark with variance estimates.",
            "",
            "## Models",
            "",
            "| Model | File | License | Verification | SHA256 |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for key, item in report["models"].items():
        lines.append(
            f"| {key} | `{item['filename']}` | {item['license']} | {item['verification']} | `{item['sha256']}` |"
        )
    lines.extend(
        [
            "",
            "## Synthetic clips",
            "",
            "| Clip | Face frames | Expected | Person detections | Single-pass avg frame ms | Single-pass est. FPS | Cross-pose Rank@1 | Hard negatives in top 5 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, item in report["clips"].items():
        ranking = item.get("ranking") or {}
        rank_one = ranking.get("same_label_rank1_rate")
        rank_text = "—" if rank_one is None else f"{ranking['same_label_rank1']}/{ranking['ranked_samples']} ({rank_one})"
        hard_negatives = ranking.get("hard_negative_top5", "—")
        lines.append(
            f"| {name} | {item['frames_with_face']} | {item['expected_positive_frames']} | "
            f"{item['observed_person_observations']} | {item['summary']['average_frame_ms']} | "
            f"{item['summary']['estimated_fps']} | {rank_text} | {hard_negatives} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Face detection, tracking, quality scoring, pose proxies and candidate embeddings ran end-to-end.",
            "- Person detection was demonstrated only with a lower threshold; procedural silhouettes are not photorealistic.",
            "- Ranking uses a query-clip-excluded isolated gallery; labels are applied only after ranking.",
            "- Rank@1 is a small synthetic cross-pose smoke test result and is not real-world accuracy.",
            (
                f"- Hard negatives returned in evaluated top-k: "
                f"`{sum((item.get('ranking') or {}).get('hard_negative_candidates', 0) for item in report['clips'].values())}`."
            ),
            "- Zero returned hard negatives does not establish hard-negative discrimination.",
            "- Synthetic hard-negative clips are procedural and cannot support a real-world discrimination claim.",
            "- Ranking results compare synthetic labels across clips and are not identity verification.",
            "- Challenge-clip flags are heuristic review signals, not mask/helmet/cap classifiers.",
            "",
            "## Limitations",
            "",
            report["limitations"],
            "",
            report["disclaimer"],
            "",
            "Reproduce with: `.venv/bin/python scripts/generate_synthetic_cv_assets.py && .venv/bin/python scripts/benchmark_cv.py`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    print(f"Benchmark JSON: {OUTPUT_JSON}")
    print(f"Benchmark report: {OUTPUT_MD}")
    print(f"Clips: {len(report['clips'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
