"""LLM transport layer — vLLM (Qwen3-VL) + Agent vLLM (Kimi-Linear).

Why this exists
---------------
The pipeline talks to two OpenAI-compatible vLLM backends, and the
integration quirks of each are isolated here so the engines stay focused
on extraction logic:

  * **vLLM (Qwen3-VL)** — local OpenAI-compatible server. Used by
    Engine 1 (vision drawing extraction) and as a fallback text backend.
    Qwen-specific ``chat_template_kwargs`` + ``<think>...</think>``
    parsing live here.
  * **Agent vLLM (Kimi-Linear)** — a second vLLM pod dedicated to the
    Engine 3 (agentic planner). Sent PLAIN JSON-by-instruction: no
    ``response_format`` (Kimi's slow tiktoken tokenizer has no vLLM
    grammar backend — guided JSON crashes the engine) and no Qwen
    ``chat_template_kwargs``.

Per-request routing happens via :func:`chat_messages`'s ``model``
parameter:

  * ``None`` or ``"vllm:<name>"`` → :class:`VLLMProvider`.
  * ``"agent:<name>"`` → :class:`AgentVLLMProvider` (Kimi pod).

Both providers share:

  * **Inactivity watchdog** — cancels the stream if no tokens arrive for
    ``inactivity_seconds`` and falls back to JSON-salvage-from-thinking.
  * **JSON salvage** — when the answer never escapes the thinking block,
    we scan the thinking for the best JSON object and use it.
  * **Forwarded thinking chunks** — the orchestrator surfaces raw
    chain-of-thought as a separate SSE event. The ``on_thinking``
    callback receives every reasoning delta as it arrives.

This module is pure transport. Prompts live with the engine that calls
it (``server.engines.extraction_2d.prompts``,
``server.engines.agentic.prompts``).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable, Protocol

import httpx

from ..core.settings import get_settings

logger = logging.getLogger("cncserver.infra.llm")

OnThinking = Callable[[str], Awaitable[None]] | None

# Hard caps so a runaway model can never blow the process.
_MAX_CONTENT_CHARS  = 200_000
_MAX_THINKING_CHARS = 80_000

# Model-slug prefix that forces routing to the local vLLM (Qwen) provider.
_VLLM_PREFIX = "vllm:"

# Model-slug prefix that routes to the dedicated agent backend (Kimi-Linear
# on a second vLLM pod). See :class:`AgentVLLMProvider`.
_AGENT_PREFIX = "agent:"


# ---------------------------------------------------------------------------
# Image MIME detection (vLLM expects a data URL)
# ---------------------------------------------------------------------------

def _image_mime_type(b64: str) -> str:
    if b64.startswith("/9j/"):
        return "image/jpeg"
    if b64.startswith("iVBOR"):
        return "image/png"
    return "image/png"


# ---------------------------------------------------------------------------
# Brace walker — finds the closing brace that matches an opening { or [
# while respecting strings + escapes
# ---------------------------------------------------------------------------

def find_matching_brace(s: str) -> int:
    """Walk from index 0 (must be ``{`` or ``[``) → return index of the match."""
    depth = 0
    in_str = False
    esc = False
    for i, c in enumerate(s):
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c in ("{", "["):
            depth += 1
        elif c in ("}", "]"):
            depth -= 1
            if depth == 0:
                return i
    return -1


def _strip_think_tags(text: str) -> str:
    """Strip the leading ``<think>...</think>`` block, return the answer.

    Returns empty string if the text consists *only* of thinking.
    """
    trimmed = text.strip()
    idx = trimmed.find("</think>")
    if trimmed.startswith("<think>") and idx != -1:
        return trimmed[idx + 8:].strip()
    if trimmed.startswith("<think>"):
        return ""
    return trimmed


# ---------------------------------------------------------------------------
# JSON salvage helpers
# ---------------------------------------------------------------------------

def extract_json_from_thinking(thinking: str) -> str:
    """Find the highest-scoring JSON object inside a thinking transcript.

    The model often produces several candidate JSONs mid-thought; we walk
    from the end backwards, parse each ``{ "dimensions": ...}``-shaped
    candidate, and pick the one with the most extracted dims/threads/GD&T.

    Falls back to any parseable object, then to a non-technical-page
    sentinel based on keyword heuristics.
    """
    candidates: list[dict] = []
    search_from = len(thinking)
    while search_from > 0:
        dims_idx = thinking.rfind('"dimensions"', 0, search_from)
        if dims_idx == -1:
            break
        brace_idx = thinking.rfind("{", 0, dims_idx)
        if brace_idx == -1:
            search_from = dims_idx
            continue
        from_brace = thinking[brace_idx:]
        close_idx = find_matching_brace(from_brace)
        if close_idx == -1:
            search_from = dims_idx
            continue
        json_str = from_brace[: close_idx + 1]
        try:
            parsed = json.loads(json_str)
            score = (
                len(parsed.get("dimensions") or [])
                + len(parsed.get("threads") or [])
                + len(parsed.get("gdt") or [])
            )
            candidates.append({"json": json_str, "score": score})
        except (json.JSONDecodeError, ValueError):
            pass
        search_from = dims_idx

    if candidates:
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        logger.info(
            "extract_json_from_thinking: best=%d chars score=%d (of %d candidates)",
            len(best["json"]), best["score"], len(candidates),
        )
        return best["json"]

    # Last resort: any parseable JSON object at all
    for pos in range(len(thinking) - 1, -1, -1):
        if thinking[pos] != "{":
            continue
        from_brace = thinking[pos:]
        close_idx = find_matching_brace(from_brace)
        if close_idx == -1:
            continue
        json_str = from_brace[: close_idx + 1]
        try:
            json.loads(json_str)
            return json_str
        except (json.JSONDecodeError, ValueError):
            continue

    lower = thinking.lower()
    if (
        "non_technical_page" in lower
        or "not a drawing" in lower
        or "not an engineering drawing" in lower
        or "no visible dimension" in lower
        or ("no dimension" in lower and "title" in lower)
    ):
        logger.info("extract_json_from_thinking: non-technical sentinel")
        return (
            '{"dimensions":[],"gdt":[],"threads":[],'
            '"material":null,"surface_finish":null,'
            '"notes":["non_technical_page"]}'
        )
    return thinking


# ---------------------------------------------------------------------------
# Robust JSON parser for VLM output
# ---------------------------------------------------------------------------

_EXPECTED_TOP_KEYS = (
    '"features_3d"', '"features"', '"operations"',
    '"dimensions"', '"total_minutes"', '"shape_summary"',
)


def parse_model_json(raw_text: str) -> dict:
    """Parse model output that may be raw JSON, fenced, or wrapped in prose.

    Always returns a dict. If absolutely no JSON can be extracted, returns a
    ``{"raw_model_output": <text>, "dimensions": [], "gdt": [], "threads": []}``
    sentinel so downstream merge logic can still iterate.
    """
    cleaned = (raw_text or "").strip()
    preview = cleaned.replace("\n", " ")[:500]
    logger.info(
        "parse_model_json: raw_len=%d preview=%s%s",
        len(cleaned), preview, "…" if len(cleaned) > 500 else "",
    )

    # Strip ```json ... ``` fence
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.split("\n")[1:])
    if cleaned.endswith("```"):
        cleaned = cleaned[: cleaned.rfind("```")]
    cleaned = cleaned.strip().rstrip("`").strip()

    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass

    brace_idx = cleaned.find("{")
    if brace_idx != -1:
        # Try slicing from the first '{'
        try:
            return json.loads(cleaned[brace_idx:])
        except (json.JSONDecodeError, ValueError):
            pass
        from_brace = cleaned[brace_idx:]
        close_idx = find_matching_brace(from_brace)
        if close_idx != -1:
            try:
                return json.loads(from_brace[: close_idx + 1])
            except (json.JSONDecodeError, ValueError):
                pass

    # Keyword-anchored salvage
    for key in _EXPECTED_TOP_KEYS:
        idx = cleaned.rfind(key)
        if idx == -1:
            continue
        brace_pos = cleaned.rfind("{", 0, idx)
        if brace_pos == -1:
            continue
        from_brace = cleaned[brace_pos:]
        close_idx = find_matching_brace(from_brace)
        if close_idx == -1:
            continue
        try:
            r = json.loads(from_brace[: close_idx + 1])
            if isinstance(r, dict):
                logger.info("parse_model_json: keyword-anchored parse OK for %s", key)
                return r
        except (json.JSONDecodeError, ValueError):
            continue

    logger.warning("parse_model_json: UNPARSEABLE (len=%d) — returning sentinel", len(cleaned))
    return {"raw_model_output": raw_text, "dimensions": [], "gdt": [], "threads": []}


# ---------------------------------------------------------------------------
# Streaming vision chat
# ---------------------------------------------------------------------------

async def vision_chat(
    image_base64: str | list[str],
    system_prompt: str,
    user_prompt: str,
    *,
    on_thinking: OnThinking = None,
    temperature: float = 0.15,
    repetition_penalty: float = 1.12,
) -> dict:
    """Call vLLM ``/v1/chat/completions`` with vision content and stream.

    Returns ``{"content": str}`` — the model's answer with the
    ``<think>...</think>`` block stripped. Raises on transport failure.

    The ``on_thinking`` callback (if provided) receives reasoning deltas as
    they arrive, so the orchestrator can forward them to the SSE stream as
    a separate ``thinking`` event.
    """
    settings = get_settings().llm
    endpoint = f"{settings.base_url}/v1/chat/completions"
    images = image_base64 if isinstance(image_base64, list) else [image_base64]
    inactivity = settings.vlm_inactivity_seconds
    t0 = time.time()

    logger.info(
        "vision_chat START model=%s url=%s images=%d total_b64=%d",
        settings.model, settings.base_url, len(images),
        sum(len(b) for b in images),
    )

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    *[
                        {"type": "image_url",
                         "image_url": {"url": f"data:{_image_mime_type(b)};base64,{b}"}}
                        for b in images
                    ],
                    {"type": "text", "text": user_prompt},
                ],
            },
        ],
        "stream":             True,
        "temperature":        temperature,
        "repetition_penalty": repetition_penalty,
        "max_tokens":         settings.vlm_max_tokens,
        "chat_template_kwargs": {
            "enable_thinking":         True,
            "thinking_budget_tokens":  settings.vlm_thinking_budget_tokens,
        },
        "skip_special_tokens": False,
    }

    full_content = ""
    think_content = ""
    stream_inactive = False
    content_in_think = True  # everything is thinking until we see </think>

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", endpoint, json=payload, timeout=None) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"VLM HTTP {resp.status_code}: "
                        f"{body[:200].decode(errors='replace')}"
                    )
                buf = ""
                aiter = resp.aiter_bytes().__aiter__()
                while True:
                    try:
                        raw_bytes = await asyncio.wait_for(
                            aiter.__anext__(), timeout=inactivity,
                        )
                    except asyncio.TimeoutError:
                        stream_inactive = True
                        logger.warning("VLM inactivity timeout after %gs", inactivity)
                        break
                    except StopAsyncIteration:
                        break

                    buf += raw_bytes.decode("utf-8", errors="replace")
                    lines = buf.split("\n")
                    buf = lines.pop()

                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        raw = line[6:] if line.startswith("data: ") else line
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                            if delta.get("reasoning_content"):
                                think_content += delta["reasoning_content"]
                                content_in_think = False
                                if on_thinking:
                                    await on_thinking(delta["reasoning_content"])
                            if delta.get("content"):
                                full_content += delta["content"]
                                if content_in_think and not think_content:
                                    if "</think>" in delta["content"]:
                                        idx = delta["content"].index("</think>")
                                        chunk_think = delta["content"][:idx]
                                        if chunk_think and on_thinking:
                                            await on_thinking(chunk_think)
                                        content_in_think = False
                                    elif on_thinking:
                                        await on_thinking(delta["content"])
                            if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                                break
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass

                    if len(full_content) > _MAX_CONTENT_CHARS:
                        logger.warning("VLM content > %d chars — breaking", _MAX_CONTENT_CHARS)
                        break
                    if len(think_content) > _MAX_THINKING_CHARS:
                        logger.warning("VLM thinking > %d chars — breaking", _MAX_THINKING_CHARS)
                        break
    except Exception as exc:
        raise RuntimeError(f"VLM stream error: {exc}") from exc

    if stream_inactive and not full_content and not think_content:
        raise RuntimeError(
            f"VLM stopped responding (no tokens for {inactivity}s). "
            "Check the vLLM endpoint health."
        )

    # Qwen3-VL: <think>...</think> followed by the answer in ``content``
    if (
        full_content and not think_content
        and "</think>" in full_content and "<think>" not in full_content
    ):
        close_idx = full_content.index("</think>")
        after_think = full_content[close_idx + 8:].strip()
        thinking = full_content[:close_idx].strip()
        think_content = thinking
        full_content = after_think

    # Other servers wrap the lot in <think>...</think>
    if full_content and not think_content and "<think>" in full_content:
        after = _strip_think_tags(full_content)
        if after:
            full_content = after
        else:
            think_content = full_content.lstrip("<think>").split("</think>")[0]
            full_content = ""

    # Inactive stream → try to salvage JSON from whatever we got
    if stream_inactive and not full_content:
        partial = think_content
        if partial:
            logger.warning("VLM inactive — salvaging JSON from %d-char thinking", len(partial))
            full_content = extract_json_from_thinking(partial)

    # Content empty but thinking has data → extract JSON
    if not full_content and think_content:
        logger.warning("VLM content=0 thinking=%d — extracting JSON", len(think_content))
        full_content = extract_json_from_thinking(think_content)

    # Two-pass: text-only second call to reformat thinking into JSON
    if full_content == think_content and think_content:
        logger.warning("VLM produced no JSON in answer — attempting reformat pass")
        try:
            json_extract = await _reformat_thinking_to_json(
                think_content, settings.base_url, settings.model,
            )
            if json_extract:
                full_content = json_extract
        except Exception as exc:
            logger.warning("VLM reformat pass failed: %s", exc)

    logger.info(
        "vision_chat DONE elapsed=%.1fs content=%d thinking=%d",
        time.time() - t0, len(full_content), len(think_content),
    )
    return {"content": full_content}


async def _reformat_thinking_to_json(
    thinking: str, base_url: str, model: str,
) -> str:
    """Text-only second pass: ask the model to convert its thinking to JSON.

    Used when the first vision pass produced reasoning but no usable answer.
    The reformat call is text-only (no images) and runs against the same
    endpoint with a deterministic ``temperature=0`` config.
    """
    last_think = thinking.rfind("<think>")
    fresh = thinking[last_think + 7:] if last_think != -1 else thinking
    context = fresh[:8000]

    payload = {
        "model": model,
        "messages": [
            {"role": "system",
             "content": "You are a JSON formatter. Output ONLY a valid JSON object."},
            {"role": "user", "content": (
                f"Engineering drawing analysis:\n\n{context}\n\n"
                "Convert to JSON schema:\n"
                '{"dimensions":[{"id":"D001","label":"short description","nominal":0,"unit":"mm or in","tolerance_plus":null,"tolerance_minus":null,"quantity":1}],"gdt":[],"threads":[{"id":"T001","spec":"e.g. M8x1.25","depth_mm":null,"quantity":1}],"material":null,"surface_finish":null,"notes":[]}\n\n'
                'If no dimensions found: '
                '{"dimensions":[],"gdt":[],"threads":[],"material":null,"surface_finish":null,"notes":["non_technical_page"]}'
            )},
        ],
        "stream":      True,
        "temperature": 0,
        "max_tokens":  8192,
    }
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    out = ""
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", endpoint, json=payload) as resp:
            if resp.status_code != 200:
                return ""
            buf = ""
            async for chunk in resp.aiter_bytes():
                buf += chunk.decode("utf-8", errors="replace")
                lines = buf.split("\n")
                buf = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    raw = line[6:] if line.startswith("data: ") else line
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                        delta = (data.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("content"):
                            out += delta["content"]
                        if (data.get("choices") or [{}])[0].get("finish_reason"):
                            break
                    except (json.JSONDecodeError, IndexError):
                        pass
                    if len(out) > 10_000:
                        break
    trimmed = out.strip()
    after = _strip_think_tags(trimmed)
    return after if after else trimmed


# ---------------------------------------------------------------------------
# Text-only chat (used by engine 3 sub-agents in future iterations)
# ---------------------------------------------------------------------------

async def text_chat(
    system_prompt: str,
    user_prompt: str,
    *,
    on_thinking: OnThinking = None,
    temperature: float = 0.0,
) -> dict:
    """Text-only streaming chat call. Returns ``{"content": str}``.

    Honours the same inactivity watchdog as :func:`vision_chat`.
    """
    settings = get_settings().llm
    endpoint = f"{settings.base_url}/v1/chat/completions"
    inactivity = settings.vlm_inactivity_seconds

    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "stream":      True,
        "temperature": temperature,
        "max_tokens":  settings.text_max_tokens,
        "chat_template_kwargs": {
            "enable_thinking":         True,
            "thinking_budget_tokens":  settings.text_thinking_budget_tokens,
        },
        "skip_special_tokens": False,
    }

    full_content = ""
    think_content = ""

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", endpoint, json=payload, timeout=None) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(
                    f"LLM HTTP {resp.status_code}: "
                    f"{body[:200].decode(errors='replace')}"
                )
            buf = ""
            aiter = resp.aiter_bytes().__aiter__()
            while True:
                try:
                    raw_bytes = await asyncio.wait_for(
                        aiter.__anext__(), timeout=inactivity,
                    )
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                buf += raw_bytes.decode("utf-8", errors="replace")
                lines = buf.split("\n")
                buf = lines.pop()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    raw = line[6:] if line.startswith("data: ") else line
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                        if delta.get("reasoning_content"):
                            think_content += delta["reasoning_content"]
                            if on_thinking:
                                await on_thinking(delta["reasoning_content"])
                        if delta.get("content"):
                            full_content += delta["content"]
                        if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                            break
                    except (json.JSONDecodeError, IndexError, KeyError):
                        pass
                if len(full_content) > _MAX_CONTENT_CHARS:
                    break

    if full_content and not think_content and "</think>" in full_content:
        idx = full_content.index("</think>")
        think_content = full_content[:idx].lstrip("<think>").strip()
        full_content = full_content[idx + 8:].strip()

    if not full_content and think_content:
        full_content = extract_json_from_thinking(think_content)

    return {"content": full_content}


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class LLMProvider(Protocol):
    """Provider interface for multi-turn streaming chat.

    Implementations return ``{"content": str, "thinking": str, "usage":
    dict | None, "model": str | None}``. ``usage`` carries token /
    cost telemetry when the backend reports it.
    """

    name: str

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None,
        on_thinking: OnThinking,
        temperature: float,
        response_format: dict | None,
        max_tokens: int | None,
        enable_thinking: bool,
        reasoning_effort: str | None,
    ) -> dict: ...


def _normalize_vllm_model(slug: str | None) -> str | None:
    """Strip the ``vllm:`` routing prefix when present."""
    if not slug:
        return None
    if slug.lower().startswith(_VLLM_PREFIX):
        return slug[len(_VLLM_PREFIX):] or None
    return slug


def _normalize_agent_model(slug: str | None) -> str | None:
    """Strip the ``agent:`` routing prefix when present."""
    if not slug:
        return None
    if slug.lower().startswith(_AGENT_PREFIX):
        return slug[len(_AGENT_PREFIX):] or None
    return slug


class VLLMProvider:
    """Local vLLM OpenAI-compatible backend (Qwen3-VL).

    Owns the Qwen-specific chat-template kwargs and the legacy
    ``<think>...</think>`` post-processing that newer providers don't
    need.
    """

    name = "vllm"

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None,
        on_thinking: OnThinking,
        temperature: float,
        response_format: dict | None,
        max_tokens: int | None,
        enable_thinking: bool,
        reasoning_effort: str | None,  # accepted for parity; ignored on vLLM
    ) -> dict:
        settings = get_settings().llm
        endpoint = f"{settings.base_url}/v1/chat/completions"
        inactivity = settings.vlm_inactivity_seconds
        resolved_model = _normalize_vllm_model(model) or settings.model

        payload: dict = {
            "model": resolved_model,
            "messages": messages,
            "stream":      True,
            "temperature": temperature,
            "max_tokens":  max_tokens or settings.text_max_tokens,
            "chat_template_kwargs": {
                "enable_thinking":         enable_thinking,
                "thinking_budget_tokens":  settings.text_thinking_budget_tokens,
            },
            "skip_special_tokens": False,
        }
        if response_format:
            payload["response_format"] = response_format

        full_content = ""
        think_content = ""
        usage: dict | None = None

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", endpoint, json=payload, timeout=None) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"LLM HTTP {resp.status_code}: "
                        f"{body[:200].decode(errors='replace')}"
                    )
                buf = ""
                aiter = resp.aiter_bytes().__aiter__()
                while True:
                    try:
                        raw_bytes = await asyncio.wait_for(
                            aiter.__anext__(), timeout=inactivity,
                        )
                    except (asyncio.TimeoutError, StopAsyncIteration):
                        break
                    buf += raw_bytes.decode("utf-8", errors="replace")
                    lines = buf.split("\n")
                    buf = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        raw = line[6:] if line.startswith("data: ") else line
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            if isinstance(chunk.get("usage"), dict):
                                usage = chunk["usage"]
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                            if delta.get("reasoning_content"):
                                think_content += delta["reasoning_content"]
                                if on_thinking:
                                    await on_thinking(delta["reasoning_content"])
                            if delta.get("content"):
                                full_content += delta["content"]
                            if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                                break
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass
                    if len(full_content) > _MAX_CONTENT_CHARS:
                        break
                    if len(think_content) > _MAX_THINKING_CHARS:
                        break

        if full_content and not think_content and "</think>" in full_content:
            idx = full_content.index("</think>")
            think_content = full_content[:idx].lstrip("<think>").strip()
            full_content = full_content[idx + 8:].strip()

        if not full_content and think_content:
            full_content = extract_json_from_thinking(think_content)

        return {
            "content":  full_content,
            "thinking": think_content,
            "usage":    usage,
            "model":    resolved_model,
        }


# Kimi/Moonshot native function-calling control tokens. Kimi is heavily
# tool-trained and emits these to frame a tool call even when we drive tool
# use via JSON-in-content (we do NOT pass an OpenAI `tools` array). The model
# terminates the call with `<|tool_call_end|>` *instead of* the JSON object's
# closing brace, so the streamed content arrives as a structurally-truncated
# object (more `{` than `}`) that `parse_model_json` cannot recover. We both
# (a) stop generation at these tokens and (b) strip + brace-repair any that
# still leak through. Kimi path only — the Qwen `VLLMProvider` never sees them.
_KIMI_TOOL_TOKENS = (
    "<|tool_calls_section_begin|>",
    "<|tool_call_begin|>",
    "<|tool_call_argument_begin|>",
    "<|tool_call_end|>",
    "<|tool_calls_section_end|>",
)

# Kimi-VL-A3B-Thinking-2506 emits its reasoning INLINE in ``content`` wrapped
# in literal-text markers — NOT vLLM special tokens, and NOT surfaced as
# ``reasoning_content`` (no Kimi reasoning parser is registered in this vLLM
# build). The shape is:  ◁think▷ …reasoning… ◁/think▷ {answer json}
# (U+25C1 LEFT-POINTING TRIANGLE / U+25B7 RIGHT-POINTING TRIANGLE). We split
# the block off client-side so the tool loop parses only the answer.
_KIMI_THINK_OPEN = "◁think▷"      # ◁think▷
_KIMI_THINK_CLOSE = "◁/think▷"    # ◁/think▷


def _split_kimi_think(text: str) -> tuple[str, str]:
    """Split a Kimi-VL ◁think▷…◁/think▷ payload into (reasoning, answer).

    * Closed block — answer is everything after the LAST ◁/think▷; reasoning
      is the text between the (first) open and that close marker.
    * Unclosed block (model hit the token cap mid-thought) — the whole thing
      is reasoning and there is no answer yet; the caller's
      :func:`extract_json_from_thinking` salvage then has a chance, else the
      tool loop retries with more budget.
    * No marker present — returns ``("", text)`` unchanged.
    """
    if _KIMI_THINK_OPEN not in text and _KIMI_THINK_CLOSE not in text:
        return "", text
    close = text.rfind(_KIMI_THINK_CLOSE)
    if close != -1:
        answer = text[close + len(_KIMI_THINK_CLOSE):].strip()
        head = text[:close]
        open_i = head.find(_KIMI_THINK_OPEN)
        reasoning = head[open_i + len(_KIMI_THINK_OPEN):] if open_i != -1 else head
        return reasoning.strip(), answer
    open_i = text.find(_KIMI_THINK_OPEN)
    reasoning = text[open_i + len(_KIMI_THINK_OPEN):] if open_i != -1 else text
    return reasoning.strip(), ""


def _repair_trailing_braces(text: str) -> str:
    """Close a JSON object whose tail brace(s)/string were lost to a cut.

    String-aware so braces inside string values are not miscounted. Appends
    exactly the trailing ``}`` (and a closing ``"`` if a string was left
    dangling) needed to balance the object — nothing more.
    """
    depth = 0
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    if in_str:
        text += '"'
    if depth > 0:
        text += "}" * depth
    return text


def _sanitize_agent_content(text: str) -> str:
    """Cut at the first leaked Kimi tool-call token, then brace-repair.

    Everything from the first control token onward is native-tool-call framing,
    not our JSON — drop it. The cut (or the token standing in for the final
    brace) leaves the object short its closing brace, so repair it so the
    tool loop's :func:`parse_model_json` can parse a clean object.
    """
    if not text:
        return text
    cut = len(text)
    for tok in _KIMI_TOOL_TOKENS:
        i = text.find(tok)
        if i != -1 and i < cut:
            cut = i
    if cut < len(text):
        text = text[:cut]
    text = text.rstrip()
    if "{" in text:
        text = _repair_trailing_braces(text)
    return text


class AgentVLLMProvider:
    """Dedicated vLLM backend for the Engine-3 agentic planner (Kimi-Linear).

    Why a separate provider instead of reusing :class:`VLLMProvider`? The
    Kimi-Linear-48B-A3B-Instruct endpoint differs from the Qwen3-VL one in
    two ways that matter for the JSON tool loop:

      * **No ``response_format``.** Kimi ships a slow tiktoken tokenizer,
        so no vLLM grammar backend (xgrammar / guidance / llguidance) can
        attach — requesting guided JSON *crashes the engine core*. We drop
        ``response_format`` entirely and lean on the system prompt's
        "respond with EXACTLY ONE JSON object" contract plus the robust
        :func:`parse_model_json` salvage in the tool loop.
      * **No Qwen ``chat_template_kwargs``.** ``enable_thinking`` /
        ``thinking_budget_tokens`` are Qwen-template knobs; Kimi-Linear is
        a non-reasoning Instruct model with its own chat template.

    Everything else — the SSE parse, ``<think>`` salvage, usage capture —
    mirrors :class:`VLLMProvider` so loop behaviour stays predictable. The
    endpoint comes from ``AGENT_LLM_URL`` (falls back to the vision
    ``base_url`` with a warning if that is somehow unset).
    """

    name = "agent_vllm"

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None,
        on_thinking: OnThinking,
        temperature: float,             # IGNORED — see agent_temperature below
        response_format: dict | None,  # accepted for parity; NEVER forwarded
        max_tokens: int | None,
        enable_thinking: bool,          # accepted for parity; ignored
        reasoning_effort: str | None,   # accepted for parity; ignored
    ) -> dict:
        settings = get_settings().llm
        base_url = (settings.agent_base_url or settings.base_url).rstrip("/")
        if not settings.agent_base_url:
            logger.warning(
                "AgentVLLMProvider: AGENT_LLM_URL unset — falling back to "
                "vision base_url %s", base_url,
            )
        endpoint = f"{base_url}/v1/chat/completions"
        inactivity = settings.agent_inactivity_seconds
        resolved_model = _normalize_agent_model(model) or settings.agent_model

        payload: dict = {
            "model": resolved_model,
            "messages": messages,
            "stream":      True,
            # Ask vLLM for a trailing usage chunk (streaming omits it
            # otherwise) so per-turn token telemetry is captured.
            "stream_options": {"include_usage": True},
            # Kimi-tuned sampling, NOT the inbound `temperature`. The agentic
            # loop passes 0.0 (a Qwen-era deterministic default), but greedy
            # decoding drops Kimi-Linear into a degenerate repetition attractor
            # ('{"!!!!…'). Use Moonshot's recommended non-greedy sampling.
            "temperature": settings.agent_temperature,
            "top_p":       settings.agent_top_p,
            "max_tokens":  max_tokens or settings.agent_max_tokens,
            # Halt cleanly at Kimi's native tool-call framing tokens so one
            # assistant turn = one JSON object (our protocol), and the model
            # can't append a second native-format tool-call section. `stop` is
            # a plain sampling param (unlike response_format) — safe for Kimi.
            "stop": list(_KIMI_TOOL_TOKENS),
        }
        # Deliberately NO `response_format` and NO `chat_template_kwargs` —
        # see the class docstring; both break the Kimi endpoint.

        headers = {"Content-Type": "application/json"}
        if settings.agent_api_key:
            headers["Authorization"] = f"Bearer {settings.agent_api_key}"

        full_content = ""
        think_content = ""
        usage: dict | None = None

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", endpoint, headers=headers, json=payload, timeout=None,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"Agent LLM HTTP {resp.status_code}: "
                        f"{body[:200].decode(errors='replace')}"
                    )
                buf = ""
                aiter = resp.aiter_bytes().__aiter__()
                while True:
                    try:
                        raw_bytes = await asyncio.wait_for(
                            aiter.__anext__(), timeout=inactivity,
                        )
                    except (asyncio.TimeoutError, StopAsyncIteration):
                        break
                    buf += raw_bytes.decode("utf-8", errors="replace")
                    lines = buf.split("\n")
                    buf = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        raw = line[6:] if line.startswith("data: ") else line
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            if isinstance(chunk.get("usage"), dict):
                                usage = chunk["usage"]
                            delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                            if delta.get("reasoning_content"):
                                think_content += delta["reasoning_content"]
                                if on_thinking:
                                    await on_thinking(delta["reasoning_content"])
                            if delta.get("content"):
                                full_content += delta["content"]
                            if (chunk.get("choices") or [{}])[0].get("finish_reason"):
                                break
                        except (json.JSONDecodeError, IndexError, KeyError):
                            pass
                    if len(full_content) > _MAX_CONTENT_CHARS:
                        break
                    if len(think_content) > _MAX_THINKING_CHARS:
                        break

        # Kimi-VL-A3B-Thinking wraps reasoning inline in ◁think▷…◁/think▷
        # (literal text in `content`, never reasoning_content). Pull the
        # answer out from after the closing marker; keep the reasoning for the
        # trace. Falls through to the legacy <think> handling for other models.
        if _KIMI_THINK_OPEN in full_content or _KIMI_THINK_CLOSE in full_content:
            reasoning, answer = _split_kimi_think(full_content)
            if reasoning and not think_content:
                think_content = reasoning
            full_content = answer
        elif full_content and not think_content and "</think>" in full_content:
            idx = full_content.index("</think>")
            think_content = full_content[:idx].lstrip("<think>").strip()
            full_content = full_content[idx + 8:].strip()

        if not full_content and think_content:
            full_content = extract_json_from_thinking(think_content)

        # Strip + brace-repair any leaked Kimi tool-call control tokens so the
        # tool loop receives a parseable single JSON object (Kimi path only).
        full_content = _sanitize_agent_content(full_content)

        return {
            "content":  full_content,
            "thinking": think_content,
            "usage":    usage,
            "model":    resolved_model,
        }


_VLLM_PROVIDER = VLLMProvider()
_AGENT_PROVIDER = AgentVLLMProvider()


def _select_provider(model: str | None) -> LLMProvider:
    """Resolve a model slug to a backend — **failover escape-hatch only**.

    The agentic engine (Engine 3) is Kimi-only: :func:`chat_messages` always
    routes its primary call to :class:`AgentVLLMProvider` regardless of slug,
    so this helper is no longer on the hot path. It survives solely to resolve
    the optional, off-by-default ``AGENT_LLM_FAILOVER`` slug, where an operator
    may *explicitly* point at a backup planner:

      * ``"agent:<name>"`` → :class:`AgentVLLMProvider` (Kimi pod).
      * anything else (``None`` / ``"vllm:<name>"``) → :class:`VLLMProvider`.

    Qwen is never reached implicitly by the agentic engine — only via this
    deliberate failover opt-in.
    """
    if model and model.strip().lower().startswith(_AGENT_PREFIX):
        return _AGENT_PROVIDER
    return _VLLM_PROVIDER


# ---------------------------------------------------------------------------
# Multi-turn chat (used by the agentic engine's ReAct loop)
# ---------------------------------------------------------------------------

async def chat_messages(
    messages: list[dict],
    *,
    model: str | None = None,
    on_thinking: OnThinking = None,
    temperature: float = 0.0,
    response_format: dict | None = None,
    max_tokens: int | None = None,
    enable_thinking: bool = True,
    reasoning_effort: str | None = None,
) -> dict:
    """Multi-turn streaming chat. Returns ``{"content", "thinking", "usage", "model"}``.

    This is the agentic engine's (Engine 3) sole LLM entry, and Engine 3 is
    **Kimi-only** — the primary call always routes to
    :class:`AgentVLLMProvider` (the Kimi-Linear pod), irrespective of the
    ``model`` slug. Qwen drives Engine 1's drawing extraction via the separate
    :func:`vision_chat` path and is never reached here, except through the
    explicit, off-by-default ``AGENT_LLM_FAILOVER`` escape hatch below. The
    agentic loop carries tool results forward as additional user turns.

    Parameters
    ----------
    messages:
        OpenAI-style chat messages.
    model:
        Model slug forwarded to the Kimi provider (the ``"agent:"`` prefix is
        stripped to recover the served model name). Does not change routing.
    on_thinking:
        Callback for reasoning deltas; forwarded to the SSE bridge.
    temperature:
        Sampling temperature (0 for the deterministic agentic loop).
    response_format:
        Accepted for signature parity but NEVER forwarded — guided JSON
        crashes the Kimi engine (slow tiktoken, no grammar backend).
    max_tokens:
        Max-tokens cap; falls back to the agent settings default.
    enable_thinking:
        Accepted for parity; ignored by the Kimi backend (non-reasoning
        Instruct model with its own chat template).
    reasoning_effort:
        ``"low" | "medium" | "high"``. Accepted for parity; ignored.
    """
    # Engine 3 is Kimi-only — never route the agentic loop to Qwen implicitly.
    provider = _AGENT_PROVIDER
    try:
        return await provider.chat(
            messages,
            model=model,
            on_thinking=on_thinking,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            reasoning_effort=reasoning_effort,
        )
    except (httpx.HTTPError, RuntimeError) as exc:
        # Explicit, off-by-default escape hatch: if the Kimi pod is
        # unreachable / erroring and an operator has set AGENT_LLM_FAILOVER,
        # retry once on that slug (resolved via _select_provider — this is the
        # ONLY place Qwen can re-enter the agentic engine, and only by
        # deliberate config). A different LLM planner, not a rule-based
        # fallback, so it respects the "agent only" design.
        failover = get_settings().llm.agent_failover
        if failover:
            logger.warning(
                "agent LLM call failed (%s) — failing over to %r", exc, failover,
            )
            return await _select_provider(failover).chat(
                messages,
                model=failover,
                on_thinking=on_thinking,
                temperature=temperature,
                response_format=response_format,
                max_tokens=max_tokens,
                enable_thinking=enable_thinking,
                reasoning_effort=reasoning_effort,
            )
        raise


__all__ = [
    "chat_messages",
    "vision_chat",
    "text_chat",
    "parse_model_json",
    "extract_json_from_thinking",
    "find_matching_brace",
    "VLLMProvider",
    "AgentVLLMProvider",
    "LLMProvider",
]
