"""Agentic-specific KB writeback (L0 session notes).

Per the locked rollout decision **"Never auto-write; expose a /v1/feedback
endpoint"**, this module never touches ``KNOWLEDGE_BASE/parts/`` or any
synthesised pattern file. The engine-neutral writers (full-result dump
that the FE detail view consumes, /v1/feedback persistence) now live in
:mod:`server.core.writeback` so the orchestrator and API routes don't
have to import from any one engine package.

What stays here is the agentic-only session-note dump
(:func:`write_session_note`): per-analysis diagnostic JSON capturing the
agent's ranked machines, fallback rungs, and per-phase iteration counts.
These dumps land in ``KNOWLEDGE_BASE/_research/notes/<analysis_id>.json``
and feed the FE history list via ``GET /v1/analyses``.

The writer is best-effort: filesystem errors log + return ``False``
rather than crashing the analysis or the API. Path validation is
inherited from :mod:`server.core.writeback`.

Backwards-compatible re-exports (``write_full_result``, ``write_feedback``,
``_ANALYSIS_ID_RE``, ``_NOTES_DIR``) are intentionally not provided —
callers must import those from :mod:`server.core.writeback` directly.
That coupling is what keeps ``server/engines/agentic/`` deletable
without taking the rest of the API down with it.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from ...core.writeback import _NOTES_DIR, _ensure_dir, _safe_id

logger = logging.getLogger("cncserver.engines.agentic.writeback")


def _summarize_plan(plan_dict: dict) -> dict:
    """Distill a :class:`ProcessPlan` dump into a session-note payload.

    Keeps the diagnostically useful bits (machine class, analogues,
    fallback rungs, iterations) and drops anything heavy (catalog
    snapshot, full G-code). The point is a fast skim for the human
    reviewer, not a complete archive.
    """
    components = plan_dict.get("components") or []
    notes_components: list[dict] = []
    for comp in components:
        agentic = (comp or {}).get("agentic") or {}
        notes_components.append({
            "component_index": comp.get("component_index"),
            "name": comp.get("name"),
            "part_type": comp.get("part_type"),
            "material": comp.get("material"),
            "machine_class": agentic.get("machine_class"),
            "chosen_machine_id": agentic.get("chosen_machine_id"),
            "ranked_machines": [
                {"rank": m.get("rank"), "machine_id": m.get("machine_id"),
                 "machine_name": m.get("machine_name"), "score": m.get("score")}
                for m in (agentic.get("ranked_machines") or [])
            ],
            "total_run_min_per_part": agentic.get("total_run_min_per_part"),
            "setup_min_per_lot": agentic.get("setup_min_per_lot"),
            "analogues_used": agentic.get("analogues_used"),
            "fallback_rungs": agentic.get("fallback_rungs"),
            "iterations_by_phase": agentic.get("iterations_by_phase"),
            "tool_call_count_by_phase": agentic.get("tool_call_count_by_phase"),
        })
    cost = plan_dict.get("cost") or {}
    return {
        "components": notes_components,
        "total_usd": cost.get("total_usd"),
        "n_components": len(components),
        "n_routing_rows": sum(
            len(rows or []) for rows in (plan_dict.get("processes_per_component") or [])
        ),
    }


def write_session_note(
    analysis_id: str,
    plan_dict: dict[str, Any],
    *,
    extra: dict | None = None,
) -> bool:
    """Write a diagnostic session note for one analysis. Returns success."""
    safe = _safe_id(analysis_id)
    if not safe:
        logger.warning("writeback: rejected analysis_id %r", analysis_id)
        return False
    if not _ensure_dir(_NOTES_DIR):
        return False
    payload = {
        "analysis_id": safe,
        "written_at_epoch": time.time(),
        "summary": _summarize_plan(plan_dict or {}),
    }
    if extra:
        payload["extra"] = extra
    target = _NOTES_DIR / f"{safe}.json"
    try:
        target.write_text(
            json.dumps(payload, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("writeback: session-note write failed (%s)", exc)
        return False
    logger.info("writeback: session note saved → %s", target)
    return True


__all__ = ["write_session_note"]
