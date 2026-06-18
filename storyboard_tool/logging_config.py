from __future__ import annotations

import logging
from pathlib import Path

_LOG_DIR = Path.home() / ".storyboard_tool" / "logs"
LOG_FILE: Path = _LOG_DIR / "storyboard_tool.log"

_FMT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"


def setup_logging(log_file: Path | None = None) -> None:
    """Configure structured file + console logging for the storyboard_tool package.

    Safe to call multiple times ? skips setup if the logger already has handlers.
    The file handler writes DEBUG+ to the log file; the console handler emits
    WARNING+ only, so debug noise never reaches the terminal.
    """
    logger = logging.getLogger("storyboard_tool")
    if logger.handlers:
        return

    logger.setLevel(logging.DEBUG)

    target = log_file if log_file is not None else LOG_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(target, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
        logger.addHandler(fh)
    except OSError:
        pass  # read-only filesystem or permission denied ? skip file handler

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s storyboard_tool: %(message)s"))
    logger.addHandler(ch)
