"""Tests for shared helpers."""
import zipfile

from yt import utils


def test_extract_urls_dedupes_and_strips_punctuation():
    text = """
    check https://youtu.be/dQw4w9WgXcQ, and (https://example.com/page)
    again: https://youtu.be/dQw4w9WgXcQ
    """
    assert utils.extract_urls(text) == [
        "https://youtu.be/dQw4w9WgXcQ",
        "https://example.com/page",
    ]


def test_extract_urls_empty():
    assert utils.extract_urls("") == []
    assert utils.extract_urls("no links here") == []


def test_human_size():
    assert utils.human_size(None) == "-"
    assert utils.human_size(0) == "0 B"
    assert utils.human_size(1023) == "1023 B"
    assert utils.human_size(1536) == "1.50 KiB"
    assert utils.human_size(5 * 1024 * 1024) == "5.00 MiB"


def test_human_duration():
    assert utils.human_duration(None) == "-"
    assert utils.human_duration(59) == "0:59"
    assert utils.human_duration(125) == "2:05"
    assert utils.human_duration(3725) == "1:02:05"


def test_human_count():
    assert utils.human_count(None) == "-"
    assert utils.human_count(999) == "999"
    assert utils.human_count(1000) == "1K"
    assert utils.human_count(1234567) == "1.2M"
    assert utils.human_count(2_500_000_000) == "2.5B"


def test_json_roundtrip(tmp_path):
    target = tmp_path / "nested" / "state.json"
    utils.atomic_write_json(target, {"key": "välue"})
    assert utils.read_json(target, None) == {"key": "välue"}


def test_read_json_defaults(tmp_path):
    assert utils.read_json(tmp_path / "missing.json", 42) == 42
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{ nope", encoding="utf-8")
    assert utils.read_json(corrupt, "fallback") == "fallback"


def test_make_zip_dedupes_names_and_skips_missing(tmp_path):
    first = tmp_path / "a" / "clip.mp4"
    second = tmp_path / "b" / "clip.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    dest = tmp_path / "out" / "export.zip"
    count = utils.make_zip([first, second, tmp_path / "missing.mp4"], dest)
    assert count == 2
    with zipfile.ZipFile(dest) as archive:
        assert sorted(archive.namelist()) == ["clip (1).mp4", "clip.mp4"]
