"""FastAPI surface for the modular monolith.

The :func:`create_app` factory wires routers and CORS; ``server.main``
imports it to start uvicorn. Keep this module thin — every route lives
under :mod:`server.api.routes`.
"""
from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
