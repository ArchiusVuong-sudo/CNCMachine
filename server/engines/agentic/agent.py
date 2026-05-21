"""Single-loop per-component agent.

Replaces the previous deterministic Phase A → Phase B → Phase C → Phase D
chain. One LLM-driven loop now produces the whole plan in one shot:
machine pick + operations + tools + parameters + totals.

The coordinator runs this once per component in parallel. Failure to
emit a valid ``final`` (iteration cap, parse blowup, chat error) raises
:class:`ToolLoopError` — the coordinator catches it and records the
component as failed without stopping the rest of the assembly.

The output dict matches what :func:`server.engines.agentic.coordinator._build_routing_rows`
expects, so the routing-row projection is unchanged.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from ...core.events import OnEvent, safe_emit
from .prompts import build_agent_user_message, build_system_prompt
from .tool_loop import ToolLoopError, run_tool_loop
from .tools import (
    compute_cycle_time,
    kb_find_analogues,
    kb_query_csv,
    kb_read,
    make_catalog_lookup,
    make_workspace_tools,
)
from .workspace import ComponentWorkspace

logger = logging.getLogger("cncserver.engines.agentic.agent")

OnThinking = Callable[[str], Awaitable[None]] | None

# Cap the per-component plan dump for the trace log. Matches the cap in
# tracing.py — keeps a very chatty model from flooding stdout.
_PLAN_DUMP_CHARS = 8000


def _dump_plan(payload: dict) -> str:
    try:
        text = json.dumps(payload, indent=2, default=str, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover
        return f"<serialize failed: {exc}>"
    if len(text) > _PLAN_DUMP_CHARS:
        return text[:_PLAN_DUMP_CHARS] + f"\n... <truncated {len(text) - _PLAN_DUMP_CHARS} chars>"
    return text


def _pick_default_machine(plan: dict) -> str | None:
    """Pick rank-1 from ``top_machines`` when the agent didn't set ``chosen_machine_id``.

    The UI lets the operator override this from the top-3 list; the
    default is just the highest-ranked machine.
    """
    existing = plan.get("chosen_machine_id")
    if existing:
        return str(existing)
    top = plan.get("top_machines") or []
    if not top:
        return None
    ranked = sorted(top, key=lambda m: (m or {}).get("rank", 99))
    rank1 = ranked[0] or {}
    return rank1.get("machine_id")


def _build_tools(
    catalog: dict | None,
    workspace: ComponentWorkspace | None,
) -> dict[str, Callable[..., Any]]:
    """Wire the per-analysis catalog + per-component workspace into the tool set.

    The dict's keys MUST match the ``"name"`` fields in
    :data:`server.engines.agentic.tools.ALL_TOOL_SPECS` — that's the
    contract the agent learns about in the system prompt.
    """
    return {
        "kb_read": kb_read,
        "kb_find_analogues": kb_find_analogues,
        "kb_query_csv": kb_query_csv,
        "catalog_lookup": make_catalog_lookup(catalog or {}),
        "compute_cycle_time": compute_cycle_time,
        **make_workspace_tools(workspace),
    }


async def run_component_agent(
    drawing: dict,
    component: dict,
    *,
    catalog: dict | None = None,
    batch_size: int = 1,
    on_event: OnEvent = None,
    on_thinking: OnThinking = None,
    max_iterations: int | None = None,
    workspace: ComponentWorkspace | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Run the single-loop agent for one component.

    Parameters
    ----------
    drawing:
        Engine 1's :class:`DrawingExtraction` as a dict.
    component:
        One entry from ``AssemblyData.components`` (already enriched
        with BOM mapping by the coordinator).
    catalog:
        Per-user shop catalog (``labor`` / ``machines`` / ``tools`` /
        ``materials``). Bound into ``catalog_lookup`` for this analysis.
    batch_size:
        Lot size — affects setup amortization downstream.
    on_event / on_thinking:
        SSE bridge callbacks from the orchestrator.
    max_iterations:
        Cap. Defaults to :attr:`AgenticSettings.max_iterations_per_phase`
        (which used to govern one phase but now governs the whole loop).
    workspace:
        Per-component on-disk scratch dir for checkpoint + resume.
    model:
        Optional LLM slug. ``None`` or ``"vllm:..."`` routes to local
        vLLM; ``"<vendor>/<name>"`` routes to OpenRouter (default for
        the agentic engine).

    Returns
    -------
    The plan dict, shaped so the coordinator can mechanically project it
    onto :class:`ProcessPlan`. Keys match what
    :func:`server.engines.agentic.coordinator._build_routing_rows`
    consumes.
    """
    component_index = component.get("component_index")
    component_name = component.get("name") or f"component_{component_index}"
    system_prompt = build_system_prompt()
    tools = _build_tools(catalog, workspace)

    # Resume hint: enumerate any pre-existing workspace files so the
    # prompt can ask the agent to rehydrate before doing anything else.
    workspace_files: list[str] = []
    if workspace is not None:
        listing = workspace.list_files()
        for entry in listing.get("files") or []:
            name = (entry or {}).get("name")
            if name:
                workspace_files.append(str(name))
        if workspace_files:
            logger.info(
                "agent: component %s — RESUMING (%d workspace files: %s)",
                component_name, len(workspace_files), workspace_files,
            )

    user_prompt = build_agent_user_message(
        drawing, component,
        batch_size=batch_size,
        workspace_files=workspace_files,
    )

    await safe_emit(on_event, "status", {
        "title":   "Agentic planner",
        "message": (
            f"{component_name}: planning (resume)" if workspace_files
            else f"{component_name}: planning"
        ),
    })

    run = await run_tool_loop(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        tools=tools,
        on_event=on_event,
        on_thinking=on_thinking,
        max_iterations=max_iterations,
        label=component_name,
        model=model,
    )

    plan = dict(run["final"] or {})
    plan["chosen_machine_id"] = _pick_default_machine(plan)
    logger.info(
        "── %s PLAN ──\n%s", component_name, _dump_plan(plan),
    )

    return {
        "component_index":           component_index,
        "component_name":            component_name,
        "machine_class":             plan.get("machine_class"),
        "ranked_machines":           plan.get("top_machines") or [],
        "chosen_machine_id":         plan.get("chosen_machine_id"),
        "operations":                plan.get("operations") or [],
        "tools_per_operation":       plan.get("tools_per_operation") or [],
        "parameters_per_operation":  plan.get("parameters_per_operation") or [],
        "total_run_min_per_part":    plan.get("total_run_min_per_part"),
        "setup_min_per_lot":         plan.get("setup_min_per_lot"),
        "rationale":                 plan.get("rationale"),
        "iterations":                run["iterations"],
        "tool_call_count":           len(run["tool_calls"]),
        "resumed_from_workspace":    bool(workspace_files),
        "workspace_files_at_start":  workspace_files,
    }


__all__ = ["run_component_agent", "ToolLoopError"]
