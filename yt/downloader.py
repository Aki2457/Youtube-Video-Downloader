"""yt-dlp wrapper: command construction, subprocess execution, live progress.

yt-dlp is always invoked as `python -m yt_dlp` with an argument list (never
shell=True), which is PATH-independent and works identically on Windows,
Linux, and macOS.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from yt import config, logger, ui


class YtDlpError(RuntimeError):
    """A failed yt-dlp invocation, carrying the most useful error line."""


@dataclass
class DownloadResult:
    url: str
    ok: bool
    files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# Machine-readable progress lines. The title is the last field so it may
# safely contain the delimiter.
_PROGRESS_PREFIX = "YTPROG"
_FILE_PREFIX = "YTFILE"
_PROGRESS_TEMPLATE = (
    "download:"
    f"{_PROGRESS_PREFIX}"
    "|%(info.id)s|%(progress.status)s|%(progress.downloaded_bytes)s"
    "|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s"
    "|%(info.title)s"
)

_ffmpeg_warned = False


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def format_for_quality(quality: str) -> Optional[str]:
    """Map a --quality preset to a yt-dlp format selector.

    Without ffmpeg, separate video+audio streams cannot be merged, so the
    presets degrade to the best/worst single-file format (with one warning).
    """
    global _ffmpeg_warned
    if quality not in config.QUALITY_FORMATS:
        return None
    if ffmpeg_available():
        return config.QUALITY_FORMATS[quality]
    if quality in ("best", "worst") and not _ffmpeg_warned:
        logger.warning(
            "ffmpeg not found: streams cannot be merged, using single-file "
            "formats instead (install ffmpeg for full quality)"
        )
        _ffmpeg_warned = True
    return config.QUALITY_FORMATS_NO_FFMPEG[quality]


def base_command() -> List[str]:
    return [sys.executable, "-m", "yt_dlp", "--no-warnings"]


def probe(
    target: str,
    *,
    flat: bool = False,
    extra: Optional[List[str]] = None,
    timeout: int = 300,
) -> dict:
    """Return yt-dlp's JSON metadata for *target* (video, playlist, or search)."""
    command = base_command() + ["-J"]
    if flat:
        command.append("--flat-playlist")
    if extra:
        command.extend(extra)
    command += ["--", target]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise YtDlpError(f"could not launch yt-dlp: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise YtDlpError(f"yt-dlp timed out after {timeout}s inspecting {target!r}") from exc
    if completed.returncode != 0 or not completed.stdout.strip():
        raise YtDlpError(_error_detail(completed.stderr, target))
    try:
        return json.loads(completed.stdout)
    except ValueError as exc:
        raise YtDlpError(f"unreadable yt-dlp metadata for {target!r}: {exc}") from exc


def download(
    url: str,
    *,
    fmt: Optional[str] = None,
    output_dir: Optional[str] = None,
    audio_only: bool = False,
    no_playlist: bool = False,
    template: Optional[str] = None,
) -> DownloadResult:
    """Download *url* with a live progress display.

    Failures inside playlists/channels are ignored by yt-dlp (--ignore-errors)
    so one broken video never aborts the rest; everything that went wrong is
    reported in the result.
    """
    global _ffmpeg_warned
    out_dir = Path(output_dir) if output_dir else config.DEFAULT_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    command = base_command() + [
        "--ignore-errors",
        "--no-simulate",
        "--quiet",
        "--progress",
        "--newline",
        "--retries", "3",
        "--progress-template", _PROGRESS_TEMPLATE,
        "--print", f"after_move:{_FILE_PREFIX}|%(filepath)s",
        "--output", str(out_dir / (template or config.OUTPUT_TEMPLATE)),
    ]
    if audio_only:
        if ffmpeg_available():
            command += ["--extract-audio", "--audio-quality", "0"]
        else:
            if not _ffmpeg_warned:
                logger.warning("ffmpeg not found: saving the raw audio stream without conversion")
                _ffmpeg_warned = True
            command += ["--format", "ba/b"]
    elif fmt:
        command += ["--format", fmt]
    if no_playlist:
        command.append("--no-playlist")
    command += ["--", url]

    files: List[str] = []
    errors: List[str] = []
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YtDlpError(f"could not launch yt-dlp: {exc}") from exc

    tasks: Dict[str, int] = {}
    with ui.download_progress() as progress:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if line.startswith(_PROGRESS_PREFIX + "|"):
                _update_progress(progress, tasks, line)
            elif line.startswith(_FILE_PREFIX + "|"):
                files.append(line.split("|", 1)[1])
            elif line.startswith("ERROR:"):
                errors.append(line[len("ERROR:"):].strip())
        process.wait()

    if process.returncode != 0 and not errors:
        errors.append(f"yt-dlp exited with status {process.returncode}")
    return DownloadResult(url=url, ok=process.returncode == 0, files=files, errors=errors)


def _update_progress(progress, tasks: Dict[str, int], line: str) -> None:
    parts = line.split("|", 6)
    if len(parts) < 7:
        return
    _, video_id, status, downloaded, total, total_estimate, title = parts
    completed = _as_float(downloaded)
    total_bytes = _as_float(total) or _as_float(total_estimate)
    if video_id not in tasks:
        description = _shorten(title if title not in ("", "NA") else video_id, 45)
        tasks[video_id] = progress.add_task(description, total=total_bytes)
    task_id = tasks[video_id]
    if status == "finished":
        final = total_bytes or completed or 0
        progress.update(task_id, completed=final, total=final or None)
    elif completed is not None:
        progress.update(task_id, completed=completed, total=total_bytes)


def _as_float(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shorten(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text.ljust(width)
    return text[: width - 1] + "…"


def _error_detail(stderr: str, target: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("ERROR:"):
            return line[len("ERROR:"):].strip()
    return lines[-1] if lines else f"yt-dlp failed for {target!r}"
