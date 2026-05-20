"""SSE pipeline orchestrator — wires the three engines together.

The orchestrator owns the SSE-stream contract: it consumes URLs (or raw
bytes), spins up the engines in the right concurrency pattern (engines 1
+ 2 in parallel, then engine 3), bridges their ``on_event`` callbacks
into a single async-generator of ``(event_type, data)`` tuples, and
writes a per-analysis JSON trace.

Public surface::

    from server.pipeline import run_pipeline

    async for ev_type, data in run_pipeline(
        analysis_id="…",
        drawing_url="https://…",
        step_url="https://…",
        file_name="example.step",
    ):
        ...  # forward to SSE client
"""
from __future__ import annotations

from .orchestrator import run_pipeline

__all__ = ["run_pipeline"]
