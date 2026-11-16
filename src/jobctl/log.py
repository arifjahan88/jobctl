"""Console and run-file logging helpers for jobctl."""

from __future__ import annotations

import logging
from pathlib import Path
import sys


def setup_logger(verbose: bool = False) -> logging.Logger:
    """Configure the root `jobctl` console logger."""
    logger = logging.getLogger("jobctl")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    else:
        for h in logger.handlers:
            h.setLevel(logging.DEBUG if verbose else logging.INFO)

    return logger


def attach_file_handler(log_path: Path) -> logging.FileHandler:
    """Attach a per-run log file handler inside search_results/<YYYY-MM-DD>/."""
    logger = logging.getLogger("jobctl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    return fh
