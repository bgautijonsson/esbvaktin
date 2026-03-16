"""Structured logging for the ESBvaktin pipeline.

Configures per-analysis and per-export log files alongside console output.
"""

import logging
import sys
from pathlib import Path

_CONFIGURED = False


def setup_pipeline_logging(
    work_dir: Path,
    *,
    name: str = "esbvaktin",
    log_filename: str = "pipeline.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure logging for an analysis pipeline run.

    Writes to both console (INFO) and a file in work_dir (DEBUG).
    Safe to call multiple times — handlers are only added once per work_dir.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers
    log_path = work_dir / log_filename
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and h.baseFilename == str(log_path):
            return logger

    # File handler — captures everything (DEBUG+)
    work_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(fh)

    # Console handler — only if not already present
    if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers):
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logger.addHandler(ch)

    return logger


def setup_export_logging(
    export_dir: Path,
    *,
    name: str = "esbvaktin.export",
    log_filename: str = "export.log",
) -> logging.Logger:
    """Configure logging for export pipeline runs.

    Appends to a single export.log in the export directory.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    log_path = export_dir / log_filename
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and h.baseFilename == str(log_path):
            return logger

    export_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_path, encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(fh)

    if not any(isinstance(h, logging.StreamHandler) and h.stream == sys.stderr for h in logger.handlers):
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logger.addHandler(ch)

    return logger
