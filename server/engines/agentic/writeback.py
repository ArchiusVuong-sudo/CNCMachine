"""KB writeback for the agentic engine.

Per the locked rollout decision **"Never auto-write; expose a /v1/feedback
endpoint"**, this module never touches ``KNOWLEDGE_BASE/parts/`` or any
synthesised pattern file. It writes two kinds of files only:

  * **L0 session notes** — :func:`write_session_note` dumps a per-analysis
    diagnostic JSON (analogues consulted, fallback rungs, iterations
    used). Lands in ``KNOWLEDGE_BASE/_research/notes/<analysis_id>.json``.
    These are scratch traces; a human reviewer harvests them into real
    patterns/parts content only if they spot a useful signal.

  * **Operator feedback** — :func:`write_feedback` lands the payload from
    the ``POST /v1/feedback`` endpoint at
    ``KNOWLEDGE_BASE/_research/feedback/<analysis_id>.json``.

Both writers are best-effort: filesystem errors log + return ``False``
rather than crashing the analysis or the API. Path validation ensures
writes can never escape ``_research/``.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("cncserver.engines.agentic.writeback")

# writeback.py → agentic → engines → server → data
_REPO_ROOT = Path(__file__).resolve().parents[3]
_RESEARCH_ROOT = (_REPO_ROOT / "KNOWLEDGE_BASE" / "_research").resolve()
_NOTES_DIR = _RESEARCH_ROOT / "notes"
_FEEDBACK_DIR = _RESEARCH_ROOT / "feedback"

_ANALYSIS_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def _safe_id(analysis_id: str) -> str | None:
    """Reject anything that could escape the target directory."""
    if not analysis_id:
        return None
    if not _ANALYSIS_ID_RE.match(analysis_id):
        return None
    return analysis_id


def _ensure_dir(target: Path) -> bool:
    try:
        target.mkdir(parents=True, exist_ok=True)
        return True
    except OSError as exc:
        logger.warning("writeback: mkdir failed for %s — %s", target, exc)
        return False


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


def write_full_result(
    analysis_id: str,
    results: dict[str, Any],
) -> bool:
    """Persist the full orchestrator ``results`` envelope.

    Companion to :func:`write_session_note`. Where the session note is a
    compact diagnostic distilled from the agentic plan, this dumps the
    complete ``final_answer.results`` payload so the FE's
    ``GET /v1/analyses/{id}`` endpoint can serve a real detail view.
    Best-effort; never raises.
    """
    safe = _safe_id(analysis_id)
    if not safe:
        logger.warning("writeback: rejected analysis_id %r", analysis_id)
        return False
    if not _ensure_dir(_NOTES_DIR):
        return False
    target = _NOTES_DIR / f"{safe}_full.json"
    try:
        target.write_text(
            json.dumps(results or {}, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("writeback: full-result write failed (%s)", exc)
        return False
    logger.info("writeback: full result saved → %s", target)
    return True


def write_feedback(
    analysis_id: str,
    payload: dict[str, Any],
) -> bool:
    """Persist a /v1/feedback payload. Returns success.

    The endpoint handler is the only caller; this function does NOT
    promote feedback into ``parts/*.md`` — that step is human-curated.
    """
    safe = _safe_id(analysis_id)
    if not safe:
        logger.warning("writeback: rejected analysis_id %r", analysis_id)
        return False
    if not _ensure_dir(_FEEDBACK_DIR):
        return False
    record = {
        "analysis_id": safe,
        "written_at_epoch": time.time(),
        "payload": payload,
    }
    target = _FEEDBACK_DIR / f"{safe}.json"
    try:
        target.write_text(
            json.dumps(record, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("writeback: feedback write failed (%s)", exc)
        return False
    logger.info("writeback: feedback saved → %s", target)
    return True


__all__ = [
    "write_session_note",
    "write_full_result",
    "write_feedback",
    "_NOTES_DIR",
    "_ANALYSIS_ID_RE",
]
