"""Logging setup — one place to configure the root logger."""
from __future__ import annotations

import logging
import os

_CONFIGURED = False

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(level: str | int | None = None) -> None:
    """Idempotent logger setup. Honours the `LOG_LEVEL` env var."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    logging.basicConfig(level=level, format=_DEFAULT_FORMAT)
    # Quiet down libraries that spam INFO logs by default.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a named child of the `cncserver` logger tree."""
    if not name.startswith("cncserver"):
        name = f"cncserver.{name}"
    return logging.getLogger(name)
