"""Interactive guided mode for bulk downloading.

Launched with ``yt interactive`` (or ``yt gui``).  Walks the user through:

1. Choosing an input type from a menu
2. Entering a query / URL
3. (Search modes) Fetching results → displaying a Markdown table →
   arrow-key checkbox picker → user selects items
4. (URL modes) Resolving the URL directly
5. All selected items are added to the batch queue, then the user is asked
   whether to start downloading immediately.

Supported input types
---------------------
* YouTube Channel  — URL
* YouTube Channel  — Search
* YouTube Video    — URL
* YouTube Video    — Search
* YouTube Playlist — URL
* YouTube Playlist — Search  (search → pick a video from a playlist, or
                               search channels and treat their /videos as a
                               playlist)
* YouTube Short    — URL
* YouTube Short    — Search
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from rich.console import Console
from rich.text import Text

from yt import config, logger
from yt.tui import CheckboxMenu, render_markdown_table, pick, _is_tty

console = Console(highlight=False)
_err    = Console(stderr=True, highlight=False)

# ── Menu definitions ─────────────────────────────────────────────────────────

_INPUT_TYPES: List[Tuple[str, str]] = [
    ("channel_url",      "YouTube Channel  (URL)"),
    ("channel_search",   "YouTube Channel  (Search)"),
    ("video_url",        "YouTube Video    (URL)"),
    ("video_search",     "YouTube Video    (Search)"),
    ("playlist_url",     "YouTube Playlist (URL)"),
    ("playlist_search",  "YouTube Playlist (Search)"),
    ("short_url",        "YouTube Short    (URL)"),
    ("short_search",     "YouTube Short    (Search)"),
]

# ── Entry point ───────────────────────────────────────────────────────────────

def run_interactive(
    *,
    quality: str = "best",
    output: Optional[str] = None,
    audio_only: bool = False,
    auto_run: Optional[bool] = None,
) -> int:
    """Run the full interactive guided download session.

    Returns an exit code (0 = success, 1 = failure/abort).
    """
    if not _is_tty():
        logger.error("Interactive mode requires an interactive terminal (TTY).")
        return 2

    console.print()
    console.print(Text("  yt — Interactive Bulk Downloader", style="bold red"))
    console.print(Text("  ─────────────────────────────────", style="bright_black"))
    console.print()

    # ── Step 1: choose input type ────────────────────────────────────────────
    type_labels = [label for _, label in _INPUT_TYPES]
    type_keys   = [key   for key, _  in _INPUT_TYPES]

    console.print(Text("  Step 1 of 3 — What would you like to download?", style="bold"))
    console.print()

    selected_types = pick(
        type_keys,
        labels=type_labels,
        prompt="Choose an input type  (↑↓ move · SPACE select · ENTER confirm · q quit)",
    )
    if not selected_types:
        logger.fail("No input type selected — aborting.")
        return 1

    # Process each chosen input type in turn.
    all_queued: List[Dict] = []   # {url, title, kind}

    for input_type in selected_types:
        label = dict(_INPUT_TYPES)[input_type]
        console.print()
        console.print(Text(f"  ── {label}", style="bold cyan"))

        # ── Step 2: get query / URL ──────────────────────────────────────────
        is_search = input_type.endswith("_search")
        prompt_text = "  Search query: " if is_search else "  URL: "
        try:
            console.print(Text(prompt_text, style="bold"), end="")
            user_input = input("").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            logger.fail("Aborted.")
            return 1

        if not user_input:
            logger.warning(f"No input provided for [{label}] — skipping.")
            continue

        if is_search:
            items = _do_search(input_type, user_input)
        else:
            items = _do_resolve(input_type, user_input)

        if not items:
            continue

        # ── Step 3 (search only): show table + picker ────────────────────────
        if is_search:
            _render_results_table(input_type, items)
            chosen = _pick_results(items, input_type)
            if not chosen:
                logger.warning("Nothing selected — skipping.")
                continue
        else:
            chosen = items

        all_queued.extend(chosen)

    if not all_queued:
        logger.fail("Nothing was queued — exiting.")
        return 1

    # ── Queue everything ─────────────────────────────────────────────────────
    console.print()
    console.print(Text(f"  Queueing {len(all_queued)} item(s) …", style="bold"))
    from yt.batch import BatchQueue

    q = BatchQueue()
    added = 0
    for item in all_queued:
        if q.add_item(item["url"], item.get("kind", "video"), item.get("title")):
            added += 1
            logger.info(f"Queued: {item.get('title') or item['url']}")
        else:
            logger.warning(f"Already queued: {item['url']}")
    if added:
        q.save()
    console.print()
    console.print(
        Text(f"  ✓  {added} item(s) added to the batch queue.", style="bold green")
    )

    # ── Optionally start downloading now ─────────────────────────────────────
    if auto_run is None:
        try:
            console.print()
            console.print(Text("  Download now? [y/N] ", style="bold"), end="")
            answer = input("").strip().lower()
            auto_run = answer in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            auto_run = False

    if auto_run:
        console.print()
        from yt import downloader

        fmt: Optional[str] = None
        if quality != "custom":
            fmt = downloader.format_for_quality(quality)
        return q.run(fmt=fmt, output_dir=output, audio_only=audio_only)

    console.print()
    console.print(
        Text("  Run  yt batch run  when you are ready to start downloading.", style="bright_black")
    )
    return 0


# ── Search helpers ─────────────────────────────────────────────────────────────

def _do_search(input_type: str, query: str) -> List[Dict]:
    """Perform the appropriate search and return a normalised result list."""
    from yt import search

    limit = config.DEFAULT_SEARCH_LIMIT

    logger.info(f"Searching: {query!r} …")

    try:
        if input_type == "video_search":
            raw = search.search_videos(query, limit=limit)
            return [_norm_video(r) for r in raw]

        elif input_type == "short_search":
            # Shorts are videos — we search videos and tag them.
            raw = search.search_videos(query + " #shorts", limit=limit)
            return [_norm_video(r, kind="short") for r in raw]

        elif input_type == "channel_search":
            raw = search.search_channels(query, limit=limit)
            return [_norm_channel(r) for r in raw]

        elif input_type == "playlist_search":
            # Search for playlists via yt-dlp's ytsearchN: with a playlist
            # filter, then fall back to plain video results.
            raw = _search_playlists(query, limit=limit)
            return raw

        else:
            logger.error(f"Unknown search type: {input_type}")
            return []

    except Exception as exc:  # noqa: BLE001
        logger.error(f"Search failed: {exc}")
        return []


def _search_playlists(query: str, limit: int = 10) -> List[Dict]:
    """Search YouTube for playlists."""
    from yt.downloader import probe, YtDlpError
    from urllib.parse import urlencode

    # YouTube playlist filter parameter
    _PLAYLIST_FILTER = "EgIQAw=="
    params = urlencode({"search_query": query, "sp": _PLAYLIST_FILTER})
    try:
        data = probe(
            f"https://www.youtube.com/results?{params}",
            flat=True,
            extra=["--playlist-items", f"1:{limit}"],
        )
        entries = data.get("entries") or []
        results = []
        for e in entries:
            if not e:
                continue
            pid = e.get("id") or ""
            url = e.get("url") or (
                f"https://www.youtube.com/playlist?list={pid}" if pid else ""
            )
            if not url:
                continue
            results.append({
                "url":   url,
                "title": e.get("title") or "(untitled playlist)",
                "kind":  "playlist",
                "channel": e.get("channel") or e.get("uploader") or "-",
                "views": e.get("view_count"),
                "duration": None,
            })
        if results:
            return results[:limit]
    except YtDlpError:
        pass

    # Fallback: surface channel /videos pages from a video search.
    from yt import search as _search
    videos = _search.search_videos(query, limit=limit)
    seen: dict = {}
    for v in videos:
        cid  = v.get("channel_id")
        curl = v.get("channel_url") or (
            f"https://www.youtube.com/channel/{cid}" if cid else None
        )
        if curl and curl not in seen:
            seen[curl] = {
                "url":     curl.rstrip("/") + "/videos",
                "title":   f"{v.get('channel', 'Unknown')} — all videos",
                "kind":    "playlist",
                "channel": v.get("channel", "-"),
                "views":   None,
                "duration": None,
            }
    return list(seen.values())[:limit]


# ── URL-resolution helpers ────────────────────────────────────────────────────

def _do_resolve(input_type: str, url: str) -> List[Dict]:
    """Resolve a raw URL to a normalised result item."""
    from yt import resolver

    try:
        resolved = resolver.normalize(url)
    except resolver.ResolveError as exc:
        logger.error(f"Could not resolve {url!r}: {exc}")
        return []

    if resolved.note:
        logger.warning(f"Resolved via fallback: {resolved.note}")

    # Determine kind from the input_type (overrides resolver guess for shorts).
    kind = resolved.kind
    if input_type == "short_url":
        kind = "short"

    return [{
        "url":   resolved.url,
        "title": resolved.url,
        "kind":  kind,
        "channel": "-",
        "duration": None,
        "views": None,
    }]


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _norm_video(r: Dict, *, kind: str = "video") -> Dict:
    from yt.utils import human_duration, human_count
    return {
        "url":      r.get("url", ""),
        "title":    r.get("title", "(untitled)"),
        "kind":     kind,
        "channel":  r.get("channel", "-"),
        "duration": r.get("duration"),
        "views":    r.get("views"),
        # pre-formatted for the table
        "_duration_fmt": human_duration(r.get("duration")),
        "_views_fmt":    human_count(r.get("views")),
    }


def _norm_channel(r: Dict) -> Dict:
    from yt.utils import human_count
    return {
        "url":         r.get("url", ""),
        "title":       r.get("title", "(unnamed channel)"),
        "kind":        "channel",
        "channel":     r.get("title", "-"),
        "subscribers": r.get("subscribers"),
        "_subs_fmt":   human_count(r.get("subscribers")),
        "duration":    None,
        "views":       None,
    }


# ── Table rendering ───────────────────────────────────────────────────────────

_VIDEO_COLUMNS: List[Tuple[str, str]] = [
    ("#",        "_index"),
    ("Title",    "title"),
    ("Channel",  "channel"),
    ("Duration", "_duration_fmt"),
    ("Views",    "_views_fmt"),
    ("URL",      "url"),
]

_CHANNEL_COLUMNS: List[Tuple[str, str]] = [
    ("#",           "_index"),
    ("Channel",     "title"),
    ("Subscribers", "_subs_fmt"),
    ("URL",         "url"),
]

_PLAYLIST_COLUMNS: List[Tuple[str, str]] = [
    ("#",       "_index"),
    ("Title",   "title"),
    ("Channel", "channel"),
    ("URL",     "url"),
]


def _render_results_table(input_type: str, items: List[Dict]) -> None:
    """Print the Markdown results table for the given input type."""
    # Inject a 1-based index into each row so it shows in the table.
    indexed = []
    for i, item in enumerate(items, 1):
        row = dict(item)
        row["_index"] = str(i)
        # Provide defaults for any missing formatted fields.
        row.setdefault("_duration_fmt", "-")
        row.setdefault("_views_fmt", "-")
        row.setdefault("_subs_fmt", "-")
        indexed.append(row)

    if input_type in ("video_search", "short_search"):
        columns = _VIDEO_COLUMNS
        title = "Search Results"
    elif input_type == "channel_search":
        columns = _CHANNEL_COLUMNS
        title = "Channel Results"
    else:
        columns = _PLAYLIST_COLUMNS
        title = "Playlist Results"

    console.print()
    render_markdown_table(indexed, columns, title=title)


# ── Result picker ─────────────────────────────────────────────────────────────

def _pick_results(items: List[Dict], input_type: str) -> List[Dict]:
    """Show a checkbox menu over *items* and return the chosen subset."""
    labels = []
    for i, item in enumerate(items, 1):
        title   = item.get("title", "")[:55]
        channel = item.get("channel", "")
        if input_type in ("video_search", "short_search"):
            dur = item.get("_duration_fmt") or item.get("duration") or "-"
            labels.append(f"{i:>2}. {title:<56} {channel:<22}  {dur}")
        elif input_type == "channel_search":
            subs = item.get("_subs_fmt") or "-"
            labels.append(f"{i:>2}. {title:<56} {subs} subscribers")
        else:
            labels.append(f"{i:>2}. {title}")

    return pick(items, labels=labels, prompt="Select items to download  (↑↓ move · SPACE toggle · ENTER confirm · q quit)")
