import json
import sqlite3
from typing import Any

import pytest
from pydantic import ValidationError

from app.cv.types import FrameAnalysis
from app.db import get_db
from app.routers import cv as cv_router
from app.schemas import CvRunCreateRequest
from app.services import cv_integration as integration

TRANSACTION_TS = "2026-01-15T09:00:03+00:00"
CCTV_TS = "2026-01-15T09:00:03+00:00"
VIDEO_START_TS = "2026-01-15T09:00:00+00:00"


def _video(duration: float = 12.0, fps: float = 10.0) -> dict[str, Any]:
    return {"id": "video", "sha256": "a" * 64, "duration": duration, "fps": fps}


def _request(**extra: Any) -> CvRunCreateRequest:
    payload: dict[str, Any] = {
        "case_id": "case",
        "video_id": "video",
        "transaction_id": "tx",
        "transaction_ts": TRANSACTION_TS,
        "cctv_ts": CCTV_TS,
        "video_start_ts": VIDEO_START_TS,
        "window_mode": "transaction_aligned",
        "before_seconds": 1,
        "after_seconds": 1,
    }
    payload.update(extra)
    return CvRunCreateRequest(**payload)


def _create_case(client: Any, suffix: str) -> dict[str, Any]:
    return client.post(
        "/api/cases",
        json={"case_number": f"ALIGN-{suffix}", "title": f"Alignment case {suffix}", "location": "Test"},
    ).json()


def _upload_video(client: Any, case_id: str, synthetic_video: Any) -> dict[str, Any]:
    with synthetic_video.open("rb") as handle:
        response = client.post(
            "/api/videos/upload",
            params={"case_id": case_id},
            files={"file": ("synthetic_test.mp4", handle, "video/mp4")},
        )
    assert response.status_code in (200, 201), response.text
    return response.json()


def _create_transaction(client: Any, case_id: str, suffix: str) -> dict[str, Any]:
    return client.post(
        f"/api/cases/{case_id}/transactions",
        json={
            "reference": f"ALIGN-TX-{suffix}",
            "atm_id": f"ATM-{suffix}",
            "transaction_ts": TRANSACTION_TS,
            "cctv_ts": CCTV_TS,
            "transaction_type": "withdrawal",
            "amount": "100",
            "note": "test",
        },
    ).json()


def _aligned_payload(
    case_id: str,
    video_id: str,
    transaction_id: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case_id,
        "video_id": video_id,
        "transaction_id": transaction_id,
        "window_mode": "transaction_aligned",
        "transaction_ts": TRANSACTION_TS,
        "cctv_ts": CCTV_TS,
        "video_start_ts": VIDEO_START_TS,
        "before_seconds": 1,
        "after_seconds": 1,
        "max_frames": 20,
        "frame_stride": 1,
    }
    payload.update(extra)
    return payload


def _patch_window_pipeline(
    monkeypatch: Any,
    calls: list[tuple[int, float, str]],
    captures: list[Any],
    failure: Exception | None = None,
) -> None:
    class FakeCapture:
        def __init__(self, path: Any) -> None:
            self.path = path
            self.index = 0
            self.released = False
            captures.append(self)

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

    class FakePipeline:
        runtime = {"fake": True}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def analyze_frame(self, frame: Any, frame_number: int = 0, timestamp: float = 0.0, **kwargs: Any) -> FrameAnalysis:
            calls.append((int(frame_number), float(timestamp), str(kwargs["source_id"])))
            if failure is not None:
                raise failure
            record = {
                "sample_id": f"aligned-sample-{int(frame_number)}",
                "frame_number": int(frame_number),
                "timestamp": float(timestamp),
                "bbox": [5.0, 6.0, 7.0, 8.0],
                "detector_confidence": 0.88,
                "track_id": None,
                "quality": {"quality_score": 75.0},
                "pose": {"frontal_score": 0.7},
                "flags": {"low_sharpness": False},
            }
            return FrameAnalysis(
                frame_number=int(frame_number),
                timestamp=float(timestamp),
                faces=[record],
                persons=[],
                counts={"faces": 1, "persons": 0},
                total_counts={"faces": 1, "persons": 0},
                truncation={},
                duration_ms=1.0,
            )

        def _apply_analysis_caps(self, frames: list[FrameAnalysis]) -> tuple[list[FrameAnalysis], dict[str, int]]:
            return frames, {
                "face_observations_dropped_by_analysis": 0,
                "person_observations_dropped_by_analysis": 0,
            }

        def analyze_video(self, **kwargs: Any) -> Any:
            raise AssertionError("full-video analyze_video must not be used for aligned runs")

    monkeypatch.setattr(integration.cv2, "VideoCapture", lambda path: FakeCapture(path))
    monkeypatch.setattr(integration, "CVPipeline", FakePipeline)


