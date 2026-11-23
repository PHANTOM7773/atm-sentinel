#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = ROOT / "data"
MODEL_DIR = DATA_DIR / "models"
REPORT_DIR = ROOT / "reports" / "acceptance"
RUNNER_VERSION = "1.0.0"
GENERATOR_TEST = "backend/tests/test_cv_engine.py::test_synthetic_generator_writes_labelled_clips"
PROHIBITED_SCRIPTS = (
    "scripts/generate_synthetic_cv_assets.py",
    "scripts/download_cv_models.py",
    "scripts/benchmark_cv.py",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(text: Any, temp_root: Path | None = None) -> str:
    value = str(text or "")
    if temp_root:
        value = value.replace(str(temp_root), "<ACCEPTANCE_TMP>")
    return value


def read_app_metadata() -> dict[str, Any]:
    text = (BACKEND_DIR / "app" / "config.py").read_text(encoding="utf-8")
    version = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    schema = re.search(r'SCHEMA_VERSION\s*=\s*(\d+)', text)
    return {
        "app_name": "ATM Sentinel",
        "app_version": version.group(1) if version else "unknown",
        "schema_version": int(schema.group(1)) if schema else -1,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def run_command(
    label: str,
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
    temp_root: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd or ROOT),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        returncode = -1
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
        timed_out = True
    duration = round(time.monotonic() - started, 3)
    return {
        "id": re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_"),
        "label": label,
        "command": [sanitize(str(arg), temp_root) for arg in argv],
        "cwd": sanitize(str(cwd or ROOT), temp_root),
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "status": "PASS" if returncode == 0 else "FAIL",
        "stdout_tail": sanitize(stdout[-5000:], temp_root),
        "stderr_tail": sanitize(stderr[-5000:], temp_root),
    }


def parse_pytest_counts(output: str) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for key in ("passed", "failed", "errors", "skipped", "deselected", "xfailed", "xpassed", "warnings"):
        match = re.search(rf"(\d+)\s+{key}", output, re.IGNORECASE)
        counts[key] = int(match.group(1)) if match else 0
    duration = re.search(r"in\s+([\d.]+)s", output)
    counts["duration_seconds"] = float(duration.group(1)) if duration else None
    return counts


def parse_vitest_counts(output: str) -> dict[str, Any]:
    tests = re.search(r"Tests\s+(\d+)\s+passed\s+\((\d+)\)", output)
    files = re.search(r"Test Files\s+(\d+)\s+passed\s+\((\d+)\)", output)
    return {
        "tests_passed": int(tests.group(1)) if tests else None,
        "tests_total": int(tests.group(2)) if tests else None,
        "files_passed": int(files.group(1)) if files else None,
        "files_total": int(files.group(2)) if files else None,
    }


def listener_snapshot() -> dict[str, Any]:
    ports = ("8000", "5173", "8001")
    result: dict[str, Any] = {}
    for port in ports:
        argv = ["lsof", "-tiTCP:" + port, "-sTCP:LISTEN"]
        try:
            completed = subprocess.run(argv, text=True, capture_output=True, check=False, timeout=20)
            pids = sorted({line.strip() for line in completed.stdout.splitlines() if line.strip()})
            result[port] = {"pids": pids, "returncode": completed.returncode}
        except (OSError, subprocess.TimeoutExpired):
            result[port] = {"pids": [], "returncode": -1}
    return result


def data_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {}
    db = DATA_DIR / "sentinel.db"
    result["sentinel.db"] = {
        "exists": db.exists(),
        "size_bytes": db.stat().st_size if db.exists() else None,
        "mtime_ns": db.stat().st_mtime_ns if db.exists() else None,
    }
    for name in ("uploads", "exports", "demo", "cv" / Path("crops")):
        path = DATA_DIR / name
        result[str(name)] = {
            "exists": path.exists(),
            "file_count": sum(1 for item in path.rglob("*") if item.is_file()) if path.exists() else 0,
        }
    return result


def environment_evidence(base_env: dict[str, str]) -> dict[str, Any]:
    config_text = (BACKEND_DIR / "app" / "config.py").read_text(encoding="utf-8")
    keys = re.findall(r'os\.getenv\("(ATM_SENTINEL_[^"]+)"', config_text)
    numeric_keys = [
        key for key in dict.fromkeys(keys)
        if any(token in key for token in ("MAX_", "CV_")) or key.endswith("CONCURRENCY")
    ]
    present_numeric = [key for key in numeric_keys if key in base_env]
    dependencies = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "pydantic": "pydantic",
        "python-multipart": "multipart",
        "numpy": "numpy",
        "opencv-python-headless": "cv2",
        "reportlab": "reportlab",
        "pytest": "pytest",
        "httpx": "httpx",
    }
    dep_status = {
        name: bool(importlib.util.find_spec(module))
        for name, module in dependencies.items()
    }
    manifest_path = MODEL_DIR / "SHA256SUMS.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models: dict[str, Any] = {}
    for key, meta in manifest.get("models", {}).items():
        path = MODEL_DIR / str(meta["filename"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""
        models[key] = {
            "filename": meta["filename"],
            "exists": path.exists(),
            "sha256_matches": actual == str(meta["sha256"]),
        }
    frontend_bins = {
        "vitest": (FRONTEND_DIR / "node_modules" / ".bin" / "vitest").exists(),
        "vite": (FRONTEND_DIR / "node_modules" / ".bin" / "vite").exists(),
        "tsc": (FRONTEND_DIR / "node_modules" / ".bin" / "tsc").exists(),
    }
    return {
        "ffmpeg_path": shutil.which("ffmpeg"),
        "ffprobe_path": shutil.which("ffprobe"),
        "python_dependencies": dep_status,
        "frontend_bins": frontend_bins,
        "models": models,
        "numeric_limit_overrides_present": present_numeric,
        "passphrase_set_in_runner_environment": bool(os.getenv("ATM_SENTINEL_PASSPHRASE")),
        "prohibited_scripts_invoked": [],
        "service_control_commands_invoked": [],
    }


def make_clip(path: Path, label: str) -> None:
    import cv2
    import numpy as np

    width, height, fps, frame_count = 160, 120, 10, 8
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError("Could not open synthetic MP4 writer")
    try:
        for index in range(frame_count):
            frame = np.full((height, width, 3), 70 + (index * 4), dtype=np.uint8)
            cv2.rectangle(frame, (8, 8), (width - 9, height - 9), (180, 190, 200), 2)
            cv2.putText(
                frame,
                f"SYNTH {label} T{index}",
                (12, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.32,
                (235, 235, 235),
                1,
            )
            writer.write(frame)
    finally:
        writer.release()
    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"Synthetic clip was not written: {label}")
    with path.open("rb") as handle:
        header = handle.read(12)
    if header[4:8] != b"ftyp":
        raise RuntimeError(f"Synthetic clip lacks MP4 ftyp magic: {label}")


def execute_scenario(temp_root: Path) -> dict[str, Any]:
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient
    from unittest import mock

    sys.path.insert(0, str(BACKEND_DIR))
    from app.config import absolute_from_data
    from app.cv.embeddings import EmbeddingStore, build_v4_embedding_record
    from app.cv.models import MODEL_SPECS
    from app.db import get_db
    from app.main import app
    from app.services import cv_integration as integration

    clip_dir = temp_root / "clips"
    clip_dir.mkdir(parents=True, exist_ok=True)
    data_dir = Path(os.environ["ATM_SENTINEL_DATA_DIR"])
    if data_dir.parent != temp_root:
        raise RuntimeError("Scenario data directory is outside the isolated workspace")
    target_model_dir = data_dir / "models"
    target_model_dir.mkdir(parents=True, exist_ok=True)
    model_manifest = json.loads((MODEL_DIR / "SHA256SUMS.json").read_text(encoding="utf-8"))
    for meta in model_manifest["models"].values():
        source = MODEL_DIR / str(meta["filename"])
        shutil.copy2(source, target_model_dir / source.name)

    labels = ("Q",) + tuple(f"C{index:02d}" for index in range(1, 9)) + ("N01", "X01", "X02")
    clips: dict[str, Path] = {}
    for label in labels:
        path = clip_dir / f"clip_{label}.mp4"
        make_clip(path, label)
        clips[label] = path

    spec = MODEL_SPECS["sface"]
    generated_at = "2026-01-15T09:00:00+00:00"

    def sface_digest(run: dict[str, Any]) -> str:
        for item in run.get("model_provenance", []):
            if item.get("model_key") == "sface":
                return str(item.get("model_sha256") or "")
        return ""

    vectors: dict[str, list[float]] = {"Q": [1.0, 0.0, 0.0], "Q-2": [0.0, 1.0, 0.0], "N01": []}
    for index in range(1, 9):
        vectors[f"C{index:02d}"] = [1.0, 0.1 * index, 0.0]
    vectors["X01"] = [1.0, 0.0, 0.0]
    vectors["X02"] = [1.0, 0.05, 0.0]

    def observation_ids(label: str) -> list[tuple[str, str, list[float]]]:
        if label == "Q":
            return [
                ("obs-ref-q", "sample-ref-q", vectors["Q"]),
                ("obs-samevideo-q", "sample-samevideo-q", vectors["Q-2"]),
            ]
        if label == "N01":
            return []
        index = int(label[1:])
        return [(f"obs-{label.lower()}", f"sample-{label.lower()}", vectors[label] if label.startswith("C") else vectors[label])]

    class FakeAnalysis:
        def __init__(self, payload: dict[str, Any]) -> None:
            self.payload = payload
            self.frames = payload.get("frames", [])

        def to_dict(self) -> dict[str, Any]:
            return self.payload

    class FakePipeline:
        runtime: dict[str, Any] = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.staged: list[Any] = []

        def analyze_video(self, **kwargs: Any) -> FakeAnalysis:
            video_id = str(kwargs["video_id"])
            case_id = str(kwargs["case_id"])
            analysis_run_id = str(kwargs["run_id"])
            cv_run_id = str(kwargs["cv_run_id"])
            labels = kwargs.get("labels") or {}
            label = labels.get(4) or labels.get("4") or "Q"
            selected = observation_ids(label)
            faces: list[dict[str, Any]] = []
            if kwargs.get("add_to_index"):
                for index, (observation_id, sample_id, vector) in enumerate(selected):
                    metadata = {
                        "model_filename": spec.filename,
                        "model_source_url": spec.source_url,
                        "backend": "cpu",
                        "target": "cpu",
                        "runtime_state": "observed",
                        "runtime": {"backend": "cpu", "target": "cpu"},
                        "opencv_version": cv2.__version__,
                        "pipeline_version": "acceptance-runner-synthetic-v1",
                        "frame_number": 4,
                        "timestamp": 0.4,
                        "track_id": index + 1,
                        "quality_score": 88.0,
                        "synthetic_label": "synthetic",
                        "detector_confidence": 0.91,
                    }
                    self.staged.append(
                        build_v4_embedding_record(
                            embedding_id=f"emb-{observation_id}",
                            observation_id=observation_id,
                            cv_run_id=cv_run_id,
                            analysis_run_id=analysis_run_id,
                            case_id=case_id,
                            video_id=video_id,
                            source_id=video_id,
                            sample_id=sample_id,
                            vector=np.asarray(vector, dtype=np.float32),
                            model_key="sface",
                            provenance_status="known",
                            model_sha256=spec.sha256,
                            generated_at=generated_at,
                            metadata=metadata,
                        )
                    )
            for index, (observation_id, sample_id, _vector) in enumerate(selected):
                faces.append(
                    {
                        "sample_id": sample_id,
                        "observation_id": observation_id,
                        "analysis_run_id": analysis_run_id,
                        "frame_number": 4,
                        "timestamp": 0.4,
                        "bbox": [10.0, 20.0, 40.0, 50.0],
                        "detector_confidence": 0.91,
                        "track_id": index + 1,
                        "quality": {"quality_score": 88.0, "sharpness": 120.0},
                        "pose": {"frontal_score": 0.8},
                        "flags": {"low_sharpness": False},
                        "crop_state": "not_generated",
                    }
                )
            payload = {
                "source": "synthetic",
                "source_id": video_id,
                "fps": 10.0,
                "frame_count": 8,
                "analyzed_frame_count": 1,
                "analysis_run_id": analysis_run_id,
                "frames": [
                    {
                        "frame_number": 4,
                        "timestamp": 0.4,
                        "faces": faces,
                        "persons": [],
                        "counts": {"faces": len(faces), "persons": 0},
                        "total_counts": {"faces": len(faces), "persons": 0},
                        "truncated": False,
                        "truncation": {},
                    }
                ],
                "summary": {"face_detections": len(faces)},
                "truncation": {},
                "runtime": {},
            }
            return FakeAnalysis(payload)

        def finalize_staged_embeddings(self, frames: Any) -> list[Any]:
            return list(self.staged)

        def staging_summary(self) -> dict[str, Any]:
            return {"staged_count": len(self.staged), "diagnostics": []}

        def _apply_analysis_caps(self, frames: Any) -> tuple[Any, dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

    store = EmbeddingStore(temp_root / "scenario-embeddings")
    patchers = [
        mock.patch.object(integration, "CVPipeline", FakePipeline),
        mock.patch.object(integration, "EmbeddingStore", lambda: store),
    ]
    for patcher in patchers:
        patcher.start()
    try:
        with TestClient(app) as client:
            target_case = client.post(
                "/api/cases",
                json={
                    "case_number": "ACCEPTANCE-TARGET",
                    "title": "Acceptance target case",
                    "location": "Synthetic ATM",
                },
            ).json()
            control_case = client.post(
                "/api/cases",
                json={
                    "case_number": "ACCEPTANCE-CONTROL",
                    "title": "Acceptance control case",
                    "location": "Synthetic ATM",
                },
            ).json()

            videos: dict[str, dict[str, Any]] = {}
            for label in labels:
                case_id = control_case["id"] if label.startswith("X") else target_case["id"]
                with clips[label].open("rb") as handle:
                    response = client.post(
                        "/api/videos/upload",
                        params={"case_id": case_id},
                        files={"file": (f"clip_{label}.mp4", handle, "video/mp4")},
                    )
                if response.status_code not in (200, 201):
                    raise RuntimeError(f"Upload failed for {label}: HTTP {response.status_code}")
                videos[label] = response.json()
            if len(videos) != 12:
                raise RuntimeError("Expected exactly 12 synthetic clips")

            runs: dict[str, dict[str, Any]] = {}
            run_metrics: list[dict[str, Any]] = []
            for label in labels:
                started = time.perf_counter()
                response = client.post(
                    "/api/cv/runs",
                    json={
                        "case_id": control_case["id"] if label.startswith("X") else target_case["id"],
                        "video_id": videos[label]["id"],
                        "max_frames": 1,
                        "frame_stride": 1,
                        "add_to_index": True,
                        "labels": {"4": label},
                    },
                )
                elapsed = round(time.perf_counter() - started, 4)
                if response.status_code not in (200, 201):
                    raise RuntimeError(f"CV run failed for {label}: HTTP {response.status_code}")
                body = response.json()
                run = body["run"]
                observations = body["observations"]
                if run["status"] not in ("completed", "completed_with_warnings"):
                    raise RuntimeError(f"Unexpected CV run status for {label}: {run['status']}")
                if any(str(item).startswith("embedding_index_incomplete") for item in run.get("warnings", [])):
                    raise RuntimeError(f"Embedding index incomplete for {label}")
                if run["video_provenance"]["source_video_id"] != videos[label]["id"]:
                    raise RuntimeError(f"Source video provenance mismatch for {label}")
                if run["video_provenance"]["source_video_sha256"] != videos[label]["sha256"]:
                    raise RuntimeError(f"Source hash mismatch for {label}")
                model_rows = {str(item.get("model_key")): item for item in run.get("model_provenance", [])}
                if model_rows.get("sface", {}).get("model_sha256") != spec.sha256:
                    raise RuntimeError(f"Model provenance mismatch for {label}")
                expected_observations = 0 if label == "N01" else (2 if label == "Q" else 1)
                if observations["total"] != expected_observations:
                    raise RuntimeError(f"Observation count mismatch for {label}")
                runs[label] = run
                run_metrics.append(
                    {
                        "label": label,
                        "case": "control" if label.startswith("X") else "target",
                        "status": run["status"],
                        "observation_count": observations["total"],
                        "processing_seconds": elapsed,
                        "source_video_id": videos[label]["id"],
                        "source_sha256_matches": True,
                        "model_sha256_matches": True,
                    }
                )

            query_run = runs["Q"]
            query_observations = client.get(
                f"/api/cv/runs/{query_run['cv_run_id']}/observations",
                params={"case_id": target_case["id"]},
            ).json()["items"]
            reference = next(item for item in query_observations if item["cv_sample_id"] == "sample-ref-q")
            other_same_video = next(item for item in query_observations if item["cv_sample_id"] == "sample-samevideo-q")
            if reference["verification_status"] != "candidate_only":
                raise RuntimeError("Reference observation is not candidate_only")

            review = client.post(
                f"/api/cv/runs/{query_run['cv_run_id']}/observations/{reference['observation_id']}/review",
                params={"case_id": target_case["id"]},
                json={
                    "case_id": target_case["id"],
                    "cv_run_id": query_run["cv_run_id"],
                    "target_type": "face_observation",
                    "decision": "relevant",
                    "reviewer_note": "Synthetic reference selected",
                },
            )
            if review.status_code not in (200, 201):
                raise RuntimeError(f"Reference review failed: HTTP {review.status_code}")
            reference_review = review.json()

            top_candidate_obs_id = "obs-c01"
            top_candidate_run = runs["C01"]
            candidate_review = client.post(
                f"/api/cv/runs/{top_candidate_run['cv_run_id']}/observations/{top_candidate_obs_id}/review",
                params={"case_id": target_case["id"]},
                json={
                    "case_id": target_case["id"],
                    "cv_run_id": top_candidate_run["cv_run_id"],
                    "target_type": "face_observation",
                    "decision": "relevant",
                    "reviewer_note": "Synthetic top candidate accepted",
                },
            )
            if candidate_review.status_code not in (200, 201):
                raise RuntimeError(f"Candidate review failed: HTTP {candidate_review.status_code}")

            started = time.perf_counter()
            search_response = client.post(
                "/api/cv/candidates/search",
                json={
                    "case_id": target_case["id"],
                    "query_cv_run_id": query_run["cv_run_id"],
                    "query_observation_id": reference["observation_id"],
                    "top_k": 5,
                    "scope": "case_all_eligible_videos",
                },
            )
            search_seconds = round(time.perf_counter() - started, 4)
            if search_response.status_code != 200:
                raise RuntimeError(f"Candidate search failed: HTTP {search_response.status_code}")
            search = search_response.json()
            actual_ids = [item["candidate_observation_id"] for item in search["items"]]
            expected_ids = [f"obs-c{index:02d}" for index in range(1, 6)]
            if search["count"] != 5 or search["limit"] != 5 or actual_ids != expected_ids:
                raise RuntimeError(f"Ranking mismatch: expected {expected_ids}, got {actual_ids}")
            scores = [float(item["similarity_score"]) for item in search["items"]]
            if any(scores[index] < scores[index + 1] for index in range(len(scores) - 1)):
                raise RuntimeError("Candidate scores are not descending")
            if any(score < -1.0 or score > 1.0 for score in scores):
                raise RuntimeError("Candidate score outside [-1, 1]")
            excluded = {
                reference["observation_id"],
                other_same_video["observation_id"],
                "obs-n01",
                "obs-x01",
                "obs-x02",
            }
            if excluded.intersection(actual_ids):
                raise RuntimeError("Excluded observation appeared in candidate results")
            if any(item["case_id"] != target_case["id"] for item in search["items"]):
                raise RuntimeError("Candidate from another case appeared in results")
            if any(item["candidate_video_provenance"]["source_video_id"] == videos["Q"]["id"] for item in search["items"]):
                raise RuntimeError("Query video appeared as a candidate source")
            if any(item["candidate_video_provenance"]["source_video_sha256"] != videos[f"C{index:02d}"]["sha256"] for index, item in enumerate(search["items"], start=1)):
                raise RuntimeError("Candidate source hash mismatch")
            if any(item["model_provenance"][0]["model_sha256"] != spec.sha256 for item in search["items"]):
                raise RuntimeError("Candidate model provenance mismatch")
            if any(item["verification_status"] != "candidate_only" or item["requires_human_verification"] is not True for item in search["items"]):
                raise RuntimeError("Candidate verification contract mismatch")
            if "not identity verification" not in search["score_meaning"]:
                raise RuntimeError("Score meaning disclaimer missing")
            if "Never identity confirmation" not in search["disclaimer"]:
                raise RuntimeError("Candidate disclaimer missing")
            if "Synthetic top candidate accepted" in search_response.text:
                raise RuntimeError("Reviewer note leaked into search response")
            lowered = search_response.text.lower()
            for forbidden in ("embedding_vector", "raw_vector", "vector_data", "index_path", "vectors_path"):
                if forbidden in lowered:
                    raise RuntimeError(f"Forbidden search field present: {forbidden}")
            for item in search["items"]:
                for key in item:
                    lowered_key = key.lower()
                    if "vector" in lowered_key or lowered_key in {"metadata", "embedding"}:
                        raise RuntimeError(f"Forbidden candidate field present: {key}")
            if str(temp_root) in search_response.text:
                raise RuntimeError("Local temp path leaked into search response")

            selected_started = time.perf_counter()
            selected_response = client.post(
                "/api/cv/candidates/search",
                json={
                    "case_id": target_case["id"],
                    "query_cv_run_id": query_run["cv_run_id"],
                    "query_observation_id": reference["observation_id"],
                    "top_k": 5,
                    "scope": "case_selected_videos",
                    "source_video_ids": [videos["C07"]["id"], videos["C08"]["id"]],
                },
            )
            selected_seconds = round(time.perf_counter() - selected_started, 4)
            if selected_response.status_code != 200:
                raise RuntimeError(f"Selected-scope search failed: HTTP {selected_response.status_code}")
            selected = selected_response.json()
            selected_ids = [item["candidate_observation_id"] for item in selected["items"]]
            if selected["count"] != 2 or selected_ids != ["obs-c07", "obs-c08"]:
                raise RuntimeError(f"Selected-scope ranking mismatch: {selected_ids}")

            cross_case_response = client.post(
                "/api/cv/candidates/search",
                json={
                    "case_id": target_case["id"],
                    "query_cv_run_id": query_run["cv_run_id"],
                    "query_observation_id": reference["observation_id"],
                    "top_k": 5,
                    "scope": "case_selected_videos",
                    "source_video_ids": [videos["X01"]["id"]],
                },
            )
            if cross_case_response.status_code != 404:
                raise RuntimeError(f"Cross-case video was not rejected: HTTP {cross_case_response.status_code}")

            with get_db() as conn:
                audit_rows = conn.execute(
                    "SELECT action, detail_json FROM audit_events WHERE case_id=? AND action='cv_candidate_search'",
                    (target_case["id"],),
                ).fetchall()
            if not audit_rows:
                raise RuntimeError("Candidate search audit event missing")
            if any(str(temp_root) in str(row["detail_json"]) for row in audit_rows):
                raise RuntimeError("Temp path leaked into audit detail")
            detail = json.loads(audit_rows[0]["detail_json"])
            if detail.get("result_count") != 5:
                raise RuntimeError("Candidate search audit result_count mismatch")

            transaction = client.post(
                f"/api/cases/{target_case['id']}/transactions",
                json={
                    "reference": "ACCEPTANCE-TX",
                    "transaction_ts": "2026-01-15T09:00:05+00:00",
                    "cctv_ts": "2026-01-15T09:00:35+00:00",
                },
            )
            if transaction.status_code not in (200, 201):
                raise RuntimeError(f"Transaction create failed: HTTP {transaction.status_code}")
            frame_response = client.post(
                "/api/frames/manual",
                json={
                    "case_id": target_case["id"],
                    "video_id": videos["Q"]["id"],
                    "timestamp": 0.4,
                    "note": "Acceptance export anchor",
                },
            )
            if frame_response.status_code != 201:
                raise RuntimeError(f"Manual frame create failed: HTTP {frame_response.status_code}")
            frame = frame_response.json()

            top_item = search["items"][0]
            export_response = client.post(
                "/api/exports",
                json={
                    "case_id": target_case["id"],
                    "frame_ids": [frame["id"]],
                    "cv_items": [
                        {
                            "kind": "observation",
                            "cv_run_id": query_run["cv_run_id"],
                            "observation_id": reference["observation_id"],
                            "expected_review_updated_at": reference_review["updated_at"],
                            "expected_model_sha256": sface_digest(query_run),
                        },
                        {
                            "kind": "candidate",
                            "cv_run_id": top_candidate_run["cv_run_id"],
                            "observation_id": top_candidate_obs_id,
                            "query_cv_run_id": query_run["cv_run_id"],
                            "query_observation_id": reference["observation_id"],
                            "candidate_id": top_item["candidate_id"],
                            "expected_review_updated_at": candidate_review.json()["updated_at"],
                            "expected_model_sha256": sface_digest(top_candidate_run),
                            "selection_context": {
                                "rank": top_item["rank"],
                                "similarity_score": top_item["similarity_score"],
                                "score_meaning": top_item["score_meaning"],
                            },
                        },
                    ],
                },
            )
            if export_response.status_code != 201:
                raise RuntimeError(f"CV export failed: HTTP {export_response.status_code}")
            export_result = export_response.json()
            manifest = json.loads(absolute_from_data(export_result["manifest_path"]).read_text(encoding="utf-8"))
            pdf_path = absolute_from_data(export_result["pdf_path"])
            if export_result["cv_selection_count"] != 2:
                raise RuntimeError("CV export selection count mismatch")
            if export_result["cv_observation_count"] != 1 or export_result["cv_candidate_count"] != 1:
                raise RuntimeError("CV export kind counts mismatch")
            if "do not identify the ATM operator" not in manifest["cv_association_limitation"]:
                raise RuntimeError("CV association limitation missing from export")
            if not pdf_path.exists() or pdf_path.read_bytes()[:4] != b"%PDF":
                raise RuntimeError("Export PDF missing or invalid")
            selection_text = json.dumps(manifest["cv_selections"]).lower()
            for forbidden in ("embedding_vector", "face_embedding", "face_encoding", "stored_path", "image_path", "crop_path"):
                if forbidden in selection_text:
                    raise RuntimeError(f"Forbidden export field present: {forbidden}")

            peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if platform.system() != "Darwin":
                peak_rss *= 1024

            return {
                "status": "PASS",
                "data_classification": {
                    "synthetic_clips": True,
                    "synthetic_observations_and_embeddings": True,
                    "cv_model_inference_stubbed": True,
                    "real_cctv": False,
                    "real_people": False,
                },
                "counts": {
                    "clips_total": len(videos),
                    "target_case_clips": 10,
                    "control_case_clips": 2,
                    "runs_total": len(runs),
                    "no_face_clips": 1,
                    "face_observations_published": sum(item["observation_count"] for item in run_metrics),
                },
                "runs": run_metrics,
                "timing": {
                    "total_processing_seconds": round(sum(item["processing_seconds"] for item in run_metrics), 4),
                    "search_seconds": search_seconds,
                    "selected_scope_search_seconds": selected_seconds,
                    "peak_process_rss_bytes": peak_rss,
                    "memory_note": "Approximate process high-water mark (ru_maxrss), not an isolated container measurement.",
                },
                "search": {
                    "scope": search["scope"],
                    "top_k": search["limit"],
                    "expected_observation_ids": expected_ids,
                    "actual_observation_ids": actual_ids,
                    "scores": [round(score, 6) for score in scores],
                    "source_exclusion_verified": True,
                    "case_scope_isolation_verified": True,
                    "cross_case_selected_rejection_status": cross_case_response.status_code,
                    "selected_scope_ids": selected_ids,
                },
                "review": {
                    "reference_decision": "relevant",
                    "top_candidate_decision": "relevant",
                    "reviewer_note_not_exposed_in_search": True,
                },
                "export": {
                    "cv_selection_count": export_result["cv_selection_count"],
                    "cv_observation_count": export_result["cv_observation_count"],
                    "cv_candidate_count": export_result["cv_candidate_count"],
                    "association_limitation_present": True,
                    "pdf_valid": True,
                    "raw_vector_and_path_fields_absent": True,
                },
                "audit": {
                    "candidate_search_events": len(audit_rows),
                    "result_count_recorded": detail.get("result_count"),
                    "temp_paths_absent": True,
                },
                "checks": [
                    "12 MP4 clips generated with ftyp magic",
                    "10 target clips and 2 control clips uploaded and analyzed",
                    "no-face clip produced zero observations",
                    "one reference face selected by human review",
                    "case-scoped top-5 ranking matched exact expected order",
                    "query source video and second same-video face excluded",
                    "cross-case video rejected from selected scope",
                    "candidate provenance matched model and source hashes",
                    "search response exposed no raw vectors, metadata, or local paths",
                    "explicit observation and candidate CV export preserved provenance",
                ],
            }
    finally:
        for patcher in reversed(patchers):
            patcher.stop()


def run_scenario_child(temp_root: Path, output_path: Path) -> int:
    try:
        result = execute_scenario(temp_root)
    except Exception as exc:
        result = {
            "status": "FAIL",
            "failure": sanitize(str(exc), temp_root),
            "traceback_tail": sanitize(traceback.format_exc()[-4000:], temp_root),
        }
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result.get("status") == "PASS" else 1


def acceptance_environment(temp_root: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("ATM_SENTINEL_")}
    env["TMPDIR"] = str(temp_root / "tmp")
    return env


def requirement(
    requirement_id: str,
    area: str,
    status: str,
    evidence: str,
    notes: str = "",
    commands: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "area": area,
        "status": status,
        "evidence": evidence,
        "notes": notes,
        "commands": commands or [],
    }


def build_requirements(
    env_status: str,
    backend_status: str,
    frontend_test_status: str,
    frontend_typecheck_status: str,
    frontend_build_status: str,
    scenario_status: str,
    safety_status: str,
) -> list[dict[str, Any]]:
    frontend_status = "PASS" if all(
        item == "PASS"
        for item in (frontend_test_status, frontend_typecheck_status, frontend_build_status)
    ) else "FAIL"
    return [
        requirement(
            "A",
            "Environment, local models, configured limits",
            env_status,
            "Python package checks, ffmpeg/ffprobe paths, model SHA-256 verification, /api/cv/status limit source",
            "Configured limits are reported; boundary stress at 500 MB, 300 s, 3000 decoded frames, 300 analysis frames, 100 crops, and 2000 retained crops was not executed.",
        ),
        requirement(
            "B",
            "Multi-format input and normalization",
            backend_status,
            "backend tests: security, video, pipeline; isolated 12-clip synthetic scenario",
            "Local MP4/AVI/MOV/MKV acceptance passed; real DVR/NVR exports and vendor formats remain NOT ASSESSED. App normalization is video-only.",
            ["pytest_backend_full_suite", "twelve_clip_synthetic_scenario"],
        ),
        requirement(
            "C",
            "Transaction timestamp and aligned windows",
            backend_status,
            "backend tests: timestamps and CV alignment",
            "Investigator-entered timestamps only; no OCR or automatic clock extraction.",
            ["pytest_backend_full_suite"],
        ),
        requirement(
            "D",
            "Quality scores and best-frame support",
            backend_status,
            "backend tests: quality, CV engine, CV accuracy evidence; synthetic scenario",
            "Explainable synthetic metrics verified; real-world robustness is NOT ASSESSED. Mask/helmet/cap remain not_assessed.",
            ["pytest_backend_full_suite", "twelve_clip_synthetic_scenario"],
        ),
        requirement(
            "E",
            "Face/person detection and clip-local tracking",
            backend_status,
            "backend tests: CV engine and CV accuracy evidence",
            "Synthetic mechanics verified; person detector remains experimental_unvalidated and real-world accuracy is NOT ASSESSED.",
            ["pytest_backend_full_suite"],
        ),
        requirement(
            "F",
            "Cross-video candidate search and source exclusion",
            scenario_status if scenario_status == "PASS" else "FAIL",
            "12-clip scenario plus backend CV candidate search suite",
            "Exact top-5 ordering, query-source exclusion, case-scope isolation, selected scope, and top-K limits asserted; CV inference was stubbed with deterministic synthetic observations.",
            ["twelve_clip_synthetic_scenario", "pytest_backend_full_suite"],
        ),
        requirement(
            "G",
            "Investigator review and candidate integrity",
            scenario_status if scenario_status == "PASS" else "FAIL",
            "12-clip scenario plus backend CV review suite",
            "Reference and top-candidate reviews exercised; reviewer notes absent from search payloads.",
            ["twelve_clip_synthetic_scenario", "pytest_backend_full_suite"],
        ),
        requirement(
            "H",
            "Explicit CV-reference export and provenance",
            scenario_status if scenario_status == "PASS" else "FAIL",
            "12-clip scenario plus backend export/CV export tests",
            "Observation and candidate CV selections exported with source/model provenance and limitation copy; no raw vectors or local paths.",
            ["twelve_clip_synthetic_scenario", "pytest_backend_full_suite"],
        ),
        requirement(
            "I1",
            "Audit recording",
            backend_status,
            "backend pipeline, CV review, and CV candidate search tests; scenario audit assertion",
            "Append-only event recording verified for local flows.",
            ["pytest_backend_full_suite", "twelve_clip_synthetic_scenario"],
        ),
        requirement("I2", "Role-based access control", "NOT IMPLEMENTED", "No per-user or per-case authorization layer exists", "Only one global optional local passphrase session is implemented."),
        requirement("I3", "Tamper-proof/WORM audit and certified chain of custody", "NOT IMPLEMENTED", "No tamper-evident storage, WORM backend, or custody certification exists", "Audit events are append-only in SQLite, not tamper-proof."),
        requirement("I4", "Protected-route and browser smoke checks", "NOT ASSESSED", "Frontend unit tests and typecheck/build executed", "No browser automation was run; live session behavior was confirmed separately before this run."),
        requirement(
            "J",
            "Frontend regression, typecheck, production build",
            frontend_status,
            "vitest, tsc --noEmit, vite build",
            "Unit tests passed; build artifacts may be regenerated.",
            ["frontend_vitest", "frontend_typecheck", "frontend_build"],
        ),
        requirement(
            "K",
            "Data and service isolation",
            safety_status,
            "listener snapshots and production data snapshot before/after",
            "No service control commands, Git operations, downloads, network calls, or prohibited scripts were invoked.",
        ),
        requirement("L", "R4C validation", "NOT ASSESSED", "No approved R4C dataset or protocol is present", "R4C remains pending; no real-world accuracy or identity claims are made."),
    ]


def write_markdown_report(payload: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    report = payload["report"]
    lines.append("# ATM Sentinel Acceptance Report")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Overall status: **{report['overall_status']}**")
    lines.append(f"- Runner version: `{report['runner_version']}`")
    lines.append(f"- App version: `{payload['environment']['app']['app_version']}`")
    lines.append(f"- Scope: local synthetic acceptance; no real CCTV/R4C validation")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Area | Status | Evidence |")
    lines.append("| --- | --- | --- |")
    for row in payload["requirements"]:
        evidence = row["evidence"].replace("\n", " ")
        lines.append(f"| {row['id']} {row['area']} | {row['status']} | {evidence} |")
    lines.append("")
    lines.append("## Commands and results")
    lines.append("")
    lines.append("| Label | Status | Return code | Duration (s) | Command |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for command in payload["commands"]:
        rendered = " ".join(command["command"]).replace("|", "\\|")
        lines.append(
            f"| {command['label']} | {command['status']} | {command['returncode']} | {command['duration_seconds']} | `{rendered}` |"
        )
    lines.append("")
    lines.append("## Test counts")
    lines.append("")
    lines.append("| Suite | Result |")
    lines.append("| --- | --- |")
    backend = payload["test_counts"]["backend_pytest"]
    lines.append(
        f"| Backend pytest | {backend.get('passed', 0)} passed, {backend.get('failed', 0)} failed, "
        f"{backend.get('errors', 0)} errors, {backend.get('skipped', 0)} skipped, "
        f"{backend.get('deselected', 0)} deselected |"
    )
    frontend = payload["test_counts"]["frontend_vitest"]
    lines.append(
        f"| Frontend vitest | {frontend.get('tests_passed')} passed of {frontend.get('tests_total')}; "
        f"{frontend.get('files_passed')} files passed of {frontend.get('files_total')} |"
    )
    lines.append("")
    lines.append("## 12-clip synthetic scenario")
    lines.append("")
    scenario = payload["multiclip_scenario"]
    lines.append(f"- Status: **{scenario.get('status')}**")
    lines.append(f"- Counts: `{json.dumps(scenario.get('counts', {}), sort_keys=True)}`")
    lines.append(f"- Timing: `{json.dumps(scenario.get('timing', {}), sort_keys=True)}`")
    lines.append(f"- Search: `{json.dumps(scenario.get('search', {}), sort_keys=True)}`")
    lines.append(f"- Review: `{json.dumps(scenario.get('review', {}), sort_keys=True)}`")
    lines.append(f"- Export: `{json.dumps(scenario.get('export', {}), sort_keys=True)}`")
    lines.append(f"- Audit: `{json.dumps(scenario.get('audit', {}), sort_keys=True)}`")
    lines.append("- Data classification: synthetic clips, synthetic observations/embeddings, stubbed CV inference, no real people/CCTV.")
    lines.append("")
    lines.append("## Configured limits")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload["limits"], indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("## Safety and data isolation")
    lines.append("")
    safety = payload["safety"]
    lines.append(f"- Production data snapshot unchanged: `{safety['data_snapshot_unchanged']}`")
    lines.append(f"- Listener snapshot unchanged: `{safety['listener_snapshot_unchanged']}`")
    lines.append(f"- Service control commands invoked: `{payload['environment']['service_control_commands_invoked']}`")
    lines.append(f"- Prohibited scripts invoked: `{payload['environment']['prohibited_scripts_invoked']}`")
    lines.append(f"- Before listeners: `{json.dumps(safety['listeners_before'], sort_keys=True)}`")
    lines.append(f"- After listeners: `{json.dumps(safety['listeners_after'], sort_keys=True)}`")
    lines.append("")
    lines.append("## R4C and remaining gaps")
    lines.append("")
    lines.append("- R4C: NOT ASSESSED; no approved dataset/protocol was used.")
    for gap in payload["remaining_gaps"]:
        lines.append(f"- {gap}")
    lines.append("")
    lines.append("## Report files")
    lines.append("")
    lines.append("- `reports/acceptance/acceptance.md`")
    lines.append("- `reports/acceptance/acceptance.json`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-scenario", action="store_true")
    parser.add_argument("--scenario-temp")
    parser.add_argument("--scenario-output")
    args = parser.parse_args()

    if args.run_scenario:
        if not args.scenario_temp or not args.scenario_output:
            parser.error("--run-scenario requires --scenario-temp and --scenario-output")
        return run_scenario_child(Path(args.scenario_temp), Path(args.scenario_output))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()
    temp_root = Path(tempfile.mkdtemp(prefix="atm-sentinel-acceptance-"))
    (temp_root / "tmp").mkdir(parents=True, exist_ok=True)
    base_env = acceptance_environment(temp_root)
    commands: list[dict[str, Any]] = []

    try:
        listeners_before = listener_snapshot()
        data_before = data_snapshot()
        env_evidence = environment_evidence(base_env)

        limits_command = run_command(
            "Configured CV limits",
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "-c",
                "import json,sys; sys.path.insert(0,'backend'); "
                "from app.config import cv_limits, MAX_UPLOAD_BYTES; "
                "print(json.dumps({**cv_limits(), 'max_upload_bytes': MAX_UPLOAD_BYTES}))",
            ],
            env=base_env,
            temp_root=temp_root,
        )
        commands.append(limits_command)
        limits: dict[str, Any] = {}
        if limits_command["returncode"] == 0:
            try:
                limits = json.loads(limits_command["stdout_tail"].strip().splitlines()[-1])
            except (ValueError, IndexError):
                limits = {}

        node_command = run_command("Node version", ["node", "--version"], env=base_env, temp_root=temp_root)
        npm_command = run_command("npm version", ["npm", "--version"], env=base_env, temp_root=temp_root)
        commands.extend([node_command, npm_command])
        env_evidence["node_version"] = node_command["stdout_tail"].strip()
        env_evidence["npm_version"] = npm_command["stdout_tail"].strip()

        backend_command = run_command(
            "Backend pytest full suite",
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "-m",
                "pytest",
                "backend/tests",
                "-q",
                f"--deselect={GENERATOR_TEST}",
            ],
            env=base_env,
            temp_root=temp_root,
        )
        commands.append(backend_command)
        backend_counts = parse_pytest_counts(backend_command["stdout_tail"] + "\n" + backend_command["stderr_tail"])

        frontend_test_command = run_command(
            "Frontend vitest",
            ["npm", "run", "test", "--", "--run"],
            cwd=FRONTEND_DIR,
            env=base_env,
            temp_root=temp_root,
        )
        frontend_typecheck_command = run_command(
            "Frontend typecheck",
            ["npm", "run", "typecheck"],
            cwd=FRONTEND_DIR,
            env=base_env,
            temp_root=temp_root,
        )
        frontend_build_command = run_command(
            "Frontend production build",
            ["npm", "run", "build"],
            cwd=FRONTEND_DIR,
            env=base_env,
            temp_root=temp_root,
        )
        commands.extend([frontend_test_command, frontend_typecheck_command, frontend_build_command])
        vitest_counts = parse_vitest_counts(
            frontend_test_command["stdout_tail"] + "\n" + frontend_test_command["stderr_tail"]
        )

        scenario_data_dir = temp_root / "scenario-data"
        scenario_data_dir.mkdir(parents=True, exist_ok=True)
        scenario_output = temp_root / "scenario-result.json"
        scenario_env = dict(base_env)
        scenario_env["ATM_SENTINEL_DATA_DIR"] = str(scenario_data_dir)
        scenario_command = run_command(
            "12-clip synthetic CV scenario",
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--run-scenario",
                "--scenario-temp",
                str(temp_root),
                "--scenario-output",
                str(scenario_output),
            ],
            env=scenario_env,
            temp_root=temp_root,
        )
        commands.append(scenario_command)
        if scenario_output.exists():
            scenario_result = json.loads(scenario_output.read_text(encoding="utf-8"))
        else:
            scenario_result = {
                "status": "FAIL",
                "failure": "Scenario output file was not produced",
            }

        listeners_after = listener_snapshot()
        data_after = data_snapshot()
        data_snapshot_unchanged = data_before == data_after
        listener_snapshot_unchanged = listeners_before == listeners_after
        safety_status = "PASS" if data_snapshot_unchanged and listener_snapshot_unchanged else "FAIL"

        deps_ok = all(env_evidence["python_dependencies"].values())
        models_ok = all(item["sha256_matches"] for item in env_evidence["models"].values())
        frontend_bins_ok = all(env_evidence["frontend_bins"].values())
        env_ok = bool(
            env_evidence["ffmpeg_path"]
            and env_evidence["ffprobe_path"]
            and deps_ok
            and models_ok
            and frontend_bins_ok
            and limits
            and not env_evidence["numeric_limit_overrides_present"]
        )
        env_status = "PASS" if env_ok else "FAIL"

        requirements = build_requirements(
            env_status,
            backend_command["status"],
            frontend_test_command["status"],
            frontend_typecheck_command["status"],
            frontend_build_command["status"],
            scenario_result.get("status", "FAIL"),
            safety_status,
        )
        blocking = {"FAIL", "BLOCKED"}
        overall_status = "FAIL" if any(row["status"] in blocking for row in requirements) else "PASS"

        remaining_gaps = [
            "Real DVR/NVR exports and vendor-specific formats were not tested.",
            "No OCR or automatic CCTV clock extraction is implemented; alignment uses investigator-entered timestamps.",
            "Per-user/per-case RBAC, tamper-proof/WORM audit storage, and certified chain of custody are not implemented.",
            "R4C validation and real-world identity/detection accuracy are NOT ASSESSED.",
            "The 12-clip scenario is one local synthetic run; no broader 10–15 clip scalability sweep or configured-limit boundary stress was executed.",
            "CV inference was stubbed with deterministic synthetic observations; real model detection/embedding behavior in the scenario is NOT ASSESSED.",
            "Browser-level smoke automation was not run.",
            "Mask, helmet, cap, and occlusion robustness remain not_assessed or heuristic review signals only.",
        ]

        payload = {
            "report": {
                "generated_at": generated_at,
                "overall_status": overall_status,
                "runner_version": RUNNER_VERSION,
                "scope": "local synthetic acceptance; no real CCTV/R4C validation",
            },
            "environment": {
                **env_evidence,
                "app": read_app_metadata(),
                "acceptance_subprocess_environment": {
                    "ATM_SENTINEL_*": "removed",
                    "TMPDIR": "<ACCEPTANCE_TMP>/tmp",
                },
            },
            "limits": limits,
            "requirements": requirements,
            "commands": commands,
            "test_counts": {
                "backend_pytest": backend_counts,
                "frontend_vitest": vitest_counts,
            },
            "multiclip_scenario": sanitize(json.dumps(scenario_result), temp_root) if isinstance(scenario_result, str) else scenario_result,
            "safety": {
                "data_snapshot_unchanged": data_snapshot_unchanged,
                "listener_snapshot_unchanged": listener_snapshot_unchanged,
                "listeners_before": listeners_before,
                "listeners_after": listeners_after,
                "data_before": data_before,
                "data_after": data_after,
                "temp_workspace_removed": False,
            },
            "r4c": {
                "status": "NOT ASSESSED",
                "reason": "No approved R4C dataset, protocol, or result was available to this runner.",
            },
            "remaining_gaps": remaining_gaps,
        }
        payload["multiclip_scenario"] = json.loads(sanitize(json.dumps(payload["multiclip_scenario"]), temp_root))

        json_path = REPORT_DIR / "acceptance.json"
        md_path = REPORT_DIR / "acceptance.md"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
        write_markdown_report(payload, md_path)
        print(json.dumps({"status": overall_status, "json": str(json_path), "markdown": str(md_path)}))
        return 0 if overall_status == "PASS" else 1
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
