"""Assembly-level coordinator for the agentic engine.

Mirrors the public surface of :func:`server.engines.process_mapping.run`
so the dispatcher and orchestrator can swap engines without changing the
call site.

Reused from ``process_mapping``:
  * :func:`fetch_shop_catalog`     — per-user labor/machines/tools/materials
  * :func:`map_bom_to_components`  — drawing BOM ↔ STEP component linkage
  * :func:`reconcile_part_categories` — OCR-declared vs AFR-detected
  * :func:`tag_all_components`     — VLM dims/threads → AFR features
  * :func:`compute_cost`           — RoutingRow lists → CostBreakdown

Owned here:
  * Per-analysis :class:`AnalysisWorkspace` lifecycle — opened up front,
    handed to each component, deleted in ``finally`` once cost has been
    computed.
  * Per-component single-loop agent
    (:func:`server.engines.agentic.agent.run_component_agent`)
  * Agent output → :class:`RoutingRow` + :class:`ManufacturingProcess`
    projection
  * "Agent only, no fallback" failure handling: if the agent raises,
    record the component as failed and continue with the rest of the
    assembly.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ...core.events import OnEvent, safe_emit
from ...core.schemas import AssemblyData, DrawingExtraction, ProcessPlan
from ..process_mapping.bom_mapper import map_bom_to_components
from ..process_mapping.category_reconciler import reconcile_part_categories
from ..process_mapping.component_classifier import (
    classify_components,
    detect_top_assembly,
    synthesize_assembly_top_component,
)
from ..process_mapping.cost_engine import compute_cost, fetch_shop_catalog
from ..process_mapping.dim_tagger import tag_all_components
from .agent import run_component_agent
from .tool_loop import ToolLoopError
from .workspace import AnalysisWorkspace

logger = logging.getLogger("cncserver.engines.agentic.coordinator")


# ---------------------------------------------------------------------------
# Agent → RoutingRow / ManufacturingProcess projection
# ---------------------------------------------------------------------------

def _f(value: Any, default: float = 0.0) -> float:
    """Coerce LLM output (string, None, etc.) to float without crashing."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _index_by_op_sequence(items: list[dict]) -> dict[int, dict]:
    """Bucket per-op entries by their ``op_sequence`` for fast lookup.

    Defensive against malformed LLM output: string fragments, ``None``,
    or other non-dict entries mixed into the list are silently skipped
    so a single bad entry can't poison the entire projection.
    """
    out: dict[int, dict] = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        seq = item.get("op_sequence")
        try:
            out[int(seq)] = item
        except (TypeError, ValueError):
            continue
    return out


