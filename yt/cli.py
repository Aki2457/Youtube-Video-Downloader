"""Argument parsing and command routing.

The parser tree mirrors the public interface:

    yt download     <url...> [--quality ...] [--format ID] [--output DIR]
    yt batch        add | run | list | clear | export
    yt search       video | channel | add
    yt info         <url>
    yt interactive  (guided bulk-download wizard — also: yt gui)

Handlers import the heavy modules lazily so `yt --help` stays instant.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List, Optional, Sequence

from yt import __version__, config


class CommandError(Exception):
    """A user-facing command failure with an actionable message."""


_EXAMPLES = """\
examples:
  yt interactive                               # guided bulk-download wizard
  yt download https://youtu.be/dQw4w9WgXcQ
  yt download <url> --quality worst --output ~/Videos
  yt download <url> --format 137+140
  yt info <url>
  yt search video "lofi hip hop" --limit 5
  yt search add "boards of canada" --top 3
  yt batch add <url> <url> ...
  yt batch add --channel @veritasium --limit 10
  yt batch run
  yt batch export --zip
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt",
        description="A fast, scriptable YouTube downloader built on yt-dlp.",
        epilog=_EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(
        dest="command", metavar="<command>", required=True, title="commands"
    )

    # -- download ------------------------------------------------------------
    download = commands.add_parser(
        "download",
        help="Download videos, shorts, playlists, or channels",
        description="Download one or more URLs (videos, shorts, playlists, channels).",
    )
    download.add_argument(
        "urls",
        nargs="+",
        metavar="URL",
        help="URLs to download; non-URL text is resolved via search",
    )
    _add_download_options(download)
    download.add_argument(
        "--audio-only", action="store_true", help="Download/extract audio only"
    )
    download.add_argument(
        "--no-playlist",
        action="store_true",
        help="For URLs that reference both a video and a playlist, take only the video",
    )
    download.set_defaults(handler=_cmd_download)

    # -- batch ---------------------------------------------------------------
    batch = commands.add_parser(
        "batch",
        help="Manage the persistent download queue",
        description=f"Persistent download queue (stored in {config.APP_DIR}).",
    )
    batch_commands = batch.add_subparsers(
        dest="batch_command", metavar="<subcommand>", required=True, title="subcommands"
    )

    batch_add = batch_commands.add_parser(
        "add",
        help="Queue URLs, clipboard/stdin contents, or a channel's uploads",
        description="Queue URLs directly, from --paste, or expand a channel's uploads.",
    )
    batch_add.add_argument("urls", nargs="*", metavar="URL", help="URLs to queue")
    batch_add.add_argument(
        "--paste",
        action="store_true",
        help="Read URLs from stdin when piped, otherwise from the system clipboard",
    )
    batch_add.add_argument(
        "--channel",
        metavar="NAME_OR_URL",
        help="Queue a channel's uploads (accepts @handle, channel URL, or plain name)",
    )
    batch_add.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="With --channel: queue only the N most recent uploads",
    )
    batch_add.set_defaults(handler=_cmd_batch_add)

    batch_run = batch_commands.add_parser(
        "run",
        help="Download every pending item, sequentially",
        description="Download every pending queue item sequentially; failures don't stop the run.",
    )
    _add_download_options(batch_run)
    batch_run.add_argument(
        "--audio-only", action="store_true", help="Download/extract audio only"
    )
    batch_run.set_defaults(handler=_cmd_batch_run)

    batch_list = batch_commands.add_parser(
        "list", help="Show the queue", description="Show every queued item and its status."
    )
    batch_list.set_defaults(handler=_cmd_batch_list)

    batch_clear = batch_commands.add_parser(
        "clear", help="Empty the queue", description="Remove every item from the queue."
    )
    batch_clear.add_argument(
        "--yes", action="store_true", help="Do not ask for confirmation"
    )
    batch_clear.set_defaults(handler=_cmd_batch_clear)

    batch_export = batch_commands.add_parser(
        "export",
        help="Archive downloaded files",
        description="Create a ZIP archive of the files downloaded so far.",
    )
    batch_export.add_argument(
        "--zip",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Write a ZIP archive (default name: yt-export-<timestamp>.zip)",
    )
    batch_export.set_defaults(handler=_cmd_batch_export)

    # -- search ----------------------------------------------------------------
    search = commands.add_parser(
        "search", help="Search YouTube", description="Search YouTube for videos or channels."
    )
    search_commands = search.add_subparsers(
        dest="search_command", metavar="<subcommand>", required=True, title="subcommands"
    )

    search_video = search_commands.add_parser(
        "video", help="Search videos", description="Search videos and list the results."
    )
    search_video.add_argument("query", metavar="QUERY")
    _add_search_options(search_video)
    search_video.set_defaults(handler=_cmd_search_video)

    search_channel = search_commands.add_parser(
        "channel", help="Search channels", description="Search channels and list the results."
    )
    search_channel.add_argument("query", metavar="QUERY")
    _add_search_options(search_channel)
    search_channel.set_defaults(handler=_cmd_search_channel)

    search_add = search_commands.add_parser(
        "add",
        help="Search videos and queue a selection",
        description=(
            "Search videos and add a selection to the batch queue. "
            "Non-interactive selection: --index or --top."
        ),
    )
    search_add.add_argument("query", metavar="QUERY")
    search_add.add_argument(
        "--limit",
        type=int,
        default=config.DEFAULT_SEARCH_LIMIT,
        metavar="N",
        help=f"Number of results to consider (default: {config.DEFAULT_SEARCH_LIMIT})",
    )
    search_add.add_argument(
        "--index",
        metavar="I,J,...",
        help="Queue specific results by number, e.g. --index 1,3,5",
    )
    search_add.add_argument(
        "--top", type=int, metavar="N", help="Queue the first N results"
    )
    search_add.set_defaults(handler=_cmd_search_add)

    # -- info --------------------------------------------------------------------
    info = commands.add_parser(
        "info",
        help="Show formats, resolutions, and sizes for a URL",
        description="Show metadata and every available format for a URL.",
    )
    info.add_argument("url", metavar="URL")
    info.add_argument("--json", action="store_true", help="Emit raw metadata as JSON")
    info.set_defaults(handler=_cmd_info)

    # -- interactive / gui -------------------------------------------------------
    _interactive_desc = (
        "Launch the interactive guided bulk-download wizard.\n\n"
        "The wizard walks you through:\n"
        "  1. Choosing an input type (channel, video, playlist, or short — URL or search)\n"
        "  2. Entering a query or URL\n"
        "  3. Browsing search results in a Markdown table\n"
        "  4. Picking items with arrow-key checkboxes ([ ] / [X])\n"
        "  5. Queueing selected items and optionally downloading immediately\n\n"
        "Also available as: yt gui"
    )
    for _alias in ("interactive", "gui"):
        _p = commands.add_parser(
            _alias,
            help=(
                "Guided bulk-download wizard (arrow-key picker)"
                if _alias == "interactive"
                else "Alias for 'interactive'"
            ),
            description=_interactive_desc,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        _add_download_options(_p)
        _p.add_argument(
            "--audio-only", action="store_true", help="Download audio-only when running the queue"
        )
        _p.add_argument(
            "--run",
            action="store_true",
            dest="auto_run",
            default=None,
            help="Start downloading immediately after queueing (skip the confirmation prompt)",
        )
        _p.add_argument(
            "--no-run",
            action="store_false",
            dest="auto_run",
            help="Queue items but do NOT download — skip the confirmation prompt",
        )
        _p.set_defaults(handler=_cmd_interactive)

    return parser


def _add_download_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--quality",
        choices=config.QUALITY_CHOICES,
        default="best",
        help="Quality preset (default: best); 'custom' picks a format interactively",
    )
    parser.add_argument(
        "--format",
        dest="format_id",
        metavar="FORMAT_ID",
        help="Explicit yt-dlp format selector (e.g. 137+140); overrides --quality",
    )
    parser.add_argument(
        "--output",
        metavar="DIR",
        help=f"Output directory (default: ./{config.DEFAULT_OUTPUT_DIR})",
    )


