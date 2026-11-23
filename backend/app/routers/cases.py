from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import audit, get_db, normalize_tags, row_to_dict, rows_to_dicts, utc_now
from ..schemas import CaseCreate, CaseUpdate, ClipLinkCreate, NoteCreate, TransactionCreate
from ..services.security import new_id

router = APIRouter(prefix="/api", tags=["cases"])


def _case_or_404(conn, case_id: str):
    case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not case:
        raise HTTPException(404, "Case not found")
    return case


@router.get("/cases")
def list_cases(include_archived: bool = Query(default=False)):
    with get_db() as conn:
        query = "SELECT * FROM cases"
        if not include_archived:
            query += " WHERE status='active'"
        query += " ORDER BY updated_at DESC"
        return rows_to_dicts(conn.execute(query).fetchall())


@router.post("/cases", status_code=201)
def create_case(payload: CaseCreate):
    case_id = new_id()
    now = utc_now()
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO cases(id, case_number, title, location, tags, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    payload.case_number.strip(),
                    payload.title.strip(),
                    payload.location.strip(),
                    normalize_tags(payload.tags),
                    "active",
                    now,
                    now,
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "Case number already exists") from exc
            raise
        audit(conn, case_id, "case_created", {"case_number": payload.case_number}, now)
        return row_to_dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())


@router.get("/cases/{case_id}")
def get_case(case_id: str):
    with get_db() as conn:
        return row_to_dict(_case_or_404(conn, case_id))


@router.patch("/cases/{case_id}")
def update_case(case_id: str, payload: CaseUpdate):
    with get_db() as conn:
        _case_or_404(conn, case_id)
        fields = {key: value for key, value in payload.model_dump(exclude_none=True).items()}
        if not fields:
            raise HTTPException(400, "No changes supplied")
        if "tags" in fields:
            fields["tags"] = normalize_tags(fields["tags"])
        assignments = ", ".join(f"{key}=?" for key in fields)
        conn.execute(f"UPDATE cases SET {assignments}, updated_at=? WHERE id=?", [*fields.values(), utc_now(), case_id])
        audit(conn, case_id, "case_updated", fields)
        return row_to_dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())


@router.post("/cases/{case_id}/archive")
def archive_case(case_id: str, archived: bool = Query(default=True)):
    with get_db() as conn:
        _case_or_404(conn, case_id)
        status = "archived" if archived else "active"
        conn.execute("UPDATE cases SET status=?, updated_at=? WHERE id=?", (status, utc_now(), case_id))
        audit(conn, case_id, "case_archived" if archived else "case_restored", {})
        return row_to_dict(conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone())


