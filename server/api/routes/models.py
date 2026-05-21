"""GET /v1/models — list available planner LLMs for the UI dropdown.

The Engine 3 planner can run against either local vLLM (Qwen3-VL) or any
OpenRouter-hosted model. This endpoint returns the union the operator is
allowed to pick from:

  * The local vLLM model (always included; prefixed ``vllm:`` to force
    routing through :class:`server.infra.llm.VLLMProvider`).
  * Every OpenRouter slug listed in :attr:`LLMSettings.openrouter_allowed_models`
    that OpenRouter actually exposes, enriched with capability /
    pricing metadata fetched from ``GET /api/v1/models``.

Failure modes are intentionally lenient: if OpenRouter is unreachable or
``OPENROUTER_API_KEY`` is unset, we still return the vLLM entry so the
UI can render *something*. The ``warnings`` field surfaces the reason.

The OpenRouter catalog is cached in-process for ``_CACHE_TTL_SECONDS``
to avoid hammering their API on every page load.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter

from ...core.settings import get_settings

logger = logging.getLogger("cncserver.api.models")

router = APIRouter(prefix="/v1", tags=["models"])

_CACHE_TTL_SECONDS = 3600.0
_cache: dict[str, Any] = {"fetched_at": 0.0, "models": None, "error": None}


async def _fetch_openrouter_catalog() -> tuple[dict[str, dict] | None, str | None]:
    """Fetch the OpenRouter catalog and bucket it by slug.

    Returns ``(by_slug, None)`` on success or ``(None, reason)`` on
    failure. Uses an in-process TTL cache so repeat polls during a
    session don't burn quota.
    """
    now = time.monotonic()
    if (
        _cache["models"] is not None
        and now - float(_cache["fetched_at"] or 0.0) < _CACHE_TTL_SECONDS
    ):
        return _cache["models"], _cache["error"]

    settings = get_settings().llm
    if not settings.openrouter_api_key:
        msg = "OPENROUTER_API_KEY is not configured"
        _cache.update(fetched_at=now, models=None, error=msg)
        return None, msg

    endpoint = f"{settings.openrouter_base_url}/models"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    if settings.openrouter_http_referer:
        headers["HTTP-Referer"] = settings.openrouter_http_referer
    if settings.openrouter_app_title:
        headers["X-Title"] = settings.openrouter_app_title

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(endpoint, headers=headers)
        if resp.status_code != 200:
            msg = f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}"
            logger.warning("models: %s", msg)
            _cache.update(fetched_at=now, models=None, error=msg)
            return None, msg
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        msg = f"OpenRouter fetch failed: {exc.__class__.__name__}: {exc}"
        logger.warning("models: %s", msg)
        _cache.update(fetched_at=now, models=None, error=msg)
        return None, msg

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        msg = "OpenRouter response missing 'data' list"
        _cache.update(fetched_at=now, models=None, error=msg)
        return None, msg

    by_slug: dict[str, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        slug = item.get("id")
        if isinstance(slug, str):
            by_slug[slug] = item

    _cache.update(fetched_at=now, models=by_slug, error=None)
    logger.info("models: cached %d OpenRouter entries", len(by_slug))
    return by_slug, None


def _capabilities(entry: dict) -> dict[str, bool]:
    """Project an OpenRouter ``models`` entry to a capability map."""
    supported = entry.get("supported_parameters") or []
    if not isinstance(supported, list):
        supported = []
    flags = {p for p in supported if isinstance(p, str)}
    architecture = entry.get("architecture") or {}
    input_modalities = architecture.get("input_modalities") or []
    if not isinstance(input_modalities, list):
        input_modalities = []
    return {
        "tools":      "tools" in flags or "tool_choice" in flags,
        "json_mode":  "response_format" in flags,
        "reasoning":  "reasoning" in flags or "include_reasoning" in flags,
        "vision":     "image" in input_modalities,
    }


def _vllm_entry() -> dict:
    """Static descriptor for the local vLLM Qwen3-VL backend."""
    settings = get_settings().llm
    return {
        "id":            f"vllm:{settings.model}",
        "label":         f"vLLM · {settings.model}",
        "provider":      "vllm",
        "vendor":        "qwen",
        "context_tokens": None,
        "pricing":       None,
        "capabilities":  {
            "tools":     False,
            "json_mode": True,
            "reasoning": True,
            "vision":    True,
        },
        "is_default":    False,
    }


def _openrouter_entry(slug: str, entry: dict | None, is_default: bool) -> dict:
    """Project one OpenRouter slug to the wire shape consumed by the UI."""
    if entry is None:
        return {
            "id":            slug,
            "label":         slug,
            "provider":      "openrouter",
            "vendor":        slug.split("/", 1)[0] if "/" in slug else "unknown",
            "context_tokens": None,
            "pricing":       None,
            "capabilities":  {},
            "is_default":    is_default,
            "available":     False,
        }
    pricing = entry.get("pricing") or {}
    return {
        "id":      slug,
        "label":   entry.get("name") or slug,
        "provider": "openrouter",
        "vendor":   slug.split("/", 1)[0] if "/" in slug else (entry.get("hugging_face_id") or "unknown"),
        "context_tokens": entry.get("context_length"),
        "pricing": {
            "prompt":     pricing.get("prompt"),
            "completion": pricing.get("completion"),
            "currency":   "USD",
        } if pricing else None,
        "capabilities": _capabilities(entry),
        "is_default":   is_default,
        "available":    True,
    }


@router.get("/models")
async def list_models() -> dict:
    """Return the merged dropdown payload: vLLM + allowed OpenRouter models."""
    settings = get_settings().llm
    allowed = list(settings.openrouter_allowed_models or ())
    default_model = settings.openrouter_default_model or ""

    by_slug, error = await _fetch_openrouter_catalog()

    models: list[dict] = [_vllm_entry()]
    warnings: list[str] = []

    if error:
        warnings.append(error)

    for slug in allowed:
        entry = (by_slug or {}).get(slug)
        models.append(_openrouter_entry(slug, entry, is_default=(slug == default_model)))

    return {
        "default":  default_model or models[0]["id"],
        "models":   models,
        "warnings": warnings,
    }
