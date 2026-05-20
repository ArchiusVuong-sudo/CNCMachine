"""SSE wire-format serialization.

A FastAPI route hands the orchestrator's ``(event_type, data)`` tuples
into :func:`format_sse_frame` which emits the canonical ``event: …\\ndata: …\\n\\n``
frames the browser ``EventSource`` API consumes. ``data`` is JSON-encoded
with ``ensure_ascii=False`` so we can carry non-ASCII characters (mm
arrows, degree signs) without escaping.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from ..core.schemas import SSEEvent  # noqa: F401  — re-exported for typing

logger = logging.getLogger("cncserver.api.sse")


def format_sse_frame(event_type: str, data: dict[str, Any]) -> bytes:
    """Encode one ``(event_type, data)`` pair into an SSE frame."""
    try:
        payload = json.dumps(data, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.warning("format_sse_frame: json dump failed (%s) — emitting empty payload", exc)
        payload = "{}"
    return f"event: {event_type}\ndata: {payload}\n\n".encode("utf-8")


async def stream_to_sse(
    events: AsyncIterator[tuple[str, dict]],
) -> AsyncIterator[bytes]:
    """Wrap an async iterator of pipeline events into SSE-framed bytes."""
    async for ev_type, data in events:
        yield format_sse_frame(ev_type, data)
