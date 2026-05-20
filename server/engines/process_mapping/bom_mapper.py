"""
bom_mapper.py â€” Map BOM line items to assembly components via fuzzy text matching.

Primary strategy : rapidfuzz token_set_ratio on description fields (threshold 75).
Fallback strategy: TEngC/part-number regex match from component name.
Result           : one mapping dict per component.

Public API:
    def map_bom_to_components(bom_items, components) -> list[dict]

Mapping dict shape:
    {
        "component_index": int,
        "mapped_to_bom_item": int | None,   # item_no from BOM, 1-based
        "material": str | None,
        "bom_part_type": str | None,        # "cnc_machined" | "hardware" | etc.
        "mapping_method": "description" | "tengc" | "unknown",
        "match_score": float,               # 0.0â€“1.0
    }

Usage example:
    bom = [
        {"item_no": 1, "part_number": "TC2-41223", "description": "BRACKET ASSY",
         "qty": 2, "tengc": "TC2-41223", "material": "AL6061-T6", "part_type": ""},
        {"item_no": 2, "part_number": "TC2-41224", "description": "GUSSET PLATE",
         "qty": 1, "tengc": "", "material": "304 SS", "part_type": ""},
    ]
    comps = [
        {"component_index": 0, "name": "TC2-41223_BRACKET", "description": "BRACKET ASSY"},
        {"component_index": 1, "name": "TC2-41224", "description": "GUSSET PLATE"},
    ]
    result = map_bom_to_components(bom, comps)
    # result[0] â†’ {"component_index": 0, "mapped_to_bom_item": 1,
    #               "material": "AL6061-T6", "mapping_method": "description",
    #               "match_score": 0.95}
    # result[1] â†’ {"component_index": 1, "mapped_to_bom_item": 2,
    #               "material": "304 SS", "mapping_method": "description",
    #               "match_score": 1.0}
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cncserver.engines.process_mapping.bom_mapper")

# TEngC# patterns typically: TC2-41223, TC-41224-01, 3410-00489
_TENGC_RE = re.compile(r"(?:TC\d*-\d+|TC-\d+(?:-\d+)*|\d{4}-\d{5}(?:_\d+)?)", re.IGNORECASE)

_DESCRIPTION_THRESHOLD = 75    # rapidfuzz token_set_ratio 0â€“100
_TENGC_EXACT_SCORE     = 1.0
_TENGC_FUZZY_SCORE     = 0.8


def _try_import_rapidfuzz():
    """Import rapidfuzz if available; return (fuzz, process) or (None, None)."""
    try:
        from rapidfuzz import fuzz as _fuzz, process as _process
        return _fuzz, _process
    except ImportError:
        logger.warning("rapidfuzz not installed â€” falling back to simple contains match")
        return None, None


def _simple_token_score(a: str, b: str) -> float:
    """Naive fallback when rapidfuzz is not installed: token overlap ratio."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = tokens_a & tokens_b
    return len(overlap) / max(len(tokens_a), len(tokens_b))


def _extract_tengc(text: str) -> list[str]:
    """Extract all TEngC-like tokens from a string."""
    return [m.group(0).upper() for m in _TENGC_RE.finditer(text)]


