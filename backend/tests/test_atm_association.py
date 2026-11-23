import sqlite3
from typing import Any

import pytest
from pydantic import ValidationError

from app.config import SCHEMA_VERSION
from app.db import get_db
from app.schemas import (
    CV_ASSOCIATION_EVIDENCE_MEANING,
    CV_ASSOCIATION_LIMITATION,
    CV_ATM_ZONE_COORDINATE_CONVENTION,
    AtmInteractionZone,
    CvRunCreateRequest,
    TransactionPersonAssociationRecord,
)
from app.services import cv_integration as integration
from app.services.atm_association import (
    MAX_TRACK_GAP_SECONDS,
    build_associations,
    build_zone_record,
    zone_to_pixels,
)

TRANSACTION_TS = "2026-01-15T09:00:03+00:00"
CCTV_TS = "2026-01-15T09:00:03+00:00"
VIDEO_START_TS = "2026-01-15T09:00:00+00:00"
ZONE = {"name": "atm_keypad", "x": 0.5, "y": 0.5, "width": 0.25, "height": 0.25}


def _direct_zone() -> dict[str, Any]:
    zone = build_zone_record(AtmInteractionZone(**ZONE), "case", "video", "a" * 64, 640, 480)
    assert zone is not None
    return zone


def _observation(
    track_id: int,
    timestamp: float,
    *,
    confidence: float = 0.8,
    overlap: float = 1.0,
    iou: float = 0.5,
    in_zone: bool = True,
) -> dict[str, Any]:
    return {
        "track_id": track_id,
        "original_frame_number": int(round(timestamp * 10)),
        "original_video_timestamp_seconds": timestamp,
        "bbox": [160.0, 240.0, 80.0, 60.0],
        "detector_confidence": confidence,
        "zone_overlap_ratio": overlap,
        "zone_iou": iou,
        "in_zone": int(in_zone),
    }


def _direct_associations(
    rows: list[dict[str, Any]],
    *,
    window_start: float = 0.0,
    window_end: float = 3.0,
    transaction_seconds: float = 1.5,
) -> list[dict[str, Any]]:
    return build_associations(
        rows,
        case_id="case",
        transaction_id="tx",
        cv_run_id="direct-run",
        video_id="video",
        zone_record=_direct_zone(),
        window={"start_seconds": window_start, "end_seconds": window_end},
        timestamp={"analysis_run_id": "direct-analysis", "transaction_video_seconds": transaction_seconds},
        model_provenance=[],
        transaction_ts=TRANSACTION_TS,
        cctv_ts=CCTV_TS,
        fps=10.0,
    )


def _zone_request(**extra: Any) -> CvRunCreateRequest:
    payload: dict[str, Any] = {
        "case_id": "case",
        "video_id": "video",
        "window_mode": "transaction_aligned",
        "transaction_id": "tx",
        "transaction_ts": TRANSACTION_TS,
        "cctv_ts": CCTV_TS,
        "video_start_ts": VIDEO_START_TS,
        "before_seconds": 1,
        "after_seconds": 1,
        "atm_zone": ZONE,
    }
    payload.update(extra)
    return CvRunCreateRequest(**payload)


def test_atm_zone_schema_enforces_normalized_geometry() -> None:
    zone = AtmInteractionZone(**ZONE)
    assert zone.model_dump() == ZONE
    with pytest.raises(ValidationError):
        AtmInteractionZone(**{**ZONE, "x": 0.9})
    with pytest.raises(ValidationError):
        AtmInteractionZone(**{**ZONE, "width": 0})
    with pytest.raises(ValidationError):
        AtmInteractionZone(**{**ZONE, "y": float("nan")})


def test_atm_zone_requires_transaction_aligned_request() -> None:
    with pytest.raises(ValidationError):
        CvRunCreateRequest(
            case_id="case",
            video_id="video",
            window_mode="full_video",
            atm_zone=ZONE,
        )
    assert _zone_request().atm_zone is not None