def _build_routing_rows(agent_out: dict, default_machine_id: str | None) -> tuple[list[dict], list[dict]]:
    """Project agent output to ``(routing_rows, manufacturing_processes)``.

    Returns two lists:
      * ``routing_rows`` — one per agent operation (op_code, sequence,
        setup, run, machine, tools, features). Wire shape for
        ``ProcessPlan.processes_per_component``.
      * ``manufacturing_processes`` — finer-grained, one per tool inside
        an operation. Stashed on the component for downstream FreeCAD
        Path generation (carries diameter_mm, flute_no, feeds/speeds).
    """
    operations = [o for o in (agent_out.get("operations") or []) if isinstance(o, dict)]
    tools_by_seq = _index_by_op_sequence(agent_out.get("tools_per_operation") or [])
    params_by_seq = _index_by_op_sequence(agent_out.get("parameters_per_operation") or [])
    machine_id = agent_out.get("chosen_machine_id") or default_machine_id

    routing_rows: list[dict] = []
    manufacturing_processes: list[dict] = []

    for op in operations:
        try:
            seq = int(op.get("sequence", 0))
        except (TypeError, ValueError):
            seq = 0
        op_code = op.get("op_code") or "CNCM_OP"
        description = op.get("description") or ""
        feature_ids = list(op.get("feature_ids") or [])
        setup_min = _f(op.get("setup_min_per_lot"))
        params_block = params_by_seq.get(seq, {})
        # Non-CNC ops (admin/assy/insp/pack/vendor) don't have feeds/speeds, so
        # the agent declares run_min_per_part directly on the op. CNC ops still
        # derive their cycle time from parameters_per_operation when available.
        explicit_run_min = _f(op.get("run_min_per_part"))
        op_cycle_min = _f(params_block.get("op_cycle_time_min")) or explicit_run_min
        labor_role = _labor_role_for_op_code(op_code)
        fixed_hrs_per_lot = _f(op.get("fixed_hrs_per_lot"))

        # operation_type: prefer the agent's explicit answer, then the
        # parameter-block echo, falling back to the op_code suffix.
        op_type = (
            _normalize_operation_type(op.get("operation_type"))
            or _normalize_operation_type(params_block.get("operation_type"))
            or _operation_type_for_op_code(op_code)
        )

        tool_entries = [
            t for t in (tools_by_seq.get(seq, {}).get("tools") or [])
            if isinstance(t, dict)
        ]
        param_entries = [
            p for p in (params_block.get("tools") or [])
            if isinstance(p, dict)
        ]
        param_by_tool_id = {
            (p.get("tool_id") or i): p for i, p in enumerate(param_entries)
        }

        tool_ids: list[str] = []
        # Pick a representative tool_type / dimensions for the routing
        # row (the row carries one summary; the per-tool detail lives on
        # ManufacturingProcess). Uses the first non-empty entry.
        row_tool_type: str | None = None
        row_tool_dims: dict[str, float] | None = None

        for i, tool in enumerate(tool_entries):
            tid = tool.get("tool_id") or f"agent_tool_{seq}_{i}"
            tool_ids.append(str(tid))
            params = param_by_tool_id.get(tool.get("tool_id") or i, {})

            tool_type = (
                tool.get("tool_type")
                or params.get("tool_type")
                or tool.get("tool_family")
            )
            tool_dims = (
                _coerce_tool_dimensions(tool)
                or _coerce_tool_dimensions(params)
            )
            if row_tool_type is None and tool_type:
                row_tool_type = str(tool_type)
            if row_tool_dims is None and tool_dims:
                row_tool_dims = tool_dims

            diameter_mm = (tool_dims or {}).get("diameter_mm")

            manufacturing_processes.append({
                "process_type": _process_type_for_op_code(op_code),
                "category": _category_for_op_code(op_code),
                "labor_role": labor_role,
                "sequence_order": seq,
                "operation_count": 1,
                "driven_by_features": list(tool.get("feature_ids") or feature_ids),
                "notes": tool.get("reason") or params.get("rationale"),
                "operation_type": op_type,
                "cycle_time_minutes": _f(params.get("cycle_time_min_calibrated")) or None,
                "machine_id": machine_id,
                "tool_id": str(tid),
                "tool_type": str(tool_type) if tool_type else None,
                "tool_dimensions": tool_dims,
                "tool_diameter_mm": diameter_mm,
                "spindle_speed_rpm": _f(params.get("spindle_speed_rpm")) or None,
                "feed_rate_mm_min": _f(params.get("feed_rate_mm_min")) or None,
                "stepover_mm": _f(params.get("stepover_mm")) or None,
                "stepdown_mm": _f(params.get("stepdown_mm")) or None,
                "flute_count": _f(tool.get("flute_no")) or None,
                "tool_name": tool.get("tool_name"),
                "would_need_to_buy": bool(tool.get("would_need_to_buy")),
            })

        # Non-CNC ops have no tools but still need a cost-engine row. Emit a
        # single placeholder manufacturing_process so the projection isn't
        # discarded.
        if not tool_entries and explicit_run_min > 0:
            manufacturing_processes.append({
                "process_type": _process_type_for_op_code(op_code),
                "category": _category_for_op_code(op_code),
                "labor_role": labor_role,
                "sequence_order": seq,
                "operation_count": 1,
                "driven_by_features": feature_ids,
                "notes": op.get("notes") or description,
                "operation_type": op_type,
                "cycle_time_minutes": explicit_run_min,
                "setup_min_per_lot": setup_min,
                "fixed_hrs_per_lot": fixed_hrs_per_lot or None,
                "machine_id": machine_id,
                "tool_id": None,
                "tool_type": None,
                "tool_dimensions": None,
                "tool_diameter_mm": None,
                "spindle_speed_rpm": None,
                "feed_rate_mm_min": None,
                "stepover_mm": None,
                "stepdown_mm": None,
                "flute_count": None,
                "tool_name": None,
                "would_need_to_buy": False,
            })

        routing_rows.append({
            "sequence": seq,
            "op_code": op_code,
            "description": description,
            "process_type": _process_type_for_op_code(op_code),
            "category": _category_for_op_code(op_code),
            "labor_role": labor_role,
            "operation_type": op_type,
            "setup_min_per_lot": setup_min,
            "run_min_per_part": op_cycle_min,
            "cycle_time_min": op_cycle_min,
            "fixed_hrs_per_lot": fixed_hrs_per_lot or None,
            "machine_id": machine_id,
            "machine_name": None,
            "tool_ids": tool_ids,
            "tool_type": row_tool_type,
            "tool_dimensions": row_tool_dims,
            "feature_ids": feature_ids,
            "notes": op.get("notes"),
        })

    routing_rows.sort(key=lambda r: r.get("sequence", 0))
    return routing_rows, manufacturing_processes