def _add_search_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=config.DEFAULT_SEARCH_LIMIT,
        metavar="N",
        help=f"Number of results (default: {config.DEFAULT_SEARCH_LIMIT})",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit results as JSON (machine-readable)"
    )


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from yt import logger
    from yt.downloader import YtDlpError
    from yt.resolver import ResolveError

    try:
        return args.handler(args)
    except CommandError as exc:
        logger.error(str(exc))
        return 1
    except (ResolveError, YtDlpError) as exc:
        logger.error(str(exc))
        return 1


# -- handlers -------------------------------------------------------------------


def _cmd_download(args) -> int:
    from yt import batch, downloader, logger, resolver

    interactive_custom = (
        args.quality == "custom" and not args.format_id and not args.audio_only
    )
    if interactive_custom and not _is_tty():
        raise CommandError(
            "--quality custom needs an interactive terminal; pass --format <FORMAT_ID> instead"
        )
    base_fmt = _base_format(args)
    template = config.OUTPUT_TEMPLATE_ALL if args.quality == "all" else None

    failures = 0
    for raw in args.urls:
        try:
            resolved = resolver.normalize(raw)
        except resolver.ResolveError as exc:
            logger.fail(f"Could not resolve {raw!r}: {exc}")
            failures += 1
            continue
        if resolved.note:
            logger.warning(f"Resolved {raw!r} -> {resolved.url} ({resolved.note})")
        fmt = _pick_format(resolved.url) if interactive_custom else base_fmt
        logger.info(f"Downloading {resolved.kind}: {resolved.url}")
        result = downloader.download(
            resolved.url,
            fmt=fmt,
            output_dir=args.output,
            audio_only=args.audio_only,
            no_playlist=args.no_playlist,
            template=template,
        )
        batch.record_history(result)
        if result.ok:
            logger.info(f"Completed: {len(result.files)} file(s) saved")
        else:
            failures += 1
            for message in result.errors[:3]:
                logger.fail(message)
            if result.files:
                logger.warning(
                    f"Partially completed: {len(result.files)} file(s) saved before failure"
                )
    if failures:
        logger.warning(f"{failures} of {len(args.urls)} input(s) failed")
        return 1
    return 0


