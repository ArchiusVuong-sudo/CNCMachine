"""Agentic engine — single-loop LLM process planner.

The dispatcher fans out one async task per component; each task runs a
single ReAct/JSON loop (see :mod:`server.engines.agentic.agent`) that
picks the machine, lays out operations, selects tools, sets feeds and
speeds, and emits a ``final`` plan in one go. There is no Phase A→B→C→D
chain anymore.

Per-component state is checkpointed to a small on-disk workspace so the
loop survives interruption — see :mod:`server.engines.agentic.workspace`.

Public surface::

    from server.engines.agentic import dispatch

    plan = await dispatch(
        drawing, assembly, step_bytes,
        batch_size=..., user_id=..., supabase_client=..., catalog=...,
        on_event=..., analysis_id=...,
    )
"""
from __future__ import annotations

from .dispatcher import dispatch

__all__ = ["dispatch"]
