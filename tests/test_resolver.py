"""Offline tests for the URL normalization pipeline (no network involved)."""
import pytest

from yt import resolver

WATCH = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    ("raw", "expected_url", "expected_kind"),
    [
        # youtu.be short links
        ("https://youtu.be/dQw4w9WgXcQ", WATCH, "video"),
        ("https://youtu.be/dQw4w9WgXcQ?si=tracking123", WATCH, "video"),
        # watch URLs, with tracking params stripped
        (WATCH, WATCH, "video"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&pp=xyz", WATCH, "video"),
        # scheme-less and mobile/music hosts
        ("youtube.com/watch?v=dQw4w9WgXcQ", WATCH, "video"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", WATCH, "video"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ", WATCH, "video"),
        # shorts / embed / live
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", WATCH, "video"),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", WATCH, "video"),
        ("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ", WATCH, "video"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", WATCH, "video"),
        # video inside a playlist keeps the list context
        (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLtest123",
            WATCH + "&list=PLtest123",
            "video",
        ),
        # playlists
        (
            "https://www.youtube.com/playlist?list=PLtest123",
            "https://www.youtube.com/playlist?list=PLtest123",
            "playlist",
        ),
        (
            "https://www.youtube.com/watch?list=PLtest123",
            "https://www.youtube.com/playlist?list=PLtest123",
            "playlist",
        ),
        # channel shapes
        (
            "https://www.youtube.com/@veritasium",
            "https://www.youtube.com/@veritasium",
            "channel",
        ),
        (
            "https://www.youtube.com/@veritasium/videos",
            "https://www.youtube.com/@veritasium",
            "channel",
        ),
        (
            "https://www.youtube.com/c/veritasium",
            "https://www.youtube.com/c/veritasium",
            "channel",
        ),
        (
            "https://www.youtube.com/user/nasa",
            "https://www.youtube.com/user/nasa",
            "channel",
        ),
        (
            "https://www.youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA",
            "https://www.youtube.com/channel/UCHnyfMqiRRG1u-2MsSQLbXA",
            "channel",
        ),
    ],
)
def test_normalize(raw, expected_url, expected_kind):
    resolved = resolver.normalize(raw, allow_fallback=False)
    assert resolved.url == expected_url
    assert resolved.kind == expected_kind
    assert resolved.original == raw


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url at all",
        "https://www.youtube.com/watch",  # no video id, no list
        "https://www.youtube.com/watch?v=tooshort",
        "https://www.youtube.com/",
        "https://youtu.be/",
    ],
)
def test_normalize_rejects(raw):
    with pytest.raises(resolver.ResolveError):
        resolver.normalize(raw, allow_fallback=False)


def test_resolve_channel_from_handle():
    resolved = resolver.resolve_channel("@mkbhd")
    assert resolved.url == "https://www.youtube.com/@mkbhd"
    assert resolved.kind == "channel"


def test_resolve_channel_rejects_video_url():
    with pytest.raises(resolver.ResolveError):
        resolver.resolve_channel(WATCH)


def test_keywords_from_url():
    query = resolver._keywords_from_url("https://blog.example.com/posts/my-cool-video-2024.html")
    assert query == "cool video"


def test_keywords_fall_back_to_domain():
    assert resolver._keywords_from_url("https://www.example.com/") == "example"
