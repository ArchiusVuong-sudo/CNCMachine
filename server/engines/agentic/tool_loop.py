"""ReAct/JSON tool-call driver for the single-loop agentic engine (Engine 3).

Engine 3's only LLM is the Kimi-Linear pod (Qwen drives Engine 1's drawing
extraction on a different path and is never used here). Kimi ships a slow
tiktoken tokenizer, so no vLLM grammar backend can attach — guided JSON
(``response_format``) *crashes* the engine. We therefore drive tool use with a
robust JSON-in-content protocol and do NOT request guided decoding:

  * Every assistant turn emits exactly ONE JSON object.
  * ``{"thought": ..., "tool": <name>, "args": {...}}`` invokes a tool.
  * ``{"thought": ..., "final": {...}}`` ends the loop with the answer.

Kimi's native tool-call control tokens (``<|tool_call_*|>``) are stopped at
the transport (:class:`server.infra.llm.AgentVLLMProvider`) and any leakage is
brace-repaired there, so this loop receives a single parseable object. The
model's reasoning (``<think>...</think>`` / ``reasoning_content``) is streamed
out and forwarded to the SSE ``thinking`` event via ``on_thinking``.

Tool execution is dispatched from a ``tools`` dict keyed by name. Sync and
async tool functions are both supported. Errors never crash the loop — they
come back to the agent as ``{"tool": <name>, "result": {"error": "..."}}`` so
it can recover or switch tools.

**Convergence guard.** Kimi (no guided decoding) is prone to degenerate
repetition on novel parts — re-calling the same tool instead of emitting
``final``. To keep the loop bounded we (a) block exact-duplicate tool calls
(identical name + args) and steer the model on, and (b) escalate toward a
forced ``final`` as the iteration budget runs low or one tool is over-used.

The previous version enforced a citation gate that rejected ``final`` payloads
without an ``evidence`` array. That gate has been removed — the prompt asks the
agent to write a clear ``rationale`` but does not require citation tokens.
"""
from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Awaitable, Callable

from ...core.events import OnEvent, safe_emit
from ...core.settings import get_settings
from ...infra.llm import chat_messages as _default_chat
from ...infra.llm import parse_model_json

logger = logging.getLogger("cncserver.engines.agentic.tool_loop")

ToolFn = Callable[..., Any | Awaitable[Any]]
ChatFn = Callable[..., Awaitable[dict]]


def _agentic_settings():
    """Re-resolved on every loop call so ``/v1/feedback`` can hot-reload."""
    return get_settings().agentic


class ToolLoopError(RuntimeError):
    """Raised when the loop exhausts retries or violates the protocol."""


def _truncate_result(payload: Any, *, cap: int) -> Any:
    """Cap tool results so a chatty tool can't blow the context window."""
    try:
        encoded = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"error": "tool result not JSON-serializable"}
    if len(encoded) <= cap:
        return payload
    return {
        "truncated": True,
        "original_chars": len(encoded),
        "preview": encoded[:cap],
    }


