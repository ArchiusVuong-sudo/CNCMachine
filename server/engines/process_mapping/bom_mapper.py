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

    # Pre-extract TEngC tokens from BOM items, kept in SEPARATE pools per
    # field. The `teng_c` field is the manufactured-part identity (the
    # strongest match signal); `part_number` is the customer drawing number
    # which a *different* component can legitimately reference inside its STEP
    # node name (e.g. a Helicoil insert installed into adaptor "3410-00013"
    # is named `TC1-0048965_05-3410-00013` — its OWN identity is the leading
    # TEngC `TC1-0048965`, while `3410-00013` is the host adaptor's part
    # number). Folding both fields into one pool and taking the first item
    # that shares ANY token mis-maps the insert onto the adaptor's BOM line.
    bom_tengc_field: dict[int, set[str]] = {}  # item_no → teng_c tokens
    bom_pn_field:    dict[int, set[str]] = {}  # item_no → part_number tokens
    for bom in bom_items:
        item_no = bom.get("item_no")
        if item_no is None:
            continue
        tengc_field = str(bom.get("teng_c") or bom.get("tengc") or "")
        pn_field    = str(bom.get("part_number") or "")
        bom_tengc_field[item_no] = set(_extract_tengc(tengc_field))
        bom_pn_field[item_no]    = set(_extract_tengc(pn_field))

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

        # Picks the strongest match over every BOM item rather than the first
        # item that shares any token. Priority, highest first:
        #   1. component's OWN identity (leading TEngC token from the node name)
        #      == a BOM item's `teng_c` field  — the definitive match.
        #   2. any component token == a BOM `teng_c` field token.
        #   3. own-identity / any token == a BOM `part_number` token.
        #   4. substring matches (either direction), same field ordering.
        # teng_c-field beats part_number-field, exact beats substring, and the
        # leading identity token beats trailing referenced tokens — so a
        # Helicoil named `TC1-0048965_05-3410-00013` maps to its OWN line
        # (teng_c TC1-0048965) instead of the host adaptor it references.
        if best_item_no is None:
            name_tokens = _extract_tengc(comp_name)
            primary     = name_tokens[0] if name_tokens else None
            all_tokens  = set(_extract_tengc(comp_label))

            def _tengc_tier(teng_set: set[str], pn_set: set[str]) -> float:
                # Exact, teng_c field
                if primary and primary in teng_set:
                    return 1.00
                if teng_set & all_tokens:
                    return 0.95
                # Exact, part_number field
                if primary and primary in pn_set:
                    return 0.90
                if pn_set & all_tokens:
                    return 0.85
                # Substring (either direction) — guard both sides non-empty so
                # an empty BOM identifier can't match every component (the
                # 0042-88459 INSERT-THREAD false-match bug).
                def _sub(tok: str, pool: set[str]) -> bool:
                    return bool(tok) and any(p and (tok in p or p in tok) for p in pool)
                if primary and _sub(primary, teng_set):
                    return 0.80
                if any(_sub(t, teng_set) for t in all_tokens):
                    return 0.78
                if primary and _sub(primary, pn_set):
                    return 0.76
                if any(_sub(t, pn_set) for t in all_tokens):
                    return 0.74
                return 0.0

            best_tier = 0.0
            for bom in bom_items:
                item_no = bom.get("item_no")
                tier = _tengc_tier(
                    bom_tengc_field.get(item_no) or set(),
                    bom_pn_field.get(item_no) or set(),
                )
                if tier > best_tier:
                    best_tier      = tier
                    best_item_no   = item_no
                    best_score     = tier
                    best_method    = "tengc"
                    best_material  = bom.get("material") or bom.get("materials_inferred") or None
                    best_part_type = bom.get("part_type") or None

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
