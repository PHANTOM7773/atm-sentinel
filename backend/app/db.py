from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DB_PATH, SCHEMA_VERSION, ensure_dirs

SCHEMA = f"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    case_number TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    reference TEXT NOT NULL,
    atm_id TEXT NOT NULL DEFAULT '',
    transaction_ts TEXT NOT NULL,
    cctv_ts TEXT NOT NULL DEFAULT '',
    transaction_type TEXT NOT NULL DEFAULT 'withdrawal',
    amount TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    container TEXT NOT NULL DEFAULT '',
    codec TEXT NOT NULL DEFAULT '',
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    fps REAL NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    stream_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{{}}',
    integrity_status TEXT NOT NULL DEFAULT 'pending',
    integrity_detail TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'Queued',
    progress INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{{}}',
    alignment_json TEXT NOT NULL DEFAULT '{{}}',
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS frames (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    relative_time REAL NOT NULL,
    image_path TEXT NOT NULL,
    thumb_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    sharpness REAL NOT NULL DEFAULT 0,
    brightness REAL NOT NULL DEFAULT 0,
    contrast REAL NOT NULL DEFAULT 0,
    quality_score REAL NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    metrics_json TEXT NOT NULL DEFAULT '{{}}',
    source TEXT NOT NULL DEFAULT 'coarse',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    frame_id TEXT NOT NULL UNIQUE REFERENCES frames(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    selected_at TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    selection_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_id TEXT REFERENCES videos(id) ON DELETE CASCADE,
    frame_id TEXT REFERENCES frames(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_links (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_a TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    video_b TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{{}}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    pdf_path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    report_hash TEXT NOT NULL,
    pdf_sha256 TEXT NOT NULL,
    frame_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_videos_case_id ON videos(case_id, id);

CREATE TABLE IF NOT EXISTS cv_runs (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    source_video_sha256 TEXT NOT NULL,
    normalized_video_id TEXT REFERENCES videos(id) ON DELETE SET NULL,
    normalized_video_sha256 TEXT,
    status TEXT NOT NULL CHECK(status IN ('queued', 'running', 'completed', 'completed_with_warnings', 'failed')),
    window_mode TEXT NOT NULL CHECK(window_mode IN ('full_video', 'transaction_aligned')),
    before_seconds REAL,
    after_seconds REAL,
    window_start_seconds REAL NOT NULL DEFAULT 0,
    window_end_seconds REAL NOT NULL DEFAULT 0,
    source_video_duration_seconds REAL NOT NULL DEFAULT 0,
    clamped INTEGER NOT NULL DEFAULT 0,
    analysis_run_id TEXT NOT NULL,
    request_json TEXT NOT NULL DEFAULT '{{}}',
    atm_zone_json TEXT NOT NULL DEFAULT '{{}}',
    window_json TEXT NOT NULL DEFAULT '{{}}',
    timestamp_provenance_json TEXT NOT NULL DEFAULT '{{}}',
    model_provenance_json TEXT NOT NULL DEFAULT '[]',
    budget_json TEXT NOT NULL DEFAULT '{{}}',
    truncation_json TEXT NOT NULL DEFAULT '{{}}',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    disclaimer TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    failure_detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY(case_id, video_id) REFERENCES videos(case_id, id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cv_runs_case_id ON cv_runs(case_id, id);

CREATE TABLE IF NOT EXISTS cv_observations (
    id TEXT PRIMARY KEY,
    cv_run_id TEXT NOT NULL REFERENCES cv_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    source_video_sha256 TEXT NOT NULL,
    original_frame_number INTEGER NOT NULL,
    original_video_timestamp_seconds REAL NOT NULL,
    analysis_relative_timestamp_seconds REAL,
    extracted_frame_id TEXT,
    bbox_json TEXT NOT NULL DEFAULT '[]',
    detector_confidence REAL NOT NULL DEFAULT 0,
    track_id INTEGER,
    quality_json TEXT NOT NULL DEFAULT '{{}}',
    pose_json TEXT NOT NULL DEFAULT '{{}}',
    review_flags_json TEXT NOT NULL DEFAULT '{{}}',
    crop_id TEXT,
    crop_available INTEGER NOT NULL DEFAULT 0,
    crop_status TEXT NOT NULL DEFAULT 'not_generated' CHECK(crop_status IN ('not_generated', 'available', 'unavailable', 'retired')),
    crop_retrieval_state TEXT NOT NULL DEFAULT 'not_supported' CHECK(crop_retrieval_state IN ('not_requested', 'retrievable', 'pending', 'expired', 'not_supported')),
    verification_status TEXT NOT NULL DEFAULT 'candidate_only',
    created_at TEXT NOT NULL,
    UNIQUE(cv_run_id, sample_id),
    FOREIGN KEY(case_id, cv_run_id) REFERENCES cv_runs(case_id, id) ON DELETE CASCADE,
    FOREIGN KEY(case_id, video_id) REFERENCES videos(case_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cv_review_decisions (
    decision_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    cv_run_id TEXT NOT NULL REFERENCES cv_runs(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK(target_type='face_observation'),
    target_id TEXT NOT NULL REFERENCES cv_observations(id) ON DELETE CASCADE,
    decision TEXT NOT NULL CHECK(decision IN ('relevant','irrelevant','needs_review')),
    reviewer_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(case_id, cv_run_id, target_type, target_id)
);

CREATE TABLE IF NOT EXISTS cv_person_observations (
    id TEXT PRIMARY KEY,
    cv_run_id TEXT NOT NULL REFERENCES cv_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    source_video_sha256 TEXT NOT NULL,
    original_frame_number INTEGER NOT NULL,
    original_video_timestamp_seconds REAL NOT NULL,
    analysis_relative_timestamp_seconds REAL,
    bbox_json TEXT NOT NULL DEFAULT '[]',
    detector_confidence REAL NOT NULL DEFAULT 0,
    track_id INTEGER NOT NULL,
    zone_overlap_ratio REAL NOT NULL DEFAULT 0,
    zone_iou REAL NOT NULL DEFAULT 0,
    in_zone INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(cv_run_id, sample_id),
    FOREIGN KEY(case_id, cv_run_id) REFERENCES cv_runs(case_id, id) ON DELETE CASCADE,
    FOREIGN KEY(case_id, video_id) REFERENCES videos(case_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_person_associations (
    association_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
    cv_run_id TEXT NOT NULL REFERENCES cv_runs(id) ON DELETE CASCADE,
    video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    candidate_key TEXT NOT NULL,
    source_video_sha256 TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    zone_id TEXT NOT NULL,
    person_track_id INTEGER,
    review_state TEXT NOT NULL CHECK(review_state IN ('proposed','confirmed','rejected','insufficient_evidence')),
    evidence_strength TEXT NOT NULL CHECK(evidence_strength IN ('strong','moderate','weak','insufficient')),
    heuristic_score REAL NOT NULL DEFAULT 0,
    dwell_seconds REAL NOT NULL DEFAULT 0,
    zone_frame_count INTEGER NOT NULL DEFAULT 0,
    transaction_window_overlap_seconds REAL NOT NULL DEFAULT 0,
    first_video_timestamp_seconds REAL,
    last_video_timestamp_seconds REAL,
    transaction_video_seconds REAL,
    window_start_seconds REAL NOT NULL DEFAULT 0,
    window_end_seconds REAL NOT NULL DEFAULT 0,
    evidence_json TEXT NOT NULL DEFAULT '{{}}',
    reviewer_note TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(cv_run_id, zone_id, candidate_key),
    FOREIGN KEY(case_id, cv_run_id) REFERENCES cv_runs(case_id, id) ON DELETE CASCADE,
    FOREIGN KEY(case_id, video_id) REFERENCES videos(case_id, id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_frames_case ON frames(case_id);
CREATE INDEX IF NOT EXISTS idx_frames_video ON frames(video_id);
CREATE INDEX IF NOT EXISTS idx_videos_case ON videos(case_id);
CREATE INDEX IF NOT EXISTS idx_jobs_case ON processing_jobs(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id);
CREATE INDEX IF NOT EXISTS idx_cv_runs_case ON cv_runs(case_id);
CREATE INDEX IF NOT EXISTS idx_cv_runs_video ON cv_runs(video_id);
CREATE INDEX IF NOT EXISTS idx_cv_runs_status ON cv_runs(status);
CREATE INDEX IF NOT EXISTS idx_cv_observations_run ON cv_observations(cv_run_id);
CREATE INDEX IF NOT EXISTS idx_cv_observations_case ON cv_observations(case_id);
CREATE INDEX IF NOT EXISTS idx_cv_observations_video ON cv_observations(video_id);
CREATE INDEX IF NOT EXISTS idx_cv_review_decisions_scope ON cv_review_decisions(case_id, cv_run_id);
CREATE INDEX IF NOT EXISTS idx_cv_review_decisions_run_target ON cv_review_decisions(cv_run_id, target_id);
CREATE INDEX IF NOT EXISTS idx_cv_person_observations_run ON cv_person_observations(cv_run_id);
CREATE INDEX IF NOT EXISTS idx_cv_person_observations_track ON cv_person_observations(cv_run_id, track_id);
CREATE INDEX IF NOT EXISTS idx_transaction_person_associations_run ON transaction_person_associations(cv_run_id);
CREATE INDEX IF NOT EXISTS idx_transaction_person_associations_case ON transaction_person_associations(case_id);
CREATE INDEX IF NOT EXISTS idx_transaction_person_associations_tx ON transaction_person_associations(transaction_id);
"""


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for table in ("cases", "videos"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if "tags" not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        cv_run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cv_runs)")}
        if "atm_zone_json" not in cv_run_columns:
            conn.execute("ALTER TABLE cv_runs ADD COLUMN atm_zone_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )


def rows_to_dicts(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def audit(conn: sqlite3.Connection, case_id: str | None, action: str, detail: dict[str, Any] | None = None, created_at: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_events(case_id, action, detail_json, created_at) VALUES(?,?,?,?)",
        (case_id, action, json.dumps(detail or {}), created_at or utc_now()),
    )


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_tags(value: str | None) -> str:
    seen: set[str] = set()
    tags: list[str] = []
    for raw in (value or "").split(","):
        tag = raw.strip()[:40]
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag)
    return ",".join(tags[:12])
