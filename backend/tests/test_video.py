import pytest

from app.services.video import VideoError, check_integrity, dependencies, probe_video, require_ffprobe


def test_dependencies_available():
    result = dependencies()
    assert result["opencv"] is True
    assert result["ffmpeg"] is True
    assert result["ffprobe"] is True


def test_probe_synthetic_video(synthetic_video):
    metadata = probe_video(synthetic_video)
    assert metadata["codec"]
    assert metadata["fps"] == pytest.approx(10, abs=0.01)
    assert metadata["duration"] == pytest.approx(6, abs=0.2)
    assert metadata["width"] == 320
    assert metadata["height"] == 240
    assert metadata["stream_count"] >= 1


def test_integrity_check(synthetic_video):
    status, detail = check_integrity(synthetic_video)
    assert status == "verified"
    assert detail


def test_missing_ffprobe(monkeypatch, synthetic_video):
    monkeypatch.setattr("app.services.video.FFPROBE", None)
    with pytest.raises(VideoError, match="ffprobe is not installed"):
        probe_video(synthetic_video)
    with pytest.raises(VideoError):
        require_ffprobe()


def test_missing_ffmpeg(monkeypatch, synthetic_video):
    monkeypatch.setattr("app.services.video.FFMPEG", None)
    with pytest.raises(VideoError, match="FFmpeg is not installed"):
        check_integrity(synthetic_video)


@pytest.mark.parametrize("extension", ["avi", "mov", "mkv"])
def test_probe_and_integrity_common_containers(ffmpeg_synthetic_video_factory, extension):
    path = ffmpeg_synthetic_video_factory(extension)
    metadata = probe_video(path)
    assert metadata["codec"]
    assert metadata["width"] == 160
    assert metadata["height"] == 120
    assert metadata["fps"] == pytest.approx(10, abs=0.01)
    assert metadata["duration"] == pytest.approx(1, abs=0.2)
    status, detail = check_integrity(path)
    assert status == "verified"
    assert detail


def test_probe_invalid_file(tmp_path):
    path = tmp_path / "invalid.mp4"
    path.write_bytes(b"this is not a video")
    with pytest.raises(VideoError):
        probe_video(path)
