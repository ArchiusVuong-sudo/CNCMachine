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
    kb_adopt_routing,
    make_catalog_lookup,
    make_holdout_aware_adopt_routing,
    make_holdout_aware_kb_tools,
    make_memory_tools,
    make_self_aware_find_analogues,
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
    holdout_part_number: str | None = None,
    self_part_number: str | None = None,
) -> dict[str, Callable[..., Any]]:
    """Wire the per-analysis catalog + per-component workspace into the tool set.

    The dict's keys MUST match the ``"name"`` fields in
    :data:`server.engines.agentic.tools.ALL_TOOL_SPECS` — that's the
    contract the agent learns about in the system prompt.

    When ``holdout_part_number`` is set (eval mode), the KB-reading tools
    refuse to surface the in-flight part's own page / row so the agent
    can't find its answer key in the analogue corpus. Memory writes
    (``memory_update``) are likewise frozen in holdout mode so the agent
    can't mutate its own prompt-loaded memory mid-measurement. Production
    runs pass ``None`` and get the plain, live tools.

    When ``self_part_number`` is set (production, holdout OFF), the
    ``kb_find_analogues`` tool becomes identity-aware: if the in-flight
    part already exists in the KB it is surfaced at rank 1 as an ``exact``
    match so the agent copies the known routing verbatim instead of
    re-deriving it from a looser cousin. It MUST stay ``None`` in holdout
    mode (the eval is deliberately measuring novel-part reasoning).
    """
    kb_tools = make_holdout_aware_kb_tools(holdout_part_number)
    # Layer identity-awareness ON TOP of holdout-awareness. In holdout mode
    # self_part_number is None, so this is a no-op and the answer key stays
    # hidden; in production it floats the in-flight part's own page to #1.
    kb_tools["kb_find_analogues"] = make_self_aware_find_analogues(
        kb_tools["kb_find_analogues"], self_part_number
    )
    adopt_routing = make_holdout_aware_adopt_routing(holdout_part_number)
    return {
        **kb_tools,
        "kb_adopt_routing": adopt_routing,
        "catalog_lookup": make_catalog_lookup(catalog or {}),
        "compute_cycle_time": compute_cycle_time,
        **make_memory_tools(holdout_part_number),
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
    assembly_top_present: bool = False,
    is_only_planned_component: bool = True,
    holdout_part_number: str | None = None,
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
    # Identity for the "copy a known part verbatim" branch. Prefer the
    # component's own BOM part number, fall back to the drawing's. Disabled
    # under holdout (the eval must not let the agent copy its answer key).
    self_part_number = (
        None if holdout_part_number
        else (component.get("part_number") or drawing.get("part_number"))
    )
    tools = _build_tools(
        catalog, workspace,
        holdout_part_number=holdout_part_number,
        self_part_number=self_part_number,
    )
    if holdout_part_number:
        logger.info(
            "agent: component %s — HOLDOUT mode (part_number=%s "
            "filtered from kb_read / kb_find_analogues / kb_query_csv / "
            "kb_adopt_routing)",
            component_name, holdout_part_number,
        )
    elif self_part_number:
        logger.info(
            "agent: component %s — identity-aware (self_part_number=%s; "
            "exact KB match will be surfaced at rank 1 for verbatim copy)",
            component_name, self_part_number,
        )

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
        assembly_top_present=assembly_top_present,
        is_only_planned_component=is_only_planned_component,
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
        "family_coverage":           plan.get("family_coverage") or {},
        "family_coverage_reasons":   plan.get("family_coverage_reasons") or {},
        "iterations":                run["iterations"],
        "tool_call_count":           len(run["tool_calls"]),
        "resumed_from_workspace":    bool(workspace_files),
        "workspace_files_at_start":  workspace_files,
        # Full adopted-analogue routings (pre-truncation) for the
        # coordinator's deterministic family-coverage gate.
        "_adopted_routings":         run.get("adopted_routings") or [],
    }


__all__ = ["run_component_agent", "ToolLoopError"]