def map_bom_to_components(
    bom_items: list[dict],
    components: list[dict],
) -> list[dict]:
    """
    For each component, find the best-matching BOM line item.

    Parameters
    ----------
    bom_items   : list of BOM line item dicts with keys:
                    item_no, part_number, description, qty, tengc, material, part_type
    components  : list of component dicts from analyze_step_assembly with keys:
                    component_index, name, description, ...

    Returns
    -------
    list[dict] â€” one entry per component (ordered by component_index).
    """
    fuzz, _process = _try_import_rapidfuzz()

    if not bom_items:
        logger.info("bom_mapper: no BOM items â€” all components unmapped")
        return [
            {
                "component_index":    c.get("component_index", i),
                "mapped_to_bom_item": None,
                "material":           None,
                "bom_part_type":      None,
                "mapping_method":     "unknown",
                "match_score":        0.0,
            }
            for i, c in enumerate(components)
        ]

    # Pre-extract TEngC tokens from BOM items.
    # Field name varies across VLM extractions: `teng_c` (current schema) and
    # legacy `tengc` are both supported. part_number is the secondary source.
    bom_tengc: dict[int, list[str]] = {}  # item_no â†’ tokens
    for bom in bom_items:
        item_no = bom.get("item_no")
        if item_no is None:
            continue
        tengc_field = str(bom.get("teng_c") or bom.get("tengc") or "")
        pn_field    = str(bom.get("part_number") or "")
        tokens      = list({*_extract_tengc(tengc_field), *_extract_tengc(pn_field)})
        bom_tengc[item_no] = tokens

    mappings: list[dict] = []

    for i, comp in enumerate(components):
        comp_idx   = comp.get("component_index", i)
        comp_name  = str(comp.get("name") or "")
        comp_desc  = str(comp.get("description") or "")
        comp_label = f"{comp_name} {comp_desc}".strip()

        best_item_no:   int | None = None
        best_score:     float      = 0.0
        best_method:    str        = "unknown"
        best_material:  str | None = None
        best_part_type: str | None = None

        # â”€â”€ Primary: fuzzy description match â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        for bom in bom_items:
            item_no  = bom.get("item_no")
            bom_desc = str(bom.get("description") or "")
            bom_pn   = str(bom.get("part_number") or "")
            bom_label = f"{bom_pn} {bom_desc}".strip()

            if fuzz is not None:
                raw_score = fuzz.token_set_ratio(comp_label, bom_label)
                score = raw_score / 100.0
            else:
                score = _simple_token_score(comp_label, bom_label)
                # scale to 0â€“1; threshold was 75/100 â†’ 0.75
                raw_score = score * 100.0

            if raw_score >= _DESCRIPTION_THRESHOLD and score > best_score:
                best_score     = score
                best_item_no   = item_no
                best_method    = "description"
                best_material  = bom.get("material") or bom.get("materials_inferred") or None
                best_part_type = bom.get("part_type") or None

        # â”€â”€ Fallback: TEngC token match â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if best_item_no is None:
            comp_tengc_tokens = _extract_tengc(comp_label)
            for bom in bom_items:
                item_no = bom.get("item_no")
                for ct in comp_tengc_tokens:
                    if ct in (bom_tengc.get(item_no) or []):
                        best_item_no   = item_no
                        best_score     = _TENGC_EXACT_SCORE
                        best_method    = "tengc"
                        best_material  = bom.get("material") or bom.get("materials_inferred") or None
                        best_part_type = bom.get("part_type") or None
                        break
                if best_item_no is not None:
                    break

        # â”€â”€ Partial TEngC fuzzy: comp token appears as substring in BOM â”€â”€â”€â”€â”€
        # Try both `teng_c` and `part_number` as the BOM-side identifier so we
        # handle assemblies whose BOM only carries the TEngC code (PVC sheet
        # parts in 0042-83323).
        # Guard: require BOTH sides non-empty â€” otherwise "" in anything == True
        # and BOM items without a part_number match every component spuriously
        # (the 0042-88459 INSERT-THREAD false-match bug).
        if best_item_no is None:
            comp_tengc_tokens = _extract_tengc(comp_label)
            for bom in bom_items:
                item_no = bom.get("item_no")
                bom_ids: list[str] = []
                for k in ("part_number", "teng_c", "tengc"):
                    v = str(bom.get(k) or "").upper().strip()
                    if v:
                        bom_ids.append(v)
                if not bom_ids:
                    continue
                matched = False
                for bid in bom_ids:
                    for ct in comp_tengc_tokens:
                        if not ct:
                            continue
                        if ct in bid or bid in ct:
                            score = _TENGC_FUZZY_SCORE
                            if score > best_score:
                                best_item_no   = item_no
                                best_score     = score
                                best_method    = "tengc"
                                best_material  = bom.get("material") or bom.get("materials_inferred") or None
                                best_part_type = bom.get("part_type") or None
                                matched = True
                                break
                    if matched:
                        break

        mappings.append({
            "component_index":    comp_idx,
            "mapped_to_bom_item": best_item_no,
            "material":           best_material,
            "bom_part_type":      best_part_type,
            "mapping_method":     best_method,
            "match_score":        round(best_score, 4),
        })

        logger.debug(
            "bom_mapper: comp[%d] '%s' â†’ bom_item=%s method=%s score=%.2f mat=%s bom_part_type=%s",
            comp_idx, comp_name, best_item_no, best_method, best_score,
            best_material, best_part_type,
        )

    logger.info(
        "bom_mapper: %d/%d components mapped",
        sum(1 for m in mappings if m["mapped_to_bom_item"] is not None),
        len(mappings),
    )
    return mappings
