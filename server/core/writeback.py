"""Engine-neutral filesystem writeback under ``KNOWLEDGE_BASE/_research/``.

This module owns the bits of the writeback layer that are not tied to
any particular planning engine:

  * :func:`write_full_result` — persists the orchestrator's full
    ``final_answer.results`` envelope to
    ``_research/notes/<id>_full.json``. Read back by
    ``GET /v1/analyses/{id}`` regardless of which engine produced it.
  * :func:`write_feedback`    — persists the ``POST /v1/feedback``
    payload to ``_research/feedback/<id>.json``.
  * Path-validation primitives (:data:`_ANALYSIS_ID_RE`,
    :data:`_NOTES_DIR`, :data:`_FEEDBACK_DIR`, :func:`_safe_id`,
    :func:`_ensure_dir`) shared by the API listing route.

Engine-specific writers (e.g. the agentic session-note dump) live in
their own engine package and consume the helpers exposed here.

All writes are best-effort: filesystem errors log + return ``False``
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

logger = logging.getLogger("cncserver.core.writeback")

# writeback.py → core → server → data
_REPO_ROOT = Path(__file__).resolve().parents[2]
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


def write_full_result(
    analysis_id: str,
    results: dict[str, Any],
) -> bool:
    """Persist the full orchestrator ``results`` envelope.

    Companion to engine-specific session notes. This dumps the complete
    ``final_answer.results`` payload so the FE's
    ``GET /v1/analyses/{id}`` endpoint can serve a real detail view,
    regardless of which planner engine ran. Best-effort; never raises.
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
    """Persist a ``/v1/feedback`` payload. Returns success.

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
    "_ANALYSIS_ID_RE",
    "_NOTES_DIR",
    "_FEEDBACK_DIR",
    "_safe_id",
    "_ensure_dir",
    "write_full_result",
    "write_feedback",
]
