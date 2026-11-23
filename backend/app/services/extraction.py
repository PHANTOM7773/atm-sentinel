from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import cv2

from ..config import FRAME_DIR, absolute_from_data
from ..db import get_db, parse_json, utc_now
from .quality import analyze_frame
from .security import sha256_file


def _set_job(conn, job_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key}=?" for key in fields)
    values = list(fields.values()) + [utc_now(), job_id]
    conn.execute(f"UPDATE processing_jobs SET {assignments}, updated_at=? WHERE id=?", values)


def _sample_targets(alignment: dict[str, Any], coarse: float, fine: float, fine_radius: float, max_frames: int) -> list[dict[str, float]]:
    start = float(alignment["window_start_seconds"])
    end = float(alignment["window_end_seconds"])
    center = float(alignment["transaction_video_seconds"])
    targets: list[dict[str, float]] = []
    cursor = start
    guard = 0
    while cursor <= end and guard < 100000 and len(targets) < max_frames:
        source = "fine" if abs(cursor - center) <= fine_radius else "coarse"
        step = fine if source == "fine" else coarse
        targets.append({"time": round(cursor, 4), "step": float(step), "source": source})
        cursor += step
        guard += 1
    if not targets:
        targets.append({"time": start, "step": coarse, "source": "coarse"})
    return targets


def start_job(job_id: str) -> None:
    worker = threading.Thread(target=run_job, args=(job_id,), daemon=True, name=f"sentinel-job-{job_id[:8]}")
    worker.start()


def run_job(job_id: str) -> None:
    try:
        _run_job(job_id)
    except Exception as exc:
        with get_db() as conn:
            _set_job(
                conn,
                job_id,
                status="failed",
                stage="Failed",
                progress=0,
                message=f"Processing failed: {type(exc).__name__}: {exc}"[:1000],
                finished_at=utc_now(),
            )


