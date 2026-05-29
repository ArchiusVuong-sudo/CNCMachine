"""Pipeline result persistence to Supabase.

Writes the new schema introduced by migrations 001-003:

    a4_analyses        — top-level row per analysis run
    a4_2d_extraction   — drawing-extraction snapshot
    a4_components      — per-component results with agentic_plan + chosen_machine_id
    a4_features        — per-component features (key_face_ids, feature_id)
    a4_processes       — per-component routing rows
    a4_cam_runs        — CAM job header
    a4_gcode           — one row per .nc file produced by the CAM run

Design notes
------------

* All writes are best-effort. Persistence failures NEVER raise to the
  caller — they log and return None. The SSE pipeline must keep working
  even if Supabase is offline.
* The orchestrator allocates ``analysis_id`` itself (so the SSE response
  carries the same id the DB row uses). Component/feature/process ids
  are server-allocated via ``gen_random_uuid()`` defaults.
* Calls are sync against the supabase-py client (PostgREST is HTTP-only;
  there's no async client today). We wrap in :func:`asyncio.to_thread`
  to keep the FastAPI event loop responsive.
* ``extra="allow"`` on the wire schemas means engines may attach fields
  the DB doesn't have a column for. We filter to known columns before
  insert so unknown keys don't trip PostgREST.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("cncserver.infra.persistence")


# ---------------------------------------------------------------------------
# Column allow-lists per table — keys outside these are dropped before insert
# ---------------------------------------------------------------------------

_ANALYSIS_COLS = {
    "id", "user_id", "status", "file_name", "step_url", "drawing_url",
    "assembly_name", "component_count", "total_volume_mm3", "total_minutes",
    "total_usd", "batch_size", "pmi_available", "welding_contacts",
    "error_message", "elapsed_seconds", "assembly_data", "data_quality",
    "trace_json", "cam_run_id",
}

_EXTRACTION_2D_COLS = {
    "analysis_id", "part_number", "revision", "description", "material",
    "dimension_unit", "bom_items", "drawing_notes", "dimensions",
    "gdt_callouts", "threads", "surface_finish", "title_block",
}

_COMPONENT_COLS = {
    "id", "analysis_id", "component_index", "name", "description",
    "instance_count", "part_type", "part_type_confidence", "volume_mm3",
    "surface_area_mm2", "bbox_length_mm", "bbox_width_mm", "bbox_height_mm",
    "thickness_min_mm", "thickness_max_mm", "thickness_mean_mm",
    "thickness_std_dev_mm", "thickness_is_uniform", "total_perimeter_mm",
    "mapped_to_bom_item", "material", "mapping_method", "cycle_time_min",
    "cost_usd", "cost_breakdown", "bom_part_type", "pmi_annotations",
    "stock_json", "agentic_plan", "chosen_machine_id", "machine_class",
}

_FEATURE_COLS = {
    "component_id", "feature_index", "feature_type", "feature_id",
    "key_face_ids", "count", "confidence", "source", "dimensions",
    "perimeter_mm", "location", "tolerance_plus", "tolerance_minus",
    "gdt_callouts",
}

_PROCESS_COLS = {
    "component_id", "sequence_order", "process_type", "category",
    "feature_ids", "operation_count", "notes", "tooling_id", "machine_id",
    "spindle_rpm", "feed_mm_per_min", "depth_of_cut_mm", "cut_length_mm",
    "cycle_time_min", "labor_cost_usd", "machine_cost_usd",
    "total_cost_usd", "setup_min_per_lot", "run_min_per_part",
    "labor_role", "work_center", "tooling_ref", "machine_ref", "op_id",
    "agent_phase", "tool_dimensions", "feeds_speeds",
}

_CAM_RUN_COLS = {
    "id", "analysis_id", "runs_dir", "ok", "total_files",
    "elapsed_seconds", "error", "post_processor",
}

_GCODE_COLS = {
    "component_id", "cam_run_id", "sequence", "op_code", "nc_file_path",
    "size_bytes", "post_processor", "gcode_text",
    "total_path_length_mm", "rapid_length_mm", "estimated_time_min",
    "operation_count",
}


def _filter(row: dict, cols: set[str]) -> dict:
    """Keep only the keys in `cols`; drop None values too (let the DB default)."""
    return {k: v for k, v in row.items() if k in cols and v is not None}


# ---------------------------------------------------------------------------
# Enum normalizers — keep DB CHECK constraints from rejecting agent output
# ---------------------------------------------------------------------------
# The DB enforces CHECK constraints on a4_processes.category and
# a4_processes.process_type. The coordinator emits canonical values today,
# but free-text variants can sneak in (custom routing rows, future ops,
# operator edits). Map them here before insert so PostgREST 23514s don't
# kill the persist call. Unknown values get a safe default.

_CATEGORY_ENUM = {
    "cutting", "hole_making", "forming", "machining", "finishing",
    "setup", "inspection", "deburring", "welding", "purchased", "assembly",
}
_CATEGORY_ALIASES = {
    "rough": "machining", "roughing": "machining",
    "finish": "finishing",
    "mill": "machining", "milling": "machining",
    "turn": "machining", "turning": "machining",
    "drill": "hole_making", "drilling": "hole_making",
    "tap": "hole_making", "tapping": "hole_making",
    "ream": "hole_making", "reaming": "hole_making",
    "bore": "hole_making", "boring": "hole_making",
    "chamfer": "machining", "chamfering": "machining",
    "deburr": "deburring",
    "inspect": "inspection",
    "weld": "welding", "welding": "welding",
    "cut": "cutting", "cutting": "cutting",
    "form": "forming", "forming": "forming",
    "assemble": "assembly", "assembly": "assembly",
    "purchase": "purchased", "purchased": "purchased",
}


def _norm_category(value: Any) -> str:
    """Map a free-text category to the DB enum. Defaults to 'machining'."""
    if not value:
        return "machining"
    s = str(value).strip().lower()
    if s in _CATEGORY_ENUM:
        return s
    return _CATEGORY_ALIASES.get(s, "machining")


_PROCESS_TYPE_ENUM = {
    "cnc_milling", "cnc_turning", "drilling", "tapping", "thread_milling",
    "threading", "boring", "reaming", "facing", "grooving", "chamfering",
    "filleting", "deburring", "inspection", "setup", "laser_cutting",
    "plasma_cutting", "waterjet_cutting", "punching", "press_brake",
    "rolling", "welding", "spot_welding", "tube_laser_cutting",
    "tube_bending", "tube_end_forming", "pocket_milling", "end_milling",
    "slot_milling", "face_milling", "counterbore", "countersink",
    "assembly", "part_mark", "outsourced", "packaging",
    "cnc_milling_rough", "cnc_milling_finish", "powder_coat", "tube_laser",
    "end_facing", "painting", "turning_rough", "turning_finish",
    "live_tool_milling", "cutoff", "backwork", "fixture_setup",
    "tack_welding", "grinding",
}
_PROCESS_TYPE_ALIASES = {
    "milling":  "cnc_milling",
    "turning":  "cnc_turning",
    "mill":     "cnc_milling",
    "turn":     "cnc_turning",
    "lathe":    "cnc_turning",
    "drill":    "drilling",
    "tap":      "tapping",
    "ream":     "reaming",
    "bore":     "boring",
    "grind":    "grinding",
    "deburr":   "deburring",
    "inspect":  "inspection",
    "weld":     "welding",
    "face":     "facing",
    "groove":   "grooving",
    "chamfer":  "chamfering",
    "fillet":   "filleting",
    "rough":    "cnc_milling_rough",
    "finish":   "cnc_milling_finish",
    "roughing": "cnc_milling_rough",
    "finishing": "cnc_milling_finish",
    "part_off": "cutoff",
    "partoff":  "cutoff",
    "cnct_partoff": "cutoff",
}


def _norm_process_type(value: Any) -> str:
    """Map a free-text process_type to the DB enum. Defaults to 'cnc_milling'."""
    if not value:
        return "cnc_milling"
    s = str(value).strip().lower()
    if s in _PROCESS_TYPE_ENUM:
        return s
    return _PROCESS_TYPE_ALIASES.get(s, "cnc_milling")


_STATUS_ENUM = {"pending", "running", "completed", "failed"}
_STATUS_ALIASES = {"complete": "completed", "ok": "completed", "success": "completed",
                   "error": "failed", "fail": "failed"}


def _norm_status(value: Any) -> str:
    if not value:
        return "running"
    s = str(value).strip().lower()
    if s in _STATUS_ENUM:
        return s
    return _STATUS_ALIASES.get(s, "running")


_PART_TYPE_ENUM = {"sheet_metal", "cnc_milling", "cnc_lathe", "cnc_lathe_milling",
                   "tube_pipe", "hardware", "unknown"}
_PART_TYPE_ALIASES = {
    "sheet":     "sheet_metal",
    "milling":   "cnc_milling",
    "machined":  "cnc_milling",
    "mill":      "cnc_milling",
    "cnc":       "cnc_milling",
    "turning":   "cnc_lathe",
    "lathe":     "cnc_lathe",
    "tube":      "tube_pipe",
    "pipe":      "tube_pipe",
    "purchased": "hardware",
    "fastener":  "hardware",
}


def _norm_part_type(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _PART_TYPE_ENUM:
        return s
    return _PART_TYPE_ALIASES.get(s, "unknown")


_MAPPING_METHOD_ENUM = {"description", "tengc", "unknown", "single_cnc_fallback"}


def _norm_mapping_method(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    return s if s in _MAPPING_METHOD_ENUM else "unknown"


_FEATURE_TYPE_ENUM = {
    "through_hole", "blind_hole", "counterbore", "countersink", "pocket",
    "slot", "fillet", "chamfer", "thread", "boss", "rib", "draft", "undercut",
    "step", "groove", "stock_face", "bend", "hem", "joggle", "bridge",
    "emboss", "coin", "bead", "curl", "flange", "lance",
    "perforation_pattern", "deep_draw", "unknown",
}
_FEATURE_TYPE_ALIASES = {
    "hole":             "through_hole",
    "drilled_hole":     "through_hole",
    "tapped_hole":      "thread",
    "threaded_hole":    "thread",
    "c_bore":           "counterbore",
    "c_sink":           "countersink",
    "fil":              "fillet",
    "round":            "fillet",
    "edge_chamfer":     "chamfer",
    "edge_fillet":      "fillet",
}


def _norm_feature_type(value: Any) -> str:
    if not value:
        return "unknown"
    s = str(value).strip().lower()
    if s in _FEATURE_TYPE_ENUM:
        return s
    return _FEATURE_TYPE_ALIASES.get(s, "unknown")


_FEATURE_SOURCE_ENUM = {"rule_based", "uvnet", "merged"}
_FEATURE_SOURCE_ALIASES = {
    "afr":         "rule_based",
    "occ":         "rule_based",
    "occt":        "rule_based",
    "rules":       "rule_based",
    "ml":          "uvnet",
    "neural":      "uvnet",
}


def _norm_feature_source(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _FEATURE_SOURCE_ENUM:
        return s
    return _FEATURE_SOURCE_ALIASES.get(s, "rule_based")


_DIM_UNIT_ENUM = {"mm", "in", "inch"}


def _norm_dim_unit(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _DIM_UNIT_ENUM:
        return s
    if s in {"millimeter", "millimetre", "millimeters", "millimetres"}:
        return "mm"
    if s in {"inches", "in.", "\""}:
        return "in"
    return "mm"


_POST_PROC_ENUM = {"linuxcnc", "grbl", "fanuc"}


def _norm_post_processor(value: Any) -> str:
    if not value:
        return "linuxcnc"
    s = str(value).strip().lower()
    return s if s in _POST_PROC_ENUM else "linuxcnc"


# ---------------------------------------------------------------------------
# Sync helpers (run on a worker thread by the async wrappers)
# ---------------------------------------------------------------------------

def _upsert(client: Any, table: str, row: dict, *, on_conflict: str = "id") -> dict | None:
    try:
        res = client.table(table).upsert(row, on_conflict=on_conflict).execute()
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.warning("persistence: upsert %s failed: %s", table, exc)
        return None


def _insert(client: Any, table: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    try:
        res = client.table(table).insert(rows).execute()
        return res.data or []
    except Exception as exc:
        logger.warning("persistence: insert %s (n=%d) failed: %s", table, len(rows), exc)
        return []


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

async def persist_analysis_start(
    client: Any,
    *,
    analysis_id: str,
    file_name: str,
    step_url: str | None,
    drawing_url: str | None,
    user_id: str | None,
    batch_size: int,
) -> None:
    """Insert an in-flight row so the dashboard sees the analysis exists.

    Idempotent: re-running with the same id upserts the row.
    """
    if client is None:
        return
    row = _filter({
        "id":          analysis_id,
        "user_id":     user_id,
        "status":      _norm_status("running"),
        "file_name":   file_name,
        "step_url":    step_url,
        "drawing_url": drawing_url,
        "batch_size":  batch_size,
    }, _ANALYSIS_COLS)
    await asyncio.to_thread(_upsert, client, "a4_analyses", row)


async def persist_analysis_failed(
    client: Any,
    *,
    analysis_id: str,
    error_message: str,
    elapsed_seconds: float | None = None,
) -> None:
    """Mark an in-flight analysis as failed. Best-effort upsert."""
    if client is None:
        return
    row = _filter({
        "id":              analysis_id,
        "status":          _norm_status("failed"),
        "error_message":   error_message,
        "elapsed_seconds": round(elapsed_seconds, 2) if elapsed_seconds else None,
    }, _ANALYSIS_COLS)
    await asyncio.to_thread(_upsert, client, "a4_analyses", row)


async def persist_analysis_complete(
    client: Any,
    *,
    analysis_id: str,
    status: str,
    extraction_2d: dict | None,
    assembly_data: dict | None,
    components: list[dict],
    components_processes: list[list[dict]],
    cam_output: dict | None,
    elapsed_seconds: float,
    trace: dict | None,
    error_message: str | None = None,
) -> None:
    """Persist the full pipeline result tree.

    Best-effort. Order:
        1. update a4_analyses row with totals + status
        2. upsert a4_2d_extraction
        3. upsert each component → grab returned ids
        4. for each component, insert features + processes
        5. (CAM has its own helper — call separately)
    """
    if client is None:
        return

    assembly_data = assembly_data or {}
    extraction_2d = extraction_2d or {}

    cam_run_id = None
    if cam_output:
        cam_run_id = await persist_cam_run(
            client,
            analysis_id=analysis_id,
            cam_output=cam_output,
        )

    total_usd = sum(
        float((c.get("cost") or {}).get("total_usd") or 0.0)
        for c in components
    )
    total_minutes = sum(
        float(c.get("cycle_time_min") or 0.0)
        for c in components
    )

    analysis_row = _filter({
        "id":              analysis_id,
        "status":          _norm_status(status),
        "assembly_name":   assembly_data.get("assembly_name"),
        "component_count": len(components),
        "total_volume_mm3": assembly_data.get("total_volume_mm3"),
        "total_minutes":   round(total_minutes, 2) if total_minutes else None,
        "total_usd":       round(total_usd, 2) if total_usd else None,
        "pmi_available":   assembly_data.get("pmi_available"),
        "welding_contacts": assembly_data.get("welding_contacts") or [],
        "error_message":   error_message,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "assembly_data":   assembly_data,
        "data_quality":    "production",
        "trace_json":      trace,
        "cam_run_id":      cam_run_id,
    }, _ANALYSIS_COLS)
    await asyncio.to_thread(_upsert, client, "a4_analyses", analysis_row)

    if extraction_2d:
        ext_row = _filter({
            "analysis_id":      analysis_id,
            "part_number":      extraction_2d.get("part_number"),
            "revision":         extraction_2d.get("revision"),
            "description":      extraction_2d.get("description"),
            "material":         extraction_2d.get("material"),
            "dimension_unit":   _norm_dim_unit(extraction_2d.get("dimension_unit")),
            "bom_items":        extraction_2d.get("bom_items") or [],
            "drawing_notes":    extraction_2d.get("drawing_notes") or [],
            "dimensions":       extraction_2d.get("dimensions") or [],
            "gdt_callouts":     extraction_2d.get("gdt_callouts") or [],
            "threads":          extraction_2d.get("threads") or [],
            "surface_finish":   extraction_2d.get("surface_finish"),
            "title_block":      extraction_2d.get("title_block"),
        }, _EXTRACTION_2D_COLS)
        await asyncio.to_thread(
            _upsert, client, "a4_2d_extraction", ext_row,
            on_conflict="analysis_id",
        )

    for idx, comp in enumerate(components):
        comp_row = _filter({
            "analysis_id":          analysis_id,
            "component_index":      comp.get("component_index", idx),
            "name":                 comp.get("name"),
            "description":          comp.get("description"),
            "instance_count":       comp.get("instance_count"),
            "part_type":            _norm_part_type(comp.get("part_type")),
            "part_type_confidence": comp.get("part_type_confidence"),
            "volume_mm3":           comp.get("volume_mm3"),
            "surface_area_mm2":     comp.get("surface_area_mm2"),
            "bbox_length_mm":       comp.get("bbox_length_mm"),
            "bbox_width_mm":        comp.get("bbox_width_mm"),
            "bbox_height_mm":       comp.get("bbox_height_mm"),
            "thickness_min_mm":     comp.get("thickness_min_mm"),
            "thickness_max_mm":     comp.get("thickness_max_mm"),
            "thickness_mean_mm":    comp.get("thickness_mean_mm"),
            "thickness_std_dev_mm": comp.get("thickness_std_dev_mm"),
            "thickness_is_uniform": comp.get("thickness_is_uniform"),
            "total_perimeter_mm":   comp.get("total_perimeter_mm"),
            "mapped_to_bom_item":   comp.get("mapped_to_bom_item"),
            "material":             comp.get("material"),
            "mapping_method":       _norm_mapping_method(comp.get("mapping_method")),
            "cycle_time_min":       comp.get("cycle_time_min"),
            "cost_usd":             (comp.get("cost") or {}).get("total_usd"),
            "cost_breakdown":       comp.get("cost"),
            "pmi_annotations":      comp.get("pmi_annotations") or [],
            "stock_json":           comp.get("stock"),
            # Prefer `planner` (engine-agnostic) but accept `agentic` for
            # back-compat — DB column name kept as `agentic_plan` for migration
            # stability; rename is at the API/UI/code boundary only.
            "agentic_plan":         comp.get("planner") or comp.get("agentic"),
            "chosen_machine_id":    (comp.get("planner") or comp.get("agentic") or {}).get("chosen_machine_id"),
            "machine_class":        (comp.get("planner") or comp.get("agentic") or {}).get("machine_class"),
        }, _COMPONENT_COLS)

        inserted = await asyncio.to_thread(
            _insert, client, "a4_components", [comp_row],
        )
        if not inserted:
            continue
        component_id = inserted[0].get("id")
        if not component_id:
            continue

        features = comp.get("features") or []
        if features:
            feature_rows = [
                _filter({
                    "component_id":    component_id,
                    "feature_index":   f_idx,
                    "feature_type":    _norm_feature_type(f.get("feature_type")),
                    "feature_id":      f.get("feature_id") or f"F{f_idx}",
                    "key_face_ids":    f.get("key_face_ids") or [],
                    "count":           f.get("count") or 1,
                    "confidence":      f.get("confidence"),
                    "source":          _norm_feature_source(f.get("source")),
                    "dimensions":      f.get("dimensions"),
                    "perimeter_mm":    f.get("perimeter_mm"),
                    "location":        f.get("location"),
                    "tolerance_plus":  f.get("tolerance_plus"),
                    "tolerance_minus": f.get("tolerance_minus"),
                    "gdt_callouts":    f.get("gdt_callouts") or [],
                }, _FEATURE_COLS)
                for f_idx, f in enumerate(features)
            ]
            await asyncio.to_thread(
                _insert, client, "a4_features", feature_rows,
            )

        processes = (
            components_processes[idx] if idx < len(components_processes) else []
        )
        if processes:
            process_rows = [
                _filter({
                    "component_id":      component_id,
                    "sequence_order":    p.get("sequence_order", seq_idx),
                    "process_type":      _norm_process_type(p.get("process_type")),
                    "category":          _norm_category(p.get("category")),
                    "feature_ids":       p.get("feature_ids") or [],
                    "operation_count":   p.get("operation_count") or 1,
                    "notes":             p.get("notes"),
                    "tooling_id":        (p.get("tooling_ref") or {}).get("tool_id"),
                    "machine_id":        (p.get("machine_ref") or {}).get("machine_id"),
                    "spindle_rpm":       p.get("spindle_rpm"),
                    "feed_mm_per_min":   p.get("feed_mm_per_min"),
                    "depth_of_cut_mm":   p.get("depth_of_cut_mm"),
                    "cut_length_mm":     p.get("cut_length_mm"),
                    "cycle_time_min":    p.get("cycle_time_min"),
                    "labor_cost_usd":    p.get("labor_cost_usd"),
                    "machine_cost_usd":  p.get("machine_cost_usd"),
                    "total_cost_usd":    p.get("total_cost_usd"),
                    "setup_min_per_lot": p.get("setup_min_per_lot"),
                    "run_min_per_part":  p.get("run_min_per_part"),
                    "labor_role":        p.get("labor_role"),
                    "work_center":       p.get("work_center"),
                    "tooling_ref":       p.get("tooling_ref"),
                    "machine_ref":       p.get("machine_ref"),
                    "op_id":             p.get("op_id"),
                    "agent_phase":       p.get("agent_phase"),
                    "tool_dimensions":   p.get("tool_dimensions"),
                    "feeds_speeds":      p.get("feeds_speeds"),
                }, _PROCESS_COLS)
                for seq_idx, p in enumerate(processes)
            ]
            await asyncio.to_thread(
                _insert, client, "a4_processes", process_rows,
            )

    logger.info(
        "persistence: wrote analysis=%s components=%d total=$%.2f",
        analysis_id, len(components), total_usd,
    )


async def persist_cam_run(
    client: Any,
    *,
    analysis_id: str,
    cam_output: dict,
) -> str | None:
    """Insert one a4_cam_runs row + N a4_gcode rows (one per .nc file).

    Returns the cam_run id (str(uuid)) or None on failure.
    """
    if client is None or not cam_output:
        return None

    run_row = _filter({
        "analysis_id":     analysis_id,
        "runs_dir":        cam_output.get("runs_dir") or "",
        "ok":              bool(cam_output.get("ok")),
        "total_files":     int(cam_output.get("total_files") or 0),
        "elapsed_seconds": cam_output.get("elapsed_seconds"),
        "error":           cam_output.get("error"),
        "post_processor":  _norm_post_processor(cam_output.get("post_processor")),
    }, _CAM_RUN_COLS)

    inserted = await asyncio.to_thread(_insert, client, "a4_cam_runs", [run_row])
    if not inserted:
        return None
    cam_run_id = inserted[0].get("id")

    gcode_rows: list[dict] = []
    for comp in (cam_output.get("by_component") or []):
        for op in (comp.get("outputs") or []):
            gcode_rows.append(_filter({
                "cam_run_id":     cam_run_id,
                "sequence":       op.get("sequence"),
                "op_code":        op.get("op_code"),
                "nc_file_path":   op.get("path"),
                "size_bytes":     op.get("size"),
                "post_processor": _norm_post_processor(cam_output.get("post_processor")),
            }, _GCODE_COLS))
    if gcode_rows:
        await asyncio.to_thread(_insert, client, "a4_gcode", gcode_rows)

    logger.info(
        "persistence: wrote cam_run=%s files=%d analysis=%s",
        cam_run_id, len(gcode_rows), analysis_id,
    )
    return cam_run_id
