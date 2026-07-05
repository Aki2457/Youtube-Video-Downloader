"""Shared helpers: text parsing, JSON persistence, sizes, clipboard, archives."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union

PathLike = Union[str, Path]

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ").,;]"


def extract_urls(text: str) -> List[str]:
    """Return unique URLs found in *text*, preserving first-seen order."""
    seen = set()
    urls: List[str] = []
    for match in _URL_RE.findall(text or ""):
        url = match.rstrip(_TRAILING_PUNCTUATION)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def read_stdin_or_clipboard() -> str:
    """Return text from stdin when piped, otherwise from the system clipboard."""
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return read_clipboard()


_CLIPBOARD_COMMANDS = {
    "darwin": [["pbpaste"]],
    "win32": [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]],
}
# Linux and other unixes: try Wayland first, then the X11 tools.
_UNIX_CLIPBOARD_COMMANDS = [
    ["wl-paste", "--no-newline"],
    ["xclip", "-selection", "clipboard", "-o"],
    ["xsel", "--clipboard", "--output"],
]


def read_clipboard() -> str:
    """Best-effort clipboard read via native tools; returns "" when unavailable."""
    commands = _CLIPBOARD_COMMANDS.get(sys.platform, _UNIX_CLIPBOARD_COMMANDS)
    for command in commands:
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout
    return ""


def read_json(path: PathLike, default: Any) -> Any:
    """Load JSON from *path*, returning *default* when missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def atomic_write_json(path: PathLike, data: Any) -> None:
    """Write JSON atomically (temp file + rename) so state never half-writes."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp_name, str(target))
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def human_size(num_bytes: Optional[float]) -> str:
    """1536 -> '1.50 KiB'; None -> '-'."""
    if num_bytes is None:
        return "-"
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return "-"  # pragma: no cover - unreachable


def human_duration(seconds: Optional[float]) -> str:
    """125 -> '2:05'; 3725 -> '1:02:05'; None -> '-'."""
    if seconds is None:
        return "-"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def human_count(num: Optional[float]) -> str:
    """1234567 -> '1.2M'; None -> '-'."""
    if num is None:
        return "-"
    value = float(num)
    for suffix, factor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if value >= factor:
            scaled = f"{value / factor:.1f}".rstrip("0").rstrip(".")
            return f"{scaled}{suffix}"
    return str(int(value))


def make_zip(files: Iterable[PathLike], dest: PathLike) -> int:
    """Zip existing *files* (flat, deduplicated names) into *dest*; return count."""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    used_names = set()
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for item in files:
            path = Path(item)
            if not path.is_file():
                continue
            arcname = path.name
            suffix = 1
            while arcname in used_names:
                arcname = f"{path.stem} ({suffix}){path.suffix}"
                suffix += 1
            used_names.add(arcname)
            archive.write(path, arcname)
            count += 1
    return count


def short_id() -> str:
    return uuid.uuid4().hex[:8]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