def _run_job(job_id: str) -> None:
    from .timestamp import analyze_window, compute_alignment

    with get_db() as conn:
        job = conn.execute("SELECT * FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            return
        if job["status"] not in {"queued", "running"}:
            return
        video = conn.execute("SELECT * FROM videos WHERE id=?", (job["video_id"],)).fetchone()
        tx = conn.execute("SELECT * FROM transactions WHERE id=?", (job["transaction_id"],)).fetchone()
        if not video or not tx:
            _set_job(conn, job_id, status="failed", stage="Failed", message="Missing video or transaction", finished_at=utc_now())
            return
        config = parse_json(job["config_json"], {})
        _set_job(conn, job_id, status="running", stage="Validating", progress=4, message="Checking source video")

    source = absolute_from_data(video["stored_path"])
    if not source.exists():
        raise FileNotFoundError("Stored video file is missing")

    with get_db() as conn:
        _set_job(conn, job_id, stage="Reading metadata", progress=10, message="Reading video metadata")

    fps = float(video["fps"] or 0)
    duration = float(video["duration"] or 0)
    if fps <= 0 or duration <= 0:
        from .video import probe_video

        metadata = probe_video(source)
        fps = metadata["fps"]
        duration = metadata["duration"]
        if fps <= 0:
            raise ValueError("Video frame rate could not be determined")
        with get_db() as conn:
            conn.execute(
                "UPDATE videos SET fps=?, duration=?, codec=?, width=?, height=? WHERE id=?",
                (fps, duration, metadata["codec"], metadata["width"], metadata["height"], video["id"]),
            )

    with get_db() as conn:
        _set_job(conn, job_id, stage="Synchronizing timestamps", progress=15, message="Mapping transaction to video time")

    alignment = compute_alignment(
        transaction_ts=tx["transaction_ts"],
        cctv_ts=tx["cctv_ts"] or tx["transaction_ts"],
        video_duration=duration,
        video_start_ts=config.get("video_start_ts"),
        cctv_reference_video_time=float(config.get("cctv_reference_video_time", 0) or 0),
        clock_offset_minutes=config.get("clock_offset_minutes"),
    )
    alignment = analyze_window(
        alignment,
        float(config.get("window_before_seconds", 20)),
        float(config.get("window_after_seconds", 20)),
    )
    with get_db() as conn:
        _set_job(conn, job_id, alignment_json=json.dumps(alignment), progress=18, message="Timestamp alignment verified")

    targets = _sample_targets(
        alignment,
        coarse=float(config.get("coarse_interval_seconds", 1.0)),
        fine=float(config.get("fine_interval_seconds", 0.25)),
        fine_radius=float(config.get("fine_radius_seconds", 5.0)),
        max_frames=int(config.get("max_frames", 240)),
    )

    frame_dir = FRAME_DIR / video["case_id"] / job_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open the video for frame extraction")

    extracted = 0
    current_index = 0
    created_at = utc_now()
    try:
        with get_db() as conn:
            _set_job(conn, job_id, stage="Extracting frames", progress=20, message=f"Extracting {len(targets)} candidate frames")
        for target in targets:
            target_index = max(0, min(int(round(target["time"] * fps)), max(int(duration * fps) - 1, 0)))
            while current_index < target_index:
                if not capture.grab():
                    break
                current_index += 1
            ok, image = capture.retrieve()
            if not ok or image is None or getattr(image, "size", 0) == 0:
                continue
            current_index = target_index + 1

            filename = f"frame_{target_index:08d}_{extracted:04d}.jpg"
            image_path = frame_dir / filename
            thumb_path = frame_dir / f"thumb_{filename}"
            if not cv2.imwrite(str(image_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 90]):
                continue
            scale = min(1.0, 320.0 / max(float(image.shape[1]), 1.0))
            thumb = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))))
            cv2.imwrite(str(thumb_path), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 78])

            metrics = analyze_frame(image)
            if extracted == 0:
                with get_db() as conn:
                    _set_job(conn, job_id, stage="Analyzing quality", message="Scoring extracted frames")
            relative = float(target["time"]) - float(alignment["transaction_video_seconds"])
            frame_id = f"frm_{extracted:06d}_{job_id[:8]}"
            with get_db() as conn:
                should_cancel = conn.execute(
                    "SELECT cancel_requested FROM processing_jobs WHERE id=?", (job_id,)
                ).fetchone()
                if should_cancel and should_cancel["cancel_requested"]:
                    _set_job(conn, job_id, status="cancelled", stage="Cancelled", message="Cancelled by investigator", finished_at=utc_now())
                    return
                conn.execute(
                    """INSERT INTO frames(
                        id, job_id, video_id, case_id, frame_number, timestamp, relative_time,
                        image_path, thumb_path, sha256, sharpness, brightness, contrast,
                        quality_score, warnings_json, metrics_json, source, created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        frame_id,
                        job_id,
                        video["id"],
                        video["case_id"],
                        target_index,
                        round(float(target["time"]), 3),
                        round(relative, 3),
                        str(image_path.relative_to(_data_root())),
                        str(thumb_path.relative_to(_data_root())),
                        sha256_file(image_path),
                        metrics["sharpness"],
                        metrics["brightness"],
                        metrics["contrast"],
                        metrics["quality_score"],
                        json.dumps(metrics["warnings"]),
                        json.dumps(metrics),
                        target["source"],
                        created_at,
                    ),
                )
                progress = 20 + int(65 * (extracted + 1) / len(targets))
                _set_job(conn, job_id, progress=progress, message=f"Extracted {extracted + 1} of {len(targets)} frames")
            extracted += 1
    finally:
        capture.release()

    with get_db() as conn:
        _set_job(conn, job_id, stage="Generating thumbnails", progress=92, message="Finalizing evidence index")
        conn.execute(
            "UPDATE processing_jobs SET status='completed', stage='Completed', progress=100, message=?, finished_at=?, updated_at=? WHERE id=?",
            (f"{extracted} frames extracted", utc_now(), utc_now(), job_id),
        )


def _data_root() -> Path:
    from ..config import DATA_DIR

    return DATA_DIR


def cancel_job(job_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT status FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] in {"completed", "failed", "cancelled"}:
            return False
        _set_job(conn, job_id, cancel_requested=1, message="Cancellation requested")
        return True


def capture_manual_frame(case_id: str, video_id: str, timestamp: float, note: str = "") -> dict[str, Any]:
    from ..config import DATA_DIR

    with get_db() as conn:
        video = conn.execute("SELECT * FROM videos WHERE id=? AND case_id=?", (video_id, case_id)).fetchone()
        if not video:
            raise ValueError("Video not found in this case")
        job_id = f"manual_{video_id}"
        row = conn.execute("SELECT id FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO processing_jobs(id, case_id, video_id, transaction_id, status, stage, progress,
                   message, config_json, created_at, updated_at, finished_at)
                   SELECT ?, ?, ?, id, 'completed', 'Manual capture', 100, 'Manual frame captures', '{"source":"manual"}', ?, ?, ?
                   FROM transactions WHERE case_id=? ORDER BY created_at LIMIT 1""",
                (job_id, case_id, video_id, utc_now(), utc_now(), utc_now(), case_id),
            )
        latest = conn.execute("SELECT COALESCE(MAX(frame_number), -1) AS n FROM frames WHERE job_id=?", (job_id,)).fetchone()

    source = absolute_from_data(video["stored_path"])
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError("OpenCV could not open the video")
    try:
        fps = float(video["fps"] or capture.get(cv2.CAP_PROP_FPS) or 0)
        frame_number = max(0, int(round(float(timestamp) * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, image = capture.read()
        if not ok or image is None:
            raise ValueError(f"No frame could be read at {timestamp:.2f}s")
    finally:
        capture.release()

    frame_dir = FRAME_DIR / case_id / job_id
    frame_dir.mkdir(parents=True, exist_ok=True)
    sequence = int(latest["n"]) + 1
    image_path = frame_dir / f"manual_{sequence:05d}.jpg"
    thumb_path = frame_dir / f"thumb_manual_{sequence:05d}.jpg"
    cv2.imwrite(str(image_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    scale = min(1.0, 320.0 / max(float(image.shape[1]), 1.0))
    thumb = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))))
    cv2.imwrite(str(thumb_path), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
    metrics = analyze_frame(image)
    frame_id = f"man_{sequence:05d}_{video_id[:8]}"

    with get_db() as conn:
        conn.execute(
            """INSERT INTO frames(id, job_id, video_id, case_id, frame_number, timestamp, relative_time,
               image_path, thumb_path, sha256, sharpness, brightness, contrast, quality_score,
               warnings_json, metrics_json, source, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                frame_id,
                job_id,
                video_id,
                case_id,
                frame_number,
                round(float(timestamp), 3),
                0.0,
                str(image_path.relative_to(DATA_DIR)),
                str(thumb_path.relative_to(DATA_DIR)),
                sha256_file(image_path),
                metrics["sharpness"],
                metrics["brightness"],
                metrics["contrast"],
                metrics["quality_score"],
                json.dumps(metrics["warnings"]),
                json.dumps(metrics),
                "manual",
                utc_now(),
            ),
        )
        if note:
            conn.execute(
                "INSERT INTO notes(id, case_id, video_id, frame_id, body, created_at) VALUES(?,?,?,?,?,?)",
                (f"note_{frame_id}", case_id, video_id, frame_id, note, utc_now()),
            )
    return {"frame_id": frame_id, "metrics": metrics}
