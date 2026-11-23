from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

from ..config import APP_VERSION, DATA_DIR, EXPORT_DIR
from ..db import get_db, parse_json
from ..schemas import (
    CV_ASSOCIATION_LIMITATION,
    CV_CANDIDATE_DISCLAIMER,
    CV_SIMILARITY_SCORE_MEANING,
    CvExportItem,
)
from .security import new_id, sha256_bytes, sha256_file

DISCLAIMER = (
    "Prototype evidence organization and integrity tracking. Not legally or court certified. "
    "CV similarity candidates are review-only ranking evidence; no identity assessment is performed."
)
ELIGIBLE_CV_RUN_STATUSES = {"completed", "completed_with_warnings"}
MODEL_PROVENANCE_FIELDS = (
    "model_key",
    "model_filename",
    "model_sha256",
    "model_source_url",
    "backend",
    "target",
    "runtime_state",
    "opencv_version",
    "pipeline_version",
    "embedding_schema_version",
    "generated_at",
)
MODEL_FINGERPRINT_FIELDS = tuple(field for field in MODEL_PROVENANCE_FIELDS if field != "generated_at")
QUALITY_EXPORT_FIELDS = (
    "quality_score",
    "sharpness",
    "brightness",
    "contrast",
    "face_size_px",
    "crop_size_px",
    "occlusion_status",
    "warnings",
    "disclaimer",
)
REVIEW_FLAG_EXPORT_FIELDS = (
    "low_sharpness",
    "underexposed",
    "overexposed",
    "small_face",
    "pose_away",
    "partial_occlusion_suspected",
    "occlusion_review",
    "mask",
    "helmet",
    "cap",
)


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("TitleATMS", parent=base["Title"], fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=colors.HexColor("#0f2540")),
        "h2": ParagraphStyle("H2ATMS", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=5, textColor=colors.HexColor("#173a63")),
        "body": ParagraphStyle("BodyATMS", parent=base["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11.5, alignment=TA_LEFT),
        "small": ParagraphStyle("SmallATMS", parent=base["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9.2, textColor=colors.HexColor("#44515f")),
        "warn": ParagraphStyle("WarnATMS", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=10, textColor=colors.HexColor("#8a4b00")),
    }


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table([[Paragraph(escape(str(cell)), _styles()["small"]) for cell in row] for row in rows], colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#173a63")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3df")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _parse_export_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _public_model_provenance(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for record in value:
        if not isinstance(record, dict):
            continue
        digest = str(record.get("model_sha256") or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            continue
        public = {field: record[field] for field in MODEL_PROVENANCE_FIELDS if field in record}
        public["model_sha256"] = digest
        result.append(public)
    return result


def _model_fingerprint(record: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(record.get(field) or "") for field in MODEL_FINGERPRINT_FIELDS)


def _eligible_run(row: Any) -> bool:
    return bool(row) and str(row["status"]) in ELIGIBLE_CV_RUN_STATUSES and bool(str(row["analysis_run_id"] or ""))


def _resolve_cv_selections(case_id: str, items: list[CvExportItem]) -> list[dict[str, Any]]:
    if not items:
        return []
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    with get_db() as conn:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            raise ValueError("Case not found")
        for item in items:
            key = (item.kind, item.cv_run_id, item.observation_id)
            if key in seen:
                raise ValueError("Duplicate CV selection")
            seen.add(key)
            run = conn.execute(
                "SELECT * FROM cv_runs WHERE id=? AND case_id=?",
                (item.cv_run_id, case_id),
            ).fetchone()
            if not _eligible_run(run):
                raise ValueError("One or more selected CV items are not eligible")
            video = conn.execute(
                "SELECT * FROM videos WHERE id=? AND case_id=?",
                (str(run["video_id"]), case_id),
            ).fetchone()
            if not video or str(video["sha256"]) != str(run["source_video_sha256"]):
                raise ValueError("CV source video provenance mismatch")
            if run["normalized_video_id"]:
                normalized = conn.execute(
                    "SELECT * FROM videos WHERE id=? AND case_id=?",
                    (str(run["normalized_video_id"]), case_id),
                ).fetchone()
                if not normalized or str(normalized["sha256"]) != str(run["normalized_video_sha256"]):
                    raise ValueError("CV normalized video provenance mismatch")
            observation = conn.execute(
                """
                SELECT * FROM cv_observations
                WHERE id=? AND cv_run_id=? AND case_id=? AND video_id=?
                """,
                (item.observation_id, item.cv_run_id, case_id, str(video["id"])),
            ).fetchone()
            if not observation or str(observation["verification_status"]) != "candidate_only":
                raise ValueError("One or more selected CV observations are not eligible")
            review = conn.execute(
                """
                SELECT * FROM cv_review_decisions
                WHERE case_id=? AND cv_run_id=? AND target_type='face_observation' AND target_id=?
                """,
                (case_id, item.cv_run_id, item.observation_id),
            ).fetchone()
            if item.kind == "candidate" and (not review or str(review["decision"]) != "relevant"):
                raise ValueError("Selected CV candidates require a relevant human review decision")
            if item.expected_review_updated_at:
                expected = _parse_export_timestamp(item.expected_review_updated_at)
                current = _parse_export_timestamp(review["updated_at"]) if review else None
                if expected is None or current is None or expected != current:
                    raise ValueError("CV review selection is stale")
            models = _public_model_provenance(parse_json(run["model_provenance_json"], []))
            if not models:
                raise ValueError("CV model provenance is unavailable")
            if item.expected_model_sha256 and not any(
                record["model_sha256"] == item.expected_model_sha256 for record in models
            ):
                raise ValueError("CV model provenance selection is stale")
            quality_raw = parse_json(observation["quality_json"], {})
            quality = (
                {field: quality_raw[field] for field in QUALITY_EXPORT_FIELDS if field in quality_raw}
                if isinstance(quality_raw, dict)
                else {}
            )
            flags_raw = parse_json(observation["review_flags_json"], {})
            flags = (
                {field: flags_raw[field] for field in REVIEW_FLAG_EXPORT_FIELDS if field in flags_raw}
                if isinstance(flags_raw, dict)
                else {}
            )
            bbox = parse_json(observation["bbox_json"], [])
            review_export = None
            if review:
                review_export = {
                    "decision_id": str(review["decision_id"]),
                    "decision": str(review["decision"]),
                    "reviewer_note": review["reviewer_note"] or "",
                    "created_at": str(review["created_at"]),
                    "updated_at": str(review["updated_at"]),
                }
            query_export: dict[str, Any] | None = None
            if item.kind == "candidate":
                query_run = conn.execute(
                    "SELECT * FROM cv_runs WHERE id=? AND case_id=?",
                    (str(item.query_cv_run_id), case_id),
                ).fetchone()
                if not _eligible_run(query_run):
                    raise ValueError("One or more selected CV candidates are not eligible")
                query_video = conn.execute(
                    "SELECT * FROM videos WHERE id=? AND case_id=?",
                    (str(query_run["video_id"]), case_id),
                ).fetchone()
                if not query_video:
                    raise ValueError("CV query video not found in case")
                query_observation = conn.execute(
                    """
                    SELECT * FROM cv_observations
                    WHERE id=? AND cv_run_id=? AND case_id=? AND video_id=?
                    """,
                    (str(item.query_observation_id), str(query_run["id"]), case_id, str(query_video["id"])),
                ).fetchone()
                if not query_observation:
                    raise ValueError("CV query observation not found in case")
                if str(query_observation["id"]) == str(observation["id"]) or str(query_video["id"]) == str(video["id"]):
                    raise ValueError("Selected CV candidate is not eligible for this query")
                query_models = _public_model_provenance(parse_json(query_run["model_provenance_json"], []))
                query_fingerprints = {_model_fingerprint(record) for record in query_models}
                if not any(_model_fingerprint(record) in query_fingerprints for record in models):
                    raise ValueError("CV candidate and query model provenance do not match")
                query_export = {
                    "query_cv_run_id": str(query_run["id"]),
                    "query_observation_id": str(query_observation["id"]),
                    "query_video_id": str(query_video["id"]),
                    "query_original_frame_number": int(query_observation["original_frame_number"]),
                    "query_original_video_timestamp_seconds": float(
                        query_observation["original_video_timestamp_seconds"]
                    ),
                }
            selection_context = None
            if item.kind == "candidate" and item.selection_context:
                context = item.selection_context
                selection_context = {
                    "status": "unverified_client_selection_context",
                    "candidate_id": item.candidate_id,
                    "rank": context.rank,
                    "similarity_score": context.similarity_score,
                    "score_meaning": context.score_meaning or CV_SIMILARITY_SCORE_MEANING,
                    "candidate_disclaimer": context.candidate_disclaimer or CV_CANDIDATE_DISCLAIMER,
                    "disclaimer": (
                        "Rank and similarity were supplied by the client at selection time and are not persisted or "
                        "independently verifiable. They are ranking evidence only."
                    ),
                }
            resolved.append(
                {
                    "kind": item.kind,
                    "cv_run_id": str(run["id"]),
                    "analysis_run_id": str(run["analysis_run_id"]),
                    "observation_id": str(observation["id"]),
                    "cv_sample_id": str(observation["sample_id"]),
                    "source_video_id": str(video["id"]),
                    "source_video_sha256": str(video["sha256"]),
                    "normalized_video_id": str(run["normalized_video_id"]) if run["normalized_video_id"] else None,
                    "normalized_video_sha256": (
                        str(run["normalized_video_sha256"]) if run["normalized_video_id"] else None
                    ),
                    "original_frame_number": int(observation["original_frame_number"]),
                    "original_video_timestamp_seconds": float(observation["original_video_timestamp_seconds"]),
                    "analysis_relative_timestamp_seconds": observation["analysis_relative_timestamp_seconds"],
                    "bbox": bbox if isinstance(bbox, list) and len(bbox) == 4 else [],
                    "quality": quality,
                    "review_flags": flags,
                    "crop": {
                        "crop_id": observation["crop_id"] if observation["crop_available"] else None,
                        "available": bool(observation["crop_available"]),
                        "status": str(observation["crop_status"]),
                        "retrieval_state": str(observation["crop_retrieval_state"]),
                    },
                    "verification_status": str(observation["verification_status"]),
                    "requires_human_verification": True,
                    "model_provenance": models,
                    "human_review": review_export,
                    "query": query_export,
                    "selection_context": selection_context,
                    "candidate_disclaimer": CV_CANDIDATE_DISCLAIMER,
                    "association_limitation": CV_ASSOCIATION_LIMITATION,
                }
            )
    return resolved


def build_report_payload(case_id: str, frame_ids: list[str], cv_items: list[CvExportItem] | None = None) -> dict[str, Any]:
    from ..db import utc_now

    with get_db() as conn:
        case = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not case:
            raise ValueError("Case not found")
        txs = [dict(row) for row in conn.execute("SELECT * FROM transactions WHERE case_id=? ORDER BY created_at", (case_id,))]
        videos = [dict(row) for row in conn.execute("SELECT * FROM videos WHERE case_id=? ORDER BY uploaded_at", (case_id,))]
        jobs = [dict(row) for row in conn.execute("SELECT * FROM processing_jobs WHERE case_id=? ORDER BY created_at", (case_id,))]
        notes = [dict(row) for row in conn.execute("SELECT * FROM notes WHERE case_id=? ORDER BY created_at", (case_id,))]
        links = [dict(row) for row in conn.execute("SELECT * FROM clip_links WHERE case_id=? ORDER BY created_at", (case_id,))]
        audit = [dict(row) for row in conn.execute("SELECT * FROM audit_events WHERE case_id=? ORDER BY id", (case_id,))]
        if frame_ids:
            placeholders = ",".join("?" for _ in frame_ids)
            frame_rows = conn.execute(
                f"SELECT * FROM frames WHERE case_id=? AND id IN ({placeholders})", [case_id, *frame_ids]
            ).fetchall()
            order = {fid: index for index, fid in enumerate(frame_ids)}
            frames = sorted([dict(row) for row in frame_rows], key=lambda row: order.get(row["id"], 9999))
        else:
            frames = []

    if not frames:
        raise ValueError("Select at least one evidence frame before exporting")
    cv_selections = _resolve_cv_selections(case_id, cv_items or [])

    return {
        "software": "ATM Sentinel",
        "version": APP_VERSION,
        "generated_at": utc_now(),
        "disclaimer": DISCLAIMER,
        "case": dict(case),
        "transactions": txs,
        "videos": videos,
        "processing_jobs": jobs,
        "frames": frames,
        "notes": notes,
        "clip_links": links,
        "audit_events": audit,
        "cv_selections": cv_selections,
        "cv_selection_count": len(cv_selections),
        "cv_candidate_count": sum(1 for item in cv_selections if item["kind"] == "candidate"),
        "cv_observation_count": sum(1 for item in cv_selections if item["kind"] == "observation"),
        "cv_disclaimer": CV_CANDIDATE_DISCLAIMER,
        "cv_association_limitation": CV_ASSOCIATION_LIMITATION,
    }


def build_report(case_id: str, frame_ids: list[str], cv_items: list[CvExportItem] | None = None) -> dict[str, Any]:
    payload = build_report_payload(case_id, frame_ids, cv_items)
    report_hash = sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    export_id = new_id()
    pdf_path = EXPORT_DIR / f"{case_id[:8]}_{export_id[:8]}.pdf"
    manifest_path = EXPORT_DIR / f"{case_id[:8]}_{export_id[:8]}.json"

    styles = _styles()
    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"ATM Sentinel evidence report {payload['case']['case_number']}",
        author="ATM Sentinel prototype",
    )
    story: list[Any] = []
    story.append(Paragraph("ATM Sentinel — Evidence Report", styles["title"]))
    story.append(Paragraph("Transaction-driven CCTV evidence analysis", styles["body"]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(f"<b>{escape(DISCLAIMER)}</b>", styles["warn"]))
    story.append(Spacer(1, 8))

    case = payload["case"]
    story.append(Paragraph("1. Case information", styles["h2"]))
    story.append(
        _table(
            [
                ["Field", "Value"],
                ["Case number", case["case_number"]],
                ["Title", case["title"]],
                ["Location", case["location"] or "—"],
                ["Tags", case.get("tags") or "—"],
                ["Status", case["status"]],
                ["Report generated", payload["generated_at"]],
            ],
            [42 * mm, 132 * mm],
        )
    )

    story.append(Paragraph("2. Transaction details", styles["h2"]))
    tx_rows = [["Reference", "ATM", "Transaction time", "CCTV time", "Type", "Amount"]]
    for tx in payload["transactions"]:
        tx_rows.append(
            [
                tx["reference"],
                tx["atm_id"] or "—",
                tx["transaction_ts"],
                tx["cctv_ts"] or "—",
                tx["transaction_type"],
                tx["amount"] or "—",
            ]
        )
    story.append(_table(tx_rows, [29 * mm, 22 * mm, 39 * mm, 39 * mm, 25 * mm, 20 * mm]))

    story.append(Paragraph("3. Source video and integrity", styles["h2"]))
    video_rows = [["File", "Container", "Codec", "Resolution", "FPS", "Duration", "SHA-256"]]
    for video in payload["videos"]:
        video_rows.append(
            [
                video["original_filename"],
                video["container"],
                video["codec"],
                f"{video['width']}x{video['height']}",
                str(video["fps"]),
                f"{video['duration']}s",
                video["sha256"],
            ]
        )
    story.append(_table(video_rows, [32 * mm, 23 * mm, 18 * mm, 22 * mm, 13 * mm, 17 * mm, 49 * mm]))

    story.append(Paragraph("4. Timestamp alignment and analysis window", styles["h2"]))
    for job in payload["processing_jobs"]:
        alignment = parse_json(job.get("alignment_json"), {}) or {}
        if not alignment:
            continue
        story.append(
            _table(
                [
                    ["Quantity", "Value"],
                    ["Job", job["id"]],
                    ["Transaction UTC", alignment.get("transaction_utc", "—")],
                    ["CCTV UTC", alignment.get("cctv_utc", "—")],
                    ["Offset", f"{alignment.get('offset_minutes', '—')} min ({alignment.get('offset_source', '—')})"],
                    ["Transaction at video time", f"{alignment.get('transaction_video_seconds', '—')} s"],
                    ["Analysis window", f"{alignment.get('window_start_seconds', '—')} s to {alignment.get('window_end_seconds', '—')} s"],
                    ["Warnings", "; ".join(alignment.get("warnings", [])) or "none"],
                ],
                [48 * mm, 126 * mm],
            )
        )
        story.append(Spacer(1, 3))

    story.append(Paragraph("5. Selected evidence frames", styles["h2"]))
    frame_notes = [note for note in payload["notes"] if note.get("frame_id")]
    for index, frame in enumerate(payload["frames"], 1):
        story.append(Paragraph(f"Evidence {index} — {escape(frame['id'])}", styles["h2"]))
        image_path = DATA_DIR / frame["image_path"]
        if image_path.exists():
            from PIL import Image as PILImage

            with PILImage.open(image_path) as pil:
                iw, ih = pil.size
            scale = min(150 * mm / iw, 72 * mm / ih)
            story.append(Image(str(image_path), width=iw * scale, height=ih * scale))
            story.append(Spacer(1, 3))
        warnings = parse_json(frame.get("warnings_json"), []) or []
        metrics = parse_json(frame.get("metrics_json"), {}) or {}
        story.append(
            _table(
                [
                    ["Attribute", "Value"],
                    ["Video", next((v["original_filename"] for v in payload["videos"] if v["id"] == frame["video_id"]), frame["video_id"])],
                    ["Video timestamp", f"{frame['timestamp']} s"],
                    ["Source frame number", str(frame["frame_number"])],
                    ["Relative to transaction", f"{frame['relative_time']} s"],
                    ["Capture source", frame["source"]],
                    ["Sharpness / brightness / contrast", f"{frame['sharpness']} / {frame['brightness']} / {frame['contrast']}"],
                    ["Overall image-quality score", f"{frame['quality_score']} / 100 (image quality only)"],
                    ["Directional blur indicator", str(metrics.get("motion_blur_indicator", "—"))],
                    ["Warnings", "; ".join(warnings) if warnings else "none"],
                    ["Frame SHA-256", frame["sha256"]],
                    ["Investigator notes", "; ".join(n["body"] for n in frame_notes if n["frame_id"] == frame["id"]) or "—"],
                ],
                [54 * mm, 120 * mm],
            )
        )
        story.append(Spacer(1, 5))

    story.append(Paragraph("6. Selection history and annotations", styles["h2"]))
    selection_rows = [["Evidence", "Selected at", "Reason", "Note"]]
    for frame in payload["frames"]:
        with get_db() as conn:
            item = conn.execute("SELECT * FROM evidence_items WHERE frame_id=?", (frame["id"],)).fetchone()
        selection_rows.append(
            [
                frame["id"],
                item["selected_at"] if item else "—",
                (item["selection_reason"] if item and item["selection_reason"] else "—"),
                (item["note"] if item and item["note"] else "—"),
            ]
        )
    story.append(_table(selection_rows, [42 * mm, 36 * mm, 49 * mm, 47 * mm]))

    case_notes = [note for note in payload["notes"] if not note.get("frame_id")]
    if case_notes:
        story.append(Paragraph("7. Investigator notes", styles["h2"]))
        story.append(_table([["Created", "Note"]] + [[n["created_at"], n["body"]] for n in case_notes], [40 * mm, 134 * mm]))

    if payload["clip_links"]:
        story.append(Paragraph("8. Manually documented clip relationships", styles["h2"]))
        story.append(
            _table(
                [["Video A", "Video B", "Investigator rationale"]]
                + [[link["video_a"], link["video_b"], link["reason"]] for link in payload["clip_links"]],
                [45 * mm, 45 * mm, 84 * mm],
            )
        )

    if payload["cv_selections"]:
        story.append(Paragraph("9. Selected CV observations and candidates", styles["h2"]))
        story.append(Paragraph(f"<b>{escape(CV_ASSOCIATION_LIMITATION)}</b>", styles["warn"]))
        for index, selection in enumerate(payload["cv_selections"], 1):
            review = selection.get("human_review") or {}
            model = (selection.get("model_provenance") or [{}])[0]
            quality = selection.get("quality") or {}
            context = selection.get("selection_context") or {}
            query = selection.get("query") or {}
            story.append(Paragraph(f"CV reference {index} — {escape(str(selection['observation_id']))}", styles["h2"]))
            rows = [
                ["Attribute", "Value"],
                ["Selection type", str(selection["kind"])],
                ["CV run / analysis", f"{selection['cv_run_id']} / {selection['analysis_run_id']}"],
                ["Source video", f"{selection['source_video_id']} · SHA-256 {selection['source_video_sha256']}"],
                [
                    "Source time / frame",
                    f"{selection['original_video_timestamp_seconds']} s · frame {selection['original_frame_number']}",
                ],
                [
                    "Quality / flags",
                    f"score {quality.get('quality_score', '—')} · occlusion {quality.get('occlusion_status', '—')} · "
                    f"flags {json.dumps(selection.get('review_flags') or {}, sort_keys=True)}",
                ],
                ["Model provenance", f"{model.get('model_key', '—')} · SHA-256 {model.get('model_sha256', '—')}"],
                [
                    "Human review",
                    f"{review.get('decision', 'not_reviewed')} · {review.get('updated_at', '—')} · "
                    f"note: {review.get('reviewer_note') or '—'}",
                ],
                ["Verification", f"{selection['verification_status']} · {CV_CANDIDATE_DISCLAIMER}"],
            ]
            if query:
                rows.append(
                    [
                        "Query context",
                        f"{query.get('query_cv_run_id', '—')} / {query.get('query_observation_id', '—')} · "
                        f"source video {query.get('query_video_id', '—')}",
                    ]
                )
            if context:
                rows.append(
                    [
                        "Selection context (unverified)",
                        f"rank {context.get('rank', '—')} · similarity {context.get('similarity_score', '—')} · "
                        "ranking evidence only",
                    ]
                )
            rows.append(["Association limitation", CV_ASSOCIATION_LIMITATION])
            story.append(_table(rows, [46 * mm, 128 * mm]))
            story.append(Spacer(1, 4))

    story.append(Paragraph("Integrity and limitations", styles["h2"]))
    story.append(
        Paragraph(
            "Original files are preserved and hashed with SHA-256. Extracted frames are derived copies with their own hashes. "
            "The report hash is computed over the canonical report data; the PDF SHA-256 is recorded in the JSON manifest. "
            "Quality scores describe image usability only, never identity. CV similarity candidates are ranking evidence only; "
            "no face recognition or identity inference is performed. Detected faces, person tracks, similarity scores and review "
            f"decisions do not identify the ATM operator or any transaction participant. Software version {APP_VERSION}.",
            styles["body"],
        )
    )
    story.append(Paragraph(f"Report data SHA-256: {report_hash}", styles["small"]))
    doc.build(story)

    pdf_hash = sha256_file(pdf_path)
    manifest = dict(payload)
    manifest.update(
        {
            "report_hash": report_hash,
            "pdf_sha256": pdf_hash,
            "pdf_filename": pdf_path.name,
            "frame_count": len(payload["frames"]),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "id": export_id,
        "pdf_path": str(pdf_path.relative_to(DATA_DIR)),
        "manifest_path": str(manifest_path.relative_to(DATA_DIR)),
        "report_hash": report_hash,
        "pdf_sha256": pdf_hash,
        "frame_count": len(payload["frames"]),
        "cv_selection_count": payload["cv_selection_count"],
        "cv_candidate_count": payload["cv_candidate_count"],
        "cv_observation_count": payload["cv_observation_count"],
        "generated_at": payload["generated_at"],
    }


def build_contact_sheet(case_id: str, frame_ids: list[str]) -> Path:
    payload = build_report_payload(case_id, frame_ids)
    styles = _styles()
    output = EXPORT_DIR / f"contact_{case_id[:8]}_{new_id()[:8]}.pdf"
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"ATM Sentinel contact sheet {payload['case']['case_number']}",
        author="ATM Sentinel prototype",
    )
    story: list[Any] = [
        Paragraph("ATM Sentinel — Contact Sheet", styles["title"]),
        Paragraph(f"Case {escape(payload['case']['case_number'])} — {len(payload['frames'])} selected frames", styles["body"]),
        Spacer(1, 3),
        Paragraph(f"<b>{escape(DISCLAIMER)}</b>", styles["warn"]),
        Spacer(1, 8),
    ]
    cells: list[list[Any]] = []
    names = {video["id"]: video["original_filename"] for video in payload["videos"]}
    for index, frame in enumerate(payload["frames"]):
        image_path = DATA_DIR / frame["image_path"]
        label = (
            f"#{index + 1} · {escape(frame['id'])}<br/>"
            f"{escape(names.get(frame['video_id'], frame['video_id']))}<br/>"
            f"video {frame['timestamp']}s · relative {frame['relative_time']}s<br/>"
            f"quality {frame['quality_score']}/100 · source {escape(frame['source'])}"
        )
        cell: list[Any] = [Paragraph(label, styles["small"])]
        if image_path.exists():
            from PIL import Image as PILImage

            with PILImage.open(image_path) as pil:
                width, height = pil.size
            scale = min(54 * mm / width, 38 * mm / height)
            cell.insert(0, Image(str(image_path), width=width * scale, height=height * scale))
        if index % 3 == 0:
            cells.append([])
        cells[-1].append(cell)
    table = Table(cells, colWidths=[58 * mm, 58 * mm, 58 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d3df")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Frame images are derived copies. Check the evidence report and JSON manifest for hashes, quality metrics, and audit history.",
            styles["small"],
        )
    )
    doc.build(story)
    return output