def test_explicit_positive_clock_offset() -> None:
    window, alignment = integration._plan_window(
        _request(clock_offset_minutes=1),
        _video(duration=120.0),
        None,
    )
    assert alignment["applied_alignment_offset_seconds"] == pytest.approx(60.0)
    assert alignment["alignment_source"] == "manual_clock_offset_minutes"
    assert alignment["transaction_video_seconds"] == pytest.approx(63.0)
    assert window["start_seconds"] == pytest.approx(62.0)
    assert window["end_seconds"] == pytest.approx(64.0)


def test_explicit_negative_clock_offset() -> None:
    window, alignment = integration._plan_window(
        _request(
            clock_offset_minutes=-0.05,
            transaction_ts="2026-01-15T09:00:10+00:00",
            cctv_ts="2026-01-15T09:00:10+00:00",
        ),
        _video(),
        None,
    )
    assert alignment["applied_alignment_offset_seconds"] == pytest.approx(-3.0)
    assert alignment["transaction_video_seconds"] == pytest.approx(7.0)
    assert window["start_seconds"] == pytest.approx(6.0)
    assert window["end_seconds"] == pytest.approx(8.0)


def test_no_explicit_offset_uses_timestamp_difference() -> None:
    window, alignment = integration._plan_window(
        _request(transaction_ts=TRANSACTION_TS, cctv_ts="2026-01-15T09:00:09+00:00"),
        _video(),
        None,
    )
    assert alignment["applied_alignment_offset_seconds"] == pytest.approx(6.0)
    assert alignment["alignment_source"] == "derived_from_transaction_and_cctv_timestamps"
    assert alignment["transaction_video_seconds"] == pytest.approx(9.0)
    assert window["start_seconds"] == pytest.approx(8.0)
    assert window["end_seconds"] == pytest.approx(10.0)


def test_video_start_timestamp_is_used_when_provided() -> None:
    _, alignment = integration._plan_window(
        _request(video_start_ts="2026-01-15T08:59:57+00:00", cctv_reference_video_time=99),
        _video(),
        None,
    )
    assert alignment["video_start_utc"] == "2026-01-15T08:59:57+00:00"
    assert alignment["transaction_video_seconds"] == pytest.approx(6.0)


def test_video_start_is_derived_from_cctv_reference() -> None:
    _, alignment = integration._plan_window(
        _request(cctv_reference_video_time=3),
        _video(),
        None,
    )
    assert alignment["video_start_utc"] == "2026-01-15T09:00:00+00:00"
    assert alignment["transaction_video_seconds"] == pytest.approx(3.0)


def test_window_clamped_at_video_start() -> None:
    window, _ = integration._plan_window(
        _request(transaction_ts="2026-01-15T09:00:00+00:00", cctv_ts="2026-01-15T09:00:00+00:00"),
        _video(duration=6.0),
        None,
    )
    assert window["start_seconds"] == pytest.approx(0.0)
    assert window["end_seconds"] == pytest.approx(1.0)
    assert window["clamped"] is True
    assert any("before the video" in warning for warning in window["warnings"])


def test_window_clamped_at_video_end() -> None:
    window, _ = integration._plan_window(
        _request(
            transaction_ts="2026-01-15T09:00:05.500+00:00",
            cctv_ts="2026-01-15T09:00:05.500+00:00",
        ),
        _video(duration=6.0),
        None,
    )
    assert window["start_seconds"] == pytest.approx(4.5)
    assert window["end_seconds"] == pytest.approx(6.0)
    assert window["clamped"] is True
    assert any("after the video" in warning for warning in window["warnings"])


