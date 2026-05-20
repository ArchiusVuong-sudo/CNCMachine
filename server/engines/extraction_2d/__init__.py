"""Engine 1 — 2D drawing extraction.

Public surface
--------------
::

    from server.engines.extraction_2d import run, DrawingExtraction

    extraction = await run(
        drawing_bytes,
        filename="my.pdf",
        on_event=bridge.as_callback(),
        on_thinking=bridge.as_thinking_callback(),
    )

The engine:
  1. Rasterizes the drawing (PDF or image) to base64 PNG pages.
  2. Streams each page through the VLM with retries.
  3. Merges per-page JSONs into a single :class:`DrawingExtraction`.
  4. Emits status / tool_result events through the optional ``on_event``
     callback so the orchestrator can bridge them into SSE.
"""
from __future__ import annotations

from ...core.schemas import DrawingExtraction
from .engine import run

__all__ = ["run", "DrawingExtraction"]
