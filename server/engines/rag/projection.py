"""Project the RAG plan JSON into the shape downstream wants.

The cost engine + frontend consume two parallel structures:

  * ``routing_rows``           — one per operation. Used by
    :func:`server.engines.process_mapping.cost_engine.compute_cost`
    (it switches to routing-style costing when any row sets
    ``setup_min_per_lot`` or ``labor_role``).
  * ``manufacturing_processes`` — one per *tool* inside an operation.
    Stashed on the component so the UI can display feeds/speeds and
    later phases (e.g. FreeCAD Path) can read the per-tool detail.

The RAG output is "flat" — tools and their parameters are inlined per
op — so the projection is a straight nested loop. We deliberately mirror
the keys produced by the agentic coordinator's ``_build_routing_rows``
so the frontend doesn't need to know which engine ran.

Op-code → process_type / category / operation_type lookup tables are
duplicated here (not imported from the agentic package) so the RAG
engine remains deletable on its own.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cncserver.engines.rag.projection")


# ---------------------------------------------------------------------------
# Op-code dictionaries (duplicated from the agentic projection to keep
# RAG self-contained per the engine-isolation rule).
# ---------------------------------------------------------------------------

_OP_CODE_PROCESS_TYPE: dict[str, str] = {
    "CNCM_ROUGH":            "cnc_milling",
    "CNCM_FINISH":           "cnc_milling",
    "CNCM_DRILL":            "cnc_milling",
    "CNCM_TAP":              "cnc_milling",
    "CNCM_CHAMFER":          "cnc_milling",
    "CNCM_PROFILE_ENGRAVE":  "cnc_milling",
    "CNCM_PROFILE_HOLES":    "cnc_milling",
    "CNCT_FACE":             "cnc_turning",
    "CNCT_TURN":             "cnc_turning",
    "CNCT_PARTOFF":          "cnc_turning",
    "CNCT_THREAD":           "cnc_turning",
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
    "MARK_PART":             "marking",
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
    "MARK_PART":             "marking",
    "PACK_CLEAN":            "packaging",
    "OUTSIDE_VENDOR":        "outside_vendor",
}

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
    "ADMIN_PLANNING":        "programmer",
    "ADMIN_PRINT":           "setup_technician",
    "ADMIN_MAT_PICK":        "setup_technician",
    "ADMIN_STAGING":         "setup_technician",
    "ASSY_HARDWARE_INSTALL": "assembler",
    "ASSY_SOLVENT_BOND":     "assembler",
    "ASSY_WELD_PVC":         "welder",
    "ASSY_WELD_METAL":       "welder",
    "MARK_PART":             "marker",
    "PACK_CLEAN":            "assembler",
    "OUTSIDE_VENDOR":        "outside_vendor",
}

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
    return _OP_CODE_LABOR_ROLE.get((op_code or "").upper(), "machinist")


def _operation_type_for_op_code(op_code: str) -> str | None:
    code = (op_code or "").upper()
    if code in _OP_CODE_OPERATION_TYPE:
        return _OP_CODE_OPERATION_TYPE[code]
    if "ROUGH" in code:
        return "Roughing"
    if "FINISH" in code:
        return "Finishing"
    return None


def _normalize_operation_type(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s.startswith("rough"):
        return "Roughing"
    if s.startswith("finish"):
        return "Finishing"
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_tool_dimensions(tool: dict) -> dict[str, float] | None:
    """Pull numeric tool dims from either a ``dimensions`` sub-dict or
    legacy flat keys. Returns None when no numeric dim is present."""
    src = tool.get("dimensions") if isinstance(tool.get("dimensions"), dict) else None
    out: dict[str, float] = {}
    for key in ("diameter_mm", "length_mm", "width_mm", "height_mm", "corner_radius_mm"):
        raw = (src.get(key) if src else None)
        if raw is None:
            raw = tool.get(key)
        if raw is None:
            continue
        try:
            out[key] = float(raw)
        except (TypeError, ValueError):
            continue
    return out or None


# ---------------------------------------------------------------------------
# Public projection
# ---------------------------------------------------------------------------

def build_routing_rows(
    plan: dict,
    *,
    default_machine_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """Convert the RAG flat plan into the cost-engine + UI tuple.

    Parameters
    ----------
    plan:
        Dict returned by :func:`server.engines.rag.generator.generate_plan`
        (after tool/machine snap). Must contain ``operations`` (list).
    default_machine_id:
        Fallback machine id when the plan didn't include one. Usually the
        ``chosen_machine_id`` (already populated by the snap pass).

    Returns
    -------
    ``(routing_rows, manufacturing_processes)`` — both ready to plug into
    the cost engine and the ProcessPlan wire schema.
    """
    operations = plan.get("operations") if isinstance(plan, dict) else None
    if not isinstance(operations, list):
        return [], []

    machine_id = plan.get("chosen_machine_id") or default_machine_id

    routing_rows: list[dict] = []
    manufacturing_processes: list[dict] = []

    for op in operations:
        if not isinstance(op, dict):
            continue
        try:
            seq = int(op.get("sequence") or 0)
        except (TypeError, ValueError):
            seq = 0
        op_code = op.get("op_code") or "CNCM_OP"
        description = op.get("description") or ""
        feature_ids = list(op.get("feature_ids") or [])
        setup_min = _f(op.get("setup_min_per_lot"))
        labor_role = _labor_role_for_op_code(op_code)
        fixed_hrs_per_lot = _f(op.get("fixed_hrs_per_lot"))

        # operation_type: prefer explicit, fall back to op_code-derived.
        op_type = (
            _normalize_operation_type(op.get("operation_type"))
            or _operation_type_for_op_code(op_code)
        )

        tools = op.get("tools") if isinstance(op.get("tools"), list) else []

        op_cycle_min = _f(op.get("op_cycle_time_min"))
        explicit_run_min = _f(op.get("run_min_per_part"))
        if op_cycle_min <= 0 and tools:
            # Derive from per-tool cycle_time_min so a missing op total
            # never zeros out the cost row.
            op_cycle_min = sum(_f(t.get("cycle_time_min")) for t in tools if isinstance(t, dict))
        if op_cycle_min <= 0:
            # Non-CNC ops declare run_min directly on the op.
            op_cycle_min = explicit_run_min

        tool_ids: list[str] = []
        row_tool_type: str | None = None
        row_tool_dims: dict[str, float] | None = None

        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                continue
            tid = tool.get("tool_id") or f"rag_tool_{seq}_{i}"
            tool_ids.append(str(tid))

            tool_type = tool.get("tool_type")
            tool_dims = _coerce_tool_dimensions(tool)
            if row_tool_type is None and tool_type:
                row_tool_type = str(tool_type)
            if row_tool_dims is None and tool_dims:
                row_tool_dims = tool_dims

            diameter_mm = (tool_dims or {}).get("diameter_mm")
            cycle_min = _f(tool.get("cycle_time_min")) or None

            manufacturing_processes.append({
                "process_type":       _process_type_for_op_code(op_code),
                "category":           _category_for_op_code(op_code),
                "labor_role":         labor_role,
                "sequence_order":     seq,
                "operation_count":    1,
                "driven_by_features": list(tool.get("feature_ids") or feature_ids),
                "notes":              tool.get("rationale"),
                "operation_type":     op_type,
                "cycle_time_minutes": cycle_min,
                "machine_id":         machine_id,
                "tool_id":            str(tid) if tool.get("tool_id") else None,
                "tool_type":          str(tool_type) if tool_type else None,
                "tool_dimensions":    tool_dims,
                "tool_diameter_mm":   diameter_mm,
                "spindle_speed_rpm":  _f(tool.get("spindle_speed_rpm")) or None,
                "feed_rate_mm_min":   _f(tool.get("feed_rate_mm_min")) or None,
                "stepover_mm":        _f(tool.get("stepover_mm")) or None,
                "stepdown_mm":        _f(tool.get("stepdown_mm")) or None,
                "flute_count":        _f(tool.get("flute_no")) or None,
                "tool_name":          tool.get("tool_name"),
                "would_need_to_buy":  bool(tool.get("would_need_to_buy")),
            })

        # Non-CNC ops with no tools but explicit run_min — emit one placeholder.
        if not tools and op_cycle_min > 0:
            manufacturing_processes.append({
                "process_type":       _process_type_for_op_code(op_code),
                "category":           _category_for_op_code(op_code),
                "labor_role":         labor_role,
                "sequence_order":     seq,
                "operation_count":    1,
                "driven_by_features": feature_ids,
                "notes":              op.get("notes") or description,
                "operation_type":     op_type,
                "cycle_time_minutes": op_cycle_min,
                "setup_min_per_lot":  setup_min,
                "fixed_hrs_per_lot":  fixed_hrs_per_lot or None,
                "machine_id":         machine_id,
                "tool_id":            None,
                "tool_type":          None,
                "tool_dimensions":    None,
                "tool_diameter_mm":   None,
                "spindle_speed_rpm":  None,
                "feed_rate_mm_min":   None,
                "stepover_mm":        None,
                "stepdown_mm":        None,
                "flute_count":        None,
                "tool_name":          None,
                "would_need_to_buy":  False,
            })

        routing_rows.append({
            "sequence":          seq,
            "op_code":           op_code,
            "description":       description,
            "process_type":      _process_type_for_op_code(op_code),
            "category":          _category_for_op_code(op_code),
            "labor_role":        labor_role,
            "operation_type":    op_type,
            "setup_min_per_lot": setup_min,
            "run_min_per_part":  op_cycle_min,
            "cycle_time_min":    op_cycle_min,
            "fixed_hrs_per_lot": fixed_hrs_per_lot or None,
            "machine_id":        machine_id,
            "machine_name":      None,
            "tool_ids":          tool_ids,
            "tool_type":         row_tool_type,
            "tool_dimensions":   row_tool_dims,
            "feature_ids":       feature_ids,
            "notes":             op.get("notes"),
        })

    routing_rows.sort(key=lambda r: r.get("sequence", 0))
    return routing_rows, manufacturing_processes


__all__ = ["build_routing_rows"]