_OP_CODE_PROCESS_TYPE: dict[str, str] = {
    # CNC milling
    "CNCM_ROUGH":            "cnc_milling",
    "CNCM_FINISH":           "cnc_milling",
    "CNCM_DRILL":            "cnc_milling",
    "CNCM_TAP":              "cnc_milling",
    "CNCM_CHAMFER":          "cnc_milling",
    "CNCM_PROFILE_ENGRAVE":  "cnc_milling",
    "CNCM_PROFILE_HOLES":    "cnc_milling",
    # CNC turning
    "CNCT_FACE":             "cnc_turning",
    "CNCT_TURN":             "cnc_turning",
    "CNCT_PARTOFF":          "cnc_turning",
    "CNCT_THREAD":           "cnc_turning",
    # Bench / secondary
    "DEBUR":                 "deburring",
    "INSPECT":               "inspection",
    "INSP_COMPONENT":        "inspection",
    "INSP_FINAL_FIXED_LOT":  "inspection",
    # Admin (planning, paperwork, kitting, staging)
    "ADMIN_PLANNING":        "admin",
    "ADMIN_PRINT":           "admin",
    "ADMIN_MAT_PICK":        "admin",
    "ADMIN_STAGING":         "admin",
    # Assembly / weld / pack
    "ASSY_HARDWARE_INSTALL": "assembly",
    "ASSY_SOLVENT_BOND":     "assembly",
    "ASSY_WELD_PVC":         "welding",
    "ASSY_WELD_METAL":       "welding",
    "PACK_CLEAN":            "packaging",
    "OUTSIDE_VENDOR":        "outside_vendor",
}

_OP_CODE_CATEGORY: dict[str, str] = {
    "CNCM_ROUGH":            "machining",
    "CNCM_FINISH":           "machining",
    "CNCM_DRILL":            "machining",
    "CNCM_TAP":              "machining",
    "CNCM_CHAMFER":          "machining",
    "CNCM_PROFILE_ENGRAVE":  "machining",
    "CNCM_PROFILE_HOLES":    "machining",
    "CNCT_FACE":             "machining",
    "CNCT_TURN":             "machining",
    "CNCT_PARTOFF":          "machining",
    "CNCT_THREAD":           "machining",
    "DEBUR":                 "deburring",
    "INSPECT":               "inspection",
    "INSP_COMPONENT":        "inspection",
    "INSP_FINAL_FIXED_LOT":  "inspection",
    "ADMIN_PLANNING":        "admin",
    "ADMIN_PRINT":           "admin",
    "ADMIN_MAT_PICK":        "admin",
    "ADMIN_STAGING":         "admin",
    "ASSY_HARDWARE_INSTALL": "assembly",
    "ASSY_SOLVENT_BOND":     "assembly",
    "ASSY_WELD_PVC":         "welding",
    "ASSY_WELD_METAL":       "welding",
    "PACK_CLEAN":            "packaging",
    "OUTSIDE_VENDOR":        "outside_vendor",
}

# Op-code → labor role for the cost engine's _ROLE_RATE lookup.
# The cost engine charges (run_min/60) × rate to whichever role wins.
_OP_CODE_LABOR_ROLE: dict[str, str] = {
    "CNCM_ROUGH":            "machinist",
    "CNCM_FINISH":           "machinist",
    "CNCM_DRILL":            "machinist",
    "CNCM_TAP":              "machinist",
    "CNCM_CHAMFER":          "machinist",
    "CNCM_PROFILE_ENGRAVE":  "machinist",
    "CNCM_PROFILE_HOLES":    "machinist",
    "CNCT_FACE":             "machinist",
    "CNCT_TURN":             "machinist",
    "CNCT_PARTOFF":          "machinist",
    "CNCT_THREAD":           "machinist",
    "DEBUR":                 "deburrer",
    "INSPECT":               "inspector",
    "INSP_COMPONENT":        "inspector",
    "INSP_FINAL_FIXED_LOT":  "inspector",
    "ADMIN_PLANNING":        "programmer",       # planner / writeup; closest to programmer
    "ADMIN_PRINT":           "setup_technician",
    "ADMIN_MAT_PICK":        "setup_technician",
    "ADMIN_STAGING":         "setup_technician",
    "ASSY_HARDWARE_INSTALL": "assembler",
    "ASSY_SOLVENT_BOND":     "assembler",
    "ASSY_WELD_PVC":         "welder",
    "ASSY_WELD_METAL":       "welder",
    "PACK_CLEAN":            "assembler",
    "OUTSIDE_VENDOR":        "outside_vendor",   # cost engine treats this as pass-through
}

