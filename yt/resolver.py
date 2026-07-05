"""URL normalization and fallback resolution.

The pipeline turns anything the user throws at the tool into a canonical
YouTube URL plus a kind ("video", "playlist", or "channel"):

1. YouTube URLs in any shape (youtu.be, /watch, /shorts, /embed, /live,
   /@handle, /c/, /user/, /channel/, /playlist) are normalized locally.
2. Non-YouTube URLs are fetched (following redirects) and scanned for an
   embedded YouTube video.
3. As a last resort, keywords are extracted from the input and resolved via
   a YouTube search, with a warning that the match is fuzzy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests

from yt import config, logger


class ResolveError(ValueError):
    """Raised when an input cannot be resolved to something downloadable."""


@dataclass
class Resolved:
    url: str
    kind: str  # "video" | "playlist" | "channel"
    original: str
    note: Optional[str] = None  # set when resolution was fuzzy (search fallback)


_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
}

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_EMBED_PATTERNS = [
    re.compile(r"youtube(?:-nocookie)?\.com/embed/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/watch\?[^\s\"'<>]*?v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
]


def normalize(raw: str, *, allow_fallback: bool = True) -> Resolved:
    """Resolve *raw* (URL or free text) to a canonical YouTube resource."""
    text = (raw or "").strip()
    if not text:
        raise ResolveError("empty input")

    if not _looks_like_url(text):
        if allow_fallback:
            return _search_fallback(text, original=raw)
        raise ResolveError(f"not a URL: {text!r}")

    url = text if "://" in text else f"https://{text}"
    parsed = urlparse(url)
    host = _clean_host(parsed.netloc)

    if host == "youtu.be":
        segments = _segments(parsed.path)
        if segments and _VIDEO_ID_RE.match(segments[0]):
            playlist_id = _first_query_value(parsed.query, "list")
            return Resolved(_watch_url(segments[0], playlist_id), "video", raw)
        raise ResolveError(f"unrecognized youtu.be link: {text}")

    if host in _YOUTUBE_HOSTS:
        return _normalize_youtube(parsed, raw, allow_fallback)

    return _resolve_external(url, raw, allow_fallback)


def resolve_channel(name_or_url: str) -> Resolved:
    """Resolve a channel from a URL, an @handle, or a plain channel name."""
    text = (name_or_url or "").strip()
    if not text:
        raise ResolveError("empty channel name")
    if _looks_like_url(text):
        resolved = normalize(text, allow_fallback=False)
        if resolved.kind != "channel":
            raise ResolveError(f"not a channel URL: {text}")
        return resolved
    if text.startswith("@") and " " not in text:
        return Resolved(f"https://www.youtube.com/{text}", "channel", name_or_url)

    from yt import search  # deferred: only the fuzzy path needs it

    logger.warning(f'Looking up channel by name: "{text}"')
    results = search.search_channels(text, limit=1)
    if not results:
        raise ResolveError(f"no channel found for {text!r}")
    best = results[0]
    return Resolved(best["url"], "channel", name_or_url, note=f"best match: {best['title']}")


def _normalize_youtube(parsed, raw: str, allow_fallback: bool) -> Resolved:
    segments = _segments(parsed.path)
    query = parse_qs(parsed.query)

    if segments[:1] == ["watch"]:
        video_id = (query.get("v") or [None])[0]
        playlist_id = (query.get("list") or [None])[0]
        if video_id and _VIDEO_ID_RE.match(video_id):
            return Resolved(_watch_url(video_id, playlist_id), "video", raw)
        if playlist_id:
            return Resolved(_playlist_url(playlist_id), "playlist", raw)
        raise ResolveError(f"watch URL without a valid video id: {raw}")

    if segments[:1] == ["playlist"]:
        playlist_id = (query.get("list") or [None])[0]
        if playlist_id:
            return Resolved(_playlist_url(playlist_id), "playlist", raw)
        raise ResolveError(f"playlist URL without a list id: {raw}")

    if len(segments) >= 2 and segments[0] in ("shorts", "embed", "live", "v"):
        if _VIDEO_ID_RE.match(segments[1]):
            return Resolved(_watch_url(segments[1]), "video", raw)
        raise ResolveError(f"invalid video id in URL: {raw}")

    if segments and segments[0].startswith("@"):
        return Resolved(f"https://www.youtube.com/{segments[0]}", "channel", raw)

    if len(segments) >= 2 and segments[0] in ("c", "user", "channel"):
        return Resolved(f"https://www.youtube.com/{segments[0]}/{segments[1]}", "channel", raw)

    if segments[:1] == ["results"]:
        search_query = (query.get("search_query") or [None])[0]
        if search_query and allow_fallback:
            return _search_fallback(search_query, original=raw)
        raise ResolveError(f"cannot resolve a search-results URL: {raw}")

    raise ResolveError(f"unsupported YouTube URL: {raw}")


def _resolve_external(url: str, raw: str, allow_fallback: bool) -> Resolved:
    """Fetch an external page and look for an embedded/linked YouTube video."""
    logger.info(f"Resolving external page: {url}")
    html = ""
    try:
        response = requests.get(
            url,
            timeout=config.HTTP_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
            allow_redirects=True,
        )
        final_host = _clean_host(urlparse(response.url).netloc)
        if final_host == "youtu.be" or final_host in _YOUTUBE_HOSTS:
            return normalize(response.url, allow_fallback=False)
        html = response.text or ""
    except requests.RequestException as exc:
        logger.warning(f"Could not fetch page ({type(exc).__name__}); trying keyword fallback")

    for pattern in _EMBED_PATTERNS:
        match = pattern.search(html)
        if match:
            return Resolved(
                _watch_url(match.group(1)), "video", raw, note="embedded video found on page"
            )

    if allow_fallback:
        keywords = _keywords_from_url(url)
        if keywords:
            return _search_fallback(keywords, original=raw)
    raise ResolveError(f"could not resolve {raw!r} to a YouTube resource")


def _search_fallback(query: str, *, original: str) -> Resolved:
    from yt import search  # deferred: only the fallback path needs it
    from yt.downloader import YtDlpError

    logger.warning(f'Falling back to search: "{query}"')
    try:
        results = search.search_videos(query, limit=1)
    except YtDlpError as exc:
        raise ResolveError(f"fallback search failed: {exc}") from exc
    if not results:
        raise ResolveError(f"no search results for {query!r}")
    best = results[0]
    return Resolved(best["url"], "video", original, note=f"best match: {best['title']}")


def _keywords_from_url(url: str) -> str:
    """Derive a search query from a URL's slug and domain."""
    parsed = urlparse(url)
    tokens: List[str] = []
    segments = _segments(parsed.path)
    if segments:
        slug = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", segments[-1])
        tokens = [
            token
            for token in re.split(r"[-_+.%\s]+", slug)
            if len(token) > 2 and not token.isdigit()
        ]
    if not tokens:
        domain = _clean_host(parsed.netloc).split(".")[0]
        tokens = [domain] if domain else []
    return " ".join(tokens[:8])


def _looks_like_url(text: str) -> bool:
    stripped = text.strip()
    if not stripped or any(ch.isspace() for ch in stripped):
        return False
    return "://" in stripped or "." in stripped


def _clean_host(netloc: str) -> str:
    host = netloc.split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _segments(path: str) -> List[str]:
    return [segment for segment in (path or "").split("/") if segment]


def _first_query_value(query: str, key: str) -> Optional[str]:
    return (parse_qs(query).get(key) or [None])[0]


def _watch_url(video_id: str, playlist_id: Optional[str] = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    if playlist_id:
        url += f"&list={quote(playlist_id, safe='')}"
    return url


def _playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={quote(playlist_id, safe='')}"