def _cmd_batch_add(args) -> int:
    from yt import batch, logger, utils

    if not args.urls and not args.paste and not args.channel:
        raise CommandError("nothing to add: pass URLs, --paste, or --channel <name_or_url>")
    if args.limit is not None and not args.channel:
        logger.warning("--limit only applies together with --channel; ignoring it")

    inputs: List[str] = list(args.urls)
    if args.paste:
        source = "stdin" if not sys.stdin.isatty() else "clipboard"
        pasted = utils.extract_urls(utils.read_stdin_or_clipboard())
        if pasted:
            logger.info(f"Read {len(pasted)} URL(s) from {source}")
            inputs.extend(pasted)
        else:
            logger.warning(f"No URLs found on {source}")

    queue = batch.BatchQueue()
    added = failed = 0
    if inputs:
        add_count, fail_count = queue.add_urls(inputs)
        added += add_count
        failed += fail_count
    if args.channel:
        added += queue.add_channel(args.channel, limit=args.limit)

    logger.info(f"Queue size: {len(queue.items)} item(s)")
    return 1 if (failed and not added) else 0


def _cmd_batch_run(args) -> int:
    from yt import batch

    if args.quality == "custom" and not args.format_id:
        raise CommandError(
            "batch run is non-interactive: pass --format <FORMAT_ID> or a quality preset"
        )
    template = config.OUTPUT_TEMPLATE_ALL if args.quality == "all" else None
    return batch.BatchQueue().run(
        fmt=_base_format(args),
        output_dir=args.output,
        audio_only=args.audio_only,
        template=template,
    )


def _cmd_batch_list(args) -> int:
    from yt import batch

    batch.BatchQueue().render()
    return 0


def _cmd_batch_clear(args) -> int:
    from yt import batch

    return batch.BatchQueue().clear(assume_yes=args.yes)


def _cmd_batch_export(args) -> int:
    from yt import batch

    if args.zip is None:
        raise CommandError("only ZIP export is supported: pass --zip [PATH]")
    return batch.BatchQueue().export_zip(args.zip or None)


def _cmd_search_video(args) -> int:
    from yt import logger, search

    results = search.search_videos(args.query, limit=args.limit)
    if args.json:
        _print_json(results)
        return 0
    if not results:
        logger.warning(f"No videos found for {args.query!r}")
        return 1
    search.render_videos(results, title=f'Videos for "{args.query}"')
    return 0


