"""Terminal-UI primitives: arrow-key navigation and checkbox selection.

Provides two building blocks used by the interactive guided mode:

* ``render_markdown_table`` – format a list of dicts as a Markdown table
  printed to the console.
* ``CheckboxMenu`` – a raw-terminal checkbox picker that renders items as

      [ ] Option A
      [X] Option B   ← selected
      [ ] Option C

  Navigation: UP/DOWN arrows move the cursor, SPACE toggles selection,
  ENTER confirms, 'q' / ESC / Ctrl-C aborts.

Both helpers are TTY-aware and fall back gracefully when stdin is not a
terminal (e.g. when the tool is piped into another process).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── Rich imports (always available after bootstrap) ─────────────────────────
from rich.console import Console
from rich.text import Text

console = Console(highlight=False)
_err = Console(stderr=True, highlight=False)

# ── Markdown-table rendering ─────────────────────────────────────────────────

def render_markdown_table(
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[Tuple[str, str]],   # [(header, key), ...]
    *,
    title: Optional[str] = None,
) -> None:
    """Print a Markdown-formatted table to stdout.

    ``columns`` is a list of ``(header_label, dict_key)`` pairs that define
    the column order and headings.  Missing keys render as ``-``.

    Example output::

        | # | Title          | Channel   | Duration | Views |
        |---|----------------|-----------|----------|-------|
        | 1 | Never Gonna…   | RickA     | 3:32     | 1.4B  |
    """
    if title:
        console.print(f"\n**{title}**\n", markup=True)

    # Build cell text for every row first so we can compute column widths.
    headers = [col[0] for col in columns]
    keys    = [col[1] for col in columns]

    table_rows: List[List[str]] = []
    for row in rows:
        table_rows.append([str(row.get(k, "-") or "-") for k in keys])

    widths = [len(h) for h in headers]
    for row in table_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def _fmt_row(cells: List[str]) -> str:
        parts = [f" {c:<{widths[i]}} " for i, c in enumerate(cells)]
        return "|" + "|".join(parts) + "|"

    separator = "|" + "|".join("-" * (w + 2) for w in widths) + "|"

    console.print(_fmt_row(headers))
    console.print(separator)
    for row in table_rows:
        console.print(_fmt_row(row))
    console.print()


# ── Raw-terminal helpers ─────────────────────────────────────────────────────

def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


if sys.platform == "win32":
    import msvcrt  # type: ignore[import]

    def _getch() -> bytes:
        ch = msvcrt.getwch()
        if isinstance(ch, str):
            ch = ch.encode("utf-8", errors="replace")
        return ch

    def _read_key() -> str:
        """Return a logical key name from a raw keypress."""
        ch = _getch()
        if ch in (b"\xe0", b"\x00"):          # escape prefix for arrow keys
            second = _getch()
            return {b"H": "UP", b"P": "DOWN"}.get(second, "")
        if ch == b"\r":
            return "ENTER"
        if ch == b" ":
            return "SPACE"
        if ch in (b"\x1b", b"q", b"Q"):
            return "QUIT"
        if ch == b"\x03":
            raise KeyboardInterrupt
        return ch.decode("utf-8", errors="replace")

else:
    import termios  # type: ignore[import]
    import tty      # type: ignore[import]

    def _read_key() -> str:
        """Return a logical key name from a raw ANSI keypress."""
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                # Peek for an ANSI escape sequence (e.g. arrow keys).
                rest = os.read(fd, 2)
                mapping = {
                    b"[A": "UP",
                    b"[B": "DOWN",
                    b"[C": "RIGHT",
                    b"[D": "LEFT",
                }
                return mapping.get(rest, "ESC")
            if ch == b"\r" or ch == b"\n":
                return "ENTER"
            if ch == b" ":
                return "SPACE"
            if ch in (b"q", b"Q", b"\x1b"):
                return "QUIT"
            if ch == b"\x03":
                raise KeyboardInterrupt
            return ch.decode("utf-8", errors="replace")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ── Checkbox menu ────────────────────────────────────────────────────────────

class CheckboxMenu:
    """Arrow-key driven, multi-select checkbox menu.

    Items are displayed as::

        [ ] Label A
        [X] Label B
        [ ] Label C

    The cursor line is highlighted.  SPACE toggles the checkbox, ENTER
    confirms the selection.  Returns a list of the *original* items that
    were checked (same type as the input list).

    Parameters
    ----------
    items:
        The items to display.  Pass ``labels`` if you want custom display
        strings; otherwise ``str(item)`` is used.
    labels:
        Optional human-readable labels, one per item.  Must be the same
        length as *items* when provided.
    prompt:
        Text printed above the menu.
    select_all:
        Pre-select all items when ``True``.
    """

    _CURSOR   = "▶"
    _NOCURSOR = " "
    _CHECKED  = "[X]"
    _EMPTY    = "[ ]"

    def __init__(
        self,
        items: Sequence[Any],
        *,
        labels: Optional[Sequence[str]] = None,
        prompt: str = "Select items  (↑↓ move · SPACE toggle · ENTER confirm · q quit)",
        select_all: bool = False,
    ) -> None:
        self.items   = list(items)
        self.labels  = list(labels) if labels else [str(it) for it in items]
        self.prompt  = prompt
        self.checked: List[bool] = [select_all] * len(self.items)
        self.cursor  = 0

    # -- public API ----------------------------------------------------------

    def run(self) -> List[Any]:
        """Display the menu and return the selected items."""
        if not self.items:
            return []
        if not _is_tty():
            # Non-interactive: return everything.
            return list(self.items)

        console.print(f"\n[bold]{self.prompt}[/bold]\n", markup=True)
        self._render()

        try:
            while True:
                key = _read_key()
                if key == "UP":
                    self.cursor = (self.cursor - 1) % len(self.items)
                elif key == "DOWN":
                    self.cursor = (self.cursor + 1) % len(self.items)
                elif key == "SPACE":
                    self.checked[self.cursor] = not self.checked[self.cursor]
                elif key == "ENTER":
                    self._clear()
                    break
                elif key in ("QUIT", "ESC"):
                    self._clear()
                    return []
                self._update()
        except KeyboardInterrupt:
            self._clear()
            return []

        return [item for item, sel in zip(self.items, self.checked) if sel]

    # -- rendering -----------------------------------------------------------

    def _lines(self) -> List[str]:
        lines = []
        for i, label in enumerate(self.labels):
            mark   = self._CHECKED if self.checked[i] else self._EMPTY
            cursor = self._CURSOR  if i == self.cursor  else self._NOCURSOR
            lines.append(f"  {cursor} {mark} {label}")
        return lines

    def _render(self) -> None:
        for line in self._lines():
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
        self._n_lines = len(self.items)

    def _clear(self) -> None:
        """Move the cursor back up and erase the drawn lines."""
        n = getattr(self, "_n_lines", 0)
        for _ in range(n):
            sys.stdout.write("\x1b[1A\x1b[2K")
        sys.stdout.flush()
        self._n_lines = 0

    def _update(self) -> None:
        self._clear()
        self._render()


# ── Convenience wrapper ──────────────────────────────────────────────────────

def pick(
    items: Sequence[Any],
    *,
    labels: Optional[Sequence[str]] = None,
    prompt: str = "Select items  (↑↓ move · SPACE toggle · ENTER confirm · q quit)",
) -> List[Any]:
    """Show a checkbox menu and return the chosen items."""
    menu = CheckboxMenu(items, labels=labels, prompt=prompt)
    return menu.run()
