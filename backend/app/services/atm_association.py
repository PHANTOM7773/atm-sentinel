from __future__ import annotations

import math
import sqlite3
from typing import Any

from ..db import audit, get_db, parse_json, utc_now
from ..schemas import (
    CV_ASSOCIATION_EVIDENCE_MEANING,
    CV_ASSOCIATION_LIMITATION,
    CV_ATM_ZONE_COORDINATE_CONVENTION,
    AtmInteractionZone,
)
from .security import new_id

MIN_ZONE_OVERLAP_RATIO = 0.25
MIN_ZONE_FRAMES = 2
MIN_DWELL_SECONDS = 0.1
MAX_TRACK_GAP_SECONDS = 1.0
STRONG_EVIDENCE_THRESHOLD = 0.7
MODERATE_EVIDENCE_THRESHOLD = 0.45
WEAK_EVIDENCE_THRESHOLD = 0.25
CV_MAX_ASSOCIATIONS = 200

SCORE_WEIGHTS = {
    "zone_overlap": 0.3,
    "dwell": 0.25,
    "transaction_timing": 0.25,
    "track_continuity": 0.1,
    "observation_quality": 0.1,
}


class AtmAssociationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def zone_to_pixels(zone: AtmInteractionZone, width: Any, height: Any) -> dict[str, float]:
    frame_width = _finite(width)
    frame_height = _finite(height)
    if frame_width <= 0 or frame_height <= 0:
        raise AtmAssociationError("Video dimensions are unavailable for ATM zone geometry", 422)
    x = float(zone.x) * frame_width
    y = float(zone.y) * frame_height
    w = float(zone.width) * frame_width
    h = float(zone.height) * frame_height
    return {"x": x, "y": y, "width": w, "height": h, "right": x + w, "bottom": y + h}


def build_zone_record(
    zone: AtmInteractionZone | None,
    case_id: str,
    video_id: str,
    source_video_sha256: str,
    width: Any,
    height: Any,
) -> dict[str, Any] | None:
    if zone is None:
        return None
    return {
        "zone_id": new_id(),
        "case_id": case_id,
        "video_id": video_id,
        "source_video_sha256": str(source_video_sha256),
        "name": zone.name,
        "coordinate_convention": CV_ATM_ZONE_COORDINATE_CONVENTION,
        "geometry": zone.model_dump(mode="json"),
        "pixel_geometry": zone_to_pixels(zone, width, height),
        "created_at": utc_now(),
    }


def _bbox_xyxy(bbox: Any) -> tuple[float, float, float, float]:
    values = list(bbox) if isinstance(bbox, (list, tuple)) else []
    padded = [(_finite(value) if index < 4 else 0.0) for index, value in enumerate(values[:4])]
    while len(padded) < 4:
        padded.append(0.0)
    x, y, w, h = padded
    if w < 0:
        x, w = x + w, -w
    if h < 0:
        y, h = y + h, -h
    return x, y, x + w, y + h


def overlap_metrics(bbox: Any, zone_pixels: dict[str, float]) -> tuple[float, float]:
    bx1, by1, bx2, by2 = _bbox_xyxy(bbox)
    zx1 = float(zone_pixels["x"])
    zy1 = float(zone_pixels["y"])
    zx2 = float(zone_pixels["right"])
    zy2 = float(zone_pixels["bottom"])
    ix = max(0.0, min(bx2, zx2) - max(bx1, zx1))
    iy = max(0.0, min(by2, zy2) - max(by1, zy1))
    intersection = ix * iy
    bbox_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    zone_area = max(0.0, zx2 - zx1) * max(0.0, zy2 - zy1)
    bbox_ratio = min(1.0, intersection / bbox_area) if bbox_area > 0 else 0.0
    union = bbox_area + zone_area - intersection
    iou = min(1.0, intersection / union) if union > 0 else 0.0
    return bbox_ratio, iou