def _cmd_search_channel(args) -> int:
    from yt import logger, search

    results = search.search_channels(args.query, limit=args.limit)
    if args.json:
        _print_json(results)
        return 0
    if not results:
        logger.warning(f"No channels found for {args.query!r}")
        return 1
    search.render_channels(results, title=f'Channels for "{args.query}"')
    return 0


def _cmd_search_add(args) -> int:
    from yt import batch, logger, search

    results = search.search_videos(args.query, limit=args.limit)
    if not results:
        logger.warning(f"No videos found for {args.query!r}")
        return 1

    if args.index:
        picked = [results[i - 1] for i in _parse_indices(args.index, len(results))]
    elif args.top is not None:
        if args.top < 1:
            raise CommandError("--top must be at least 1")
        picked = results[: args.top]
    elif _is_tty():
        search.render_videos(results, title=f'Videos for "{args.query}"')
        picked = _interactive_pick(results)
        if not picked:
            logger.info("Nothing selected")
            return 0
    else:
        raise CommandError(
            "non-interactive session: select results with --index 1,3 or --top N"
        )

    queue = batch.BatchQueue()
    queue.add_videos(picked)
    logger.info(f"Queue size: {len(queue.items)} item(s)")
    return 0


def _cmd_interactive(args) -> int:
    from yt.interactive import run_interactive

    return run_interactive(
        quality=args.quality,
        output=args.output,
        audio_only=args.audio_only,
        auto_run=args.auto_run,
    )


def _cmd_info(args) -> int:
    from yt import downloader, resolver

    resolved = resolver.normalize(args.url)
    if resolved.kind in ("playlist", "channel"):
        target = (
            resolved.url.rstrip("/") + "/videos"
            if resolved.kind == "channel"
            else resolved.url
        )
        meta = downloader.probe(target, flat=True)
        if args.json:
            _print_json(meta)
        else:
            _render_collection_info(meta, resolved)
        return 0

    meta = downloader.probe(resolved.url, extra=["--no-playlist"])
    if args.json:
        _print_json(meta)
    else:
        _render_video_info(meta)
    return 0


# -- presentation helpers -------------------------------------------------------


def _render_video_info(meta: Dict) -> None:
    from rich.text import Text

    from yt import ui
    from yt.utils import human_count, human_duration

    upload_date = meta.get("upload_date")
    if upload_date and len(upload_date) == 8:
        upload_date = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
    ui.console.print(
        ui.kv_panel(
            "Video",
            [
                ("Title", meta.get("title")),
                ("Channel", meta.get("channel") or meta.get("uploader")),
                ("Duration", human_duration(meta.get("duration"))),
                ("Views", human_count(meta.get("view_count"))),
                ("Uploaded", upload_date),
                ("URL", meta.get("webpage_url")),
            ],
        )
    )

    duration = meta.get("duration")
    formats = [
        fmt for fmt in (meta.get("formats") or []) if fmt.get("ext") != "mhtml"
    ]  # mhtml = storyboard thumbnails, not downloadable media
    table = ui.table(
        {"header": "ID", "no_wrap": True},
        "Ext",
        "Resolution",
        {"header": "FPS", "justify": "right"},
        {"header": "Size", "justify": "right"},
        "VCodec",
        "ACodec",
        {"header": "Note", "style": "muted"},
        title=f"Available formats ({len(formats)})",
    )
    for fmt in formats:
        audio_only_row = fmt.get("vcodec") in (None, "none")
        table.add_row(
            str(fmt.get("format_id", "-")),
            fmt.get("ext") or "-",
            _resolution(fmt),
            _fps(fmt),
            _size_estimate(fmt, duration),
            _codec(fmt.get("vcodec")),
            _codec(fmt.get("acodec")),
            Text(fmt.get("format_note") or ""),
            style="muted" if audio_only_row else None,
        )
    ui.console.print(table)
    ui.hint("Sizes marked ~ are estimates. Download one with: yt download <url> --format <ID>")