def test_zone_record_preserves_normalized_and_pixel_geometry() -> None:
    zone = AtmInteractionZone(**ZONE)
    record = build_zone_record(zone, "case", "video", "a" * 64, 320, 240)
    assert record is not None
    assert record["geometry"] == ZONE
    assert record["pixel_geometry"] == {
        "x": 160.0,
        "y": 120.0,
        "width": 80.0,
        "height": 60.0,
        "right": 240.0,
        "bottom": 180.0,
    }
    assert record["coordinate_convention"] == CV_ATM_ZONE_COORDINATE_CONVENTION
    with pytest.raises(Exception):
        zone_to_pixels(zone, 0, 240)


def test_association_builder_can_report_no_person_track() -> None:
    zone = build_zone_record(AtmInteractionZone(**ZONE), "case", "video", "a" * 64, 320, 240)
    assert zone is not None
    records = build_associations(
        [],
        case_id="case",
        transaction_id="tx",
        cv_run_id="run",
        video_id="video",
        zone_record=zone,
        window={"start_seconds": 2.0, "end_seconds": 4.0},
        timestamp={"analysis_run_id": "analysis", "transaction_video_seconds": 3.0},
        model_provenance=[],
        transaction_ts=TRANSACTION_TS,
        cctv_ts=CCTV_TS,
        fps=10.0,
    )
    assert len(records) == 1
    assert records[0]["review_state"] == "insufficient_evidence"
    assert records[0]["evidence_strength"] == "insufficient"
    assert records[0]["evidence"]["reason"] == "no_person_track_observed"


class _FakeCapture:
    def __init__(self, path: Any) -> None:
        self.path = path
        self.index = 0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def set(self, property_id: int, value: int) -> bool:
        self.index = int(value)
        return True

    def get(self, property_id: int) -> float:
        return float(self.index)

    def read(self) -> tuple[bool, Any]:
        if self.index >= 60:
            return False, None
        self.index += 1
        return True, object()

    def release(self) -> None:
        self.released = True


def _install_fake_pipeline(monkeypatch: Any, with_person: bool = True) -> None:
    class FakePipeline:
        runtime = {"fake": True}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.analysis_run_id = ""

        def begin_analysis(self, analysis_run_id: str) -> None:
            self.analysis_run_id = analysis_run_id

        def analyze_frame(self, frame: Any, frame_number: int = 0, timestamp: float = 0.0, **kwargs: Any) -> Any:
            from app.cv.types import FrameAnalysis

            faces: list[dict[str, Any]] = []
            persons: list[dict[str, Any]] = []
            if with_person:
                persons.append({
                    "bbox": [170.0, 130.0, 50.0, 40.0],
                    "confidence": 0.93,
                    "class_id": 0,
                    "track_id": 7,
                })
            return FrameAnalysis(
                frame_number=int(frame_number),
                timestamp=float(timestamp),
                faces=faces,
                persons=persons,
                counts={"faces": len(faces), "persons": len(persons)},
                total_counts={"faces": len(faces), "persons": len(persons)},
                person_track_ids=[7] if with_person else [],
                duration_ms=1.0,
            )

        def _apply_analysis_caps(self, frames: list[Any]) -> tuple[list[Any], dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

        def finalize_staged_embeddings(self, frames: list[Any]) -> list[Any]:
            return []

    monkeypatch.setattr(integration.cv2, "VideoCapture", lambda path: _FakeCapture(path))
    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)


