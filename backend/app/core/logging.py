"""Logging configuration."""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_CONFIGURED = False


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_JSON:
        try:
            from pythonjsonlogger import jsonlogger

            handler.setFormatter(
                jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
        except ImportError:  # pragma: no cover - optional dependency
            handler.setFormatter(_plain_formatter())
    else:
        handler.setFormatter(_plain_formatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # Ultralytics is extremely chatty at INFO level, one line per inference.
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    _CONFIGURED = True


def _plain_formatter() -> logging.Formatter:
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
