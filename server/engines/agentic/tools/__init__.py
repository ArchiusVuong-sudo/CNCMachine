"""Tool layer for the agentic engine.

Five callables the agent invokes during reasoning:

  * :func:`kb_read`            — fetch a KB markdown/text file
  * :func:`kb_find_analogues`  — rank analogue parts from parts.csv
  * :func:`kb_query_csv`       — filter rows from extracted/*.csv
  * ``catalog_lookup``         — query the per-user shop catalog (factory-bound)
  * :func:`compute_cycle_time` — calibrate raw NC minutes to per-piece time

Plus four workspace tools so the agent can checkpoint its progress and
resume after an interrupt:

  * ``workspace_list / read / write / delete`` — bound per component via
    :func:`make_workspace_tools`.

All tools return JSON-safe dicts. Errors never raise — they come back as
``{"error": "..."}`` so the agent loop can recover or escalate.

:data:`ALL_TOOL_SPECS` is the function-calling spec list used to build
the system prompt's tool catalog. Static tools are wired by name in
:mod:`server.engines.agentic.agent`; the per-analysis ``catalog_lookup``
and the per-component workspace tools are bound there via factories.
"""
from __future__ import annotations

from .analogue import (
    ANALOGUE_TOOL_SPECS,
    kb_adopt_routing,
    make_holdout_aware_adopt_routing,
)
from .catalog import CATALOG_TOOL_SPECS, make_catalog_lookup
from .compute import COMPUTE_TOOL_SPECS, compute_cycle_time
from .kb import (
    KB_TOOL_SPECS,
    kb_find_analogues,
    kb_query_csv,
    kb_read,
    make_holdout_aware_kb_tools,
    make_self_aware_find_analogues,
    normalize_part_id,
)
from .memory import MEMORY_TOOL_SPECS, make_memory_tools
from .workspace_tool import WORKSPACE_TOOL_SPECS, make_workspace_tools

ALL_TOOL_SPECS: list[dict] = [
    *KB_TOOL_SPECS,
    *ANALOGUE_TOOL_SPECS,
    *CATALOG_TOOL_SPECS,
    *COMPUTE_TOOL_SPECS,
    *MEMORY_TOOL_SPECS,
    *WORKSPACE_TOOL_SPECS,
]

__all__ = [
    "kb_read",
    "kb_find_analogues",
    "kb_query_csv",
    "kb_adopt_routing",
    "make_holdout_aware_kb_tools",
    "make_holdout_aware_adopt_routing",
    "make_self_aware_find_analogues",
    "normalize_part_id",
    "make_catalog_lookup",
    "compute_cycle_time",
    "make_memory_tools",
    "make_workspace_tools",
    "ALL_TOOL_SPECS",
    "KB_TOOL_SPECS",
    "ANALOGUE_TOOL_SPECS",
    "CATALOG_TOOL_SPECS",
    "COMPUTE_TOOL_SPECS",
    "MEMORY_TOOL_SPECS",
    "WORKSPACE_TOOL_SPECS",
]
