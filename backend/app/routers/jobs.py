from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ..db import audit, get_db, parse_json, row_to_dict, rows_to_dicts, utc_now
from ..schemas import AlignmentRequest, JobCreate
from ..services.extraction import cancel_job, start_job
from ..services.security import new_id
from ..services.timestamp import TimestampError, analyze_window, compute_alignment

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/alignment/preview")
def alignment_preview(payload: AlignmentRequest):
    try:
        alignment = compute_alignment(
            payload.transaction_ts,
            payload.cctv_ts,
            payload.video_duration,
            payload.video_start_ts,
            payload.cctv_reference_video_time,
            payload.clock_offset_minutes,
        )
        return analyze_window(alignment, payload.before_seconds, payload.after_seconds)
    except TimestampError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/jobs", status_code=201)
def create_job(payload: JobCreate):
    with get_db() as conn:
        video = conn.execute("SELECT * FROM videos WHERE id=?", (payload.video_id,)).fetchone()
        tx = conn.execute("SELECT * FROM transactions WHERE id=?", (payload.transaction_id,)).fetchone()
        if not video or not tx or video["case_id"] != tx["case_id"]:
            raise HTTPException(404, "Video and transaction must belong to the same case")
        config = dict(payload.config)
        try:
            alignment = compute_alignment(
                tx["transaction_ts"],
                tx["cctv_ts"] or tx["transaction_ts"],
                float(video["duration"]),
                config.get("video_start_ts"),
                float(config.get("cctv_reference_video_time", 0) or 0),
                config.get("clock_offset_minutes"),
            )
            alignment = analyze_window(
                alignment,
                float(config.get("window_before_seconds", 20)),
                float(config.get("window_after_seconds", 20)),
            )
            if not tx["cctv_ts"]:
                alignment["warnings"].append(
                    "CCTV timestamp was not recorded; the transaction timestamp was used as the CCTV reference."
                )
        except (TimestampError, TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

        job_id = new_id()
        now = utc_now()
        conn.execute(
            """INSERT INTO processing_jobs(id, case_id, video_id, transaction_id, status, stage, progress,
               message, config_json, alignment_json, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                video["case_id"],
                video["id"],
                tx["id"],
                "queued",
                "Queued",
                0,
                "Waiting for worker",
                json.dumps(config),
                json.dumps(alignment),
                now,
                now,
            ),
        )
        audit(conn, video["case_id"], "job_queued", {"job_id": job_id, "video_id": video["id"]})
        created = row_to_dict(conn.execute("SELECT * FROM processing_jobs WHERE id=?", (job_id,)).fetchone())
    start_job(job_id)
    return created


@router.get("/jobs")
def list_jobs(case_id: str | None = None):
    with get_db() as conn:
        if case_id:
            return rows_to_dicts(conn.execute("SELECT * FROM processing_jobs WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall())
        return rows_to_dicts(conn.execute("SELECT * FROM processing_jobs ORDER BY created_at DESC").fetchall())


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        result = row_to_dict(row)
        assert result is not None
        result["alignment"] = parse_json(result["alignment_json"], {})
        result["config"] = parse_json(result["config_json"], {})
        return result


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str):
    if not cancel_job(job_id):
        raise HTTPException(409, "Job is already finished or not found")
    return {"status": "cancellation_requested"}