# Op-code → Roughing / Finishing / None. The agent SHOULD set
# ``operation_type`` explicitly, but we derive a fallback so downstream
# consumers always get a non-empty value where it makes sense.
_OP_CODE_OPERATION_TYPE: dict[str, str | None] = {
    "CNCM_ROUGH":   "Roughing",
    "CNCM_FINISH":  "Finishing",
    "CNCT_ROUGH":   "Roughing",
    "CNCT_FINISH":  "Finishing",
}


def _process_type_for_op_code(op_code: str) -> str:
    return _OP_CODE_PROCESS_TYPE.get((op_code or "").upper(), "cnc_milling")


def _category_for_op_code(op_code: str) -> str:
    return _OP_CODE_CATEGORY.get((op_code or "").upper(), "machining")


def _labor_role_for_op_code(op_code: str) -> str:
    """Map op_code → cost-engine labor role. Defaults to machinist."""
    return _OP_CODE_LABOR_ROLE.get((op_code or "").upper(), "machinist")


def _operation_type_for_op_code(op_code: str) -> str | None:
    """Map an op_code to ``"Roughing" | "Finishing" | None``."""
    code = (op_code or "").upper()
    if code in _OP_CODE_OPERATION_TYPE:
        return _OP_CODE_OPERATION_TYPE[code]
    if "ROUGH" in code:
        return "Roughing"
    if "FINISH" in code:
        return "Finishing"
    return None


def _normalize_operation_type(value: Any) -> str | None:
    """Coerce free-text operation_type to the locked {Roughing, Finishing, None} set."""
    if value is None:
        return None
    s = str(value).strip().lower()
    if s.startswith("rough"):
        return "Roughing"
    if s.startswith("finish"):
        return "Finishing"
    return None


def _coerce_tool_dimensions(tool_block: dict) -> dict[str, float] | None:
    """Extract numeric tool dimensions from a tool entry.

    Accepts both the ``dimensions`` sub-dict shape and legacy flat
    ``diameter_mm`` / ``length_mm`` keys so older analogues still load.
    """
    src = tool_block.get("dimensions") if isinstance(tool_block.get("dimensions"), dict) else {}
    out: dict[str, float] = {}
    for key in ("diameter_mm", "length_mm", "width_mm", "height_mm", "corner_radius_mm"):
        raw = src.get(key) if src else tool_block.get(key)
        if raw is None:
            continue
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            continue
    return out or None


# ---------------------------------------------------------------------------
# Per-component agent runner with "no fallback" failure handling
# ---------------------------------------------------------------------------

