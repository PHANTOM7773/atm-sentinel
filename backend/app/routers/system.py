from __future__ import annotations

from fastapi import APIRouter

from ..config import APP_NAME, APP_VERSION
from ..db import get_db
from ..services.quality import LIMITATIONS
from ..services.video import dependencies, tool_versions

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def system_status():
    with get_db() as conn:
        counts = {
            "cases": conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"],
            "videos": conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()["n"],
            "jobs": conn.execute("SELECT COUNT(*) AS n FROM processing_jobs").fetchone()["n"],
            "frames": conn.execute("SELECT COUNT(*) AS n FROM frames").fetchone()["n"],
            "evidence_items": conn.execute("SELECT COUNT(*) AS n FROM evidence_items").fetchone()["n"],
            "exports": conn.execute("SELECT COUNT(*) AS n FROM exports").fetchone()["n"],
        }
        recent = [dict(row) for row in conn.execute("SELECT * FROM audit_events ORDER BY id DESC LIMIT 12").fetchall()]
    return {
        "app": APP_NAME,
        "version": APP_VERSION,
        "counts": counts,
        "dependencies": dependencies(),
        "tool_versions": tool_versions(),
        "quality_score_limitations": LIMITATIONS,
        "recent_activity": recent,
        "disclaimer": "Prototype evidence organization and integrity tracking.",
    }