def person_observations_from_analysis(
    analysis: dict[str, Any],
    request: Any,
    video: dict[str, Any],
    cv_run_id: str,
    analysis_run_id: str,
    window: dict[str, Any],
    zone_record: dict[str, Any],
) -> list[dict[str, Any]]:
    zone_pixels = zone_record["pixel_geometry"]
    window_start = _finite(window.get("start_seconds"))
    windowed = not bool(window.get("is_full_video", True))
    rows: list[dict[str, Any]] = []
    for frame_index, frame in enumerate(analysis.get("frames", []) or []):
        if not isinstance(frame, dict):
            continue
        frame_number = int(_finite(frame.get("frame_number", frame_index)))
        timestamp = _finite(frame.get("timestamp"))
        for person_index, person in enumerate(frame.get("persons", []) or []):
            if not isinstance(person, dict) or person.get("track_id") is None:
                continue
            try:
                track_id = int(person["track_id"])
            except (TypeError, ValueError):
                continue
            bbox = [_finite(value) for value in list(person.get("bbox") or [])[:4]]
            while len(bbox) < 4:
                bbox.append(0.0)
            ratio, iou = overlap_metrics(bbox, zone_pixels)
            rows.append(
                {
                    "id": new_id(),
                    "cv_run_id": cv_run_id,
                    "case_id": request.case_id,
                    "video_id": request.video_id,
                    "sample_id": f"{analysis_run_id}-person-{frame_number}-{track_id}-{person_index}",
                    "source_video_sha256": str(video["sha256"]),
                    "original_frame_number": frame_number,
                    "original_video_timestamp_seconds": timestamp,
                    "analysis_relative_timestamp_seconds": (
                        round(max(0.0, timestamp - window_start), 4) if windowed else None
                    ),
                    "bbox": bbox,
                    "detector_confidence": _finite(person.get("confidence")),
                    "track_id": track_id,
                    "zone_overlap_ratio": round(ratio, 4),
                    "zone_iou": round(iou, 4),
                    "in_zone": int(ratio >= MIN_ZONE_OVERLAP_RATIO),
                    "created_at": utc_now(),
                }
            )
    return rows


def _merge_intervals(timestamps: list[float], fps: float) -> list[tuple[float, float]]:
    step = 1.0 / fps if fps > 0 else 0.1
    merged: list[tuple[float, float]] = []
    for timestamp in sorted(timestamps):
        start = timestamp
        end = timestamp + step
        if merged and start <= merged[-1][1] + MAX_TRACK_GAP_SECONDS:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _interval_overlap(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))


def _evidence_strength(score: float) -> str:
    if score >= STRONG_EVIDENCE_THRESHOLD:
        return "strong"
    if score >= MODERATE_EVIDENCE_THRESHOLD:
        return "moderate"
    if score >= WEAK_EVIDENCE_THRESHOLD:
        return "weak"
    return "insufficient"


def _eligibility_failures(
    *,
    zone_frame_count: int,
    dwell_seconds: float,
    window_overlap: float,
    temporal_score: float,
    avg_confidence: float,
    discontinuity_count: int,
) -> list[str]:
    failures: list[str] = []
    if zone_frame_count < MIN_ZONE_FRAMES:
        failures.append("insufficient_zone_observation_count")
    if dwell_seconds < MIN_DWELL_SECONDS:
        failures.append("insufficient_dwell_time")
    if window_overlap <= 0:
        failures.append("outside_transaction_window")
    if temporal_score <= 0:
        failures.append("no_transaction_window_timing_evidence")
    if avg_confidence <= 0:
        failures.append("no_observation_quality_evidence")
    if discontinuity_count == 1:
        failures.append("single_excessive_track_gap")
    elif discontinuity_count > 1:
        failures.append("multiple_excessive_track_gaps")
    return failures


