"""Shared Rich console, theme, and rendering primitives.

All *data* output (tables, panels, progress) goes to stdout through `console`;
diagnostic log lines go to stderr via `yt.logger`. Every visual element in the
CLI is built from these helpers so the whole tool shares one look.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple, Union

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

ACCENT = "red"
MUTED = "bright_black"

_THEME = Theme(
    {
        "accent": f"bold {ACCENT}",
        "muted": MUTED,
        "ok": "bold green",
        "warn": "bold yellow",
        "bad": "bold red",
    }
)

console = Console(theme=_THEME, highlight=False)

_STATUS_STYLES = {
    "pending": "yellow",
    "done": "green",
    "failed": "red",
}

ColumnSpec = Union[str, dict]


def table(*columns: ColumnSpec, title: Optional[str] = None) -> Table:
    """A Table with the shared look: rounded box, dim borders, bold headers.

    Columns are either a header string or a dict of Table.add_column kwargs.
    """
    result = Table(
        box=box.ROUNDED,
        border_style=MUTED,
        header_style="bold",
        title=title,
        title_style="bold",
        title_justify="left",
        padding=(0, 1),
    )
    for column in columns:
        if isinstance(column, dict):
            result.add_column(**column)
        else:
            result.add_column(column)
    return result


def kv_panel(
    title: str,
    rows: Iterable[Tuple[str, object]],
    *,
    subtitle: Optional[str] = None,
) -> Panel:
    """A titled panel of aligned key/value rows (used by `yt info`)."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")
    for key, value in rows:
        if value in (None, "", "-"):
            continue
        grid.add_row(key, Text(str(value)))
    return Panel(
        grid,
        title=Text(title, style="accent"),
        title_align="left",
        subtitle=Text(subtitle, style="muted") if subtitle else None,
        subtitle_align="left",
        border_style=MUTED,
        padding=(0, 1),
    )


def status_text(status: str) -> Text:
    return Text(status, style=_STATUS_STYLES.get(status, "white"))


def download_progress() -> Progress:
    """The live multi-bar progress display used for every download."""
    return Progress(
        SpinnerColumn(style="accent", finished_text=Text("✓", style="ok")),
        TextColumn("{task.description}", markup=False),
        BarColumn(bar_width=28, style=MUTED, complete_style=ACCENT, finished_style="green"),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
        console=console,
        transient=False,
    )


def summary_line(done: int, failed: int, *, noun: str = "item") -> Text:
    """A compact colored 'N done / M failed' summary."""
    plural = "" if done == 1 else "s"
    text = Text()
    text.append("Summary: ", style="bold")
    text.append(f"{done} {noun}{plural} done", style="ok" if done else "muted")
    if failed:
        text.append("  ·  ", style="muted")
        text.append(f"{failed} failed", style="bad")
    return text


def hint(message: str) -> None:
    """A dim single-line usage hint printed under empty states."""
    console.print(Text(message, style="muted"))