def _estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate for the whole message list.

    ~3.3 chars/token for English+JSON is conservative-low, so we divide by 3
    to over-estimate slightly and stay on the safe side of the real limit.
    Plus ~4 tokens of role/format overhead per message.
    """
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    return chars // 3 + 4 * len(messages)


def _trim_history(messages: list[dict], *, max_input_tokens: int) -> int:
    """Bound the ReAct history in place so the prompt never overflows context.

    Keeps the system prompt (messages[0]) and the original task user message
    (messages[1]) — both load-bearing — then evicts the OLDEST middle turns in
    (assistant, tool-result) PAIRS until the estimate fits ``max_input_tokens``.
    Pair-eviction preserves the assistant/user alternation the chat endpoint
    expects. The most recent turns (where the model's working state lives) are
    always retained. Returns the number of messages dropped (0 if none).

    This is the fix for the unbounded-history overflow that silently failed
    complex components at ~iteration 18 (24577 input + 8192 output > 32768).
    """
    if len(messages) <= 4 or _estimate_tokens(messages) <= max_input_tokens:
        return 0
    head = messages[:2]
    tail = messages[2:]
    dropped = 0
    # Evict from the front of the tail in pairs, always leaving the last pair.
    while len(tail) > 2 and _estimate_tokens(head + tail) > max_input_tokens:
        del tail[0:2]
        dropped += 2
    messages[:] = head + tail
    return dropped


async def _invoke_tool(fn: ToolFn, args: dict | None) -> Any:
    """Run a tool function (sync or async) with kwargs from the model."""
    args = args or {}
    if not isinstance(args, dict):
        return {"error": f"args must be an object, got {type(args).__name__}"}
    try:
        if inspect.iscoroutinefunction(fn):
            return await fn(**args)
        result = fn(**args)
        if inspect.isawaitable(result):
            return await result
        return result
    except TypeError as exc:
        return {"error": f"invalid args: {exc}"}
    except Exception as exc:  # noqa: BLE001 — tools must never crash the loop
        logger.exception("tool_loop: tool raised — surfacing as error result")
        return {"error": f"tool execution failed: {exc.__class__.__name__}: {exc}"}


def _parse_turn(raw: str) -> dict:
    """Robust JSON parse of one assistant turn.

    Returns the parsed dict or ``{"_parse_error": "..."}`` so the caller
    can decide whether to ask the model to fix itself.
    """
    text = (raw or "").strip()
    if not text:
        return {"_parse_error": "empty assistant response"}
    parsed = parse_model_json(text)
    if not isinstance(parsed, dict):
        return {"_parse_error": f"expected JSON object, got {type(parsed).__name__}"}
    if "raw_model_output" in parsed and "final" not in parsed and "tool" not in parsed:
        return {"_parse_error": "no JSON object in response"}

    # Coerce {"tool":"final","args":{...}} -> {"final":{...}}.  Qwen3-VL
    # occasionally confuses the two protocol shapes; recognising the synonym
    # avoids burning iterations on "unknown tool 'final'" loops.
    if (
        isinstance(parsed.get("tool"), str)
        and parsed["tool"].strip().lower() in ("final", "finish", "done", "answer")
        and "final" not in parsed
    ):
        args = parsed.get("args")
        if isinstance(args, dict):
            parsed["final"] = args
        else:
            parsed["final"] = {"answer": args} if args is not None else {}
        parsed.pop("tool", None)
        parsed.pop("args", None)
    return parsed


def _shape_check(parsed: dict) -> str | None:
    """Validate the model produced a ``tool`` or ``final`` call.

    Returns an error string if the shape is wrong, ``None`` if OK.
    """
    if "_parse_error" in parsed:
        return parsed["_parse_error"]
    has_tool = "tool" in parsed
    has_final = "final" in parsed
    if has_tool and has_final:
        return "response contains both `tool` and `final` — pick one"
    if not has_tool and not has_final:
        return "response must contain either `tool` or `final`"
    if has_tool and not isinstance(parsed.get("tool"), str):
        return "`tool` must be a string"
    if has_tool and parsed.get("args") is not None and not isinstance(parsed["args"], dict):
        return "`args` must be an object"
    if has_final and not isinstance(parsed.get("final"), dict):
        return "`final` must be an object"
    return None


# --- Convergence guard (Kimi has no guided decoding → repetition-prone) -----
#
# Thresholds chosen so the working copy/exact-match path (which converges in
# ~12 iterations) never trips them, while the novel-part repetition spiral
# (observed: catalog_lookup x25, memory_update x18) is cut off.
_DUP_FORCE_FINALIZE_AFTER = 3   # blocked exact-duplicate calls → demand `final`
_TOOL_SPAM_LIMIT = 12           # one tool used this many times → nudge `final`
_FINALIZE_TAIL = 6              # last N iterations → escalating `final` nudges

_FINALIZE_INSTRUCTION = (
    "You are repeating work without making progress. STOP gathering and emit "
    "your `final` plan NOW using the information you already have. Respond with "
    'EXACTLY one JSON object: {"thought": ..., "final": {...}}.'
)


def _args_signature(tool_name: str, args: dict) -> str:
    """Stable key for (tool, args) so identical re-calls can be detected."""
    try:
        encoded = json.dumps(args or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        encoded = repr(args)
    return f"{tool_name}|{encoded}"


async def run_tool_loop(
    *,
    system_prompt: str,
    user_prompt: str,
    tools: dict[str, ToolFn],
    on_event: OnEvent = None,
    on_thinking: Callable[[str], Awaitable[None]] | None = None,
    max_iterations: int | None = None,
    label: str = "agent",
    chat_fn: ChatFn | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Drive a ReAct/JSON loop until the agent emits ``{"final": ...}``.

    Parameters
    ----------
    system_prompt:
        Role + protocol + tool catalog. Built by
        :func:`server.engines.agentic.prompts.build_system_prompt`.
    user_prompt:
        Per-component message. Built by
        :func:`server.engines.agentic.prompts.build_agent_user_message`.
    tools:
        ``name → callable``. Sync and async callables both work; missing
        tool names are surfaced to the model so it can pick another.
    on_event:
        SSE bridge from the orchestrator. We emit ``tool_call`` and
        ``tool_result`` per iteration plus a final ``tool_result`` with
        the answer.
    on_thinking:
        Forwarded to :func:`chat_messages` so the orchestrator can stream
        the model's reasoning as ``thinking`` events.
    max_iterations:
        Hard cap. Hitting it raises :class:`ToolLoopError`. The agent
        loop should checkpoint to its workspace so a retry resumes
        instead of redoing work.
    label:
        Short tag attached to ``tool_call`` event payloads (component name).
    chat_fn:
        Injection seam for tests. Defaults to
        :func:`server.infra.llm.chat_messages`.
    model:
        Model slug forwarded to ``chat_fn`` (the ``"agent:<name>"`` slug for
        the Kimi pod). Engine 3 is Kimi-only — :func:`chat_messages` ignores
        the slug for routing and always uses the Kimi backend.

    Returns
    -------
    ``{"final": <model output>, "iterations": int, "tool_calls": list[dict],
    "adopted_routings": list[dict]}``. ``adopted_routings`` holds the full
    ``kb_adopt_routing`` results (pre-truncation), so the coordinator can
    re-inject any owner-scope family the agent dropped from ``final``.
    """
    settings = _agentic_settings()
    if max_iterations is None:
        max_iterations = settings.max_iterations_per_phase
    max_parse_retries = settings.max_parse_retries
    max_tool_result_chars = settings.max_tool_result_chars

    chat = chat_fn or _default_chat

    # Input-token budget for history trimming. The model context window minus
    # the reserved completion budget minus a safety margin. Overridable via env
    # for non-32k backends. This is what stops the unbounded ReAct history from
    # eventually exceeding the context window mid-run.
    import os as _os
    _ctx_window = int(_os.environ.get("AGENT_LLM_CONTEXT_WINDOW", "32768"))
    _reserve_out = max(int(getattr(settings, "agent_max_tokens", 8192) or 8192), 4096)
    _max_input_tokens = max(_ctx_window - _reserve_out - 2048, 4096)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    tool_calls: list[dict] = []
    adopted_routings: list[dict] = []
    parse_retries = 0
    seen_call_sigs: set[str] = set()   # (tool, args) signatures already executed
    tool_name_counts: dict[str, int] = {}
    dup_blocks = 0                     # exact-duplicate calls blocked so far

    for iteration in range(1, max_iterations + 1):
        # Bound history BEFORE the call so the prompt can never exceed the
        # context window, no matter how many iterations or how large the tool
        # results. Keeps system + task message + most-recent turns.
        _dropped = _trim_history(messages, max_input_tokens=_max_input_tokens)
        if _dropped:
            logger.info(
                "tool_loop[%s] iter=%d trimmed %d old message(s) to fit context "
                "(~%d input tokens budget)",
                label, iteration, _dropped, _max_input_tokens,
            )
        try:
            # No `response_format`: guided JSON crashes the Kimi engine (no
            # grammar backend). We rely on the prompt's "one JSON object" rule
            # plus parse_model_json salvage instead.
            resp = await chat(
                messages,
                model=model,
                on_thinking=on_thinking,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            raise ToolLoopError(f"chat call failed at iteration {iteration}: {exc}") from exc

        assistant_text = (resp.get("content") or "").strip()
        messages.append({"role": "assistant", "content": assistant_text})
        parsed = _parse_turn(assistant_text)
        shape_err = _shape_check(parsed)

        if shape_err:
            parse_retries += 1
            logger.warning(
                "tool_loop[%s] iter=%d shape error: %s (retry %d/%d) raw=%r",
                label, iteration, shape_err, parse_retries, max_parse_retries,
                assistant_text[:400],
            )
            if parse_retries > max_parse_retries:
                raise ToolLoopError(
                    f"agent produced unparseable output after {parse_retries} retries: {shape_err}"
                )
            messages.append({
                "role": "user",
                "content": json.dumps({
                    "error": shape_err,
                    "instruction": (
                        "Respond with EXACTLY one JSON object: either "
                        "{\"thought\": ..., \"tool\": <name>, \"args\": {...}} or "
                        "{\"thought\": ..., \"final\": {...}}. No prose, no markdown."
                    ),
                }),
            })
            continue

        parse_retries = 0  # reset on a clean turn

        if "final" in parsed:
            final_payload = parsed["final"]
            await safe_emit(on_event, "tool_result", {
                "tool": label,
                "iteration": iteration,
                "result": {"final": final_payload},
            })
            return {
                "final": final_payload,
                "iterations": iteration,
                "tool_calls": tool_calls,
                "adopted_routings": adopted_routings,
            }

        tool_name = parsed["tool"]
        args = parsed.get("args") or {}
        await safe_emit(on_event, "tool_call", {
            "tool": tool_name,
            "iteration": iteration,
            "label": label,
        })

        # Convergence guard: re-running a tool with identical args yields an
        # identical result the model already has — pure spin. Block it, steer
        # the model on, and after a few blocks demand `final`. (Kimi has no
        # guided decoding and is prone to this on novel parts.)
        sig = _args_signature(tool_name, args)
        if sig in seen_call_sigs:
            dup_blocks += 1
            logger.warning(
                "tool_loop[%s] iter=%d blocked duplicate call to %s (block %d)",
                label, iteration, tool_name, dup_blocks,
            )
            steer = {
                "error": "duplicate_call",
                "tool": tool_name,
                "instruction": (
                    "You already called this tool with identical arguments; the "
                    "result has not changed. Do NOT repeat it. Either call a "
                    "DIFFERENT tool (or same tool with DIFFERENT args), or emit "
                    "your `final` plan now."
                ),
            }
            if dup_blocks >= _DUP_FORCE_FINALIZE_AFTER:
                steer["instruction"] = _FINALIZE_INSTRUCTION
            await safe_emit(on_event, "tool_result", {
                "tool": tool_name,
                "iteration": iteration,
                "result": steer,
            })
            messages.append({
                "role": "user",
                "content": json.dumps({"tool": tool_name, "result": steer}),
            })
            continue
        seen_call_sigs.add(sig)
        tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1

        if tool_name not in tools:
            result: Any = {
                "error": f"unknown tool {tool_name!r}",
                "available_tools": sorted(tools.keys()),
            }
        else:
            result = await _invoke_tool(tools[tool_name], args)

        # Capture the FULL (pre-truncation) adopted-analogue routing so the
        # coordinator can deterministically re-inject any owner-scope family
        # the agent later drops from its `final` plan. This is the data
        # backbone for the family-coverage gate.
        if (
            tool_name == "kb_adopt_routing"
            and isinstance(result, dict)
            and isinstance(result.get("operations"), list)
            and result.get("operations")
        ):
            adopted_routings.append({
                "part_number": (args or {}).get("part_number"),
                "role": (args or {}).get("role"),
                "operations": result["operations"],
            })

        result = _truncate_result(result, cap=max_tool_result_chars)

        tool_calls.append({
            "tool": tool_name,
            "args": args,
            "result_preview_chars": len(json.dumps(result, default=str)),
        })
        await safe_emit(on_event, "tool_result", {
            "tool": tool_name,
            "iteration": iteration,
            "result": result,
        })

        # Steer toward `final` as the budget runs low or one tool is over-used,
        # so a slow-converging component finalizes instead of hitting the cap.
        result_msg: dict[str, Any] = {"tool": tool_name, "result": result}
        guidance: list[str] = []
        if tool_name_counts[tool_name] >= _TOOL_SPAM_LIMIT:
            guidance.append(
                f"You have called `{tool_name}` {tool_name_counts[tool_name]} "
                "times — you very likely have enough. Emit `final` or switch tools."
            )
        remaining = max_iterations - iteration
        if remaining <= _FINALIZE_TAIL:
            lead = "This is your LAST step — you MUST" if remaining <= 1 else (
                f"Only {remaining} steps remain;"
            )
            guidance.append(
                f"{lead} emit your `final` plan now from what you already have; "
                "stop gathering unless strictly required."
            )
        if guidance:
            result_msg["_guidance"] = " ".join(guidance)
        messages.append({
            "role": "user",
            "content": json.dumps(result_msg, default=str),
        })

    raise ToolLoopError(
        f"agent exceeded {max_iterations} iterations without producing `final`. "
        f"tool_calls={[c['tool'] for c in tool_calls]}"
    )


__all__ = ["run_tool_loop", "ToolLoopError"]
