"""Single-shot LLM generator for the RAG engine.

Wraps :func:`server.infra.llm.chat_messages` with:

  * JSON mode (``response_format={"type": "json_object"}``).
  * One retry on parse failure with a tightened reminder.
  * Reasoning-stream forwarding via ``on_thinking`` (so the orchestrator
    can mirror the model's chain-of-thought to the SSE channel exactly
    like the agentic engine does).

The model returns ONE JSON object per call; the agentic engine's
multi-turn ReAct loop does NOT live here. That's the entire point of
having a separate RAG engine.
"""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from ...infra.llm import chat_messages, parse_model_json

logger = logging.getLogger("cncserver.engines.rag.generator")

OnThinking = Callable[[str], Awaitable[None]] | None

# Cap on the size of the JSON we let the model emit. Bigger than this and
# something has gone wrong (the schema fits comfortably in ~8k chars).
_MAX_FINAL_CHARS = 60_000


# ---------------------------------------------------------------------------
# Shape sanity
# ---------------------------------------------------------------------------

_REQUIRED_TOP_KEYS = ("machine_class", "operations", "total_run_min_per_part")


def _looks_like_plan(obj: object) -> bool:
    """Cheap structural check — full schema validation happens at projection."""
    if not isinstance(obj, dict):
        return False
    for k in _REQUIRED_TOP_KEYS:
        if k not in obj:
            return False
    ops = obj.get("operations")
    if not isinstance(ops, list) or not ops:
        return False
    return True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_plan(
    *,
    system_prompt: str,
    user_prompt: str,
    on_thinking: OnThinking = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    model: str | None = None,
) -> dict:
    """Call the LLM once with JSON mode and return the parsed plan.

    On the first try we use ``response_format={"type": "json_object"}``
    so vLLM constrains the decoder to emit valid JSON. If parsing still
    fails (or the structure doesn't pass the cheap shape check), we
    retry once with a sharper "respond with JSON only" reminder injected
    as a final assistant→user turn.

    Returns the parsed dict on success. Raises ``RagGenerationError``
    on hard failure so the per-component planner can mark the
    component as failed (mirrors agentic behavior — partial assemblies
    succeed).
    """
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]

    result = await chat_messages(
        messages,
        model=model,
        on_thinking=on_thinking,
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    content = (result.get("content") or "").strip()
    thinking = result.get("thinking") or ""
    if len(content) > _MAX_FINAL_CHARS:
        logger.warning(
            "generate_plan: model returned %d chars (cap %d) — truncating",
            len(content), _MAX_FINAL_CHARS,
        )
        content = content[:_MAX_FINAL_CHARS]

    parsed = parse_model_json(content) if content else {}
    if _looks_like_plan(parsed):
        logger.info(
            "generate_plan: ok on first try (content=%d chars, ops=%d)",
            len(content), len(parsed.get("operations") or []),
        )
        return parsed

    # Retry once with a tightened reminder. We pass the prior content
    # back so the model can see what it just emitted and fix it.
    logger.warning(
        "generate_plan: first response did not validate "
        "(content_len=%d thinking_len=%d) — retrying with reminder",
        len(content), len(thinking),
    )

    retry_messages = messages + [
        {"role": "assistant", "content": content or "(empty)"},
        {"role": "user", "content": (
            "Your previous response did not parse as a valid plan JSON.\n\n"
            "Respond again with EXACTLY ONE JSON object matching the schema "
            "in the system message. Required top-level keys: "
            "`machine_class`, `chosen_machine_id`, `operations` (non-empty "
            "list), `total_run_min_per_part`, `setup_min_per_lot`, "
            "`rationale`, `evidence`. No prose, no markdown fence."
        )},
    ]
    retry = await chat_messages(
        retry_messages,
        model=model,
        on_thinking=on_thinking,
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    retry_content = (retry.get("content") or "").strip()[:_MAX_FINAL_CHARS]
    retry_parsed = parse_model_json(retry_content) if retry_content else {}
    if _looks_like_plan(retry_parsed):
        logger.info("generate_plan: ok on retry (content=%d chars)", len(retry_content))
        return retry_parsed

    raise RagGenerationError(
        f"generator: model failed to emit a valid plan after retry. "
        f"first_content_len={len(content)} retry_content_len={len(retry_content)} "
        f"first_preview={content[:200]!r} retry_preview={retry_content[:200]!r}"
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RagGenerationError(RuntimeError):
    """Raised when the LLM fails to emit a usable plan JSON.

    Caught by the per-component planner; the component is marked failed
    and the rest of the assembly continues.
    """


__all__ = ["generate_plan", "RagGenerationError"]
