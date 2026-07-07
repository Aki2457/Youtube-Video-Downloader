"""Centralized logging for the yt CLI.

Every log line follows the exact format (capitalization and spacing are part
of the contract):

    [ INFO ] message
    [ Warning ] message
    [ ERROR ] message
    [ X ] message

Tags are colorized when Rich is available; the text itself is never altered.
All log output goes to stderr so stdout stays clean for data (tables, JSON),
keeping the tool pipe-friendly.
"""
from __future__ import annotations

import sys

try:
    from rich.console import Console
    from rich.text import Text

    _console = Console(stderr=True, highlight=False, soft_wrap=True)
except ImportError:  # pragma: no cover - only hit before the first-run bootstrap
    _console = None
    Text = None  # type: ignore[assignment]

_STYLES = {
    "[ INFO ]": "bold cyan",
    "[ Warning ]": "bold yellow",
    "[ ERROR ]": "bold red",
    "[ X ]": "bold red",
}


def _log(tag: str, message: object) -> None:
    if _console is None:
        print(f"{tag} {message}", file=sys.stderr)
        return
    line = Text()
    line.append(tag, style=_STYLES[tag])
    line.append(" ")
    line.append(str(message))
    _console.print(line)


def info(message: object) -> None:
    _log("[ INFO ]", message)


def warning(message: object) -> None:
    _log("[ Warning ]", message)


def error(message: object) -> None:
    _log("[ ERROR ]", message)


def fail(message: object) -> None:
    _log("[ X ]", message)
