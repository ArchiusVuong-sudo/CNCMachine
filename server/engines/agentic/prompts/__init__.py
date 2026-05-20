"""Prompt builders for the single-loop agentic engine.

Two public symbols only:

  * :func:`build_system_prompt` — the role + protocol + tool catalog +
    workspace contract + hard rules. Component-agnostic; built once per
    process and cached.
  * :func:`build_agent_user_message` — per-component inputs + resume
    hint + output schema. Built fresh per component.

The :data:`OUTPUT_SCHEMA` is exposed so tests / downstream code can
introspect what shape the agent is expected to produce.
"""
from __future__ import annotations

from .agent import OUTPUT_SCHEMA, build_agent_user_message
from .system import build_system_prompt, invalidate_cache

__all__ = [
    "build_system_prompt",
    "build_agent_user_message",
    "invalidate_cache",
    "OUTPUT_SCHEMA",
]
