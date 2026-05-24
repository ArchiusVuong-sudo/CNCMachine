"""Component role classifier — categorize a STEP component for the agent.

Existing `category_reconciler` decides ``part_type ∈ {cnc_milling,
cnc_turning, hardware, sheet_metal, ...}`` from BOM + AFR signals — that
field drives the cost engine.

This module adds a parallel ``component_role`` axis that drives the
*agent dispatch*: which components run through the LLM, which short-
circuit to a purchase line, and whether the assembly needs a synthesized
top-level routing.

Roles
-----
``machining``         CNC-milled or CNC-turned in-house (default).
``sub_item_sheet``    Plastic sheet stock with a profile/holes routing
                      (PVC/Acetal/HDPE on a router — multi-item welded
                      assemblies).
``hardware``          Purchased / standard part (no machining).
``outside_vendor``    Sent to an outside vendor (heat-treat, plating,
                      anodize, EDM, water-jet, etc.). Skips the agent
                      and gets a pass-through cost line in the cost
                      engine.
``assembly_top``      Synthetic — represents the welded/bonded assembly
                      itself rather than any single STEP node. Emitted
                      by :func:`synthesize_assembly_top_component` when
                      the drawing signals a multi-item weldment.

The classifier sets ``comp["component_role"]`` and ``comp[
"component_role_reason"]`` for every component, and (separately) hands
back a list of synthetic ``assembly_top`` components to append to the
working set.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cncserver.engines.process_mapping.component_classifier")


# Sheet-stock material tokens (case-insensitive) — only fires when combined
# with a thin bounding box.
_SHEET_PLASTIC_TOKENS: tuple[str, ...] = (
    "PVC", "ACETAL", "DELRIN", "HDPE", "UHMW", "POLYCARBONATE",
    "PC SHEET", "PEEK SHEET", "ABS SHEET", "PMMA", "ACRYLIC",
)

# Outside-vendor signal tokens — present in BOM description / drawing notes.
_OUTSIDE_VENDOR_TOKENS: tuple[str, ...] = (
    "OUTSIDE VENDOR", "ANODIZE", "BLACK OXIDE", "HEAT TREAT",
    "PLATING", "PASSIVATE", "POWDER COAT", "PAINT", "ZINC PLATE",
    "EDM", "WATERJET", "WATER JET", "ELECTROPOLISH", "BEAD BLAST",
    "POLISHING", "DLC COATING", "TUMBLE",
)

# Drawing-side indicators that the whole job is a multi-item assembly.
# WLDMT is an Applied-Materials-style abbreviation of WELDMENT — common on
# their drawings (e.g. "WLDMT, PLATING CELL, SCIM" on 839-323453).
_ASSEMBLY_INDICATORS: tuple[str, ...] = (
    "WLDMNT", "WLDMT", "WELDMENT", "ASSY", "ASSEMBLY", "BONDED", "WELDED",
    "MULTI-ITEM", "WELD ASSY",
)

# Below this bbox-min (mm) a plastic-sheet component plausibly came from
# a sheet on a router rather than a block on a VMC.
_SHEET_MAX_THICKNESS_MM = 25.4  # 1 inch


def _bbox_dims(comp: dict) -> tuple[float, float, float]:
    """Return (length, width, thickness) in mm, sorted ascending. Missing → 0."""
    bb = comp.get("bbox") or {}
    dims = sorted([
        float(bb.get("length_mm") or 0),
        float(bb.get("width_mm")  or 0),
        float(bb.get("height_mm") or 0),
    ])
    return tuple(dims)  # type: ignore[return-value]


def _material_text(comp: dict, vlm_extraction: dict) -> str:
    return (
        (comp.get("material") or vlm_extraction.get("material") or "")
        .upper()
        .strip()
    )


def _bom_description(comp: dict) -> str:
    """Concatenate every component-side description token we can find.

    Components don't carry a nested ``bom`` dict — after BOM mapping the
    matched material / part_type get stamped flat on the component
    itself, so we only need to look at the component's own descriptive
    fields here.
    """
    parts: list[str] = []
    for key in ("bom_description", "description", "name"):
        v = comp.get(key)
        if v:
            parts.append(str(v))
    return " | ".join(parts).upper()


def _classify_one(
    comp: dict,
    vlm_extraction: dict,
) -> tuple[str, str]:
    """Return ``(role, reason)`` for one component.

    Does NOT mutate the component — the caller stamps the fields.
    """
    part_type = (comp.get("part_type") or "").lower()
    if part_type == "hardware":
        return "hardware", "part_type_is_hardware"

    desc = _bom_description(comp)
    for tok in _OUTSIDE_VENDOR_TOKENS:
        if tok in desc:
            return "outside_vendor", f"bom_token_{tok.lower().replace(' ', '_')}"

    # Sheet-stock plastic candidate
    material = _material_text(comp, vlm_extraction)
    if any(tok in material for tok in _SHEET_PLASTIC_TOKENS):
        thickness = _bbox_dims(comp)[0]
        if 0 < thickness <= _SHEET_MAX_THICKNESS_MM:
            return "sub_item_sheet", f"sheet_plastic_thick_{thickness:.1f}mm"

    return "machining", "default_cnc"


def classify_components(
    components: list[dict],
    vlm_extraction: dict,
) -> list[dict]:
    """Stamp ``component_role`` + ``component_role_reason`` on every component.

    Returns a list of decision dicts for tracing / UI surfacing.
    """
    decisions: list[dict] = []
    for comp in components:
        role, reason = _classify_one(comp, vlm_extraction)
        comp["component_role"] = role
        comp["component_role_reason"] = reason
        decisions.append({
            "component_index": comp.get("component_index"),
            "name":            comp.get("name"),
            "role":            role,
            "reason":          reason,
        })
    logger.info(
        "component_classifier: %d components → %s",
        len(components),
        {d["role"]: sum(1 for x in decisions if x["role"] == d["role"]) for d in decisions},
    )
    return decisions


def _drawing_title_tokens(vlm_extraction: dict) -> str:
    """Concatenate every field that might carry an assembly-name signal.

    Engine 1's wire schema doesn't have ``part_name`` or top-level
    ``title`` — the drawing's title lives in ``title_block.title`` and a
    descriptive blurb in top-level ``description``. We also pull
    ``title_block.description`` because some drawings use that slot.
    """
    tb = vlm_extraction.get("title_block") or {}
    if not isinstance(tb, dict):
        tb = {}
    return " ".join([
        str(vlm_extraction.get("part_number") or ""),
        str(vlm_extraction.get("description") or ""),
        str(tb.get("title") or ""),
        str(tb.get("description") or ""),
    ]).upper()


def detect_top_assembly(vlm_extraction: dict, components: list[dict]) -> bool:
    """True if the drawing + component set indicates a multi-item weldment.

    Signal weights:
      - Drawing title contains WLDMNT / WELDMENT / ASSY / WELDED  → strong.
      - 2+ sheet-stock components share the same material family   → medium.
      - 1+ hardware (insert/screw) + 2+ machined parts             → weak.
    Returns True if total weight ≥ 2.
    """
    weight = 0

    title = _drawing_title_tokens(vlm_extraction)
    for tok in _ASSEMBLY_INDICATORS:
        if tok in title:
            weight += 2
            break

    sheet_components = [
        c for c in components
        if (c.get("component_role") or "") == "sub_item_sheet"
    ]
    hardware_components = [
        c for c in components
        if (c.get("component_role") or c.get("part_type") or "") == "hardware"
    ]
    machined_components = [
        c for c in components
        if (c.get("component_role") or "machining") == "machining"
    ]

    if len(sheet_components) >= 2:
        weight += 1
    if hardware_components and (len(machined_components) + len(sheet_components)) >= 2:
        weight += 1

    return weight >= 2


def synthesize_assembly_top_component(
    components: list[dict],
    vlm_extraction: dict,
    *,
    next_component_index: int,
) -> dict:
    """Build a synthetic ``assembly_top`` component to plan the assembly ops.

    The synthesized component does not correspond to a STEP node — it's a
    placeholder so the planner emits ADMIN / ASSY_HARDWARE / ASSY_SOLVENT /
    ASSY_WELD / INSP_FINAL / PACK ops for the welded/bonded enclosure.

    The component's "features" carry signals the agent needs:
      - sub_items: list of sub-component names + materials
      - hardware: list of insert / fastener types
      - bonding_required / welding_required: based on title tokens
    """
    title_upper = _drawing_title_tokens(vlm_extraction)
    # Include the Applied-Materials abbreviation WLDMT (no 'N'): it is in
    # _ASSEMBLY_INDICATORS so it triggers detect_top_assembly, but was
    # historically omitted here — so a WLDMT drawing got an assembly_top with
    # welding_required=False and the agent silently dropped the weld op
    # (observed: 839-323453 "WLDMT, PLATING CELL, SCIM" scored ~-29% with zero
    # weld ops). Keep this list aligned with the weld-implying indicators.
    welding = any(t in title_upper for t in
                  ("WLDMT", "WLDMNT", "WELDMENT", "WELDED", "WELD ASSY", "WELD"))
    bonding = "BOND" in title_upper or welding  # weldments usually pre-bond

    sub_items = []
    hardware_items = []
    for c in components:
        role = c.get("component_role") or ""
        entry = {
            "component_index": c.get("component_index"),
            "name":            c.get("name"),
            "material":        c.get("material"),
            "role":            role,
        }
        if role == "sub_item_sheet" or (c.get("part_type") or "").lower() in ("cnc_milling", "sheet_metal"):
            sub_items.append(entry)
        elif (role == "hardware" or (c.get("part_type") or "").lower() == "hardware"):
            hardware_items.append(entry)

    # Aggregate bbox = bounding envelope of all sub-item bboxes (rough).
    max_len = max((float((c.get("bbox") or {}).get("length_mm") or 0) for c in components), default=0.0)
    max_wid = max((float((c.get("bbox") or {}).get("width_mm")  or 0) for c in components), default=0.0)
    max_hei = max((float((c.get("bbox") or {}).get("height_mm") or 0) for c in components), default=0.0)

    return {
        "component_index": next_component_index,
        "name":             "TOP_ASSEMBLY",
        "description":      "Synthesized top-assembly routing line",
        "part_type":        "assembly_top",
        "part_type_confidence": 1.0,
        "component_role":   "assembly_top",
        "component_role_reason": "synthesized_for_multi_item_weldment",
        "instance_count":   1,
        "bom_part_type":    "assembly",
        "assembly_path":    "/" + (vlm_extraction.get("part_number") or "TOP"),
        "bbox": {
            "length_mm": max_len, "width_mm": max_wid, "height_mm": max_hei,
        },
        "volume_mm3": 0.0,
        "features": [],
        "thickness": None,
        "material": "PVC welded enclosure (multi-item)" if welding else "Multi-item assembly",
        "tagged_dimensions": [],
        "manufacturing_processes": [],
        "agentic": {},
        # Hints the agent will read in its user message.
        "assembly_hint": {
            "welding_required":  welding,
            "bonding_required":  bonding,
            "sub_item_count":    len(sub_items),
            "hardware_count":    len(hardware_items),
            "sub_items":         sub_items,
            "hardware_items":    hardware_items,
        },
    }


__all__ = [
    "classify_components",
    "detect_top_assembly",
    "synthesize_assembly_top_component",
]
