"""ReAct/JSON tool-call driver for the single-loop agentic engine.

The agent's only LLM is vLLM-served Qwen3-VL. vLLM's native function
calling is inconsistent across versions and chat-template configs, so we
drive tool use with a robust JSON protocol instead:

  * Every assistant turn emits exactly ONE JSON object.
  * ``{"thought": ..., "tool": <name>, "args": {...}}`` invokes a tool.
  * ``{"thought": ..., "final": {...}}`` ends the loop with the answer.

We request ``response_format={"type": "json_object"}`` so vLLM forces
JSON output. The model's reasoning (``<think>...</think>``) is streamed
out as ``reasoning_content`` and forwarded to the SSE ``thinking`` event
via the ``on_thinking`` callback.

Tool execution is dispatched from a ``tools`` dict keyed by name. Sync
and async tool functions are both supported. Errors never crash the
loop — they come back to the agent as ``{"tool": <name>, "result":
{"error": "..."}}`` so it can recover or switch tools.

The previous version of this file enforced a citation gate that rejected
``final`` payloads without an ``evidence`` array. That gate has been
removed — the new prompt asks the agent to write a clear ``rationale``
but does not require formal citation tokens.
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
        Optional model slug forwarded to ``chat_fn``. ``None`` or
        ``"vllm:<name>"`` routes to local vLLM; ``"<vendor>/<name>"``
        routes to OpenRouter. See
        :func:`server.infra.llm._select_provider`.

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
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    tool_calls: list[dict] = []
    adopted_routings: list[dict] = []
    parse_retries = 0

    for iteration in range(1, max_iterations + 1):
        try:
            resp = await chat(
                messages,
                model=model,
                on_thinking=on_thinking,
                temperature=0.0,
                response_format={"type": "json_object"},
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
                "tool_loop[%s] iter=%d shape error: %s (retry %d/%d)",
                label, iteration, shape_err, parse_retries, max_parse_retries,
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
        messages.append({
            "role": "user",
            "content": json.dumps({"tool": tool_name, "result": result}, default=str),
        })

    raise ToolLoopError(
        f"agent exceeded {max_iterations} iterations without producing `final`. "
        f"tool_calls={[c['tool'] for c in tool_calls]}"
    )


__all__ = ["run_tool_loop", "ToolLoopError"]
