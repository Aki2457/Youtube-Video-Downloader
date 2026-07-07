"""Persistent batch queue stored as JSON under ~/.yt/.

Queue writes are atomic and the state is saved after every processed item,
so an interrupted `batch run` can simply be re-run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from rich.text import Text

from yt import config, logger, resolver, ui
from yt.downloader import DownloadResult, YtDlpError, download, probe
from yt.utils import (
    atomic_write_json,
    human_size,
    now_iso,
    make_zip,
    read_json,
    short_id,
)


def record_history(result: DownloadResult, history_path: Optional[Path] = None) -> None:
    """Remember downloaded files so `yt batch export --zip` can find them."""
    if not result.files:
        return
    path = Path(history_path or config.HISTORY_FILE)
    history = read_json(path, {"files": []})
    files = history.get("files")
    if not isinstance(files, list):
        files = []
    stamp = now_iso()
    for file_path in result.files:
        files.append(
            {
                "file": str(Path(file_path).resolve()),
                "url": result.url,
                "downloaded_at": stamp,
            }
        )
    atomic_write_json(path, {"files": files})


class BatchQueue:
    def __init__(self, path: Optional[Path] = None, history_path: Optional[Path] = None):
        self.path = Path(path or config.BATCH_FILE)
        self.history_path = Path(history_path or config.HISTORY_FILE)
        self.items: List[Dict] = self._load()

    def _load(self) -> List[Dict]:
        data = read_json(self.path, {"items": []})
        items = data.get("items") if isinstance(data, dict) else None
        return items if isinstance(items, list) else []

    def save(self) -> None:
        atomic_write_json(self.path, {"items": self.items})

    # -- adding ------------------------------------------------------------

    def add_item(self, url: str, kind: str = "video", title: Optional[str] = None) -> bool:
        """Append one entry unless the URL is already queued."""
        if any(item.get("url") == url for item in self.items):
            return False
        self.items.append(
            {
                "id": short_id(),
                "url": url,
                "kind": kind,
                "title": title,
                "added_at": now_iso(),
                "status": "pending",
                "error": None,
            }
        )
        return True

    def add_urls(self, inputs: Sequence[str]) -> Tuple[int, int]:
        """Resolve and queue each input; returns (added, failed)."""
        added = failed = 0
        for raw in inputs:
            try:
                resolved = resolver.normalize(raw)
            except (resolver.ResolveError, YtDlpError) as exc:
                logger.fail(f"Skipped {raw!r}: {exc}")
                failed += 1
                continue
            if resolved.note:
                logger.warning(f"Resolved {raw!r} via fallback ({resolved.note})")
            if self.add_item(resolved.url, resolved.kind):
                logger.info(f"Queued {resolved.kind}: {resolved.url}")
                added += 1
            else:
                logger.warning(f"Already queued: {resolved.url}")
        if added:
            self.save()
        return added, failed

    def add_videos(self, videos: Sequence[Dict], *, verbose: bool = True) -> int:
        """Queue video dicts (url/title) coming from search or channel expansion."""
        added = 0
        for video in videos:
            if self.add_item(video["url"], "video", video.get("title")):
                added += 1
                if verbose:
                    logger.info(f"Queued video: {video.get('title') or video['url']}")
            elif verbose:
                logger.warning(f"Already queued: {video['url']}")
        if added:
            self.save()
        return added

    def add_channel(self, name_or_url: str, limit: Optional[int] = None) -> int:
        """Expand a channel's uploads into individual queue entries."""
        resolved = resolver.resolve_channel(name_or_url)
        if resolved.note:
            logger.info(f"Channel match: {resolved.note}")
        videos_url = resolved.url.rstrip("/") + "/videos"
        logger.info(f"Fetching uploads from {resolved.url}")
        extra = ["--playlist-items", f"1:{int(limit)}"] if limit else []
        data = probe(videos_url, flat=True, extra=extra)

        videos = []
        for entry in data.get("entries") or []:
            if not entry:
                continue
            url = entry.get("url")
            if not url and entry.get("id"):
                url = f"https://www.youtube.com/watch?v={entry['id']}"
            if url:
                videos.append({"url": url, "title": entry.get("title")})
        if limit:
            videos = videos[: int(limit)]
        if not videos:
            logger.warning("Channel has no downloadable uploads")
            return 0
        added = self.add_videos(videos, verbose=False)
        skipped = len(videos) - added
        message = f"Queued {added} video(s) from channel"
        if skipped:
            message += f" ({skipped} already queued)"
        logger.info(message)
        return added

    # -- inspecting / mutating ----------------------------------------------

    def render(self) -> None:
        if not self.items:
            logger.info("Batch queue is empty")
            ui.hint("Add items with: yt batch add <url> | --paste | --channel <name>")
            return
        table = ui.table(
            {"header": "#", "justify": "right", "style": "accent"},
            {"header": "Status", "no_wrap": True},
            {"header": "Kind", "no_wrap": True},
            {"header": "Title / URL", "overflow": "fold", "max_width": 60},
            {"header": "Added", "style": "muted", "no_wrap": True},
            title=f"Batch queue ({len(self.items)} item{'s' if len(self.items) != 1 else ''})",
        )
        counts = {"pending": 0, "done": 0, "failed": 0}
        for index, item in enumerate(self.items, 1):
            status = item.get("status", "pending")
            counts[status] = counts.get(status, 0) + 1
            table.add_row(
                str(index),
                ui.status_text(status),
                item.get("kind", "video"),
                Text(item.get("title") or item["url"]),
                (item.get("added_at") or "")[:10],
            )
        table.caption = (
            f"{counts.get('pending', 0)} pending · "
            f"{counts.get('done', 0)} done · "
            f"{counts.get('failed', 0)} failed"
        )
        ui.console.print(table)

    def clear(self, *, assume_yes: bool = False) -> int:
        if not self.items:
            logger.info("Batch queue is already empty")
            return 0
        count = len(self.items)
        if not assume_yes and sys.stdin.isatty() and sys.stdout.isatty():
            import questionary

            confirmed = questionary.confirm(
                f"Remove all {count} queued item(s)?", default=False
            ).ask()
            if not confirmed:
                logger.info("Aborted")
                return 1
        self.items = []
        self.save()
        logger.info(f"Cleared {count} item(s) from the batch queue")
        return 0

    # -- running / exporting -------------------------------------------------

    def run(
        self,
        *,
        fmt: Optional[str] = None,
        output_dir: Optional[str] = None,
        audio_only: bool = False,
        template: Optional[str] = None,
    ) -> int:
        pending = [item for item in self.items if item.get("status") == "pending"]
        if not pending:
            logger.info("Nothing to do: the batch queue has no pending items")
            ui.hint("Queue items with: yt batch add <url>")
            return 0
        logger.info(f"Batch run: {len(pending)} pending item(s)")
        failed = 0
        for index, item in enumerate(pending, 1):
            label = item.get("title") or item["url"]
            logger.info(f"[{index}/{len(pending)}] {label}")
            try:
                result = download(
                    item["url"],
                    fmt=fmt,
                    output_dir=output_dir,
                    audio_only=audio_only,
                    template=template,
                )
            except YtDlpError as exc:
                result = DownloadResult(url=item["url"], ok=False, errors=[str(exc)])
            record_history(result, self.history_path)
            if result.ok:
                item["status"] = "done"
                item["error"] = None
            else:
                item["status"] = "failed"
                item["error"] = "; ".join(result.errors)[:300] or "unknown error"
                failed += 1
                logger.fail(f"Failed: {label}")
            self.save()  # persist after every item so an interrupted run resumes cleanly
        done = len(pending) - failed
        ui.console.print(ui.summary_line(done, failed))
        if failed:
            logger.warning(f"{failed} of {len(pending)} item(s) failed; they stay queued as 'failed'")
            return 1
        return 0

    def export_zip(self, dest: Optional[str] = None) -> int:
        history = read_json(self.history_path, {"files": []})
        recorded = [
            entry.get("file")
            for entry in (history.get("files") or [])
            if isinstance(entry, dict) and entry.get("file")
        ]
        # Deduplicate while keeping order, then drop anything since deleted.
        candidates = [f for f in dict.fromkeys(recorded) if Path(f).is_file()]
        if not candidates:
            output_dir = Path(config.DEFAULT_OUTPUT_DIR)
            if output_dir.is_dir():
                candidates = [str(p) for p in sorted(output_dir.iterdir()) if p.is_file()]
        if not candidates:
            logger.error(
                "Nothing to export: no downloads recorded and "
                f"'{config.DEFAULT_OUTPUT_DIR}' is empty"
            )
            return 1
        dest_path = Path(dest) if dest else Path(
            f"yt-export-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        )
        total_bytes = sum(Path(f).stat().st_size for f in candidates)
        count = make_zip(candidates, dest_path)
        logger.info(f"Exported {count} file(s) ({human_size(total_bytes)}) -> {dest_path}")
        return 0