def _passthrough_component(
    comp_idx: int, component: dict,
) -> tuple[dict, list[dict], list[dict], dict | None]:
    """Short-circuit return for components the agent should NOT plan.

    ``hardware`` — purchased part; cost engine charges BOM ``unit_price``
    (or :data:`_HARDWARE_FALLBACK_PRICES_USD`). No routing rows; no
    agent invocation.

    ``outside_vendor`` — heat-treat, plating, etc. Emits a single
    ``OUTSIDE_VENDOR`` routing row with zero machining minutes; cost
    engine treats it as a pass-through line (Phase 6 wires in the actual
    vendor pricing from BOM / shop catalog).

    Returns the same ``(component, routing_rows, mp, error_event)`` shape
    as :func:`_run_one_component` so callers don't branch.
    """
    role = component.get("component_role") or ""
    updated = dict(component)
    updated["agentic"] = {
        "skipped": True,
        "skip_reason": f"component_role={role}",
        "rationale": (
            f"Component classified as {role!r} — agent skipped per "
            "component_classifier; pass-through routing only."
        ),
    }
    if role == "outside_vendor":
        # One placeholder op so the cost engine knows to bill the vendor
        # pass-through. Phase 6 will refine vendor pricing.
        row = {
            "sequence": 10,
            "op_code": "OUTSIDE_VENDOR",
            "description": "Outside-vendor pass-through",
            "process_type": "outside_vendor",
            "category": "outside_vendor",
            "labor_role": "outside_vendor",
            "operation_type": None,
            "setup_min_per_lot": 0.0,
            "run_min_per_part": 0.0,
            "cycle_time_min": 0.0,
            "fixed_hrs_per_lot": None,
            "machine_id": None,
            "machine_name": None,
            "tool_ids": [],
            "tool_type": None,
            "tool_dimensions": None,
            "feature_ids": [],
            "notes": component.get("component_role_reason"),
        }
        manufacturing_processes = [{
            "process_type": "outside_vendor",
            "category": "outside_vendor",
            "labor_role": "outside_vendor",
            "sequence_order": 10,
            "operation_count": 1,
            "driven_by_features": [],
            "notes": component.get("component_role_reason"),
            "operation_type": None,
            "cycle_time_minutes": 0.0,
            "machine_id": None, "tool_id": None, "tool_type": None,
            "tool_dimensions": None, "tool_diameter_mm": None,
            "spindle_speed_rpm": None, "feed_rate_mm_min": None,
            "stepover_mm": None, "stepdown_mm": None, "flute_count": None,
            "tool_name": None, "would_need_to_buy": False,
        }]
        updated["manufacturing_processes"] = manufacturing_processes
        return updated, [row], manufacturing_processes, None

    # Hardware path — cost engine already short-circuits on
    # part_type == "hardware" (or component_role == "hardware" once Phase 6
    # broadens the check). No routing rows; no processes.
    updated["manufacturing_processes"] = []
    return updated, [], [], None