@pytest.mark.parametrize(
    "extra",
    [
        {"transaction_ts": "2026-01-15T09:00:12+00:00", "cctv_ts": "2026-01-15T09:00:12+00:00"},
        {"video_start_ts": "2026-01-15T09:00:05+00:00"},
    ],
)
def test_window_entirely_outside_video_is_rejected(extra: dict[str, Any]) -> None:
    with pytest.raises(integration.IntegrationError) as exc_info:
        integration._plan_window(_request(**extra), _video(duration=6.0), None)
    assert exc_info.value.status_code == 422


def test_invalid_timestamp_is_rejected() -> None:
    with pytest.raises(integration.IntegrationError) as exc_info:
        integration._plan_window(_request(transaction_ts="not-a-timestamp"), _video(), None)
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize(
    "extra",
    [{"before_seconds": -1}, {"before_seconds": 0, "after_seconds": 0}],
)
def test_negative_or_inverted_window_is_rejected(extra: dict[str, Any]) -> None:
    with pytest.raises((ValidationError, integration.IntegrationError)):
        integration._plan_window(_request(**extra), _video(), None)


def test_aligned_run_analyzes_only_window_and_preserves_source_timeline(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "EXEC")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "EXEC")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures)

    response = client.post(
        "/api/cv/runs",
        json=_aligned_payload(case["id"], video["id"], tx["id"], video_start_ts=VIDEO_START_TS),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    run = body["run"]
    assert run["status"] == "completed"
    assert run["window_mode"] == "transaction_aligned"

    analyzed_frames = [frame for frame, _, _ in calls]
    assert analyzed_frames[0] == 20
    assert analyzed_frames[-1] == 39
    assert all(20 <= frame < 40 for frame in analyzed_frames)
    assert all(timestamp == pytest.approx(frame / 10) for frame, timestamp, _ in calls)
    assert all(source_id == video["id"] for _, _, source_id in calls)

    observation = body["observations"]["items"][0]
    assert observation["original_frame_number"] == 20
    assert observation["original_video_timestamp_seconds"] == pytest.approx(2.0)
    assert observation["analysis_relative_timestamp_seconds"] == pytest.approx(0.0)
    assert observation["bbox"] == [5.0, 6.0, 7.0, 8.0]
    assert observation["crop"]["retrieval_state"] == "not_supported"

    with get_db() as conn:
        row = conn.execute("SELECT window_json, timestamp_provenance_json FROM cv_runs WHERE id=?", (run["cv_run_id"],)).fetchone()
    window = json.loads(row["window_json"])
    provenance = json.loads(row["timestamp_provenance_json"])
    assert window["is_full_video"] is False
    assert window["start_seconds"] == pytest.approx(2.0)
    assert window["end_seconds"] == pytest.approx(4.0)
    assert provenance["transaction_video_seconds"] == pytest.approx(3.0)
    assert provenance["timebase"] == "source_video_seconds"
    assert all(capture.released for capture in captures)


def test_frame_stride_respects_budget(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "STRIDE")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "STRIDE")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures)

    response = client.post(
        "/api/cv/runs",
        json=_aligned_payload(case["id"], video["id"], tx["id"], max_frames=2, frame_stride=3),
    )
    assert response.status_code == 200, response.text
    assert [frame for frame, _, _ in calls] == [20, 23]


def test_aligned_run_keeps_normalized_derivative_provenance_separate(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "DERIV")
    video = _upload_video(client, case["id"], synthetic_video)
    normalized = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "DERIV")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures)

    response = client.post(
        "/api/cv/runs",
        json=_aligned_payload(
            case["id"],
            video["id"],
            tx["id"],
            normalized_video_id=normalized["id"],
            normalized_video_sha256=normalized["sha256"],
        ),
    )
    assert response.status_code == 200, response.text
    provenance = response.json()["run"]["video_provenance"]
    assert provenance["source_video_id"] == video["id"]
    assert provenance["source_video_sha256"] == video["sha256"]
    assert provenance["derivative_kind"] == "normalized"
    assert provenance["normalized_video_id"] == normalized["id"]
    assert provenance["normalized_video_sha256"] == normalized["sha256"]
    assert all(source_id == video["id"] for _, _, source_id in calls)


