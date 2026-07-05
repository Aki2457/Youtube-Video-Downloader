"""Search abstraction built on yt-dlp's search extractors.

Videos use the `ytsearchN:` pseudo-URL; channels use a results-page URL with
YouTube's "type: channel" filter. Both go through the same subprocess probe
as everything else, so no extra (and unmaintained) search library is needed.
"""
from __future__ import annotations

from typing import Dict, List, Optional
from urllib.parse import urlencode

from rich.text import Text

from yt import config, ui
from yt.downloader import YtDlpError, probe
from yt.utils import human_count, human_duration

_CHANNEL_RESULTS_FILTER = "EgIQAg=="  # results-page "type: channel" filter


def search_videos(query: str, limit: int = config.DEFAULT_SEARCH_LIMIT) -> List[Dict]:
    limit = max(1, int(limit))
    data = probe(f"ytsearch{limit}:{query}", flat=True)
    return [_video_entry(entry) for entry in (data.get("entries") or []) if entry]


def search_channels(query: str, limit: int = config.DEFAULT_SEARCH_LIMIT) -> List[Dict]:
    limit = max(1, int(limit))
    params = urlencode({"search_query": query, "sp": _CHANNEL_RESULTS_FILTER})
    try:
        data = probe(
            f"https://www.youtube.com/results?{params}",
            flat=True,
            extra=["--playlist-items", f"1:{limit}"],
        )
        entries = (data.get("entries") or [])
        channels = [c for c in (_channel_entry(e) for e in entries if e) if c["url"]]
        if channels:
            return channels[:limit]
    except YtDlpError:
        pass  # fall through to the video-derived fallback below

    # Fallback: aggregate the channels behind a video search.
    channels_by_url: Dict[str, Dict] = {}
    for video in search_videos(query, limit=max(limit * 3, 15)):
        url = video.get("channel_url")
        if not url and video.get("channel_id"):
            url = f"https://www.youtube.com/channel/{video['channel_id']}"
        if not url or url in channels_by_url:
            continue
        channels_by_url[url] = {
            "id": video.get("channel_id") or "",
            "title": video.get("channel") or "(unknown)",
            "url": url,
            "subscribers": None,
        }
    return list(channels_by_url.values())[:limit]


def _video_entry(entry: Dict) -> Dict:
    video_id = entry.get("id") or ""
    return {
        "id": video_id,
        "title": entry.get("title") or "(untitled)",
        "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
        "channel": entry.get("channel") or entry.get("uploader") or "-",
        "channel_id": entry.get("channel_id"),
        "channel_url": entry.get("channel_url") or entry.get("uploader_url"),
        "duration": entry.get("duration"),
        "views": entry.get("view_count"),
    }


def _channel_entry(entry: Dict) -> Dict:
    channel_id = entry.get("id") or ""
    url = entry.get("url") or (
        f"https://www.youtube.com/channel/{channel_id}" if channel_id else ""
    )
    return {
        "id": channel_id,
        "title": entry.get("title") or entry.get("channel") or "(unnamed)",
        "url": url,
        "subscribers": entry.get("channel_follower_count"),
    }


def render_videos(results: List[Dict], *, title: Optional[str] = None) -> None:
    table = ui.table(
        {"header": "#", "justify": "right", "style": "accent"},
        {"header": "Title", "no_wrap": True, "overflow": "ellipsis", "max_width": 48},
        {"header": "Channel", "style": "cyan", "no_wrap": True, "overflow": "ellipsis", "max_width": 22},
        {"header": "Duration", "justify": "right", "no_wrap": True},
        {"header": "Views", "justify": "right", "no_wrap": True},
        {"header": "URL", "style": "muted", "overflow": "fold"},
        title=title,
    )
    for index, video in enumerate(results, 1):
        table.add_row(
            str(index),
            Text(video["title"]),
            Text(video["channel"]),
            human_duration(video.get("duration")),
            human_count(video.get("views")),
            video["url"],
        )
    ui.console.print(table)


def render_channels(results: List[Dict], *, title: Optional[str] = None) -> None:
    table = ui.table(
        {"header": "#", "justify": "right", "style": "accent"},
        {"header": "Channel", "no_wrap": True, "overflow": "ellipsis", "max_width": 32},
        {"header": "Subscribers", "justify": "right", "no_wrap": True},
        {"header": "URL", "style": "muted", "overflow": "fold"},
        title=title,
    )
    for index, channel in enumerate(results, 1):
        table.add_row(
            str(index),
            Text(channel["title"]),
            human_count(channel.get("subscribers")),
            channel["url"],
        )
    ui.console.print(table)
