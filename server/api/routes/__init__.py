"""API route packages — each module owns one logical surface area.

  * :mod:`.analyze` — /v1/analyze-stream (the main SSE pipeline).
  * :mod:`.health`  — /v1/health (liveness + dependency probes).
"""
from __future__ import annotations

from . import analyze, health

__all__ = ["analyze", "health"]