def _setup_run(client: Any, synthetic_video: Any, monkeypatch: Any, suffix: str, with_person: bool = True) -> dict[str, Any]:
    _install_fake_pipeline(monkeypatch, with_person)
    case = client.post(
        "/api/cases",
        json={"case_number": f"ATM-ASSOC-{suffix}", "title": f"Association case {suffix}", "location": "Test"},
    ).json()
    transaction = client.post(
        f"/api/cases/{case['id']}/transactions",
        json={
            "reference": f"ATM-ASSOC-TX-{suffix}",
            "atm_id": "ATM-TEST",
            "transaction_ts": TRANSACTION_TS,
            "cctv_ts": CCTV_TS,
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "synthetic",
        },
    ).json()
    with synthetic_video.open("rb") as handle:
        video = client.post(
            "/api/videos/upload",
            params={"case_id": case["id"]},
            files={"file": (f"association_{suffix}.mp4", handle, "video/mp4")},
        ).json()
    response = client.post(
        "/api/cv/runs",
        json={
            "case_id": case["id"],
            "video_id": video["id"],
            "transaction_id": transaction["id"],
            "transaction_ts": TRANSACTION_TS,
            "cctv_ts": CCTV_TS,
            "video_start_ts": VIDEO_START_TS,
            "window_mode": "transaction_aligned",
            "before_seconds": 1,
            "after_seconds": 1,
            "atm_zone": ZONE,
            "max_frames": 21,
            "frame_stride": 1,
            "save_crops": False,
            "add_to_index": False,
        },
    )
    assert response.status_code == 200, response.text
    return {
        "case": case,
        "transaction": transaction,
        "video": video,
        "body": response.json(),
        "with_person": with_person,
    }


def test_zone_and_association_are_persisted_without_identity_fields(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
) -> None:
    assert SCHEMA_VERSION == 5
    ctx = _setup_run(client, synthetic_video, monkeypatch, "PERSIST")
    body = ctx["body"]
    assert body["run"]["atm_zone"] == ZONE
    assert body["associations"]["total"] == 1
    association = body["associations"]["items"][0]
    assert TransactionPersonAssociationRecord.model_validate(association).transaction_id == ctx["transaction"]["id"]
    assert association["review_state"] == "proposed"
    assert association["evidence_strength"] in {"moderate", "strong"}
    assert association["transaction_video_seconds"] == pytest.approx(3.0)
    assert association["evidence"]["zone"]["geometry"] == ZONE
    assert association["evidence"]["zone"]["overlap_threshold"] == 0.25
    assert association["score_meaning"] == CV_ASSOCIATION_EVIDENCE_MEANING
    assert association["association_disclaimer"] == CV_ASSOCIATION_LIMITATION
    assert association["requires_human_verification"] is True
    assert association["video_provenance"]["source_video_sha256"] == ctx["video"]["sha256"]
    forbidden = {"embedding", "embedding_vector", "face_embedding", "identity", "identity_vector"}
    assert not forbidden.intersection(association.keys())

    with get_db() as conn:
        person_count = conn.execute("SELECT COUNT(*) FROM cv_person_observations WHERE cv_run_id=?", (body["run"]["cv_run_id"],)).fetchone()[0]
        association_count = conn.execute(
            "SELECT COUNT(*) FROM transaction_person_associations WHERE cv_run_id=?",
            (body["run"]["cv_run_id"],),
        ).fetchone()[0]
        tables = ("cv_runs", "cv_person_observations", "transaction_person_associations")
        for table in tables:
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert not columns & forbidden
    assert person_count == 21
    assert association_count == 1


