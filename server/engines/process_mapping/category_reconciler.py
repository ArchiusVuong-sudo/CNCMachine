"""
category_reconciler.py â€” Reconcile OCR-derived part type with AFR (auto feature
recognition) part type to fix routing mismatches.

Background
----------
Two independent signals describe a component's part type:

  1. OCR side  â€” drawing's BOM column (set on the component as `bom_part_type`
                 by `bom_mapper.py`). Trusts the customer's intent.
  2. AFR side  â€” `part_classifier.py` voting from STEP geometry (`comp.part_type`).
                 Trusts geometry but misclassifies edge cases (silicone gaskets
                 read as TUBE_PIPE, 12mm plates read as SHEET_METAL, etc).

When the two disagree the routing engine picks the wrong path. This module
applies a small set of rules to choose the trustworthy signal and records a
decision per component so the UI can surface the call.

Public API
----------
    reconcile_part_categories(components, vlm_extraction) -> list[dict]
        Mutates each component's `part_type` if a reconciliation rule fires
        and returns one decision dict per component.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("cncserver.engines.process_mapping.category_reconciler")


# Materials whose presence is a stronger signal than any AFR call: nothing
# in this list is machined, regardless of geometry.
_NON_MACHINABLE_MATERIAL_TOKENS: tuple[str, ...] = (
    "SILICONE", "RUBBER", "ELASTOMER", "VITON", "EPDM",
    "NEOPRENE", "GASKET", "FOAM", "FELT", "CORK",
)

# OCR-side strings that mean "purchased / standard hardware".
_HARDWARE_OCR_TYPES: frozenset[str] = frozenset({
    "hardware", "purchased", "standard", "standard_part", "off_the_shelf",
    "fastener", "fasteners",
})

# OCR-side strings that mean "machined in-house".
_MACHINED_OCR_TYPES: frozenset[str] = frozenset({
    "cnc_machined", "cnc_milling", "cnc_lathe", "cnc_lathe_milling",
    "machined", "milled", "turned",
})

# Below this minimum bbox dimension (mm) a part can plausibly be sheet metal.
_SHEET_METAL_MAX_THICKNESS_MM = 12.0


def _min_bbox_dim(comp: dict) -> float:
    """Return the smallest bbox dimension; sentinel large value if missing."""
    bb = comp.get("bbox") or {}
    dims = [
        float(bb.get("length_mm") or 0),
        float(bb.get("width_mm")  or 0),
        float(bb.get("height_mm") or 0),
    ]
    nonzero = [d for d in dims if d > 0]
    return min(nonzero) if nonzero else 1e9


def _material_text(comp: dict, vlm_extraction: dict) -> str:
    """Return the material string in uppercase for token matching."""
    return (
        (comp.get("material") or vlm_extraction.get("material") or "")
        .upper()
        .strip()
    )


def reconcile_component_category(comp: dict, vlm_extraction: dict) -> dict:
    """
    Apply rules in order; first matching rule wins.

    Returns a decision dict and mutates `comp["part_type"]` when reconciliation
    changes the call.
    """
    afr_type = (comp.get("part_type") or "unknown").lower()
    ocr_type = (comp.get("bom_part_type") or "").lower() or None
    material = _material_text(comp, vlm_extraction)

    decision = {
        "component_index":      comp.get("component_index"),
        "component_name":       comp.get("name", "?"),
        "afr_part_type":        afr_type,
        "ocr_part_type":        ocr_type,
        "material":             material or None,
        "reconciled_part_type": afr_type,
        "reason":               "afr_only",
        "confidence":           float(comp.get("part_type_confidence") or 0.5),
        "changed":              False,
    }

    def _set(reconciled: str, reason: str, confidence: float) -> dict:
        decision["reconciled_part_type"] = reconciled
        decision["reason"]               = reason
        decision["confidence"]           = round(confidence, 3)
        decision["changed"]              = (reconciled != afr_type)
        if decision["changed"]:
            comp["part_type"] = reconciled
        return decision

    # Rule 1: non-machinable material â†’ hardware regardless of geometry
    if any(tok in material for tok in _NON_MACHINABLE_MATERIAL_TOKENS):
        return _set("hardware", "material_non_machinable", 0.95)

    # Rule 2: BOM explicitly says hardware/purchased â†’ trust BOM
    if ocr_type in _HARDWARE_OCR_TYPES:
        return _set("hardware", "bom_hardware", 0.90)

    # Rule 3: OCR + AFR agree on machined family â†’ keep AFR
    if ocr_type in _MACHINED_OCR_TYPES and afr_type in _MACHINED_OCR_TYPES:
        return _set(afr_type, "ocr_afr_agreement", 0.95)

    # Rule 4: BOM says machined but AFR says sheet_metal â€” geometry tiebreak
    if ocr_type in _MACHINED_OCR_TYPES and afr_type == "sheet_metal":
        thickness = _min_bbox_dim(comp)
        if thickness > _SHEET_METAL_MAX_THICKNESS_MM:
            return _set(
                ocr_type if ocr_type in _MACHINED_OCR_TYPES else "cnc_milling",
                f"bom_machined_thickness_{thickness:.1f}mm_exceeds_sheet_max",
                0.85,
            )
        # thin part, BOM might be wrong but AFR is plausible â€” keep AFR
        return _set("sheet_metal", "afr_sheet_metal_thickness_plausible", 0.7)

    # Rule 5: BOM says machined, AFR says something else â†’ trust BOM
    if ocr_type in _MACHINED_OCR_TYPES:
        return _set(ocr_type, "bom_machined_overrides_afr", 0.7)

    # Rule 6: No BOM info â†’ keep AFR
    if not ocr_type:
        return _set(afr_type, "afr_only_no_bom",
                    float(comp.get("part_type_confidence") or 0.5))

    # Rule 7: Conflict that no rule covers â†’ keep AFR, log for review
    logger.info(
        "category_reconciler: unresolved conflict comp=%s ocr=%s afr=%s â€” kept afr",
        decision["component_name"], ocr_type, afr_type,
    )
    return _set(afr_type, f"conflict_kept_afr_ocr_was_{ocr_type}", 0.5)


def reconcile_part_categories(
    components: list[dict],
    vlm_extraction: dict,
) -> list[dict]:
    """Run reconciliation across every component and return the decision list."""
    decisions: list[dict] = []
    for comp in components:
        d = reconcile_component_category(comp, vlm_extraction)
        decisions.append(d)
        if d["changed"]:
            logger.info(
                "category_reconciler: comp[%s] %s changed %s â†’ %s (%s, conf=%.2f)",
                d["component_index"], d["component_name"],
                d["afr_part_type"], d["reconciled_part_type"],
                d["reason"], d["confidence"],
            )
    return decisions
