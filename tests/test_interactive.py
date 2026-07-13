"""Offline tests for the interactive guided-mode helpers (interactive.py).

Network calls (search_videos, search_channels, resolver.normalize, probe) are
mocked so every test runs without internet access.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── _norm_video / _norm_channel ────────────────────────────────────────────────

def test_norm_video_defaults():
    from yt.interactive import _norm_video

    result = _norm_video({
        "url": "https://www.youtube.com/watch?v=abc",
        "title": "Test Video",
        "channel": "Test Channel",
        "duration": 125,
        "views": 1_234_567,
    })
    assert result["kind"] == "video"
    assert result["title"] == "Test Video"
    assert result["_duration_fmt"] == "2:05"
    assert result["_views_fmt"] == "1.2M"


def test_norm_video_kind_override():
    from yt.interactive import _norm_video

    result = _norm_video({"url": "u", "title": "t", "channel": "c"}, kind="short")
    assert result["kind"] == "short"


def test_norm_channel():
    from yt.interactive import _norm_channel

    result = _norm_channel({
        "url": "https://www.youtube.com/@test",
        "title": "Test Channel",
        "subscribers": 5_000_000,
    })
    assert result["kind"] == "channel"
    assert result["_subs_fmt"] == "5M"


def test_norm_channel_no_subs():
    from yt.interactive import _norm_channel

    result = _norm_channel({"url": "u", "title": "c", "subscribers": None})
    assert result["_subs_fmt"] == "-"


# ── _do_resolve ────────────────────────────────────────────────────────────────

def test_do_resolve_video_url():
    from yt.interactive import _do_resolve
    from yt.resolver import Resolved

    fake = Resolved(
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        kind="video",
        original="https://youtu.be/dQw4w9WgXcQ",
    )
    with patch("yt.resolver.normalize", return_value=fake):
        result = _do_resolve("video_url", "https://youtu.be/dQw4w9WgXcQ")
    assert len(result) == 1
    assert result[0]["url"] == fake.url
    assert result[0]["kind"] == "video"


def test_do_resolve_short_url_overrides_kind():
    from yt.interactive import _do_resolve
    from yt.resolver import Resolved

    fake = Resolved(
        url="https://www.youtube.com/watch?v=abc",
        kind="video",
        original="https://www.youtube.com/shorts/abc",
    )
    with patch("yt.resolver.normalize", return_value=fake):
        result = _do_resolve("short_url", "https://www.youtube.com/shorts/abc")
    assert result[0]["kind"] == "short"


def test_do_resolve_error_returns_empty(capsys):
    from yt.interactive import _do_resolve
    from yt.resolver import ResolveError

    with patch("yt.resolver.normalize", side_effect=ResolveError("bad url")):
        result = _do_resolve("video_url", "not-a-url")
    assert result == []


# ── _do_search ─────────────────────────────────────────────────────────────────

def _fake_video(n: int) -> dict:
    return {
        "id": f"vid{n}",
        "title": f"Video {n}",
        "url": f"https://www.youtube.com/watch?v=vid{n}",
        "channel": f"Channel {n}",
        "channel_id": f"cid{n}",
        "channel_url": f"https://www.youtube.com/channel/cid{n}",
        "duration": 120 * n,
        "views": 1000 * n,
    }


def test_do_search_video():
    from yt.interactive import _do_search

    fake_videos = [_fake_video(i) for i in range(1, 4)]
    with patch("yt.search.search_videos", return_value=fake_videos):
        result = _do_search("video_search", "test query")
    assert len(result) == 3
    assert all(r["kind"] == "video" for r in result)
    assert result[0]["title"] == "Video 1"


def test_do_search_short():
    from yt.interactive import _do_search

    fake_videos = [_fake_video(1)]
    with patch("yt.search.search_videos", return_value=fake_videos):
        result = _do_search("short_search", "funny cat")
    assert result[0]["kind"] == "short"


def test_do_search_channel():
    from yt.interactive import _do_search

    fake_channels = [
        {"id": "c1", "title": "Chan 1", "url": "https://www.youtube.com/channel/c1", "subscribers": 10000},
    ]
    with patch("yt.search.search_channels", return_value=fake_channels):
        result = _do_search("channel_search", "my channel")
    assert len(result) == 1
    assert result[0]["kind"] == "channel"


def test_do_search_handles_exception(capsys):
    from yt.interactive import _do_search

    with patch("yt.search.search_videos", side_effect=RuntimeError("network error")):
        result = _do_search("video_search", "anything")
    assert result == []


# ── _render_results_table (smoke test) ────────────────────────────────────────

def test_render_results_table_video(capsys):
    from yt.interactive import _render_results_table

    items = [
        {
            "title": "Hello World",
            "channel": "Test Chan",
            "url": "https://yt.com/watch?v=x",
            "kind": "video",
            "_duration_fmt": "3:30",
            "_views_fmt": "1.2M",
        }
    ]
    _render_results_table("video_search", items)
    out = capsys.readouterr().out
    assert "Hello World" in out
    assert "Test Chan" in out


def test_render_results_table_channel(capsys):
    from yt.interactive import _render_results_table

    items = [
        {
            "title": "My Channel",
            "url": "https://yt.com/@mychan",
            "kind": "channel",
            "_subs_fmt": "500K",
        }
    ]
    _render_results_table("channel_search", items)
    out = capsys.readouterr().out
    assert "My Channel" in out


# ── CLI wiring ────────────────────────────────────────────────────────────────

def test_interactive_command_registered():
    from yt.cli import build_parser

    parser = build_parser()
    # Should parse without error.
    args = parser.parse_args(["interactive", "--no-run"])
    assert args.auto_run is False
    assert args.quality == "best"


def test_gui_alias_registered():
    from yt.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["gui", "--run"])
    assert args.auto_run is True


def test_interactive_requires_tty(monkeypatch):
    """run_interactive returns 2 when not called from a TTY."""
    monkeypatch.setattr("yt.tui._is_tty", lambda: False)
    from yt.interactive import run_interactive

    code = run_interactive()
    assert code == 2
