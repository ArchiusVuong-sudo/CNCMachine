"""Prompt builders for the RAG engine.

Two messages — built afresh per component, not cached, because they
embed retrieved analogues which vary per call.

  * :func:`build_system_prompt`   — engine-agnostic role + hard rules
  * :func:`build_user_prompt`     — component + analogues + catalog
                                    + output schema

The shape we ask the LLM to emit is intentionally flatter than the
agentic engine's ``OUTPUT_SCHEMA``: tools and cutting parameters are
inlined per operation rather than split into ``tools_per_operation`` and
``parameters_per_operation`` lists. The agentic shape made sense for a
phased ReAct loop where tools were decided in phase C and parameters
in phase D; for a single-shot RAG call, flat is easier for both the
model and the projection layer.
"""

from .system import OUTPUT_SCHEMA, build_system_prompt, invalidate_cache
from .user import build_user_prompt

__all__ = [
    "OUTPUT_SCHEMA",
    "build_system_prompt",
    "build_user_prompt",
    "invalidate_cache",
]