def _association_record(
    *,
    case_id: str,
    transaction_id: str,
    cv_run_id: str,
    video_id: str,
    zone_record: dict[str, Any],
    candidate_key: str,
    person_track_id: int | None,
    review_state: str,
    evidence_strength: str,
    heuristic_score: float,
    dwell_seconds: float,
    zone_frame_count: int,
    transaction_window_overlap_seconds: float,
    first_video_timestamp_seconds: float | None,
    last_video_timestamp_seconds: float | None,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    return {
        "association_id": new_id(),
        "case_id": case_id,
        "transaction_id": transaction_id,
        "cv_run_id": cv_run_id,
        "video_id": video_id,
        "candidate_key": candidate_key,
        "source_video_sha256": str(zone_record.get("source_video_sha256") or ""),
        "analysis_run_id": str(evidence.get("provenance", {}).get("analysis_run_id") or ""),
        "zone_id": str(zone_record["zone_id"]),
        "person_track_id": person_track_id,
        "review_state": review_state,
        "evidence_strength": evidence_strength,
        "heuristic_score": round(heuristic_score, 4),
        "dwell_seconds": round(dwell_seconds, 4),
        "zone_frame_count": zone_frame_count,
        "transaction_window_overlap_seconds": round(transaction_window_overlap_seconds, 4),
        "first_video_timestamp_seconds": first_video_timestamp_seconds,
        "last_video_timestamp_seconds": last_video_timestamp_seconds,
        "transaction_video_seconds": evidence.get("temporal", {}).get("transaction_video_seconds"),
        "window_start_seconds": _finite(evidence.get("temporal", {}).get("window_start_seconds")),
        "window_end_seconds": _finite(evidence.get("temporal", {}).get("window_end_seconds")),
        "evidence": evidence,
        "reviewer_note": None,
        "reviewed_at": None,
        "created_at": now,
        "updated_at": now,
        "verification_status": "candidate_only",
        "requires_human_verification": True,
        "association_disclaimer": CV_ASSOCIATION_LIMITATION,
        "score_meaning": CV_ASSOCIATION_EVIDENCE_MEANING,
    }


def build_associations(
    person_rows: list[dict[str, Any]],
    *,
    case_id: str,
    transaction_id: str,
    cv_run_id: str,
    video_id: str,
    zone_record: dict[str, Any],
    window: dict[str, Any],
    timestamp: dict[str, Any],
    model_provenance: list[dict[str, Any]],
    transaction_ts: str | None,
    cctv_ts: str | None,
    fps: float,
) -> list[dict[str, Any]]:
    window_start = _finite(window.get("start_seconds"))
    window_end = _finite(window.get("end_seconds"))
    window_duration = max(0.0, window_end - window_start)
    transaction_seconds = timestamp.get("transaction_video_seconds")
    transaction_seconds = _finite(transaction_seconds) if transaction_seconds is not None else None
    window_interval = (window_start, window_end)
    common_evidence = {
        "zone": {
            "zone_id": zone_record["zone_id"],
            "name": zone_record.get("name"),
            "coordinate_convention": zone_record.get("coordinate_convention"),
            "geometry": zone_record.get("geometry"),
            "pixel_geometry": zone_record.get("pixel_geometry"),
            "overlap_threshold": MIN_ZONE_OVERLAP_RATIO,
        },
        "temporal": {
            "transaction_ts": transaction_ts,
            "cctv_ts": cctv_ts,
            "transaction_video_seconds": transaction_seconds,
            "window_start_seconds": window_start,
            "window_end_seconds": window_end,
            "window_duration_seconds": window_duration,
            "timebase": "source_video_seconds",
        },
        "methodology": {
            "score_meaning": CV_ASSOCIATION_EVIDENCE_MEANING,
            "weights": SCORE_WEIGHTS,
            "thresholds": {
                "min_zone_overlap_ratio": MIN_ZONE_OVERLAP_RATIO,
                "min_zone_frames": MIN_ZONE_FRAMES,
                "min_dwell_seconds": MIN_DWELL_SECONDS,
                "max_track_gap_seconds": MAX_TRACK_GAP_SECONDS,
                "continuity_eligibility": "observation gaps greater than max_track_gap_seconds are insufficient_evidence",
                "strong": STRONG_EVIDENCE_THRESHOLD,
                "moderate": MODERATE_EVIDENCE_THRESHOLD,
                "weak": WEAK_EVIDENCE_THRESHOLD,
            },
        },
        "provenance": {
            "case_id": case_id,
            "transaction_id": transaction_id,
            "cv_run_id": cv_run_id,
            "video_id": video_id,
            "source_video_sha256": zone_record.get("source_video_sha256"),
            "analysis_run_id": timestamp.get("analysis_run_id"),
            "zone_id": zone_record["zone_id"],
            "transaction_video_seconds": transaction_seconds,
            "transaction_ts": transaction_ts,
            "cctv_ts": cctv_ts,
            "model_provenance": model_provenance,
        },
        "limitations": [
            CV_ASSOCIATION_LIMITATION,
            "The heuristic score is not a calibrated probability and does not measure identity likelihood.",
            "Dwell is estimated from sampled frames and may undercount movement between analyzed frames.",
        ],
    }

    track_ids = sorted({int(row["track_id"]) for row in person_rows if row.get("track_id") is not None})
    if not track_ids:
        evidence = {
            **common_evidence,
            "reason": "no_person_track_observed",
            "eligibility": {
                "eligible": False,
                "reasons": ["no_person_track_observed"],
                "zone_observation_count": 0,
                "max_allowed_gap_seconds": MAX_TRACK_GAP_SECONDS,
                "max_observed_gap_seconds": None,
                "discontinuity_gap_count": 0,
                "transaction_window_overlap_seconds": 0.0,
            },
        }
        return [
            _association_record(
                case_id=case_id,
                transaction_id=transaction_id,
                cv_run_id=cv_run_id,
                video_id=video_id,
                zone_record=zone_record,
                candidate_key="no_person_track",
                person_track_id=None,
                review_state="insufficient_evidence",
                evidence_strength="insufficient",
                heuristic_score=0.0,
                dwell_seconds=0.0,
                zone_frame_count=0,
                transaction_window_overlap_seconds=0.0,
                first_video_timestamp_seconds=None,
                last_video_timestamp_seconds=None,
                evidence=evidence,
            )
        ]

    records: list[dict[str, Any]] = []
    for track_id in track_ids:
        track_rows = sorted(
            (row for row in person_rows if row.get("track_id") == track_id),
            key=lambda row: float(row["original_video_timestamp_seconds"]),
        )
        zone_rows = [row for row in track_rows if row.get("in_zone")]
        zone_timestamps = [float(row["original_video_timestamp_seconds"]) for row in zone_rows]
        intervals = _merge_intervals(zone_timestamps, fps)
        dwell_seconds = sum(interval[1] - interval[0] for interval in intervals)
        window_overlap = sum(_interval_overlap(interval, window_interval) for interval in intervals)
        gaps = [right - left for left, right in zip(zone_timestamps, zone_timestamps[1:])]
        discontinuity_count = sum(1 for gap in gaps if gap > MAX_TRACK_GAP_SECONDS)
        avg_overlap = sum(float(row["zone_overlap_ratio"]) for row in zone_rows) / len(zone_rows) if zone_rows else 0.0
        max_overlap = max((float(row["zone_overlap_ratio"]) for row in zone_rows), default=0.0)
        avg_iou = sum(float(row["zone_iou"]) for row in zone_rows) / len(zone_rows) if zone_rows else 0.0
        avg_confidence = sum(float(row["detector_confidence"]) for row in track_rows) / len(track_rows)
        transaction_inside = transaction_seconds is not None and any(
            interval[0] <= transaction_seconds <= interval[1] for interval in intervals
        )
        zone_score = min(avg_overlap / 0.6, 1.0)
        dwell_score = min(dwell_seconds / 1.0, 1.0)
        if transaction_inside:
            temporal_score = 1.0
        elif window_duration > 0:
            temporal_score = min(window_overlap / window_duration, 1.0)
        else:
            temporal_score = 0.0
        continuity_score = 1.0 if len(zone_rows) >= MIN_ZONE_FRAMES and discontinuity_count == 0 else max(
            0.0, 1.0 - discontinuity_count * 0.35
        )
        quality_score = min(avg_confidence / 0.8, 1.0)
        computed_score = (
            SCORE_WEIGHTS["zone_overlap"] * zone_score
            + SCORE_WEIGHTS["dwell"] * dwell_score
            + SCORE_WEIGHTS["transaction_timing"] * temporal_score
            + SCORE_WEIGHTS["track_continuity"] * continuity_score
            + SCORE_WEIGHTS["observation_quality"] * quality_score
        )
        failures = _eligibility_failures(
            zone_frame_count=len(zone_rows),
            dwell_seconds=dwell_seconds,
            window_overlap=window_overlap,
            temporal_score=temporal_score,
            avg_confidence=avg_confidence,
            discontinuity_count=discontinuity_count,
        )
        sufficient = not failures
        heuristic_score = computed_score if sufficient else 0.0
        review_state = "proposed" if sufficient else "insufficient_evidence"
        strength = _evidence_strength(heuristic_score) if sufficient else "insufficient"
        reason = "sufficient_observed_evidence" if sufficient else ";".join(failures)
        evidence = {
            **common_evidence,
            "reason": reason,
            "eligibility": {
                "eligible": sufficient,
                "reasons": failures,
                "zone_observation_count": len(zone_rows),
                "max_allowed_gap_seconds": MAX_TRACK_GAP_SECONDS,
                "max_observed_gap_seconds": round(max(gaps), 4) if gaps else None,
                "discontinuity_gap_count": discontinuity_count,
                "transaction_window_overlap_seconds": round(window_overlap, 4),
            },
            "zone_overlap": {
                "average_bbox_overlap_ratio": round(avg_overlap, 4),
                "maximum_bbox_overlap_ratio": round(max_overlap, 4),
                "average_iou": round(avg_iou, 4),
                "samples": [
                    {
                        "frame_number": row["original_frame_number"],
                        "timestamp_seconds": row["original_video_timestamp_seconds"],
                        "bbox": row["bbox"],
                        "overlap_ratio": row["zone_overlap_ratio"],
                        "iou": row["zone_iou"],
                        "in_zone": bool(row["in_zone"]),
                    }
                    for row in zone_rows
                ],
            },
            "track": {
                "person_track_id": track_id,
                "observed_frame_count": len(track_rows),
                "zone_frame_count": len(zone_rows),
                "first_video_timestamp_seconds": zone_timestamps[0] if zone_timestamps else None,
                "last_video_timestamp_seconds": zone_timestamps[-1] if zone_timestamps else None,
                "max_gap_seconds": round(max(gaps), 4) if gaps else None,
                "discontinuity_gap_count": discontinuity_count,
                "average_detector_confidence": round(avg_confidence, 4),
            },
            "scores": {
                "zone_overlap": round(zone_score, 4),
                "dwell": round(dwell_score, 4),
                "transaction_timing": round(temporal_score, 4),
                "track_continuity": round(continuity_score, 4),
                "observation_quality": round(quality_score, 4),
                "heuristic_score": round(heuristic_score, 4),
                "transaction_time_inside_zone_interval": transaction_inside,
            },
        }
        records.append(
            _association_record(
                case_id=case_id,
                transaction_id=transaction_id,
                cv_run_id=cv_run_id,
                video_id=video_id,
                zone_record=zone_record,
                candidate_key=f"track-{track_id}",
                person_track_id=track_id,
                review_state=review_state,
                evidence_strength=strength,
                heuristic_score=heuristic_score,
                dwell_seconds=dwell_seconds,
                zone_frame_count=len(zone_rows),
                transaction_window_overlap_seconds=window_overlap,
                first_video_timestamp_seconds=zone_timestamps[0] if zone_timestamps else None,
                last_video_timestamp_seconds=zone_timestamps[-1] if zone_timestamps else None,
                evidence=evidence,
            )
        )
    return records


def insert_person_observations(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT INTO cv_person_observations(
                id, cv_run_id, case_id, video_id, sample_id, source_video_sha256,
                original_frame_number, original_video_timestamp_seconds,
                analysis_relative_timestamp_seconds, bbox_json, detector_confidence,
                track_id, zone_overlap_ratio, zone_iou, in_zone, created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"],
                row["cv_run_id"],
                row["case_id"],
                row["video_id"],
                row["sample_id"],
                row["source_video_sha256"],
                row["original_frame_number"],
                row["original_video_timestamp_seconds"],
                row["analysis_relative_timestamp_seconds"],
                _json(row["bbox"]),
                row["detector_confidence"],
                row["track_id"],
                row["zone_overlap_ratio"],
                row["zone_iou"],
                row["in_zone"],
                row["created_at"],
            ),
        )


def insert_associations(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        conn.execute(
            """
            INSERT INTO transaction_person_associations(
                association_id, case_id, transaction_id, cv_run_id, video_id, candidate_key,
                source_video_sha256, analysis_run_id, zone_id, person_track_id, review_state,
                evidence_strength, heuristic_score, dwell_seconds, zone_frame_count,
                transaction_window_overlap_seconds, first_video_timestamp_seconds,
                last_video_timestamp_seconds, transaction_video_seconds, window_start_seconds,
                window_end_seconds, evidence_json, reviewer_note, reviewed_at, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["association_id"],
                row["case_id"],
                row["transaction_id"],
                row["cv_run_id"],
                row["video_id"],
                row["candidate_key"],
                row["source_video_sha256"],
                row["analysis_run_id"],
                row["zone_id"],
                row["person_track_id"],
                row["review_state"],
                row["evidence_strength"],
                row["heuristic_score"],
                row["dwell_seconds"],
                row["zone_frame_count"],
                row["transaction_window_overlap_seconds"],
                row["first_video_timestamp_seconds"],
                row["last_video_timestamp_seconds"],
                row["transaction_video_seconds"],
                row["window_start_seconds"],
                row["window_end_seconds"],
                _json(row["evidence"]),
                row["reviewer_note"],
                row["reviewed_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def association_from_row(row: sqlite3.Row) -> dict[str, Any]:
    evidence = parse_json(row["evidence_json"], {})
    return {
        "association_id": str(row["association_id"]),
        "case_id": str(row["case_id"]),
        "transaction_id": row["transaction_id"],
        "cv_run_id": str(row["cv_run_id"]),
        "video_provenance": {
            "source_video_id": str(row["video_id"]),
            "source_video_sha256": str(row["source_video_sha256"]),
            "derivative_kind": "none",
        },
        "zone_id": str(row["zone_id"]),
        "person_track_id": row["person_track_id"],
        "review_state": str(row["review_state"]),
        "evidence_strength": str(row["evidence_strength"]),
        "heuristic_score": float(row["heuristic_score"]),
        "score_meaning": CV_ASSOCIATION_EVIDENCE_MEANING,
        "dwell_seconds": float(row["dwell_seconds"]),
        "zone_frame_count": int(row["zone_frame_count"]),
        "transaction_window_overlap_seconds": float(row["transaction_window_overlap_seconds"]),
        "first_video_timestamp_seconds": row["first_video_timestamp_seconds"],
        "last_video_timestamp_seconds": row["last_video_timestamp_seconds"],
        "transaction_video_seconds": row["transaction_video_seconds"],
        "window_start_seconds": float(row["window_start_seconds"]),
        "window_end_seconds": float(row["window_end_seconds"]),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "reviewer_note": row["reviewer_note"],
        "reviewed_at": row["reviewed_at"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "verification_status": "candidate_only",
        "requires_human_verification": True,
        "association_disclaimer": CV_ASSOCIATION_LIMITATION,
    }


def get_associations(
    cv_run_id: str,
    case_id: str | None = None,
    transaction_id: str | None = None,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    with get_db() as conn:
        run = conn.execute("SELECT * FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
        if not run or (case_id and str(run["case_id"]) != case_id):
            raise AtmAssociationError("CV run not found", 404)
        run_case_id = str(run["case_id"])
        clauses = ["cv_run_id=?"]
        values: list[Any] = [cv_run_id]
        if transaction_id:
            clauses.append("transaction_id=?")
            values.append(transaction_id)
        where = " AND ".join(clauses)
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM transaction_person_associations WHERE {where}", values).fetchone()[0]
        )
        bounded_limit = max(1, min(int(limit), CV_MAX_ASSOCIATIONS))
        bounded_offset = max(0, int(offset))
        rows = conn.execute(
            f"""
            SELECT * FROM transaction_person_associations
            WHERE {where}
            ORDER BY heuristic_score DESC, person_track_id ASC, association_id ASC
            LIMIT ? OFFSET ?
            """,
            [*values, bounded_limit, bounded_offset],
        ).fetchall()
    items = [association_from_row(row) for row in rows]
    from .best_face import build_summaries

    summaries = build_summaries(run_case_id, cv_run_id, items)
    for item in items:
        item["best_face"] = summaries.get(str(item["association_id"]))
    status = "proposed" if any(
        item["review_state"] in {"proposed", "confirmed"} for item in items
    ) else "insufficient_evidence"
    return {
        "items": items,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
        "status": status,
        "disclaimer": CV_ASSOCIATION_LIMITATION,
    }


def review_association(
    case_id: str,
    cv_run_id: str,
    association_id: str,
    decision: str,
    reviewer_note: str | None,
) -> dict[str, Any]:
    if decision not in {"confirmed", "rejected"}:
        raise AtmAssociationError("Review decision must be confirmed or rejected", 422)
    with get_db() as conn:
        run = conn.execute("SELECT id, case_id FROM cv_runs WHERE id=?", (cv_run_id,)).fetchone()
        if not run or str(run["case_id"]) != case_id:
            raise AtmAssociationError("CV run not found", 404)
        row = conn.execute(
            """
            SELECT * FROM transaction_person_associations
            WHERE association_id=? AND cv_run_id=? AND case_id=?
            """,
            (association_id, cv_run_id, case_id),
        ).fetchone()
        if not row:
            raise AtmAssociationError("Transaction-person association not found", 404)
        if row["review_state"] not in {"proposed", "confirmed", "rejected"}:
            raise AtmAssociationError("Insufficient evidence records cannot be reviewed", 409)
        now = utc_now()
        note = (reviewer_note or "").strip()[:4000] or None
        conn.execute(
            """
            UPDATE transaction_person_associations
            SET review_state=?, reviewer_note=?, reviewed_at=?, updated_at=?
            WHERE association_id=?
            """,
            (decision, note, now, now, association_id),
        )
        audit(
            conn,
            case_id,
            "transaction_person_association_reviewed",
            {
                "association_id": association_id,
                "cv_run_id": cv_run_id,
                "transaction_id": row["transaction_id"],
                "review_state": decision,
            },
            created_at=now,
        )
        updated = conn.execute(
            "SELECT * FROM transaction_person_associations WHERE association_id=?",
            (association_id,),
        ).fetchone()
    return association_from_row(updated)
