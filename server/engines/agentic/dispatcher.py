"""Agentic-engine dispatcher.

Thin entry point in front of :func:`server.engines.agentic.coordinator.run`.
Originally this routed between ``stub`` (rule-based), ``true`` (LLM), and
``shadow`` (both) backends; per the locked rollout decision **"Agent
only, no fallback"** the rule-based engine has been removed and only the
LLM coordinator remains.

The dispatcher still exists (rather than callers importing the
coordinator directly) so that:

  * the session-note writeback runs at exactly one place per analysis;
  * a future planner backend can be slotted back in via this seam
    without touching the orchestrator.
"""
from __future__ import annotations

import logging
from typing import Any

from ...core.events import OnEvent, safe_emit
from ...core.schemas import AssemblyData, DrawingExtraction, ProcessPlan
from .coordinator import run as run_coordinator
from .writeback import write_session_note

logger = logging.getLogger("cncserver.engines.agentic")


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
) -> ProcessPlan:
    """Run the LLM coordinator and persist the session note."""
    logger.info("agentic.dispatch: analysis_id=%s", analysis_id or "-")
    await safe_emit(on_event, "status", {
        "title":   "Process Planner",
        "message": "Agentic engine (LLM coordinator)",
    })

    plan = await run_coordinator(
        drawing, assembly, step_bytes,
        batch_size=batch_size,
        user_id=user_id,
        supabase_client=supabase_client,
        catalog=catalog,
        on_event=on_event,
        forced_assembly_part_type=forced_assembly_part_type,
        analysis_id=analysis_id,
    )
    if analysis_id:
        try:
            write_session_note(analysis_id, plan.as_dict())
        except Exception as exc:  # noqa: BLE001 — writeback is best-effort
            logger.warning("agentic: session-note write skipped (%s)", exc)
    return plan
