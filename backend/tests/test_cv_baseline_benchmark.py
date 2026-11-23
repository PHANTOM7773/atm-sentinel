from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.cv.baseline_benchmark import (
    NOT_ASSESSABLE,
    compute_best_face_stats,
    compute_frame_presence_metrics,
    compute_pair_metrics,
    compute_rank_metrics,
    compute_track_metrics,
    evaluate_dataset,
    render_markdown,
    validate_manifest,
    write_report,
)


def _manifest(tmp_path: Path) -> Path:
    # create tiny dummy videos with cv2? avoid by writing minimal manifest and mocking pipeline_factory
    (tmp_path / "a.mp4").write_bytes(b"fake")
    (tmp_path / "b.mp4").write_bytes(b"fake")
    manifest = {
        "synthetic": True,
        "real_people": False,
        "notice": "synthetic",
        "videos": {
            "clip_a": {"file": "a.mp4", "frame_count": 3, "description": "a", "labels": {"0": "SYN-A", "1": "none", "2": "SYN-A"}},
            "no_face": {"file": "b.mp4", "frame_count": 2, "description": "n", "labels": {"0": "none", "1": "none"}},
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


class FakeAnalysis:
    def __init__(self, source_id, frames, summary):
        self.source_id = source_id
        self.frames = frames
        self.summary = summary

    def to_dict(self):
        return {"source_id": self.source_id, "frames": self.frames, "summary": self.summary}


class FakeStore:
    def __init__(self, rows):
        self.rows = rows

    def search(self, vector, case_id=None, top_k=5, exclude_sample_id=None, exclude_source_id=None):
        rows = [r for r in self.rows if r["metadata"]["sample_id"] != exclude_sample_id and r["metadata"]["source_id"] != exclude_source_id]
        return rows[:top_k]


class FakePipeline:
    def __init__(self, output_dir=None):
        self.output_dir = output_dir
        self.store = FakeStore([])
        self._staged_embeddings = []

    def reset_trackers(self):
        return None

    def staged_embeddings(self):
        return list(self._staged_embeddings)

    def analyze_video(self, video_path, case_id, source_id, max_frames=None, frame_stride=1, save_crops=False, add_to_index=False, labels=None, **kwargs):
        if source_id == "clip_a":
            frames = [
                {"frame_number": 0, "faces": [{"sample_id": "a0", "synthetic_label": "SYN-A", "embedding": [1, 0], "quality": {"quality_score": 90}, "frame_number": 0}]},
                {"frame_number": 1, "faces": []},
                {"frame_number": 2, "faces": [{"sample_id": "a2", "synthetic_label": "SYN-A", "embedding": [0.9, 0.1], "quality": {"quality_score": 80}, "frame_number": 2}]},
            ]
            summary = {"face_detections": 2, "person_detections": 0, "unique_face_tracks": 1, "unique_person_tracks": 0, "average_face_quality": 85.0, "average_frame_ms": 10.0, "estimated_fps": 100.0}
        else:
            frames = [{"frame_number": 0, "faces": []}, {"frame_number": 1, "faces": []}]
            summary = {"face_detections": 0, "person_detections": 0, "unique_face_tracks": 0, "unique_person_tracks": 0, "average_face_quality": 0.0, "average_frame_ms": 5.0, "estimated_fps": 200.0}
        if add_to_index and source_id == "clip_a":
            self.store.rows = [
                {"cosine_similarity": 0.99, "metadata": {"sample_id": "a0", "source_id": "clip_a", "synthetic_label": "SYN-A"}},
                {"cosine_similarity": 0.10, "metadata": {"sample_id": "b0", "source_id": "clip_b", "synthetic_label": "SYN-B"}},
            ]
        return FakeAnalysis(source_id, frames, summary)


def test_frame_presence_metrics():
    m = compute_frame_presence_metrics({0: True, 1: False, 2: True}, {0: True, 1: True, 2: False})
    assert m["tp"] == 1 and m["fp"] == 1 and m["fn"] == 1 and m["tn"] == 0
    assert m["precision"] == 0.5 and m["recall"] == 0.5


def test_track_metrics_missing_gt():
    r = compute_track_metrics(None)
    assert r.status == NOT_ASSESSABLE


def test_rank_and_pair_metrics():
    rows = [
        {"query_sample_id": "q1", "query_label": "SYN-A", "rank": 1, "candidate_label": "SYN-B"},
        {"query_sample_id": "q1", "query_label": "SYN-A", "rank": 2, "candidate_label": "SYN-A"},
    ]
    rank = compute_rank_metrics(rows, ks=(1, 5))
    assert rank["rank_at_k"]["1"]["hits"] == 0
    assert rank["rank_at_k"]["5"]["hits"] == 1
    pairs = compute_pair_metrics([
        {"same_subject": True, "score": 0.9},
        {"same_subject": False, "score": 0.1},
    ])
    assert pairs["same_subject_pairs"] == 1 and pairs["different_subject_pairs"] == 1


def test_validate_manifest_errors(tmp_path):
    bad = {"videos": {"x": {"file": "missing.mp4", "frame_count": 1, "labels": {"2": "SYN-A"}}}}
    errs = validate_manifest(bad, tmp_path)
    assert any("missing asset" in e for e in errs)
    assert any(">=" in e for e in errs)


def test_evaluate_dataset_and_report(tmp_path):
    ds = _manifest(tmp_path)
    report = evaluate_dataset(ds, warmup_runs=0, measurement_runs=1, include_load_timing=False, pipeline_factory=FakePipeline)
    assert report["meta"]["benchmark_name"] == "atm-sentinel-cv-baseline"
    assert report["metrics"]["tracking"]["id_switches_fragmentation"]["status"] == NOT_ASSESSABLE
    assert report["metrics"]["recognition_ranking"]["status"] in {"MEASURED", NOT_ASSESSABLE}
    md = render_markdown(report)
    assert "NOT_ASSESSABLE" in md
    out = write_report(report, tmp_path / "out")
    assert Path(out["json"]).exists() and Path(out["markdown"]).exists()
    data = json.loads(Path(out["json"]).read_text(encoding="utf-8"))
    assert data["meta"]["synthetic_only"] is True


def test_best_face_stats_heuristic():
    stats = compute_best_face_stats([{"source_id": "c", "frames": [{"faces": [{"sample_id": "s1", "frame_number": 1, "quality": {"quality_score": 50}}, {"sample_id": "s2", "frame_number": 2, "quality": {"quality_score": 70}}]}]}])
    assert stats["status"] == "HEURISTIC"
    assert stats["by_clip"]["c"]["selected_sample_id"] == "s2"