@router.get("/cases/{case_id}/transactions")
def list_transactions(case_id: str):
    with get_db() as conn:
        _case_or_404(conn, case_id)
        return rows_to_dicts(conn.execute("SELECT * FROM transactions WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall())


@router.post("/cases/{case_id}/transactions", status_code=201)
def create_transaction(case_id: str, payload: TransactionCreate):
    from ..services.timestamp import TimestampError, parse_timestamp

    try:
        parse_timestamp(payload.transaction_ts, "transaction timestamp")
        if payload.cctv_ts:
            parse_timestamp(payload.cctv_ts, "CCTV timestamp")
    except TimestampError as exc:
        raise HTTPException(422, str(exc)) from exc

    tx_id = new_id()
    with get_db() as conn:
        _case_or_404(conn, case_id)
        try:
            conn.execute(
                """INSERT INTO transactions(id, case_id, reference, atm_id, transaction_ts, cctv_ts,
                   transaction_type, amount, note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    tx_id,
                    case_id,
                    payload.reference.strip(),
                    payload.atm_id.strip(),
                    payload.transaction_ts.strip(),
                    payload.cctv_ts.strip(),
                    payload.transaction_type.strip(),
                    payload.amount.strip(),
                    payload.note.strip(),
                    utc_now(),
                ),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise HTTPException(409, "Transaction reference already exists") from exc
            raise
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        audit(conn, case_id, "transaction_added", {"reference": payload.reference})
        return row_to_dict(conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone())


@router.get("/cases/{case_id}/notes")
def list_notes(case_id: str):
    with get_db() as conn:
        _case_or_404(conn, case_id)
        return rows_to_dicts(conn.execute("SELECT * FROM notes WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall())


@router.post("/cases/{case_id}/notes", status_code=201)
def create_note(case_id: str, payload: NoteCreate):
    note_id = new_id()
    now = utc_now()
    with get_db() as conn:
        _case_or_404(conn, case_id)
        conn.execute(
            "INSERT INTO notes(id, case_id, video_id, frame_id, body, created_at) VALUES(?,?,?,?,?,?)",
            (note_id, case_id, payload.video_id, payload.frame_id, payload.body.strip(), now),
        )
        audit(conn, case_id, "note_added", {"frame_id": payload.frame_id, "video_id": payload.video_id}, now)
        return row_to_dict(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())


@router.get("/cases/{case_id}/links")
def list_links(case_id: str):
    with get_db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM clip_links WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall())


@router.post("/cases/{case_id}/links", status_code=201)
def create_link(case_id: str, payload: ClipLinkCreate):
    if payload.video_a == payload.video_b:
        raise HTTPException(400, "Choose two different clips")
    link_id = new_id()
    with get_db() as conn:
        _case_or_404(conn, case_id)
        for video_id in (payload.video_a, payload.video_b):
            if not conn.execute("SELECT 1 FROM videos WHERE id=? AND case_id=?", (video_id, case_id)).fetchone():
                raise HTTPException(404, f"Video {video_id} not found in this case")
        conn.execute(
            "INSERT INTO clip_links(id, case_id, video_a, video_b, reason, created_at) VALUES(?,?,?,?,?,?)",
            (link_id, case_id, payload.video_a, payload.video_b, payload.reason.strip(), utc_now()),
        )
        audit(conn, case_id, "clip_link_added", {"video_a": payload.video_a, "video_b": payload.video_b})
        return row_to_dict(conn.execute("SELECT * FROM clip_links WHERE id=?", (link_id,)).fetchone())


@router.get("/cases/{case_id}/timeline")
def case_timeline(case_id: str):
    with get_db() as conn:
        _case_or_404(conn, case_id)
        events: list[dict] = []
        case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        events.append({"at": case["created_at"], "type": "case", "label": "Case created", "detail": case["case_number"]})
        for row in conn.execute("SELECT created_at, reference, transaction_ts FROM transactions WHERE case_id=?", (case_id,)):
            events.append({"at": row["created_at"], "type": "transaction", "label": "Transaction added", "detail": row["reference"]})
        for row in conn.execute("SELECT uploaded_at, original_filename FROM videos WHERE case_id=?", (case_id,)):
            events.append({"at": row["uploaded_at"], "type": "video", "label": "Video uploaded", "detail": row["original_filename"]})
        for row in conn.execute("SELECT created_at, stage, status FROM processing_jobs WHERE case_id=?", (case_id,)):
            events.append({"at": row["created_at"], "type": "job", "label": "Processing job", "detail": f"{row['stage']} — {row['status']}"})
        for row in conn.execute("SELECT created_at, body FROM notes WHERE case_id=?", (case_id,)):
            events.append({"at": row["created_at"], "type": "note", "label": "Note", "detail": row["body"][:140]})
        events.sort(key=lambda event: event["at"], reverse=True)
        return events


@router.get("/search")
def search(q: str = Query(default="", max_length=200)):
    term = f"%{q.strip()}%"
    with get_db() as conn:
        cases = rows_to_dicts(
            conn.execute(
                """SELECT DISTINCT c.* FROM cases c
                   LEFT JOIN transactions t ON t.case_id=c.id
                   LEFT JOIN videos v ON v.case_id=c.id
                    WHERE c.case_number LIKE ? OR c.title LIKE ? OR c.location LIKE ? OR c.tags LIKE ?
                       OR t.reference LIKE ? OR t.atm_id LIKE ? OR v.original_filename LIKE ? OR v.tags LIKE ?
                    ORDER BY c.updated_at DESC LIMIT 50""",
                 (term, term, term, term, term, term, term, term),

            ).fetchall()
        )
        videos = rows_to_dicts(
            conn.execute(
                "SELECT * FROM videos WHERE original_filename LIKE ? OR container LIKE ? OR codec LIKE ? OR tags LIKE ? ORDER BY uploaded_at DESC LIMIT 50",
                (term, term, term, term),
            ).fetchall()
        )
        return {"cases": cases, "videos": videos}
