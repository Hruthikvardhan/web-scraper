"""Central logging configuration: everything is written to data/scraper.log."""

from __future__ import annotations

import logging
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOG_FILE = DATA_DIR / "scraper.log"
_ROOT_NAME = "webscraper"
_configured = False


def get_logger(name: str = "scraper") -> logging.Logger:
    """Return a child logger that writes timestamped lines to the log file.

    The file handler is attached only once, no matter how many times this
    function is called.

    Args:
        name: Short name shown in each log line (usually the class name).

    Returns:
        A configured ``logging.Logger``.
    """
    global _configured
    if not _configured:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        root = logging.getLogger(_ROOT_NAME)
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        root.propagate = False  # keep log noise out of the console
        _configured = True
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
