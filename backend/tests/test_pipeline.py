import json
import time
from pathlib import Path

import pytest

from app.config import DATA_DIR, absolute_from_data


def test_case_transaction_note_and_archive(client):
    case = client.post("/api/cases", json={"case_number": "DB-001", "title": "Database test", "location": "Lab"}).json()
    assert case["status"] == "active"

    duplicate = client.post("/api/cases", json={"case_number": "DB-001", "title": "Duplicate"})
    assert duplicate.status_code == 409

    updated = client.patch(f"/api/cases/{case['id']}", json={"title": "Updated", "location": "Lab 2"}).json()
    assert updated["title"] == "Updated"

    tx = client.post(
        f"/api/cases/{case['id']}/transactions",
        json={"reference": "DB-TX-1", "transaction_ts": "2026-01-15T09:00:00+05:30"},
    )
    assert tx.status_code == 201
    assert client.get(f"/api/cases/{case['id']}/transactions").json()[0]["atm_id"] == ""

    note = client.post(f"/api/cases/{case['id']}/notes", json={"body": "A note"}).json()
    assert note["body"] == "A note"

    archived = client.post(f"/api/cases/{case['id']}/archive?archived=true").json()
    assert archived["status"] == "archived"
    assert all(item["id"] != case["id"] for item in client.get("/api/cases").json())
    assert any(item["id"] == case["id"] for item in client.get("/api/cases?include_archived=true").json())


def test_invalid_transaction_timestamp_rejected(client):
    case = client.post("/api/cases", json={"case_number": "DB-002", "title": "Timestamp test"}).json()
    response = client.post(f"/api/cases/{case['id']}/transactions", json={"reference": "BAD", "transaction_ts": "yesterday"})
    assert response.status_code == 422


def test_tags_and_search(client, synthetic_video):
    case = client.post(
        "/api/cases",
        json={"case_number": "TAG-001", "title": "Tag search test", "tags": "atm-01, demo, ATM-01"},
    ).json()
    assert case["tags"] == "atm-01,demo"

    with synthetic_video.open("rb") as handle:
        video = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": ("tagged_test.mp4", handle, "video/mp4")},
        ).json()
    patched = client.patch(f"/api/videos/{video['id']}", json={"tags": "camera-a, demo"}).json()
    assert patched["tags"] == "camera-a,demo"

    results = client.get("/api/search?q=camera-a").json()
    assert any(item["id"] == case["id"] for item in results["cases"])
    assert any(item["id"] == video["id"] for item in results["videos"])
    by_case_tag = client.get("/api/search?q=atm-01").json()
    assert any(item["id"] == case["id"] for item in by_case_tag["cases"])


def test_invalid_video_uploads(client, tmp_path):
    case = client.post("/api/cases", json={"case_number": "DB-003", "title": "Upload test"}).json()

    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with empty.open("rb") as handle:
        response = client.post(f"/api/videos/upload?case_id={case['id']}", files={"file": ("empty.mp4", handle, "video/mp4")})
    assert response.status_code == 422
    assert "Empty upload" in response.json()["detail"]

    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not really a video file")
    with fake.open("rb") as handle:
        response = client.post(f"/api/videos/upload?case_id={case['id']}", files={"file": ("fake.mp4", handle, "video/mp4")})
    assert response.status_code == 422
    assert "content does not match" in response.json()["detail"]


