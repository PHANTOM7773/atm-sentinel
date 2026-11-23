from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import DATA_DIR, absolute_from_data
from ..db import audit, get_db, row_to_dict, rows_to_dicts, utc_now
from ..schemas import FrameUpdate, ManualCaptureRequest
from ..services.extraction import capture_manual_frame
from ..services.security import new_id

router = APIRouter(prefix="/api/frames", tags=["frames"])


def _frame_with_extras(conn, row):
    result = row_to_dict(row)
    assert result is not None
    result["warnings"] = json.loads(result["warnings_json"] or "[]")
    result["metrics"] = json.loads(result["metrics_json"] or "{}")
    item = conn.execute("SELECT * FROM evidence_items WHERE frame_id=?", (result["id"],)).fetchone()
    result["selected"] = item is not None
    result["selection_note"] = item["note"] if item else ""
    result["selection_reason"] = item["selection_reason"] if item else ""
    result["frame_notes"] = rows_to_dicts(
        conn.execute("SELECT * FROM notes WHERE frame_id=? ORDER BY created_at", (result["id"],)).fetchall()
    )
    return result


@router.get("")
def list_frames(case_id: str | None = None, video_id: str | None = None, job_id: str | None = None):
    clauses, params = [], []
    for field, value in (("case_id", case_id), ("video_id", video_id), ("job_id", job_id)):
        if value:
            clauses.append(f"{field}=?")
            params.append(value)
    query = "SELECT * FROM frames"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY timestamp, frame_number"
    with get_db() as conn:
        return [_frame_with_extras(conn, row) for row in conn.execute(query, params).fetchall()]


@router.post("/manual", status_code=201)
def manual_capture(payload: ManualCaptureRequest):
    try:
        result = capture_manual_frame(payload.case_id, payload.video_id, payload.timestamp, payload.note)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with get_db() as conn:
        row = conn.execute("SELECT * FROM frames WHERE id=?", (result["frame_id"],)).fetchone()
        audit(conn, payload.case_id, "manual_frame_captured", {"frame_id": result["frame_id"], "timestamp": payload.timestamp})
        return _frame_with_extras(conn, row)


@router.get("/compare")
def compare(ids: str = Query(..., description="Comma-separated frame IDs")):
    frame_ids = [item for item in ids.split(",") if item][:8]
    with get_db() as conn:
        frames = []
        for frame_id in frame_ids:
            row = conn.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone()
            if row:
                frames.append(_frame_with_extras(conn, row))
        return frames


@router.get("/{frame_id}/image")
def frame_image(frame_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT image_path FROM frames WHERE id=?", (frame_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Frame not found")
        path = absolute_from_data(row["image_path"])
    return FileResponse(path, media_type="image/jpeg")


@router.get("/{frame_id}/thumb")
def frame_thumb(frame_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT thumb_path FROM frames WHERE id=?", (frame_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Frame not found")
        path = absolute_from_data(row["thumb_path"])
    return FileResponse(path, media_type="image/jpeg")


@router.patch("/{frame_id}")
def update_frame(frame_id: str, payload: FrameUpdate):
    with get_db() as conn:
        frame = conn.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone()
        if not frame:
            raise HTTPException(404, "Frame not found")
        now = utc_now()
        if payload.selected is True:
            conn.execute(
                """INSERT INTO evidence_items(id, frame_id, case_id, selected_at, note, selection_reason)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(frame_id) DO UPDATE SET
                     note=COALESCE(excluded.note, evidence_items.note),
                     selection_reason=COALESCE(excluded.selection_reason, evidence_items.selection_reason)""",
                (
                    new_id(),
                    frame_id,
                    frame["case_id"],
                    now,
                    payload.note or "",
                    payload.reason or "",
                ),
            )
        elif payload.selected is False:
            conn.execute("DELETE FROM evidence_items WHERE frame_id=?", (frame_id,))
        elif payload.note is not None:
            conn.execute("UPDATE evidence_items SET note=?, selection_reason=? WHERE frame_id=?", (payload.note or "", payload.reason or "", frame_id))
        if payload.note is not None and not conn.execute("SELECT 1 FROM evidence_items WHERE frame_id=?", (frame_id,)).fetchone():
            conn.execute(
                "INSERT INTO notes(id, case_id, video_id, frame_id, body, created_at) VALUES(?,?,?,?,?,?)",
                (new_id(), frame["case_id"], frame["video_id"], frame_id, payload.note, now),
            )
        audit(conn, frame["case_id"], "frame_updated", {"frame_id": frame_id, "selected": payload.selected}, now)
        return _frame_with_extras(conn, conn.execute("SELECT * FROM frames WHERE id=?", (frame_id,)).fetchone())