async def _run_one_component(
    comp_idx: int,
    component: dict,
    drawing_dict: dict,
    *,
    catalog: dict,
    batch_size: int,
    on_event: OnEvent,
    workspace: AnalysisWorkspace,
    model: str | None = None,
) -> tuple[dict, list[dict], list[dict], dict | None]:
    """Run one component through the agent. Returns ``(component,
    routing_rows, manufacturing_processes, error_event)``.

    On failure, returns empty routing + an event payload describing the
    error (caller emits it). Per the locked decision "Agent only, no
    fallback" we do NOT failover to a rule-based worker.
    """
    # Classifier-driven short-circuit: hardware and outside-vendor parts
    # skip the LLM entirely.
    role = (component.get("component_role") or "").lower()
    if role in {"hardware", "outside_vendor"}:
        logger.info(
            "agentic: component %d (%s) — skipping agent (role=%s)",
            comp_idx, component.get("name"), role,
        )
        return _passthrough_component(comp_idx, component)

    component_workspace = workspace.for_component(comp_idx)
    try:
        agent_out = await run_component_agent(
            drawing_dict, component,
            catalog=catalog, batch_size=batch_size,
            on_event=on_event,
            workspace=component_workspace,
            model=model,
        )
    except ToolLoopError as exc:
        logger.warning("agentic: component %d (%s) — agent failed: %s",
                       comp_idx, component.get("name"), exc)
        return component, [], [], {
            "tool": f"agentic_component_{comp_idx}",
            "result": {
                "component":       component.get("name", f"Component_{comp_idx}"),
                "error":           str(exc),
                "cycle_time_min":  0.0,
                "operation_count": 0,
            },
        }
    except Exception as exc:  # noqa: BLE001 — never let one bad component kill the assembly
        logger.exception("agentic: component %d unexpected failure", comp_idx)
        return component, [], [], {
            "tool": f"agentic_component_{comp_idx}",
            "result": {
                "component":       component.get("name", f"Component_{comp_idx}"),
                "error":           f"{exc.__class__.__name__}: {exc}",
                "cycle_time_min":  0.0,
                "operation_count": 0,
            },
        }

    # Projection must never lose the agent's findings. If a malformed
    # entry sneaks past the dict-filters and raises here, log it but
    # still decorate the component with what the agent produced so the
    # cost engine and SSE surface see the real plan.
    projection_error: str | None = None
    try:
        routing_rows, manufacturing_processes = _build_routing_rows(
            agent_out, default_machine_id=agent_out.get("chosen_machine_id"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "agentic: component %d (%s) — projection failed: %s",
            comp_idx, component.get("name"), exc,
        )
        routing_rows, manufacturing_processes = [], []
        projection_error = f"{exc.__class__.__name__}: {exc}"

    # Decorate the component with the agent's findings — passthrough
    # fields that the SSE final_answer surface picks up via Component's
    # extra='allow' schema.
    updated = dict(component)
    updated["agentic"] = {
        "machine_class":            agent_out.get("machine_class"),
        "ranked_machines":          agent_out.get("ranked_machines") or agent_out.get("top_machines"),
        "chosen_machine_id":        agent_out.get("chosen_machine_id"),
        "total_run_min_per_part":   agent_out.get("total_run_min_per_part"),
        "setup_min_per_lot":        agent_out.get("setup_min_per_lot"),
        "rationale":                agent_out.get("rationale"),
        "evidence":                 agent_out.get("evidence") or [],
        "confidence_band_pct":      _f(agent_out.get("confidence_band_pct")) or None,
        "iterations":               agent_out.get("iterations"),
        "tool_call_count":          agent_out.get("tool_call_count"),
        "resumed_from_workspace":   agent_out.get("resumed_from_workspace"),
        "workspace_files_at_start": agent_out.get("workspace_files_at_start"),
        "projection_error":         projection_error,
    }
    updated["manufacturing_processes"] = manufacturing_processes
    error_event: dict | None = None
    if projection_error:
        error_event = {
            "tool": f"agentic_component_{comp_idx}",
            "result": {
                "component":        component.get("name", f"Component_{comp_idx}"),
                "warning":          "projection_partial_failure",
                "projection_error": projection_error,
            },
        }
    return updated, routing_rows, manufacturing_processes, error_event


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def run(
    drawing: DrawingExtraction,
    assembly: AssemblyData,
    step_bytes: bytes,
    *,
    batch_size: int = 1,
    user_id: str | None = None,
    supabase_client: Any = None,
    catalog: dict | None = None,
    on_event: OnEvent = None,
    forced_assembly_part_type: str | None = None,
    analysis_id: str | None = None,
    model: str | None = None,
) -> ProcessPlan:
    """Run the agentic Engine 3 over a drawing + assembly extraction.

    Drop-in for :func:`server.engines.process_mapping.run` — same input
    signature, same :class:`ProcessPlan` output shape. The orchestrator
    flips between them via :func:`server.engines.agentic.dispatcher.dispatch`.

    ``analysis_id`` keys the per-analysis temp workspace. The directory
    is created at the top of this function and deleted in ``finally``
    once cost computation completes — so on a successful run nothing is
    left behind, and on a mid-run crash the directory survives so a
    later retry can rehydrate state via ``workspace_list`` / ``workspace_read``.

    ``model`` is the per-request LLM slug used by every component agent.
    ``None`` falls back to the server default (typically
    ``openrouter_default_model``). See
    :func:`server.infra.llm._select_provider` for the routing rules.
    """
    t0 = time.monotonic()

    drawing_dict = drawing.as_dict() if isinstance(drawing, DrawingExtraction) else dict(drawing or {})
    assembly_dict = assembly.as_dict() if isinstance(assembly, AssemblyData) else dict(assembly or {})

    components: list[dict] = list(assembly_dict.get("components") or [])
    logger.info(
        "agentic START: components=%d batch_size=%d user=%s analysis=%s",
        len(components), batch_size, user_id or "-", analysis_id or "-",
    )

    # GC any leftover workspace dirs from crashed prior runs.
    swept = AnalysisWorkspace.sweep_stale()
    if swept:
        logger.info("agentic: swept %d stale workspace dir(s)", swept)

    workspace = AnalysisWorkspace.open(analysis_id)
    logger.info("agentic: workspace ready at %s", workspace.path)

    try:
        # ── Catalog fetch ──────────────────────────────────────────────────
        if catalog is None:
            try:
                catalog = await fetch_shop_catalog(supabase_client)
            except Exception as exc:
                logger.warning("agentic: catalog fetch failed — defaults (%s)", exc)
                catalog = await fetch_shop_catalog(None)
        logger.info(
            "agentic: catalog ready — labor=%d machines=%d tools=%d materials=%d",
            len(catalog.get("labor") or {}),
            len(catalog.get("machines") or {}),
            len(catalog.get("tools") or {}),
            len(catalog.get("materials") or {}),
        )

        # ── BOM mapping ────────────────────────────────────────────────────
        await safe_emit(on_event, "tool_call", {
            "tool": "map_bom_to_components", "iteration": 1,
            "label": "BOM → Component Mapping",
        })
        try:
            bom_mappings = map_bom_to_components(drawing_dict.get("bom_items") or [], components)
        except Exception as exc:
            logger.warning("agentic: BOM mapping failed: %s", exc)
            bom_mappings = [
                {"component_index": i, "mapped_to_bom_item": None,
                 "material": None, "mapping_method": "unknown", "match_score": 0.0}
                for i in range(len(components))
            ]
        fallback_material = drawing_dict.get("material") or "AL6061"
        for mapping in bom_mappings:
            cidx = mapping.get("component_index", 0)
            if cidx < len(components):
                components[cidx]["mapped_to_bom_item"] = mapping.get("mapped_to_bom_item")
                components[cidx]["material"] = mapping.get("material") or fallback_material
                components[cidx]["mapping_method"] = mapping.get("mapping_method")
                components[cidx]["bom_part_type"] = mapping.get("bom_part_type")

        # Single-component fallback
        if len(components) == 1 and not components[0].get("bom_part_type"):
            cnc_bom_items = [
                b for b in (drawing_dict.get("bom_items") or [])
                if (b.get("part_type") or "").lower() in (
                    "cnc_machined", "cnc_milling", "cnc_lathe", "cnc_lathe_milling",
                )
            ]
            if len(cnc_bom_items) == 1:
                only = cnc_bom_items[0]
                components[0]["bom_part_type"] = only.get("part_type")
                components[0]["material"] = (
                    components[0].get("material") or only.get("material") or fallback_material
                )
                components[0]["mapped_to_bom_item"] = only.get("item_no")
                components[0]["mapping_method"] = "single_cnc_fallback"

        if not drawing_dict.get("material"):
            first_mat = next((c.get("material") for c in components if c.get("material")), "")
            if first_mat:
                drawing_dict["material"] = first_mat

        await safe_emit(on_event, "tool_result", {
            "tool": "map_bom_to_components",
            "result": {
                "mapped_count": sum(1 for m in bom_mappings if m.get("mapped_to_bom_item") is not None),
                "total_components": len(components),
            },
        })

        # ── Forced assembly part type ─────────────────────────────────────
        if forced_assembly_part_type:
            forced = forced_assembly_part_type.strip().lower()
            for c in components:
                c["bom_part_type"] = forced
                c["part_type_override_source"] = "user_assembly_override"

        # ── Category reconciliation ────────────────────────────────────────
        await safe_emit(on_event, "tool_call", {
            "tool": "reconcile_part_category", "iteration": 1,
            "label": "Reconcile Part Category (OCR ↔ AFR)",
        })
        try:
            category_decisions = reconcile_part_categories(components, drawing_dict)
        except Exception as exc:
            logger.warning("agentic: category reconciliation failed: %s", exc)
            category_decisions = []
        await safe_emit(on_event, "tool_result", {
            "tool": "reconcile_part_category",
            "result": {
                "total_components": len(category_decisions),
                "categories_changed": sum(1 for d in category_decisions if d.get("changed")),
                "decisions": category_decisions,
            },
        })

        # ── Dim tagging ────────────────────────────────────────────────────
        await safe_emit(on_event, "tool_call", {
            "tool": "tag_dimensions_to_features", "iteration": 1,
            "label": "Tag Drawing Dimensions to 3D Features",
        })
        try:
            tag_summary = tag_all_components(components, drawing_dict)
        except Exception as exc:
            logger.warning("agentic: dim tagging failed: %s", exc)
            tag_summary = {"total_components": len(components), "total_tags": 0}
        await safe_emit(on_event, "tool_result", {
            "tool": "tag_dimensions_to_features", "result": tag_summary,
        })

        # ── Component role classification ──────────────────────────────────
        # Stamps `component_role` ∈ {machining, sub_item_sheet, hardware,
        # outside_vendor} on every component so the dispatch loop below
        # knows which ones to send through the agent and which to
        # short-circuit. Also detects multi-item weldments and synthesises
        # an `assembly_top` placeholder so the agent emits ADMIN / ASSY /
        # WELD / INSP_FINAL / PACK ops for the assembly itself.
        await safe_emit(on_event, "tool_call", {
            "tool": "classify_components", "iteration": 1,
            "label": "Classify Component Roles (machining / hardware / vendor / sheet)",
        })
        try:
            role_decisions = classify_components(components, drawing_dict)
        except Exception as exc:
            logger.warning("agentic: component classification failed: %s", exc)
            role_decisions = []
        try:
            if detect_top_assembly(drawing_dict, components):
                synth = synthesize_assembly_top_component(
                    components, drawing_dict,
                    next_component_index=len(components),
                )
                components.append(synth)
                logger.info(
                    "agentic: synthesised assembly_top component idx=%d (welding=%s bonding=%s)",
                    synth["component_index"],
                    synth.get("assembly_hint", {}).get("welding_required"),
                    synth.get("assembly_hint", {}).get("bonding_required"),
                )
                role_decisions.append({
                    "component_index": synth["component_index"],
                    "name":            synth["name"],
                    "role":            "assembly_top",
                    "reason":          "synthesized_for_multi_item_weldment",
                })
        except Exception as exc:
            logger.warning("agentic: assembly_top synthesis failed: %s", exc)
        await safe_emit(on_event, "tool_result", {
            "tool": "classify_components",
            "result": {
                "total_components": len(components),
                "decisions": role_decisions,
            },
        })

        # ── Per-component agent (parallel) ─────────────────────────────────
        await safe_emit(on_event, "status", {
            "title":   f"Agentic planner — {len(components)} component(s)",
            "message": "Single-loop agent running per component in parallel…",
        })

        t_workers = time.monotonic()
        comp_tasks = [
            asyncio.create_task(_run_one_component(
                i, comp, drawing_dict,
                catalog=catalog, batch_size=batch_size, on_event=on_event,
                workspace=workspace,
                model=model,
            ))
            for i, comp in enumerate(components)
        ]

        while comp_tasks and not all(t.done() for t in comp_tasks):
            await safe_emit(on_event, "heartbeat", {})
            await asyncio.sleep(5.0)

        processes_per_component: list[list[dict]] = []
        for i, task in enumerate(comp_tasks):
            exc = task.exception()
            if exc is not None:
                logger.warning("agentic: component %d task raised %s", i, exc)
                processes_per_component.append([])
                await safe_emit(on_event, "tool_result", {
                    "tool": f"agentic_component_{i}",
                    "result": {
                        "component": components[i].get("name", f"Component_{i}"),
                        "error": str(exc),
                    },
                })
                continue
            updated_comp, routing_rows, _mp, error_event = task.result()
            components[i] = updated_comp
            processes_per_component.append(routing_rows)
            if error_event:
                await safe_emit(on_event, "tool_result", error_event)

        logger.info(
            "agentic: per-component done in %.2fs — %d components, %d routing rows",
            time.monotonic() - t_workers, len(components),
            sum(len(p) for p in processes_per_component),
        )

        # ── Cost engine ────────────────────────────────────────────────────
        await safe_emit(on_event, "tool_call", {
            "tool": "estimate_cost", "iteration": 1, "label": "Cost Calculation",
        })
        try:
            cost_result = await compute_cost(
                components, processes_per_component, batch_size,
                supabase_client, catalog=catalog,
            )
        except Exception as exc:
            logger.exception("agentic: cost engine failed")
            cost_result = {
                "total_usd": 0.0,
                "breakdown_by_component": [
                    {"component_index": i, "total_usd": 0.0} for i in range(len(components))
                ],
            }
        await safe_emit(on_event, "tool_result", {
            "tool": "estimate_cost",
            "result": {"total_usd": cost_result.get("total_usd", 0.0)},
        })

        plan = ProcessPlan(
            components              = components,
            processes_per_component = processes_per_component,
            cost                    = cost_result,
            category_decisions      = category_decisions,
            catalog                 = catalog,
        )

        logger.info(
            "agentic DONE in %.2fs — components=%d routing_rows=%d total_usd=$%.2f",
            time.monotonic() - t0, len(components),
            sum(len(p) for p in processes_per_component),
            cost_result.get("total_usd", 0.0),
        )
        return plan
    finally:
        # On a successful run the agent's checkpoints are no longer
        # useful — delete them. If we got here via an exception the same
        # cleanup applies; a later retry will start fresh. (The directory
        # only survives across process crashes that prevent reaching this
        # block — which is the resume scenario the agent is designed for.)
        if workspace.cleanup():
            logger.info("agentic: workspace cleaned for analysis=%s", analysis_id or "-")


__all__ = ["run"]
