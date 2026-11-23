from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from ..config import DATA_DIR, MAX_UPLOAD_BYTES, UPLOAD_DIR, absolute_from_data
from ..db import audit, get_db, normalize_tags, row_to_dict, rows_to_dicts, utc_now
from ..services.security import ValidationError, internal_video_name, new_id, safe_original_name, sha256_file, validate_upload
from ..schemas import VideoUpdate
from ..services.video import VideoError, check_integrity, normalize_video, probe_video

router = APIRouter(prefix="/api/videos", tags=["videos"])
TMP_DIR = DATA_DIR / "tmp"


@router.post("/upload", status_code=201)
async def upload_video(case_id: str = Query(...), file: UploadFile = File(...)):
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    header = await file.read(64)
    await file.seek(0)
    declared_size = file.size or 0
    try:
        safe_name, ext = validate_upload(file.filename or "", declared_size, header, MAX_UPLOAD_BYTES)
    except ValidationError as exc:
        raise HTTPException(422, str(exc)) from exc

    video_id = new_id()
    temp_path = TMP_DIR / f"{video_id}.part"
    digest = ""
    written = 0
    try:
        import hashlib

        hasher = hashlib.sha256()
        with temp_path.open("wb") as sink:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"Upload exceeds the {MAX_UPLOAD_BYTES} byte limit")
                hasher.update(chunk)
                sink.write(chunk)
        digest = hasher.hexdigest()
        if written == 0:
            raise HTTPException(422, "Empty upload: the file has no bytes")
    finally:
        await file.close()

    try:
        metadata = probe_video(temp_path)
    except VideoError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc

    integrity, detail = "pending", ""
    try:
        integrity, detail = check_integrity(temp_path)
    except VideoError as exc:
        integrity, detail = "failed", str(exc)

    destination = UPLOAD_DIR / internal_video_name(video_id, ext)
    shutil.move(str(temp_path), str(destination))
    final_hash = sha256_file(destination)
    if final_hash != digest:
        raise HTTPException(500, "Hash mismatch while storing the upload")

    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM cases WHERE id=?", (case_id,)).fetchone():
            raise HTTPException(404, "Case not found")
        conn.execute(
            """INSERT INTO videos(id, case_id, original_filename, stored_path, content_type, size_bytes, sha256,
               container, codec, width, height, fps, duration, stream_count, metadata_json,
               integrity_status, integrity_detail, uploaded_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                video_id,
                case_id,
                safe_name,
                str(destination.relative_to(DATA_DIR)),
                file.content_type or "",
                written,
                final_hash,
                metadata["container"],
                metadata["codec"],
                metadata["width"],
                metadata["height"],
                metadata["fps"],
                metadata["duration"],
                metadata["stream_count"],
                json.dumps(metadata),
                integrity,
                detail,
                utc_now(),
            ),
        )
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        audit(conn, case_id, "video_uploaded", {"video_id": video_id, "filename": safe_name, "sha256": final_hash})
        return row_to_dict(conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())


@router.get("")
def list_videos(case_id: str | None = Query(default=None)):
    with get_db() as conn:
        if case_id:
            return rows_to_dicts(conn.execute("SELECT * FROM videos WHERE case_id=? ORDER BY uploaded_at DESC", (case_id,)).fetchall())
        return rows_to_dicts(conn.execute("SELECT * FROM videos ORDER BY uploaded_at DESC").fetchall())


@router.get("/{video_id}")
def get_video(video_id: str):
    with get_db() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
        if not row:
            raise HTTPException(404, "Video not found")
        row["metadata"] = json.loads(row["metadata_json"] or "{}")
        return row


@router.patch("/{video_id}")
def update_video(video_id: str, payload: VideoUpdate):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Video not found")
        tags = normalize_tags(payload.tags)
        conn.execute("UPDATE videos SET tags=? WHERE id=?", (tags, video_id))
        audit(conn, row["case_id"], "video_tags_updated", {"video_id": video_id, "tags": tags})
        return row_to_dict(conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())


@router.get("/{video_id}/file")
def video_file(video_id: str):
    from fastapi.responses import FileResponse

    with get_db() as conn:
        row = conn.execute("SELECT stored_path FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Video not found")
        path = absolute_from_data(row["stored_path"])
    return FileResponse(path, media_type="video/mp4", filename=None)


@router.post("/{video_id}/verify")
def verify_video(video_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Video not found")
        path = absolute_from_data(row["stored_path"])
        current_hash = sha256_file(path)
        if current_hash != row["sha256"]:
            conn.execute(
                "UPDATE videos SET integrity_status='failed', integrity_detail='SHA-256 changed since upload' WHERE id=?",
                (video_id,),
            )
            audit(conn, row["case_id"], "integrity_failed", {"video_id": video_id})
            return {"status": "failed", "detail": "SHA-256 changed since upload"}
        try:
            status, detail = check_integrity(path)
        except VideoError as exc:
            status, detail = "failed", str(exc)
        conn.execute(
            "UPDATE videos SET integrity_status=?, integrity_detail=? WHERE id=?", (status, detail, video_id)
        )
        audit(conn, row["case_id"], "integrity_checked", {"video_id": video_id, "status": status})
        return {"status": status, "detail": detail}


@router.post("/{video_id}/normalize", status_code=201)
def normalize(video_id: str, case_id: str = Query(...)):
    with get_db() as conn:
        source_row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not source_row or source_row["case_id"] != case_id:
            raise HTTPException(404, "Video not found in this case")
        source = absolute_from_data(source_row["stored_path"])
    new_id_value = new_id()
    destination = UPLOAD_DIR / f"{new_id_value}_normalized.mp4"
    try:
        normalize_video(source, destination)
    except VideoError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    metadata = probe_video(destination)
    digest = sha256_file(destination)
    with get_db() as conn:
        conn.execute(
            """INSERT INTO videos(id, case_id, original_filename, stored_path, content_type, size_bytes, sha256,
               container, codec, width, height, fps, duration, stream_count, metadata_json,
               integrity_status, integrity_detail, uploaded_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id_value,
                case_id,
                f"{Path(source_row['original_filename']).stem}_normalized.mp4",
                str(destination.relative_to(DATA_DIR)),
                "video/mp4",
                destination.stat().st_size,
                digest,
                metadata["container"],
                metadata["codec"],
                metadata["width"],
                metadata["height"],
                metadata["fps"],
                metadata["duration"],
                metadata["stream_count"],
                json.dumps(metadata),
                "verified",
                "Created locally by FFmpeg normalization; source file unchanged",
                utc_now(),
            ),
        )
        audit(conn, case_id, "video_normalized", {"source": video_id, "result": new_id_value})
        return row_to_dict(conn.execute("SELECT * FROM videos WHERE id=?", (new_id_value,)).fetchone())