def test_alignment_preview_api(client):
    response = client.post(
        "/api/alignment/preview",
        json={
            "transaction_ts": "2026-01-15T09:00:05+00:00",
            "cctv_ts": "2026-01-15T09:00:35+00:00",
            "video_duration": 10,
            "video_start_ts": "2026-01-15T09:00:30+00:00",
            "before_seconds": 2,
            "after_seconds": 2,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["offset_seconds"] == 30
    assert body["transaction_video_seconds"] == 5
    assert body["window_start_seconds"] == 3
    assert body["window_end_seconds"] == 7


def test_full_pipeline_upload_extract_select_export(client, case_and_transaction, synthetic_video):
    case, tx = case_and_transaction
    with synthetic_video.open("rb") as handle:
        upload = client.post(f"/api/videos/upload?case_id={case['id']}", files={"file": ("synthetic_test.mp4", handle, "video/mp4")})
    assert upload.status_code == 201
    video = upload.json()
    assert video["fps"] == 10
    assert len(video["sha256"]) == 64
    assert absolute_from_data(video["stored_path"]).exists()

    verified = client.post(f"/api/videos/{video['id']}/verify").json()
    assert verified["status"] == "verified"

    job = client.post(
        "/api/jobs",
        json={
            "video_id": video["id"],
            "transaction_id": tx["id"],
            "config": {
                "video_start_ts": "2026-01-15T09:00:30+00:00",
                "window_before_seconds": 2,
                "window_after_seconds": 2,
                "coarse_interval_seconds": 1,
                "fine_interval_seconds": 0.5,
                "fine_radius_seconds": 1,
            },
        },
    ).json()
    assert job["status"] == "queued"

    for _ in range(80):
        current = client.get(f"/api/jobs/{job['id']}").json()
        if current["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert current["status"] == "completed", current["message"]
    assert current["alignment"]["transaction_video_seconds"] == 5

    frames = client.get(f"/api/frames?case_id={case['id']}").json()
    assert len(frames) >= 3
    assert all(0 <= frame["quality_score"] <= 100 for frame in frames)
    assert all(len(frame["sha256"]) == 64 for frame in frames)
    assert {frame["source"] for frame in frames} >= {"coarse", "fine"}

    selected = client.patch(f"/api/frames/{frames[0]['id']}", json={"selected": True, "note": "Demo selection", "reason": "Clear frame"}).json()
    assert selected["selected"] is True
    assert selected["selection_note"] == "Demo selection"

    export = client.post("/api/exports", json={"case_id": case["id"], "frame_ids": [frames[0]["id"]]})
    assert export.status_code == 201
    result = export.json()
    pdf = absolute_from_data(result["pdf_path"])
    manifest = absolute_from_data(result["manifest_path"])
    assert pdf.exists() and pdf.read_bytes()[:4] == b"%PDF"
    payload = json.loads(manifest.read_text())
    assert payload["pdf_sha256"] == result["pdf_sha256"]
    assert payload["report_hash"] == result["report_hash"]
    assert payload["frames"][0]["sha256"] == frames[0]["sha256"]

    assert client.get(f"/api/exports/{result['id']}/pdf").status_code == 200
    archive = client.get(
        f"/api/exports/frames/archive?case_id={case['id']}&frame_ids={frames[0]['id']}"
    )
    assert archive.status_code == 200
    assert archive.content[:2] == b"PK"
    sheet = client.get(
        f"/api/exports/contact_sheet?case_id={case['id']}&frame_ids={frames[0]['id']}"
    )
    assert sheet.status_code == 200
    assert sheet.content[:4] == b"%PDF"
    audit = client.get("/api/system/status").json()["recent_activity"]
    assert any(event["action"] == "report_exported" for event in audit)


def test_manual_capture(client, case_and_transaction, synthetic_video):
    case, _ = case_and_transaction
    with synthetic_video.open("rb") as handle:
        video = client.post(f"/api/videos/upload?case_id={case['id']}", files={"file": ("synthetic_test.mp4", handle, "video/mp4")}).json()
    response = client.post("/api/frames/manual", json={"case_id": case["id"], "video_id": video["id"], "timestamp": 2.0, "note": "Manual note"})
    assert response.status_code == 201
    frame = response.json()
    assert frame["source"] == "manual"
    assert frame["timestamp"] == 2.0
    assert frame["frame_notes"][0]["body"] == "Manual note"


@pytest.mark.parametrize("extension", ["avi", "mov", "mkv"])
def test_supported_container_upload_verify_extract_and_normalize(
    client,
    case_and_transaction,
    ffmpeg_synthetic_video_factory,
    extension,
):
    case, _ = case_and_transaction
    source = ffmpeg_synthetic_video_factory(extension)
    with source.open("rb") as handle:
        upload = client.post(
            f"/api/videos/upload?case_id={case['id']}",
            files={"file": (f"format_test.{extension}", handle, f"video/{extension}")},
        )
    assert upload.status_code == 201, upload.text
    video = upload.json()
    assert video["width"] == 160
    assert video["height"] == 120
    assert video["fps"] == pytest.approx(10, abs=0.01)
    assert len(video["sha256"]) == 64

    verified = client.post(f"/api/videos/{video['id']}/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"

    frame = client.post(
        "/api/frames/manual",
        json={"case_id": case["id"], "video_id": video["id"], "timestamp": 0.5, "note": "Format smoke test"},
    )
    assert frame.status_code == 201, frame.text
    assert len(frame.json()["sha256"]) == 64

    normalized = client.post(
        f"/api/videos/{video['id']}/normalize",
        params={"case_id": case["id"]},
    )
    assert normalized.status_code == 201, normalized.text
    assert normalized.json()["original_filename"].endswith("_normalized.mp4")
    assert normalized.json()["integrity_status"] == "verified"


def test_sample_targets_include_coarse_and_fine():
    from app.services.extraction import _sample_targets

    targets = _sample_targets(
        {"window_start_seconds": 0, "window_end_seconds": 10, "transaction_video_seconds": 5},
        coarse=1,
        fine=0.25,
        fine_radius=2,
        max_frames=100,
    )
    sources = {target["source"] for target in targets}
    assert sources == {"coarse", "fine"}
    assert len(targets) < 100
