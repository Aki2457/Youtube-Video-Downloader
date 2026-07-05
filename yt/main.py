"""Entry point: first-run dependency bootstrap, then CLI dispatch."""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
from typing import List, Optional, Sequence

from yt import config, logger


def _missing_packages() -> List[str]:
    return [
        pip_name
        for import_name, pip_name in config.REQUIRED_PACKAGES.items()
        if importlib.util.find_spec(import_name) is None
    ]


def _bootstrap() -> None:
    """Install missing dependencies into the current interpreter (venv-aware).

    Set YT_NO_BOOTSTRAP=1 to disable the automatic install entirely.
    """
    if os.environ.get("YT_NO_BOOTSTRAP"):
        return
    missing = _missing_packages()
    if not missing:
        return
    logger.info(f"First run: installing missing dependencies: {', '.join(missing)}")
    command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *missing]
    try:
        subprocess.check_call(command)
    except (OSError, subprocess.CalledProcessError):
        logger.error("Automatic dependency install failed")
        logger.error(f"Install manually with: {sys.executable} -m pip install {' '.join(missing)}")
        raise SystemExit(1)
    importlib.invalidate_caches()
    still_missing = _missing_packages()
    if still_missing:
        logger.error(f"Dependencies still missing after install: {', '.join(still_missing)}")
        raise SystemExit(1)
    logger.info("Dependencies installed")


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        _bootstrap()
        from yt import cli  # imported after bootstrap so third-party deps exist

        return cli.run(argv)
    except KeyboardInterrupt:
        logger.fail("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