def test_clamped_window_persists_clamped_flag(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "CLAMP")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "CLAMP")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures)

    response = client.post(
        "/api/cv/runs",
        json=_aligned_payload(
            case["id"],
            video["id"],
            tx["id"],
            transaction_ts="2026-01-15T09:00:00+00:00",
            cctv_ts="2026-01-15T09:00:00+00:00",
        ),
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["status"] == "completed_with_warnings"
    with get_db() as conn:
        row = conn.execute("SELECT clamped FROM cv_runs WHERE id=?", (run["cv_run_id"],)).fetchone()
    assert row["clamped"] == 1


def test_pipeline_failure_marks_aligned_run_failed(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "PIPEFAIL")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "PIPEFAIL")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures, RuntimeError("failure at /secret/path"))

    response = client.post("/api/cv/runs", json=_aligned_payload(case["id"], video["id"], tx["id"]))
    assert response.status_code == 500
    runs = integration.list_runs(case["id"], 50, 0)
    assert runs["total"] == 1
    assert runs["items"][0]["status"] == "failed"
    assert all(capture.released for capture in captures)
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_observations").fetchone()[0]
    assert count == 0


def test_database_failure_leaves_no_partial_aligned_observations(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "DBFAIL")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "DBFAIL")
    calls: list[tuple[int, float, str]] = []
    captures: list[Any] = []
    _patch_window_pipeline(monkeypatch, calls, captures)

    def fail_insert(conn: Any, observations: list[dict[str, Any]]) -> None:
        raise sqlite3.IntegrityError("forced aligned persistence failure")

    monkeypatch.setattr(integration, "_insert_observations", fail_insert)
    response = client.post("/api/cv/runs", json=_aligned_payload(case["id"], video["id"], tx["id"]))
    assert response.status_code == 500
    run = integration.list_runs(case["id"], 50, 0)["items"][0]
    assert run["status"] == "failed"
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM cv_observations WHERE cv_run_id=?", (run["cv_run_id"],)).fetchone()[0]
    assert count == 0


def test_aligned_run_respects_busy_slot(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "BUSY")
    video = _upload_video(client, case["id"], synthetic_video)
    tx = _create_transaction(client, case["id"], "BUSY")

    class BusySlot:
        def acquire(self, blocking: bool = False) -> bool:
            return False

        def release(self) -> None:
            pass

    monkeypatch.setattr(cv_router, "_analysis_slots", BusySlot())
    response = client.post("/api/cv/runs", json=_aligned_payload(case["id"], video["id"], tx["id"]))
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert integration.list_runs(case["id"], 50, 0)["total"] == 0


def test_full_video_dispatch_remains_unchanged(client: Any, synthetic_video: Any, monkeypatch: Any) -> None:
    case = _create_case(client, "FULL")
    video = _upload_video(client, case["id"], synthetic_video)

    class FullPipeline:
        runtime = {}

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def analyze_video(self, **kwargs: Any) -> Any:
            analysis = {
                "source": "synthetic",
                "source_id": kwargs["source_id"],
                "fps": 10.0,
                "frame_count": 60,
                "analyzed_frame_count": 1,
                "analysis_run_id": kwargs["run_id"],
                "frames": [
                    {
                        "frame_number": 0,
                        "timestamp": 0.0,
                        "faces": [
                            {
                                "sample_id": "full-sample",
                                "frame_number": 0,
                                "timestamp": 0.0,
                                "bbox": [1.0, 2.0, 3.0, 4.0],
                                "detector_confidence": 0.9,
                                "quality": {"quality_score": 70.0},
                                "pose": {"frontal_score": 0.7},
                                "flags": {},
                            }
                        ],
                        "counts": {"faces": 1, "persons": 0},
                        "total_counts": {"faces": 1, "persons": 0},
                        "truncation": {},
                    }
                ],
                "summary": {},
                "truncation": {},
                "runtime": {},
            }
            return type("FullAnalysis", (), {"to_dict": lambda self: analysis})()

        def analyze_frame(self, **kwargs: Any) -> Any:
            raise AssertionError("aligned analyze_frame must not be used for full-video runs")

    monkeypatch.setattr(integration, "CVPipeline", FullPipeline)
    response = client.post(
        "/api/cv/runs",
        json={"case_id": case["id"], "video_id": video["id"], "max_frames": 1, "frame_stride": 1},
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    observation = response.json()["observations"]["items"][0]
    assert run["window_mode"] == "full_video"
    assert run["status"] == "completed"
    assert observation["analysis_relative_timestamp_seconds"] is None