def test_association_list_and_manual_review_are_case_scoped(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
) -> None:
    ctx = _setup_run(client, synthetic_video, monkeypatch, "REVIEW")
    case_id = ctx["case"]["id"]
    run_id = ctx["body"]["run"]["cv_run_id"]
    association = ctx["body"]["associations"]["items"][0]
    listed = client.get(
        f"/api/cv/runs/{run_id}/person-associations",
        params={"case_id": case_id, "transaction_id": ctx["transaction"]["id"]},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["association_id"] == association["association_id"]

    wrong_case = client.get(
        f"/api/cv/runs/{run_id}/person-associations",
        params={"case_id": "other-case"},
    )
    assert wrong_case.status_code == 404

    reviewed = client.post(
        f"/api/cv/person-associations/{association['association_id']}/review",
        params={"case_id": case_id},
        json={
            "case_id": case_id,
            "cv_run_id": run_id,
            "decision": "confirmed",
            "reviewer_note": "Zone dwell and timing reviewed",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_state"] == "confirmed"
    assert reviewed.json()["reviewer_note"] == "Zone dwell and timing reviewed"
    assert reviewed.json()["reviewed_at"]

    with get_db() as conn:
        audit_count = conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE case_id=? AND action=?",
            (case_id, "transaction_person_association_reviewed"),
        ).fetchone()[0]
    assert audit_count == 1

    wrong_case_review = client.post(
        f"/api/cv/person-associations/{association['association_id']}/review",
        params={"case_id": "other-case"},
        json={"case_id": "other-case", "cv_run_id": run_id, "decision": "rejected"},
    )
    assert wrong_case_review.status_code == 404


def test_no_person_observation_produces_only_insufficient_evidence(
    client: Any,
    synthetic_video: Any,
    monkeypatch: Any,
) -> None:
    ctx = _setup_run(client, synthetic_video, monkeypatch, "NOPERSON", with_person=False)
    association = ctx["body"]["associations"]["items"][0]
    assert association["review_state"] == "insufficient_evidence"
    assert association["evidence_strength"] == "insufficient"
    assert association["evidence"]["reason"] == "no_person_track_observed"

    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_person_observations WHERE cv_run_id=?", (ctx["body"]["run"]["cv_run_id"],)).fetchone()[0]
    assert count == 0

    review = client.post(
        f"/api/cv/person-associations/{association['association_id']}/review",
        params={"case_id": ctx["case"]["id"]},
        json={
            "case_id": ctx["case"]["id"],
            "cv_run_id": ctx["body"]["run"]["cv_run_id"],
            "decision": "confirmed",
        },
    )
    assert review.status_code == 409


def test_continuous_track_remains_proposed_with_explanatory_eligibility() -> None:
    records = _direct_associations(
        [_observation(1, 0.0), _observation(1, 0.1), _observation(1, 0.2)],
        window_end=1.0,
        transaction_seconds=0.1,
    )
    assert len(records) == 1
    record = records[0]
    assert record["review_state"] == "proposed"
    assert record["evidence_strength"] == "strong"
    assert record["heuristic_score"] > 0
    assert record["evidence"]["reason"] == "sufficient_observed_evidence"
    assert record["evidence"]["eligibility"]["eligible"] is True
    assert record["evidence"]["eligibility"]["reasons"] == []
    assert record["evidence"]["eligibility"]["zone_observation_count"] == 3
    assert record["evidence"]["eligibility"]["discontinuity_gap_count"] == 0
    assert record["evidence"]["eligibility"]["max_observed_gap_seconds"] == pytest.approx(0.1)


def test_single_zone_observation_is_insufficient_with_zero_rankable_score() -> None:
    records = _direct_associations(
        [_observation(2, 0.5)],
        window_end=1.0,
        transaction_seconds=0.5,
    )
    assert len(records) == 1
    record = records[0]
    assert record["review_state"] == "insufficient_evidence"
    assert record["evidence_strength"] == "insufficient"
    assert record["heuristic_score"] == 0
    assert "insufficient_zone_observation_count" in record["evidence"]["eligibility"]["reasons"]
    assert record["evidence"]["eligibility"]["zone_observation_count"] == 1


def test_excessive_observation_gap_is_insufficient() -> None:
    records = _direct_associations([_observation(3, 0.0), _observation(3, 2.0)])
    assert len(records) == 1
    record = records[0]
    assert record["review_state"] == "insufficient_evidence"
    assert record["evidence_strength"] == "insufficient"
    assert record["heuristic_score"] == 0
    assert record["evidence"]["eligibility"]["reasons"] == ["single_excessive_track_gap"]
    assert record["evidence"]["eligibility"]["max_observed_gap_seconds"] == pytest.approx(2.0)
    assert record["evidence"]["eligibility"]["discontinuity_gap_count"] == 1


def test_multiple_discontinuities_are_insufficient() -> None:
    records = _direct_associations(
        [_observation(4, value) for value in (0.0, 1.5, 3.0, 4.5)],
        window_end=5.0,
        transaction_seconds=2.5,
    )
    assert len(records) == 1
    record = records[0]
    assert record["review_state"] == "insufficient_evidence"
    assert record["evidence_strength"] == "insufficient"
    assert record["heuristic_score"] == 0
    assert record["evidence"]["eligibility"]["reasons"] == ["multiple_excessive_track_gaps"]
    assert record["evidence"]["eligibility"]["discontinuity_gap_count"] == 3


def test_observations_outside_transaction_window_are_insufficient() -> None:
    records = _direct_associations(
        [_observation(5, 0.0), _observation(5, 0.1)],
        window_start=5.0,
        window_end=6.0,
        transaction_seconds=5.5,
    )
    assert len(records) == 1
    record = records[0]
    assert record["review_state"] == "insufficient_evidence"
    assert record["heuristic_score"] == 0
    assert "outside_transaction_window" in record["evidence"]["eligibility"]["reasons"]
    assert "no_transaction_window_timing_evidence" in record["evidence"]["eligibility"]["reasons"]
    assert record["transaction_window_overlap_seconds"] == 0


def test_continuity_boundary_uses_existing_gap_limit() -> None:
    at_limit = _direct_associations(
        [_observation(6, 0.0), _observation(6, MAX_TRACK_GAP_SECONDS)],
        window_end=2.0,
        transaction_seconds=0.5,
    )
    assert len(at_limit) == 1
    assert at_limit[0]["review_state"] == "proposed"
    assert at_limit[0]["evidence"]["eligibility"]["discontinuity_gap_count"] == 0
    assert at_limit[0]["evidence"]["eligibility"]["max_observed_gap_seconds"] == pytest.approx(MAX_TRACK_GAP_SECONDS)

    over_limit = _direct_associations(
        [_observation(7, 0.0), _observation(7, MAX_TRACK_GAP_SECONDS + 0.01)],
        window_end=2.0,
        transaction_seconds=0.5,
    )
    assert len(over_limit) == 1
    assert over_limit[0]["review_state"] == "insufficient_evidence"
    assert over_limit[0]["heuristic_score"] == 0
    assert over_limit[0]["evidence"]["eligibility"]["reasons"] == ["single_excessive_track_gap"]


def test_discontinuous_candidate_does_not_outrank_continuous_candidate() -> None:
    records = _direct_associations(
        [
            _observation(12, 0.0),
            _observation(12, 2.0),
            _observation(11, 0.0, confidence=0.1, overlap=0.3),
            _observation(11, 0.1, confidence=0.1, overlap=0.3),
        ]
    )
    by_track = {record["person_track_id"]: record for record in records}
    assert by_track[11]["review_state"] == "proposed"
    assert by_track[12]["review_state"] == "insufficient_evidence"
    assert by_track[12]["heuristic_score"] == 0
    assert by_track[11]["heuristic_score"] > by_track[12]["heuristic_score"]
    assert sorted(records, key=lambda item: item["heuristic_score"], reverse=True)[0]["person_track_id"] == 11


def test_association_tables_and_run_migration_are_additive(client: Any) -> None:
    with get_db() as conn:
        run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cv_runs)")}
        assert "atm_zone_json" in run_columns
        assert "request_json" in run_columns
        assert "window_json" in run_columns
        association_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(transaction_person_associations)")
        }
        assert {
            "association_id",
            "case_id",
            "transaction_id",
            "cv_run_id",
            "evidence_json",
            "review_state",
            "evidence_strength",
            "heuristic_score",
        }.issubset(association_columns)
        assert isinstance(conn, sqlite3.Connection)
