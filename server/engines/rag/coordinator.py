"""Assembly-level coordinator for the RAG engine.

Mirrors the public surface of :func:`server.engines.process_mapping.run`
(and :func:`server.engines.agentic.coordinator.run`) so the dispatcher
and orchestrator can swap engines without touching call sites.

Steps:

  1. Catalog fetch         (shared kernel — process_mapping.cost_engine)
  2. BOM mapping           (shared kernel)
  3. Forced part-type      (orchestrator override)
  4. Category reconcile    (shared kernel)
  5. Dim tagging           (shared kernel)
  6. Per-component RAG plan (parallel via asyncio.gather)
  7. Cost engine           (shared kernel)

Per-component failures don't abort the assembly. The component is
flagged via an SSE ``tool_result`` event carrying ``error`` (mirrors
the agentic "no fallback" policy). Cost engine still runs over the
non-failed components so the user gets a partial answer instead of a
500.

We do NOT import anything from ``server.engines.agentic`` — the RAG
engine must remain deletable on its own.
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
from .planner import RagPlannerError, plan_one_component

logger = logging.getLogger("cncserver.engines.rag.coordinator")


# ---------------------------------------------------------------------------
# Per-component runner with "no fallback" failure handling
# ---------------------------------------------------------------------------

def _passthrough_component(
    comp_idx: int, component: dict,
) -> tuple[dict, list[dict], list[dict], dict | None]:
    """Skip the LLM for hardware / outside-vendor components.

    Mirrors :func:`server.engines.agentic.coordinator._passthrough_component`
    so both engines behave identically when the classifier says a part
    isn't ours to plan.
    """
    role = component.get("component_role") or ""
    updated = dict(component)
    updated["rag"] = {
        "skipped": True,
        "skip_reason": f"component_role={role}",
        "rationale": (
            f"Component classified as {role!r} — RAG planner skipped per "
            "component_classifier; pass-through routing only."
        ),
    }
    if role == "outside_vendor":
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
    model: str | None = None,
) -> tuple[dict, list[dict], list[dict], dict | None]:
    """Plan one component. Returns ``(component, routing_rows,
    manufacturing_processes, error_event)``.

    Mirrors the agentic coordinator's pattern: on failure return empty
    rows + an event payload describing the error, never raise.
    """
    role = (component.get("component_role") or "").lower()
    if role in {"hardware", "outside_vendor"}:
        logger.info(
            "rag: component %d (%s) — skipping planner (role=%s)",
            comp_idx, component.get("name"), role,
        )
        return _passthrough_component(comp_idx, component)

    async def _thinking_relay(text: str) -> None:
        await safe_emit(on_event, "thinking", {
            "component_index": comp_idx,
            "delta": text,
        })

    try:
        meta, routing_rows, manufacturing_processes = await plan_one_component(
            drawing_dict, component,
            catalog=catalog, batch_size=batch_size,
            on_thinking=_thinking_relay,
            model=model,
        )
    except RagPlannerError as exc:
        logger.warning("rag: component %d (%s) — planner failed: %s",
                       comp_idx, component.get("name"), exc)
        return component, [], [], {
            "tool": f"rag_component_{comp_idx}",
            "result": {
                "component":       component.get("name", f"Component_{comp_idx}"),
                "error":           str(exc),
                "cycle_time_min":  0.0,
                "operation_count": 0,
            },
        }
    except Exception as exc:  # noqa: BLE001 — one bad component shouldn't kill the assembly
        logger.exception("rag: component %d unexpected failure", comp_idx)
        return component, [], [], {
            "tool": f"rag_component_{comp_idx}",
            "result": {
                "component":       component.get("name", f"Component_{comp_idx}"),
                "error":           f"{exc.__class__.__name__}: {exc}",
                "cycle_time_min":  0.0,
                "operation_count": 0,
            },
        }

    updated = dict(component)
    updated["rag"] = meta
    updated["manufacturing_processes"] = manufacturing_processes
    return updated, routing_rows, manufacturing_processes, None


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
    """Run the RAG Engine 3 over a drawing + assembly extraction.

    Drop-in for :func:`server.engines.agentic.coordinator.run`. Same
    input signature, same :class:`ProcessPlan` output shape.

    ``analysis_id`` is accepted for API symmetry but is not used here
    (RAG has no per-analysis workspace).
    """
    t0 = time.monotonic()
    _ = step_bytes  # unused — RAG plans from drawing + features
    _ = user_id     # unused — catalog is already scoped upstream
    _ = analysis_id

    drawing_dict = drawing.as_dict() if isinstance(drawing, DrawingExtraction) else dict(drawing or {})
    assembly_dict = assembly.as_dict() if isinstance(assembly, AssemblyData) else dict(assembly or {})

    components: list[dict] = list(assembly_dict.get("components") or [])
    logger.info(
        "rag START: components=%d batch_size=%d user=%s analysis=%s",
        len(components), batch_size, user_id or "-", analysis_id or "-",
    )

    # ── Catalog fetch ──────────────────────────────────────────────────────
    if catalog is None:
        try:
            catalog = await fetch_shop_catalog(supabase_client)
        except Exception as exc:
            logger.warning("rag: catalog fetch failed — defaults (%s)", exc)
            catalog = await fetch_shop_catalog(None)
    logger.info(
        "rag: catalog ready — labor=%d machines=%d tools=%d materials=%d",
        len(catalog.get("labor") or {}),
        len(catalog.get("machines") or {}),
        len(catalog.get("tools") or {}),
        len(catalog.get("materials") or {}),
    )

    # ── BOM mapping ────────────────────────────────────────────────────────
    await safe_emit(on_event, "tool_call", {
        "tool": "map_bom_to_components", "iteration": 1,
        "label": "BOM → Component Mapping",
    })
    try:
        bom_mappings = map_bom_to_components(drawing_dict.get("bom_items") or [], components)
    except Exception as exc:
        logger.warning("rag: BOM mapping failed: %s", exc)
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

    # ── Forced assembly part type ─────────────────────────────────────────
    if forced_assembly_part_type:
        forced = forced_assembly_part_type.strip().lower()
        for c in components:
            c["bom_part_type"] = forced
            c["part_type_override_source"] = "user_assembly_override"

    # ── Category reconciliation ────────────────────────────────────────────
    await safe_emit(on_event, "tool_call", {
        "tool": "reconcile_part_category", "iteration": 1,
        "label": "Reconcile Part Category (OCR ↔ AFR)",
    })
    try:
        category_decisions = reconcile_part_categories(components, drawing_dict)
    except Exception as exc:
        logger.warning("rag: category reconciliation failed: %s", exc)
        category_decisions = []
    await safe_emit(on_event, "tool_result", {
        "tool": "reconcile_part_category",
        "result": {
            "total_components": len(category_decisions),
            "categories_changed": sum(1 for d in category_decisions if d.get("changed")),
            "decisions": category_decisions,
        },
    })

    # ── Dim tagging ────────────────────────────────────────────────────────
    await safe_emit(on_event, "tool_call", {
        "tool": "tag_dimensions_to_features", "iteration": 1,
        "label": "Tag Drawing Dimensions to 3D Features",
    })
    try:
        tag_summary = tag_all_components(components, drawing_dict)
    except Exception as exc:
        logger.warning("rag: dim tagging failed: %s", exc)
        tag_summary = {"total_components": len(components), "total_tags": 0}
    await safe_emit(on_event, "tool_result", {
        "tool": "tag_dimensions_to_features", "result": tag_summary,
    })

    # ── Component role classification ──────────────────────────────────────
    # Mirrors the agentic coordinator: stamp component_role on every
    # component and synthesize an assembly_top placeholder when the
    # drawing + component set signals a multi-item weldment.
    await safe_emit(on_event, "tool_call", {
        "tool": "classify_components", "iteration": 1,
        "label": "Classify Component Roles (machining / hardware / vendor / sheet)",
    })
    try:
        role_decisions = classify_components(components, drawing_dict)
    except Exception as exc:
        logger.warning("rag: component classification failed: %s", exc)
        role_decisions = []
    try:
        if detect_top_assembly(drawing_dict, components):
            synth = synthesize_assembly_top_component(
                components, drawing_dict,
                next_component_index=len(components),
            )
            components.append(synth)
            logger.info(
                "rag: synthesised assembly_top component idx=%d (welding=%s bonding=%s)",
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
        logger.warning("rag: assembly_top synthesis failed: %s", exc)
    await safe_emit(on_event, "tool_result", {
        "tool": "classify_components",
        "result": {
            "total_components": len(components),
            "decisions": role_decisions,
        },
    })

    # ── Per-component RAG planning (parallel) ──────────────────────────────
    await safe_emit(on_event, "status", {
        "title":   f"RAG planner — {len(components)} component(s)",
        "message": "Single-shot RAG plan per component, in parallel…",
    })

    t_workers = time.monotonic()
    comp_tasks = [
        asyncio.create_task(_run_one_component(
            i, comp, drawing_dict,
            catalog=catalog, batch_size=batch_size, on_event=on_event,
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
            logger.warning("rag: component %d task raised %s", i, exc)
            processes_per_component.append([])
            await safe_emit(on_event, "tool_result", {
                "tool": f"rag_component_{i}",
                "result": {
                    "component": components[i].get("name", f"Component_{i}"),
                    "error":     str(exc),
                },
            })
            continue
        updated_comp, routing_rows, _mp, error_event = task.result()
        components[i] = updated_comp
        processes_per_component.append(routing_rows)
        if error_event:
            await safe_emit(on_event, "tool_result", error_event)

    logger.info(
        "rag: per-component done in %.2fs — %d components, %d routing rows",
        time.monotonic() - t_workers, len(components),
        sum(len(p) for p in processes_per_component),
    )

    # ── Cost engine ────────────────────────────────────────────────────────
    await safe_emit(on_event, "tool_call", {
        "tool": "estimate_cost", "iteration": 1, "label": "Cost Calculation",
    })
    try:
        cost_result = await compute_cost(
            components, processes_per_component, batch_size,
            supabase_client, catalog=catalog,
        )
    except Exception as exc:
        logger.exception("rag: cost engine failed")
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
        "rag DONE in %.2fs — components=%d routing_rows=%d total_usd=$%.2f",
        time.monotonic() - t0, len(components),
        sum(len(p) for p in processes_per_component),
        cost_result.get("total_usd", 0.0),
    )
    return plan


__all__ = ["run"]
