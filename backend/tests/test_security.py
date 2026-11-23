import pytest

from app.services.security import (
    ValidationError,
    file_extension,
    safe_original_name,
    validate_upload,
)


def test_safe_original_name_strips_paths():
    assert safe_original_name("../../camera/clip.mp4") == "clip.mp4"
    assert safe_original_name("..\\windows\\clip.avi") == "clip.avi"


@pytest.mark.parametrize("name", ["", "..", "bad;rm.mp4", "a\nb.mp4", "$(whoami).mp4"])
def test_unsafe_names_rejected(name):
    with pytest.raises(ValidationError):
        safe_original_name(name)


@pytest.mark.parametrize("name", ["clip.MP4", "clip.avi", "clip.mov", "clip.mkv"])
def test_allowed_extensions(name):
    assert file_extension(name) in {"mp4", "avi", "mov", "mkv"}


def test_unsupported_extension_explains_conversion():
    with pytest.raises(ValidationError, match="ffmpeg"):
        file_extension("clip.exe")


def test_magic_byte_validation():
    with pytest.raises(ValidationError, match="content does not match"):
        validate_upload("fake.mp4", 1000, b"NOTANMP4", 10_000_000)


def test_empty_upload_rejected():
    with pytest.raises(ValidationError, match="Empty upload"):
        validate_upload("empty.mp4", 0, b"\x00\x00\x00\x20ftyp", 10_000_000)


def test_oversize_upload_rejected():
    with pytest.raises(ValidationError, match="too large"):
        validate_upload("large.mp4", 20, b"\x00\x00\x00\x20ftyp", 10)


@pytest.mark.parametrize(
    ("name", "header"),
    [
        ("camera.mp4", b"\x00\x00\x00\x20ftypisom"),
        ("camera.mov", b"\x00\x00\x00\x20ftypqt  "),
        ("camera.avi", b"RIFF\x20\x00\x00\x00AVI "),
        ("camera.mkv", b"\x1a\x45\xdf\xa3\x93\x42\x82\x88"),
    ],
)
def test_valid_container_headers_accepted(name, header):
    extension = name.rsplit(".", 1)[1]
    assert validate_upload(name, 100, header, 10_000_000) == (name, extension)


def test_hash_helpers(tmp_path):
    from app.services.security import sha256_bytes, sha256_file

    path = tmp_path / "bytes.bin"
    path.write_bytes(b"ATM Sentinel")
    assert sha256_file(path) == sha256_bytes(b"ATM Sentinel")
    assert len(sha256_file(path)) == 64
