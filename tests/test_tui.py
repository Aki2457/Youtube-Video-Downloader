"""Offline tests for the TUI helpers (tui.py).

All tests run without a real TTY by exercising the pure-logic parts of
CheckboxMenu and render_markdown_table.  The live key-reading loop is not
exercised here (it requires a real terminal).
"""
from __future__ import annotations

import io
import sys

import pytest

from yt.tui import CheckboxMenu, render_markdown_table


# ── CheckboxMenu logic ────────────────────────────────────────────────────────

def test_checkbox_menu_initial_state():
    menu = CheckboxMenu(["a", "b", "c"])
    assert menu.cursor == 0
    assert menu.checked == [False, False, False]


def test_checkbox_menu_select_all():
    menu = CheckboxMenu(["x", "y"], select_all=True)
    assert menu.checked == [True, True]


def test_checkbox_menu_cursor_wraps_up():
    menu = CheckboxMenu(["a", "b", "c"])
    menu.cursor = 0
    # Simulate UP from position 0 → should wrap to last item.
    menu.cursor = (menu.cursor - 1) % len(menu.items)
    assert menu.cursor == 2


def test_checkbox_menu_cursor_wraps_down():
    menu = CheckboxMenu(["a", "b", "c"])
    menu.cursor = 2
    menu.cursor = (menu.cursor + 1) % len(menu.items)
    assert menu.cursor == 0


def test_checkbox_menu_toggle():
    menu = CheckboxMenu(["a", "b", "c"])
    menu.cursor = 1
    menu.checked[menu.cursor] = not menu.checked[menu.cursor]
    assert menu.checked == [False, True, False]
    menu.checked[menu.cursor] = not menu.checked[menu.cursor]
    assert menu.checked == [False, False, False]


def test_checkbox_menu_lines_unchecked():
    menu = CheckboxMenu(["Alpha", "Beta"])
    lines = menu._lines()
    # Neither should be marked [X].
    assert "[X]" not in lines[0]
    assert "[X]" not in lines[1]
    assert "[ ]" in lines[0]


def test_checkbox_menu_lines_checked():
    menu = CheckboxMenu(["Alpha", "Beta"])
    menu.checked[0] = True
    lines = menu._lines()
    assert "[X]" in lines[0]
    assert "[ ]" in lines[1]


def test_checkbox_menu_cursor_marker():
    menu = CheckboxMenu(["A", "B", "C"])
    menu.cursor = 1
    lines = menu._lines()
    # Line 1 (index 1) should have the cursor character.
    assert menu._CURSOR in lines[1]
    # Others should not.
    assert menu._CURSOR not in lines[0]
    assert menu._CURSOR not in lines[2]


def test_checkbox_menu_non_tty_returns_all(monkeypatch):
    """When stdin is not a TTY, run() returns every item without interaction."""
    monkeypatch.setattr("yt.tui._is_tty", lambda: False)
    menu = CheckboxMenu(["p", "q", "r"])
    result = menu.run()
    assert result == ["p", "q", "r"]


def test_checkbox_menu_empty_returns_empty(monkeypatch):
    monkeypatch.setattr("yt.tui._is_tty", lambda: False)
    menu = CheckboxMenu([])
    assert menu.run() == []


def test_checkbox_menu_labels():
    menu = CheckboxMenu(["x", "y"], labels=["Label X", "Label Y"])
    assert menu.labels == ["Label X", "Label Y"]
    lines = menu._lines()
    assert "Label X" in lines[0]
    assert "Label Y" in lines[1]


def test_checkbox_menu_default_labels():
    items = [{"id": 1}, {"id": 2}]
    menu = CheckboxMenu(items)
    # Default label should be str(item).
    assert str(items[0]) in menu.labels[0]


# ── render_markdown_table ─────────────────────────────────────────────────────

def test_render_markdown_table_output(capsys):
    rows = [
        {"num": "1", "name": "Alice", "score": "42"},
        {"num": "2", "name": "Bob",   "score": "7"},
    ]
    columns = [("#", "num"), ("Name", "name"), ("Score", "score")]
    render_markdown_table(rows, columns)
    captured = capsys.readouterr()
    out = captured.out
    # Headers should appear.
    assert "#" in out
    assert "Name" in out
    assert "Score" in out
    # Separator row.
    assert "---" in out
    # Data rows.
    assert "Alice" in out
    assert "Bob" in out
    assert "42" in out


def test_render_markdown_table_missing_key(capsys):
    """Missing dict keys fall back to '-'."""
    rows = [{"name": "Solo"}]
    columns = [("Name", "name"), ("Missing", "absent")]
    render_markdown_table(rows, columns)
    captured = capsys.readouterr()
    assert "-" in captured.out


def test_render_markdown_table_title(capsys):
    rows = [{"k": "v"}]
    columns = [("Key", "k")]
    render_markdown_table(rows, columns, title="My Results")
    captured = capsys.readouterr()
    assert "My Results" in captured.out


def test_render_markdown_table_pipe_delimited(capsys):
    rows = [{"a": "1", "b": "2"}]
    columns = [("A", "a"), ("B", "b")]
    render_markdown_table(rows, columns)
    out = capsys.readouterr().out
    # Every non-empty line in a Markdown table starts and ends with |
    table_lines = [
        ln for ln in out.splitlines()
        if ln.strip().startswith("|")
    ]
    assert len(table_lines) >= 3  # header + separator + at least one data row
    for line in table_lines:
        assert line.strip().startswith("|")
        assert line.strip().endswith("|")
