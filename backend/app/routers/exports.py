from __future__ import annotations

import zipfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import DATA_DIR, EXPORT_DIR, absolute_from_data
from ..db import audit, get_db, rows_to_dicts, utc_now
from ..schemas import ExportRequest
from ..services.export import build_contact_sheet, build_report
from ..services.security import new_id

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("", status_code=201)
def create_export(payload: ExportRequest):
    try:
        result = build_report(payload.case_id, payload.frame_ids, payload.cv_items)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with get_db() as conn:
        conn.execute(
            """INSERT INTO exports(id, case_id, pdf_path, manifest_path, report_hash, pdf_sha256, frame_count, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                result["id"],
                payload.case_id,
                result["pdf_path"],
                result["manifest_path"],
                result["report_hash"],
                result["pdf_sha256"],
                result["frame_count"],
                result.get("generated_at", ""),
            ),
        )
        result["generated_at"] = result.get("generated_at", "")
        audit(
            conn,
            payload.case_id,
            "report_exported",
            {
                "export_id": result["id"],
                "frames": result["frame_count"],
                "cv_selections": result["cv_selection_count"],
                "cv_candidates": result["cv_candidate_count"],
                "cv_observations": result["cv_observation_count"],
            },
        )
    return result


@router.get("/frames/archive")
def download_selected_frames(case_id: str = Query(...), frame_ids: str = Query(...)):
    ids = [item for item in frame_ids.split(",") if item][:200]
    if not ids:
        raise HTTPException(422, "Select at least one frame")
    with get_db() as conn:
        placeholders = ",".join("?" for _ in ids)
        frames = conn.execute(
            f"SELECT * FROM frames WHERE case_id=? AND id IN ({placeholders}) ORDER BY timestamp",
            [case_id, *ids],
        ).fetchall()
        if len(frames) != len(ids):
            raise HTTPException(404, "One or more frames were not found in this case")
        archive_path = EXPORT_DIR / f"frames_{case_id[:8]}_{new_id()[:8]}.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for frame in frames:
                source = absolute_from_data(frame["image_path"])
                arcname = f"{frame['timestamp']:08.2f}s_{frame['id']}.jpg"
                archive.write(source, arcname=arcname)
        audit(conn, case_id, "frames_archive_downloaded", {"count": len(frames)}, utc_now())
    return FileResponse(archive_path, media_type="application/zip", filename=archive_path.name)


@router.get("/contact_sheet")
def download_contact_sheet(case_id: str = Query(...), frame_ids: str = Query(...)):
    ids = [item for item in frame_ids.split(",") if item][:200]
    if not ids:
        raise HTTPException(422, "Select at least one frame")
    try:
        sheet = build_contact_sheet(case_id, ids)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with get_db() as conn:
        audit(conn, case_id, "contact_sheet_downloaded", {"count": len(ids)}, utc_now())
    return FileResponse(sheet, media_type="application/pdf", filename=sheet.name)


@router.get("")
def list_exports(case_id: str | None = None):
    with get_db() as conn:
        if case_id:
            return rows_to_dicts(conn.execute("SELECT * FROM exports WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall())
        return rows_to_dicts(conn.execute("SELECT * FROM exports ORDER BY created_at DESC").fetchall())


@router.get("/{export_id}/pdf")
def download_pdf(export_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT pdf_path FROM exports WHERE id=?", (export_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Export not found")
        path = absolute_from_data(row["pdf_path"])
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/{export_id}/manifest")
def download_manifest(export_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT manifest_path FROM exports WHERE id=?", (export_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Export not found")
        path = absolute_from_data(row["manifest_path"])
    return FileResponse(path, media_type="application/json", filename=path.name)