def _render_collection_info(meta: Dict, resolved) -> None:
    from rich.text import Text

    from yt import ui
    from yt.utils import human_duration

    entries = [entry for entry in (meta.get("entries") or []) if entry]
    ui.console.print(
        ui.kv_panel(
            resolved.kind.capitalize(),
            [
                ("Title", meta.get("title") or meta.get("channel")),
                ("Uploader", meta.get("channel") or meta.get("uploader")),
                ("Items", len(entries) or meta.get("playlist_count")),
                ("URL", meta.get("webpage_url") or resolved.url),
            ],
        )
    )
    if not entries:
        return
    table = ui.table(
        {"header": "#", "justify": "right", "style": "accent"},
        {"header": "Title", "no_wrap": True, "overflow": "ellipsis", "max_width": 60},
        {"header": "Duration", "justify": "right", "no_wrap": True},
        {"header": "URL", "style": "muted", "overflow": "fold"},
    )
    shown = entries[:25]
    for index, entry in enumerate(shown, 1):
        url = entry.get("url") or (
            f"https://www.youtube.com/watch?v={entry['id']}" if entry.get("id") else "-"
        )
        table.add_row(
            str(index),
            Text(entry.get("title") or "(untitled)"),
            human_duration(entry.get("duration")),
            url,
        )
    if len(entries) > len(shown):
        table.caption = f"... and {len(entries) - len(shown)} more"
    ui.console.print(table)
    ui.hint("Run 'yt info <video-url>' to inspect formats for a single video.")


def _resolution(fmt: Dict) -> str:
    if fmt.get("vcodec") in (None, "none"):
        return "audio only"
    if fmt.get("resolution"):
        return str(fmt["resolution"])
    if fmt.get("width") and fmt.get("height"):
        return f"{fmt['width']}x{fmt['height']}"
    return "-"


def _fps(fmt: Dict) -> str:
    fps = fmt.get("fps")
    return str(int(fps)) if fps else "-"


def _size_estimate(fmt: Dict, duration: Optional[float]) -> str:
    from yt.utils import human_size

    if fmt.get("filesize"):
        return human_size(fmt["filesize"])
    if fmt.get("filesize_approx"):
        return "~" + human_size(fmt["filesize_approx"])
    if fmt.get("tbr") and duration:
        return "~" + human_size(fmt["tbr"] * 1000 / 8 * duration)
    return "-"


def _codec(value: Optional[str]) -> str:
    if not value or value == "none":
        return "-"
    return str(value).split(".")[0]


# -- shared helpers ---------------------------------------------------------------


def _base_format(args) -> Optional[str]:
    from yt import downloader

    if getattr(args, "audio_only", False):
        return None
    if args.format_id:
        return args.format_id
    if args.quality == "custom":
        return None  # resolved per-URL (interactively) by the caller
    return downloader.format_for_quality(args.quality)


def _pick_format(url: str) -> str:
    import questionary

    from yt import downloader

    meta = downloader.probe(url, extra=["--no-playlist"])
    if meta.get("_type") == "playlist" or not meta.get("formats"):
        raise CommandError(
            "--quality custom works on single videos; use --format for playlists/channels"
        )
    duration = meta.get("duration")
    choices = []
    for fmt in meta["formats"]:
        if fmt.get("ext") == "mhtml":
            continue
        format_id = str(fmt.get("format_id"))
        label = (
            f"{format_id:<9} {fmt.get('ext') or '-':<5} "
            f"{_resolution(fmt):<13} {_fps(fmt):>3} fps "
            f"{_size_estimate(fmt, duration):>12}  "
            f"{_codec(fmt.get('vcodec'))}/{_codec(fmt.get('acodec'))}"
        )
        choices.append(questionary.Choice(title=label, value=format_id))
    if not choices:
        raise CommandError("no downloadable formats reported for this video")
    answer = questionary.select("Format to download:", choices=choices).ask()
    if not answer:
        raise CommandError("no format selected")
    return answer


def _interactive_pick(results: List[Dict]) -> List[Dict]:
    import questionary

    choices = [
        questionary.Choice(title=f"{i}. {video['title']}  —  {video['channel']}", value=video)
        for i, video in enumerate(results, 1)
    ]
    return questionary.checkbox("Select videos to queue:", choices=choices).ask() or []


def _parse_indices(spec: str, count: int) -> List[int]:
    indices: List[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            raise CommandError(
                f"invalid index {chunk!r} (expected numbers like: --index 1,3,5)"
            ) from None
        if not 1 <= value <= count:
            raise CommandError(f"index {value} out of range (1-{count})")
        if value not in indices:
            indices.append(value)
    if not indices:
        raise CommandError("no valid indices given")
    return indices


def _print_json(data) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
