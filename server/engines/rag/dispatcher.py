"""RAG-engine dispatcher.

Thin entry point in front of :func:`server.engines.rag.coordinator.run`,
matching the public signature of :func:`server.engines.agentic.dispatcher.dispatch`
byte-for-byte so the pipeline orchestrator can swap engines via a
single ``if/elif`` block.

We keep this seam (rather than letting callers import the coordinator
directly) so that:

  * the engine emits a consistent "engine started" status event before
    handing off to the coordinator;
  * a future writeback / evaluation-row insert can be slotted in at a
    single, deletable place.
"""
from __future__ import annotations

import logging
from typing import Any

from ...core.events import OnEvent, safe_emit
from ...core.schemas import AssemblyData, DrawingExtraction, ProcessPlan
from .coordinator import run as run_coordinator

logger = logging.getLogger("cncserver.engines.rag")


async def dispatch(
    drawing: DrawingExtraction,
    assembly: AssemblyData,
    step_bytes: bytes,
    *,
    batch_size: int = 1,
    user_id: str | None = None,
    supabase_client: Any = None,
    catalog: dict | None = None,
    on_event: OnEvent = None,
    forced_assembly_part_type: str | None = None,
    analysis_id: str | None = None,
    model: str | None = None,
) -> ProcessPlan:
    """Run the RAG coordinator.

    ``model`` is accepted for parity with the agentic dispatcher and
    forwarded to the per-component LLM call. ``None`` keeps the server
    default (typically OpenRouter's ``openrouter_default_model``).
    """
    logger.info(
        "rag.dispatch: analysis_id=%s model=%s",
        analysis_id or "-", model or "<default>",
    )
    await safe_emit(on_event, "status", {
        "title":   "Process Planner",
        "message": "RAG engine (one-shot LLM, pgvector retrieval)",
    })

    return await run_coordinator(
        drawing, assembly, step_bytes,
        batch_size=batch_size,
        user_id=user_id,
        supabase_client=supabase_client,
        catalog=catalog,
        on_event=on_event,
        forced_assembly_part_type=forced_assembly_part_type,
        analysis_id=analysis_id,
        model=model,
    )


__all__ = ["dispatch"]
