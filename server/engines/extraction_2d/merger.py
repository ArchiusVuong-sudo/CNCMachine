"""Merge per-page VLM JSONs into one assembled :class:`DrawingExtraction`.

The VLM returns one JSON per page; we coalesce them into a single object
that downstream engines can treat as if the drawing had been a single
sheet. Specifics:

  * ``dimensions / gdt / threads`` — concatenated with renumbered IDs.
  * ``title_block`` — first non-null page wins; later pages fill missing
    fields.
  * ``bom`` — rows deduped by ``(item_no, part_number)``.
  * ``material / surface_finish / assembly_method`` — first non-null wins.
  * ``notes`` — concatenated, blank-stripped.

The output dict shape matches what the legacy ``engine_extract_2d``
returned, so engine 3 can consume it unchanged.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("cncserver.engines.extraction_2d.merger")


def merge_pages(parsed_list: list[dict]) -> dict:
    """Merge a list of per-page parsed JSONs into a single dict."""
    all_dims:        list[dict] = []
    all_gdt:         list[dict] = []
    all_threads:     list[dict] = []
    material:        Any = None
    surface_finish:  Any = None
    title_block:     dict | None = None
    bom_rows:        list[dict] = []
    assembly_method: Any = None
    notes:           list[str] = []
    seen_bom_keys: set[tuple[str, str]] = set()

    d_count = g_count = t_count = 1

    for parsed in parsed_list:
        if parsed.get("raw_model_output"):
            continue

        for d in (parsed.get("dimensions") or []):
            if not isinstance(d, dict):
                continue
            rest = {k: v for k, v in d.items() if k != "id"}
            all_dims.append({**rest, "id": f"D{str(d_count).zfill(3)}"})
            d_count += 1
        for g in (parsed.get("gdt") or []):
            if not isinstance(g, dict):
                continue
            rest = {k: v for k, v in g.items() if k != "id"}
            all_gdt.append({**rest, "id": f"G{str(g_count).zfill(3)}"})
            g_count += 1
        for t in (parsed.get("threads") or []):
            if not isinstance(t, dict):
                continue
            rest = {k: v for k, v in t.items() if k != "id"}
            all_threads.append({**rest, "id": f"T{str(t_count).zfill(3)}"})
            t_count += 1

        if not material and parsed.get("material"):
            material = parsed["material"]
        if not surface_finish and parsed.get("surface_finish"):
            surface_finish = parsed["surface_finish"]

        tb = parsed.get("title_block")
        if isinstance(tb, dict):
            if title_block is None:
                title_block = {k: v for k, v in tb.items() if v is not None}
            else:
                for k, v in tb.items():
                    if v is not None and not title_block.get(k):
                        title_block[k] = v

        bom_raw = parsed.get("bom")
        if isinstance(bom_raw, list):
            for row in bom_raw:
                if not isinstance(row, dict):
                    continue
                key = (str(row.get("item_no") or ""), str(row.get("part_number") or ""))
                if key in seen_bom_keys and key != ("", ""):
                    continue
                seen_bom_keys.add(key)
                qty = row.get("qty", 1)
                try:
                    qty = int(qty) if qty is not None else 1
                except (TypeError, ValueError):
                    qty = 1
                bom_rows.append({
                    "item_no":            row.get("item_no"),
                    "description":        row.get("description"),
                    "part_number":        row.get("part_number"),
                    "qty":                qty,
                    "teng_c":             row.get("teng_c"),
                    "materials_inferred": row.get("materials_inferred") or row.get("material"),
                    "part_type":          row.get("part_type"),
                })

        am = parsed.get("assembly_method")
        if assembly_method is None and isinstance(am, str) and am.strip():
            assembly_method = am.strip().lower()

        for note in (parsed.get("notes") or []):
            if isinstance(note, str) and note.strip():
                notes.append(note.strip())

    merged = {
        "dimensions":      all_dims,
        "gdt":             all_gdt,
        "threads":         all_threads,
        "material":        material,
        "surface_finish":  surface_finish,
        "notes":           notes,
        "title_block":     title_block,
        "bom":             bom_rows,
        "assembly_method": assembly_method,
    }
    logger.info(
        "merge_pages: pages=%d → dims=%d gdt=%d threads=%d bom=%d notes=%d tb=%s am=%s",
        len(parsed_list),
        len(all_dims), len(all_gdt), len(all_threads),
        len(bom_rows), len(notes),
        "yes" if title_block else "no",
        assembly_method or "-",
    )
    return merged


# ---------------------------------------------------------------------------
# Unit resolution: title block → dim votes → thread heuristic → fallback
# ---------------------------------------------------------------------------

def resolve_dimension_unit(merged: dict) -> str:
    """Pick the most likely dimension unit for the whole drawing.

    Returns ``"in"`` or ``"mm"``. Never returns ``None`` — downstream
    consumers always need a concrete unit to render UI.
    """
    tb = merged.get("title_block") or {}
    tb_unit = (tb.get("dimension_unit") if isinstance(tb, dict) else None) or ""
    s = str(tb_unit).strip().lower()
    if s:
        if "in" in s or "imp" in s or "inch" in s:
            return "in"
        if "mm" in s or "milli" in s or "metric" in s:
            return "mm"

    counts: dict[str, int] = {}
    for d in (merged.get("dimensions") or []):
        if not isinstance(d, dict):
            continue
        u = d.get("unit")
        if isinstance(u, str) and u.strip():
            k = u.strip().lower()
            counts[k] = counts.get(k, 0) + 1
    if counts:
        best = max(counts.items(), key=lambda kv: kv[1])[0]
        if "in" in best:
            return "in"
        if "mm" in best or "metric" in best:
            return "mm"

    thread_text = " ".join(
        str((t or {}).get("spec") or (t or {}).get("label") or "")
        for t in (merged.get("threads") or [])
    ).lower()
    if any(tok in thread_text for tok in ("unf", "unc", "unef", "npt")):
        return "in"
    if re.search(r"\bm\d", thread_text):
        return "mm"

    return "mm"
