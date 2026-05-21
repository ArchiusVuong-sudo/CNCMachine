"""LLM transport layer — vLLM (Qwen3-VL) + OpenRouter.

Why this exists
---------------
The pipeline talks to two distinct backends, and the integration quirks
of each are isolated here so the engines stay focused on extraction
logic:

  * **vLLM (Qwen3-VL)** — local OpenAI-compatible server. Used by
    Engine 1 (vision drawing extraction) and as a fallback text backend.
    Qwen-specific ``chat_template_kwargs`` + ``<think>...</think>``
    parsing live here.
  * **OpenRouter** — single OpenAI-compatible gateway in front of
    Claude / GPT / Gemini / DeepSeek / Qwen. Used by Engine 3 (agentic
    planner) as the default. Reasoning deltas arrive in three possible
    shapes (``delta.reasoning`` / ``delta.reasoning_content`` /
    ``delta.reasoning_details[*].text``); we accept all of them.

Per-request routing happens via :func:`chat_messages`'s ``model``
parameter:

  * ``None`` or ``"vllm:<name>"`` → :class:`VLLMProvider`.
  * Any other slug containing ``/`` (e.g. ``"anthropic/claude-sonnet-4.5"``)
    → :class:`OpenRouterProvider`.

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

# Model-slug prefix that forces routing back to the local vLLM provider.
# Anything else containing "/" is treated as an OpenRouter slug.
_VLLM_PREFIX = "vllm:"


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


class OpenRouterProvider:
    """OpenRouter OpenAI-compatible gateway.

    Differences from vLLM:

      * Auth header ``Authorization: Bearer <key>`` is mandatory.
      * Optional ``HTTP-Referer`` and ``X-Title`` headers identify the
        app on the OpenRouter dashboard.
      * Reasoning is requested via the unified ``reasoning: {effort: ...}``
        param. OpenRouter normalises it to each upstream's native shape
        (e.g. Claude ``thinking``, GPT-5 ``reasoning_effort``, Gemini
        ``thinkingBudget``).
      * Reasoning deltas may arrive as ``delta.reasoning`` (string),
        ``delta.reasoning_content`` (string), or
        ``delta.reasoning_details[*].text`` (list of objects). We accept
        all three.
      * ``response_format={"type": "json_object"}`` works across most
        backends OpenRouter fronts; we pass it through unchanged.

    No Qwen ``<think>...</think>`` parsing here — providers fronted by
    OpenRouter emit clean ``delta.content`` only.
    """

    name = "openrouter"

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
    ) -> dict:
        settings = get_settings().llm
        if not settings.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not configured — cannot route to "
                f"OpenRouter model {model!r}."
            )
        endpoint = f"{settings.openrouter_base_url}/chat/completions"
        inactivity = settings.openrouter_inactivity_seconds
        resolved_model = model or settings.openrouter_default_model

        payload: dict = {
            "model": resolved_model,
            "messages": messages,
            "stream":      True,
            "temperature": temperature,
            "max_tokens":  max_tokens or settings.openrouter_max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        if enable_thinking:
            effort = (reasoning_effort or settings.openrouter_default_reasoning_effort or "").strip().lower()
            if effort in ("low", "medium", "high"):
                payload["reasoning"] = {"effort": effort}

        headers = {
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type":  "application/json",
        }
        if settings.openrouter_http_referer:
            headers["HTTP-Referer"] = settings.openrouter_http_referer
        if settings.openrouter_app_title:
            headers["X-Title"] = settings.openrouter_app_title

        full_content = ""
        think_content = ""
        usage: dict | None = None
        response_model: str | None = None

        timeout = httpx.Timeout(settings.openrouter_request_timeout, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", endpoint, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise RuntimeError(
                        f"OpenRouter HTTP {resp.status_code}: "
                        f"{body[:300].decode(errors='replace')}"
                    )
                buf = ""
                aiter = resp.aiter_bytes().__aiter__()
                while True:
                    try:
                        raw_bytes = await asyncio.wait_for(
                            aiter.__anext__(), timeout=inactivity,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            "OpenRouter inactivity timeout after %gs (model=%s)",
                            inactivity, resolved_model,
                        )
                        break
                    except StopAsyncIteration:
                        break

                    buf += raw_bytes.decode("utf-8", errors="replace")
                    lines = buf.split("\n")
                    buf = lines.pop()
                    for line in lines:
                        line = line.strip()
                        if not line or line.startswith(":"):
                            # OpenRouter emits SSE keep-alive comments
                            # ("` `: OPENROUTER PROCESSING`") that must
                            # be ignored.
                            continue
                        raw = line[6:] if line.startswith("data: ") else line
                        if raw == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        if isinstance(chunk.get("usage"), dict):
                            usage = chunk["usage"]
                        if isinstance(chunk.get("model"), str):
                            response_model = chunk["model"]
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}

                        # Accept all three reasoning-delta shapes that
                        # OpenRouter producers emit.
                        reasoning_piece: str | None = None
                        if isinstance(delta.get("reasoning"), str):
                            reasoning_piece = delta["reasoning"]
                        elif isinstance(delta.get("reasoning_content"), str):
                            reasoning_piece = delta["reasoning_content"]
                        else:
                            details = delta.get("reasoning_details")
                            if isinstance(details, list):
                                pieces = []
                                for d in details:
                                    if isinstance(d, dict) and isinstance(d.get("text"), str):
                                        pieces.append(d["text"])
                                if pieces:
                                    reasoning_piece = "".join(pieces)
                        if reasoning_piece:
                            think_content += reasoning_piece
                            if on_thinking:
                                await on_thinking(reasoning_piece)

                        if isinstance(delta.get("content"), str):
                            full_content += delta["content"]

                        if (choices[0] or {}).get("finish_reason"):
                            break

                    if len(full_content) > _MAX_CONTENT_CHARS:
                        logger.warning("OpenRouter content > %d chars — breaking", _MAX_CONTENT_CHARS)
                        break
                    if len(think_content) > _MAX_THINKING_CHARS:
                        logger.warning("OpenRouter thinking > %d chars — breaking", _MAX_THINKING_CHARS)
                        break

        # Fallback: if the model wrapped its JSON answer in <think>...</think>
        # (a few OSS models do) salvage it the same way as vLLM.
        if not full_content and think_content:
            logger.warning(
                "OpenRouter content=0 thinking=%d — extracting JSON",
                len(think_content),
            )
            full_content = extract_json_from_thinking(think_content)

        return {
            "content":  full_content,
            "thinking": think_content,
            "usage":    usage,
            "model":    response_model or resolved_model,
        }


_VLLM_PROVIDER = VLLMProvider()
_OPENROUTER_PROVIDER = OpenRouterProvider()


def _select_provider(model: str | None) -> LLMProvider:
    """Route a model slug to the right backend.

    Rules:
      * ``None`` → :class:`VLLMProvider` (legacy default).
      * ``"vllm:<name>"`` → :class:`VLLMProvider` with ``<name>``.
      * Any slug containing ``"/"`` → :class:`OpenRouterProvider`.
      * Anything else → :class:`VLLMProvider` (treats bare names like
        ``"Qwen/Qwen3-VL-32B-Instruct-FP8"`` correctly only when prefixed
        with ``vllm:``; otherwise OpenRouter is preferred because the
        slug shape matches its catalog).
    """
    if not model:
        return _VLLM_PROVIDER
    slug = model.strip()
    if slug.lower().startswith(_VLLM_PREFIX):
        return _VLLM_PROVIDER
    if "/" in slug:
        return _OPENROUTER_PROVIDER
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

    Routes to vLLM or OpenRouter based on ``model`` (see
    :func:`_select_provider`). The agentic loop carries tool results
    forward as additional user turns and asks for JSON mode via
    ``response_format={"type": "json_object"}``.

    Parameters
    ----------
    messages:
        OpenAI-style chat messages.
    model:
        Optional model slug. ``None`` and ``"vllm:..."`` route to local
        vLLM; ``"<vendor>/<name>"`` routes to OpenRouter.
    on_thinking:
        Callback for reasoning deltas; forwarded to the SSE bridge.
    temperature:
        Sampling temperature (0 for the deterministic agentic loop).
    response_format:
        Pass-through. ``{"type": "json_object"}`` forces JSON output.
    max_tokens:
        Per-provider max-tokens cap; falls back to settings defaults.
    enable_thinking:
        Toggle reasoning. On vLLM this drives Qwen's
        ``chat_template_kwargs``; on OpenRouter this enables the unified
        ``reasoning: {effort: ...}`` param.
    reasoning_effort:
        ``"low" | "medium" | "high"``. Only used by OpenRouter; ignored
        by vLLM.
    """
    provider = _select_provider(model)
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


__all__ = [
    "chat_messages",
    "vision_chat",
    "text_chat",
    "parse_model_json",
    "extract_json_from_thinking",
    "find_matching_brace",
    "VLLMProvider",
    "OpenRouterProvider",
    "LLMProvider",
]
