"""Paths, constants, and defaults for the yt CLI.

This module must stay import-light (stdlib only): it is loaded by the
first-run bootstrap before third-party dependencies are guaranteed to exist.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "yt"

# Persistent application state. YT_HOME overrides the location (used by tests
# and by users who want the state somewhere else, e.g. a synced folder).
APP_DIR = Path(os.environ.get("YT_HOME", str(Path.home() / ".yt")))
BATCH_FILE = APP_DIR / "batch.json"
HISTORY_FILE = APP_DIR / "history.json"

# Downloads land under the current working directory by default.
DEFAULT_OUTPUT_DIR = Path("downloads")
OUTPUT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
# Used with --quality all so each format gets a distinct filename.
OUTPUT_TEMPLATE_ALL = "%(title)s [%(id)s].f%(format_id)s.%(ext)s"

QUALITY_CHOICES = ("best", "worst", "all", "custom")

# yt-dlp format selectors for the --quality presets. Merging separate video
# and audio streams requires ffmpeg; the NO_FFMPEG table is the graceful
# fallback when it is not installed.
QUALITY_FORMATS = {
    "best": "bv*+ba/b",
    "worst": "wv*+wa/w",
    "all": "all",
}
QUALITY_FORMATS_NO_FFMPEG = {
    "best": "b",
    "worst": "w",
    "all": "all",
}

DEFAULT_SEARCH_LIMIT = 10

HTTP_TIMEOUT = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# import name -> pip package name, checked by the first-run bootstrap.
REQUIRED_PACKAGES = {
    "yt_dlp": "yt-dlp",
    "rich": "rich",
    "questionary": "questionary",
    "requests": "requests",
}
