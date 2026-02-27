"""
Module 2 — Production-grade structured logging configuration.

Usage:
    from module2.logging_config import get_logger
    logger = get_logger("worker")
    logger.info("event", extra={"reel_id": reel_id})
"""

from __future__ import annotations

import logging
import os
import sys


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | reel_id=%(reel_id)s | %(message)s"
)
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_DEFAULT_LEVEL = "INFO"

_CONFIGURED = False


class _ReelContextFilter(logging.Filter):
    """Inject a default reel_id into every record if not already present."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "reel_id"):
            record.reel_id = "-"  # type: ignore[attr-defined]
        return True


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", _DEFAULT_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    handler.addFilter(_ReelContextFilter())

    root = logging.getLogger("module2")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the module2 namespace."""
    _configure_root()
    return logging.getLogger(f"module2.{name}")
