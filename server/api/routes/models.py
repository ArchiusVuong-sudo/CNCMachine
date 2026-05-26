"""GET /v1/models — list available planner LLMs for the UI dropdown.

The Engine 3 planner runs against one of two local vLLM backends:

  * The Qwen3-VL vLLM model (always included; prefixed ``vllm:`` to force
    routing through :class:`server.infra.llm.VLLMProvider`).
  * The Kimi-Linear agent pod, when ``AGENT_LLM_URL`` is configured
    (prefixed ``agent:`` to route through
    :class:`server.infra.llm.AgentVLLMProvider`). This is the Engine-3
    default whenever it is set.

There is no external catalog fetch — both entries are derived purely from
settings, so the endpoint never makes a network call.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter

from ...core.settings import get_settings

logger = logging.getLogger("cncserver.api.models")

router = APIRouter(prefix="/v1", tags=["models"])


def _vllm_entry(is_default: bool) -> dict:
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
        "is_default":    is_default,
        "available":     True,
    }


def _agent_entry(is_default: bool) -> dict:
    """Static descriptor for the Kimi-Linear agent backend."""
    settings = get_settings().llm
    return {
        "id":            f"agent:{settings.agent_model}",
        "label":         f"Kimi · {settings.agent_model}",
        "provider":      "agent_vllm",
        "vendor":        "moonshot",
        "context_tokens": None,
        "pricing":       None,
        "capabilities":  {
            "tools":     False,
            "json_mode": False,   # prompt-based JSON only (no guided decoding)
            "reasoning": False,
            "vision":    False,
        },
        "is_default":    is_default,
        "available":     settings.agent_base_url is not None,
    }


@router.get("/models")
async def list_models() -> dict:
    """Return the dropdown payload: Qwen vLLM + Kimi agent (when configured)."""
    settings = get_settings().llm

    # The agent (Kimi) backend is the Engine-3 default whenever AGENT_LLM_URL
    # is set; otherwise the Qwen vLLM backend is the only planner.
    agent_default = (settings.agent_default_model or "").strip()
    agent_is_default = bool(agent_default and settings.agent_base_url)

    models: list[dict] = [_vllm_entry(is_default=not agent_is_default)]
    warnings: list[str] = []

    if settings.agent_base_url:
        models.append(_agent_entry(is_default=agent_is_default))
    else:
        warnings.append("AGENT_LLM_URL is not configured — Kimi agent backend unavailable")

    default_id = next((m["id"] for m in models if m["is_default"]), models[0]["id"])

    return {
        "default":  default_id,
        "models":   models,
        "warnings": warnings,
    }
