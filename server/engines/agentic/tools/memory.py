"""Agent-maintained long-term memory — append to ``KNOWLEDGE_BASE/MEMORY.md``.

``MEMORY.md`` is the agent's learned-heuristics layer, loaded into the
system prompt next to ``AGENT.md`` (see
:mod:`server.engines.agentic.prompts.system`). This tool is the agent's
*only* sanctioned write outside ``_research/`` — it appends one
generalizable lesson to the file's **Candidate lessons** holding section.

Guards (anti-bloat + anti-overfit, mirroring the tuning anti-patterns):

  * **single-file path lock** — writes can only ever touch MEMORY.md.
  * **generalizable-only** — a lesson naming a part number is rejected, so
    the agent records principles, not memorized answers.
  * **bounded** — capped candidate count and lesson length keep the file
    (which is paid for in every future prompt) from ballooning.
  * **frozen during holdout eval** — the agent must not mutate its own
    prompt-loaded memory mid-measurement, or fixture N biases fixture N+1.

Like the other tools, every path returns a JSON-safe dict and never
raises — failures come back as ``{"error": "..."}``.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger("cncserver.engines.agentic.tools.memory")

# tools/memory.py → tools → agentic → engines → server → data
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MEMORY_MD = (_REPO_ROOT / "KNOWLEDGE_BASE" / "MEMORY.md").resolve()

_CANDIDATE_HEADER = "## Candidate lessons (holding — not yet validated against ground truth)"
_PLACEHOLDER = "_(none yet)_"
_MAX_CANDIDATES = 12
_MAX_LESSON_CHARS = 280
# Part-number-like token (0042-93726, 839-323453, 16-408773-00) — banned so
# the agent records a GENERALIZABLE principle, never a per-part lookup.
_PARTNUM_RE = re.compile(r"\b\d{2,4}-\d{3,6}(?:-[A-Za-z0-9]{1,4})?\b")


def _append_candidate(lesson: str) -> dict[str, Any]:
    """Append one validated-shape lesson to the Candidate section. Best-effort."""
    lesson = " ".join((lesson or "").split())  # collapse whitespace/newlines
    if not lesson:
        return {"error": "lesson is empty"}
    if len(lesson) > _MAX_LESSON_CHARS:
        return {"error": f"lesson too long ({len(lesson)} > {_MAX_LESSON_CHARS} chars) — distill it"}
    if _PARTNUM_RE.search(lesson):
        return {"error": (
            "lesson names a specific part number — record a GENERALIZABLE "
            "principle instead (no part-specific lookups)"
        )}

    try:
        text = _MEMORY_MD.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"MEMORY.md read failed: {exc}"}

    if _CANDIDATE_HEADER in text:
        head, cand = text.split(_CANDIDATE_HEADER, 1)
    else:
        head, cand = text.rstrip() + "\n\n", "\n"

    existing = [ln.rstrip() for ln in cand.splitlines() if ln.strip().startswith("- ")]
    if len(existing) >= _MAX_CANDIDATES:
        return {"error": (
            f"candidate section full ({_MAX_CANDIDATES} entries) — consolidate or "
            "validate existing lessons before adding more"
        )}

    bullet = f"- {lesson}  _(candidate · {date.today().isoformat()})_"
    new_cand = "\n\n" + "\n".join(existing + [bullet]) + "\n"
    new_text = head.rstrip() + "\n\n" + _CANDIDATE_HEADER + new_cand
    try:
        _MEMORY_MD.write_text(new_text, encoding="utf-8")
    except OSError as exc:
        return {"error": f"MEMORY.md write failed: {exc}"}

    # The system prompt caches MEMORY.md; drop the cache so the next prompt
    # build re-reads it. Lazy import avoids a tools<->prompts import cycle.
    try:
        from ..prompts.system import invalidate_cache
        invalidate_cache()
    except Exception:  # pragma: no cover — cache refresh is best-effort
        pass

    logger.info("memory_update: appended candidate lesson (now %d)", len(existing) + 1)
    return {"ok": True, "candidates_count": len(existing) + 1, "stored": bullet}


def make_memory_tools(holdout_part_number: str | None = None) -> dict[str, Any]:
    """Bind ``memory_update`` for this analysis.

    Returns a no-op (frozen) writer when ``holdout_part_number`` is set so
    eval runs measure the agent against a FIXED memory and stay
    reproducible. Production runs (``None``) get the live appender.
    """
    if (holdout_part_number or "").strip():
        def _frozen_memory_update(lesson: str, evidence: str | None = None) -> dict[str, Any]:
            return {
                "ok": False,
                "frozen": True,
                "note": "memory is frozen during eval/holdout — lesson not stored",
            }
        return {"memory_update": _frozen_memory_update}

    def _memory_update(lesson: str, evidence: str | None = None) -> dict[str, Any]:
        full = lesson if not (evidence or "").strip() else f"{lesson} (evidence: {evidence.strip()})"
        return _append_candidate(full)

    return {"memory_update": _memory_update}


MEMORY_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": (
                "Append ONE generalizable lesson to your long-term memory "
                "(KNOWLEDGE_BASE/MEMORY.md, loaded next to AGENT.md). Call it "
                "when a run taught you something that would help an UNSEEN "
                "part — a calibration prior, a sequencing rule, a material "
                "caveat. Do NOT store part numbers or part-specific values "
                "(rejected). The lesson lands in the Candidate (unvalidated) "
                "section. Frozen during evaluation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lesson": {
                        "type": "string",
                        "description": "One generalizable heuristic, <= 280 chars, no part numbers.",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "Optional short grounding, e.g. 'PEEK 3-axis k=1.17 across 5 ops'.",
                    },
                },
                "required": ["lesson"],
            },
        },
    },
]

__all__ = ["make_memory_tools", "MEMORY_TOOL_SPECS", "_append_candidate"]
