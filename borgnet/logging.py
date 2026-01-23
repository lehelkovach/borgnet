"""Centralized logging configuration for BorgNet."""

from __future__ import annotations

import logging
import sys
from typing import Optional


# Default format includes timestamp, level, module, and message
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a BorgNet module."""
    return logging.getLogger(f"borgnet.{name}")


def configure_logging(
    level: int | str = logging.INFO,
    fmt: Optional[str] = None,
    datefmt: Optional[str] = None,
    stream: Optional[object] = None,
) -> None:
    """
    Configure the root borgnet logger.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        fmt: Log format string
        datefmt: Date format string
        stream: Output stream (defaults to stderr)
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger("borgnet")
    root_logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt=fmt or DEFAULT_FORMAT,
            datefmt=datefmt or DEFAULT_DATE_FORMAT,
        )
    )
    root_logger.addHandler(handler)


def set_level(level: int | str) -> None:
    """Set the log level for all borgnet loggers."""
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    logging.getLogger("borgnet").setLevel(level)


# Log level constants for convenience
DEBUG = logging.DEBUG
INFO = logging.INFO
WARNING = logging.WARNING
ERROR = logging.ERROR
CRITICAL = logging.CRITICAL
