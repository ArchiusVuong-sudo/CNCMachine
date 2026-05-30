"""Public Engine 1 entry point: bytes in, :class:`DrawingExtraction` out.

This is the single function the orchestrator calls. Internally it:

  1. Rasterizes the drawing to base64 PNG pages.
  2. Streams each page through the VLM (with retry).
  3. Merges per-page parsed JSONs into one structure.
  4. Flattens legacy keys (``bom`` → ``bom_items``, ``gdt`` → ``gdt_callouts``,
     ``notes`` → ``drawing_notes``) so the wire shape matches the
     :class:`DrawingExtraction` contract.
  5. Emits status / tool_result events through the optional ``on_event``
     callback.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ...core.events import OnEvent, OnThinking, safe_emit
from ...core.schemas import DrawingExtraction
from ...core.settings import get_settings
from .merger import merge_pages, resolve_dimension_unit
from .page_analyzer import analyze_one_page
from .rasterizer import file_to_base64_pages

logger = logging.getLogger("cncserver.engines.extraction_2d")


# U+FFFD REPLACEMENT CHARACTER shows up when a glyph from the drawing (often
# ™ / ° / Ø) couldn't be decoded. Carrying it forward poisons string
# comparisons in the agent ("PEEK, Semitron� ESD 480" vs catalog "PEEK,
# Semitron ESD 480"), so drop it at the engine boundary.
def _strip_replacement(s: Any) -> Any:
    if isinstance(s, str) and "�" in s:
        return s.replace("�", "").strip()
    return s


def _derive_part_category(assembly_method: str | None, bom_rows: list[dict]) -> str | None:
    """Drawing-level "part category".

    Distinct from per-row :attr:`BomItem.part_type`; this is the
    top-level family of the WHOLE drawing.

    Priority:
      1. ``assembly_method`` (welded → "weldment", bolted → "assembly_bolted",
         riveted → "assembly_riveted", bonded → "assembly_bonded")
      2. Single non-hardware BOM row → that row's ``part_type``
      3. Multiple non-hardware BOM rows → "assembly"
      4. Nothing extractable → None
    """
    am = (assembly_method or "").strip().lower()
    if am == "welded":
        return "weldment"
    if am == "bolted":
        return "assembly_bolted"
    if am == "riveted":
        return "assembly_riveted"
    if am == "bonded":
        return "assembly_bonded"
    non_hw: list[str] = []
    for row in bom_rows or []:
        if not isinstance(row, dict):
            continue
        pt = (row.get("part_type") or "").lower().strip()
        if pt and pt != "hardware":
            non_hw.append(pt)
    unique = sorted(set(non_hw))
    if len(unique) == 1:
        return unique[0]
    if len(non_hw) > 1:
        return "assembly"
    return None


def _backfill_material_from_bom(material: str, bom_rows: list[dict]) -> str:
    """If top-level material is empty, fall back to the only non-hardware BOM
    line's material. Stays silent when ambiguous (multiple candidates with
    different materials) so we don't fabricate a wrong top-level material on a
    multi-item assembly — Engine 3 will read per-component material instead.
    """
    if material and material.strip():
        return material
    candidates: list[str] = []
    for row in bom_rows or []:
        if not isinstance(row, dict):
            continue
        pt = str(row.get("part_type") or "").lower()
        if pt == "hardware":
            continue
        m = row.get("materials_inferred") or row.get("material")
        if isinstance(m, str) and m.strip():
            candidates.append(_strip_replacement(m).strip())
    if not candidates:
        return material or ""
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0]
    return material or ""


async def run(
    drawing_bytes: bytes,
    *,
    filename: str = "",
    max_pages: int | None = None,
    on_event: OnEvent = None,
    on_thinking: OnThinking = None,
) -> DrawingExtraction:
    """Run Engine 1 on raw drawing bytes.

    Parameters
    ----------
    drawing_bytes : raw bytes of the uploaded drawing (PDF or image).
    filename      : original filename, used only for logging.
    max_pages     : cap on pages sent to VLM. ``None`` → use
                    :attr:`ExtractionSettings.pdf_max_pages` from settings.
                    ``<= 0`` means "process every page".
    on_event      : async callback receiving SSE events.
    on_thinking   : async callback receiving VLM thinking chunks.

    Returns
    -------
    :class:`DrawingExtraction` — schema-validated. On total VLM failure
    returns an empty extraction (never raises).
    """
    t0 = time.monotonic()
    if max_pages is None:
        max_pages = get_settings().extraction.pdf_max_pages
    cap_display = "all" if max_pages <= 0 else str(max_pages)

    logger.info(
        "engine_2d START: file=%s bytes=%dKB max_pages=%s",
        filename or "-", len(drawing_bytes) // 1024, cap_display,
    )
    await safe_emit(on_event, "status", {
        "title":   "2D Drawing Extraction",
        "message": "Rasterizing & sending to VLM...",
    })

    try:
        pages_b64 = file_to_base64_pages(
            drawing_bytes, filename=filename, max_pages=max_pages,
        )
    except Exception as exc:
        logger.exception("engine_2d: rasterize failed")
        await safe_emit(on_event, "tool_result", {
            "tool":   "analyze_drawing",
            "result": {"error": f"rasterize failed: {exc}"},
        })
        return DrawingExtraction.empty()

    total = len(pages_b64)
    logger.info("engine_2d: rasterized %d page(s)", total)

    all_parsed: list[dict] = []
    # Running tally so each page's status frame reports cumulative findings —
    # the live signal during 2D extraction. We deliberately do NOT stream the
    # raw per-page VLM content as "thinking" (it's JSON output, not reasoning).
    #
    # Pages run CONCURRENTLY (bounded by a semaphore) instead of one-at-a-time:
    # a 21-page drawing went from ~170s sequential to ~50s. Status frames fire
    # via asyncio.as_completed so progress still advances live as each page lands.
    tally = {"dimensions": 0, "gdt": 0, "threads": 0, "bom": 0}
    sem = asyncio.Semaphore(4)

    async def _process_page(idx: int, b64: str) -> tuple[int, dict | None, str]:
        async with sem:
            try:
                parsed, outcome = await analyze_one_page(b64, on_thinking=None)
                logger.info(
                    "engine_2d: page %d/%d outcome=%s keys=%s",
                    idx + 1, total, outcome,
                    list(parsed.keys())[:8] if parsed else [],
                )
                return idx, parsed, outcome
            except Exception as exc:  # noqa: BLE001
                logger.warning("engine_2d: page %d/%d failed: %s", idx + 1, total, exc)
                return idx, None, "error"

    await safe_emit(on_event, "status", {
        "title":   "Drawing Extraction",
        "message": f"Reading {total} drawing page(s) concurrently…",
    })

    tasks = [asyncio.create_task(_process_page(i, b64)) for i, b64 in enumerate(pages_b64)]
    done_count = 0
    for coro in asyncio.as_completed(tasks):
        _idx, parsed, _outcome = await coro
        done_count += 1
        if parsed and not parsed.get("raw_model_output"):
            all_parsed.append(parsed)
            tally["dimensions"] += len(parsed.get("dimensions") or [])
            tally["gdt"]        += len(parsed.get("gdt") or [])
            tally["threads"]    += len(parsed.get("threads") or [])
            tally["bom"]        += len(parsed.get("bom") or [])
        found = (
            f" · found so far: {tally['dimensions']} dims, {tally['gdt']} GD&T, "
            f"{tally['threads']} threads, {tally['bom']} BOM"
            if any(tally.values()) else ""
        )
        await safe_emit(on_event, "status", {
            "title":   "Drawing Extraction",
            "message": f"Page {done_count}/{total} read{found}…",
        })

    if not all_parsed:
        logger.warning("engine_2d: no parseable pages in %.2fs — empty extraction",
                       time.monotonic() - t0)
        await safe_emit(on_event, "tool_result", {
            "tool":   "analyze_drawing",
            "result": {"dimension_count": 0, "gdt_count": 0, "bom_items": 0,
                       "material": None},
        })
        await safe_emit(on_event, "status", {
            "title":   "GD&T Extraction",
            "message": "Drawing analysis complete (no data extracted)",
            "completed": True,
        })
        return DrawingExtraction.empty()

    merged = merge_pages(all_parsed)
    unit = resolve_dimension_unit(merged)

    tb = merged.get("title_block") or {}
    part_number = ""
    revision    = ""
    description = ""
    if isinstance(tb, dict):
        part_number = _strip_replacement(tb.get("part_number") or "")
        revision    = _strip_replacement(tb.get("revision") or "")
        description = _strip_replacement(tb.get("description") or tb.get("title") or "")

    bom_items_raw = merged.get("bom") or []
    bom_items = [
        {k: _strip_replacement(v) for k, v in row.items()}
        if isinstance(row, dict) else row
        for row in bom_items_raw
    ]
    raw_material = _strip_replacement(merged.get("material") or "")
    material = _backfill_material_from_bom(raw_material, bom_items)
    if material != raw_material:
        logger.info(
            "engine_2d: top-level material was empty — backfilled from BOM → %r",
            material,
        )

    assembly_method = _strip_replacement(merged.get("assembly_method")) or None
    if isinstance(assembly_method, str):
        assembly_method = assembly_method.strip().lower() or None
    part_category = _derive_part_category(assembly_method, bom_items)

    extraction = DrawingExtraction(
        part_number     = part_number,
        revision        = revision,
        description     = description,
        material        = material,
        surface_finish  = _strip_replacement(merged.get("surface_finish")) or None,
        dimension_unit  = unit,
        assembly_method = assembly_method,
        part_category   = part_category,
        title_block     = tb if isinstance(tb, dict) and tb else None,
        bom_items       = bom_items,
        drawing_notes   = merged.get("notes") or [],
        dimensions      = merged.get("dimensions") or [],
        gdt_callouts    = merged.get("gdt") or [],
        threads         = merged.get("threads") or [],
    )

    logger.info(
        "engine_2d DONE in %.2fs — part=%s mat=%s dims=%d gdt=%d threads=%d bom=%d notes=%d unit=%s",
        time.monotonic() - t0,
        extraction.part_number or "-",
        (extraction.material or "-")[:24],
        len(extraction.dimensions),
        len(extraction.gdt_callouts),
        len(extraction.threads),
        len(extraction.bom_items),
        len(extraction.drawing_notes),
        unit,
    )
    await safe_emit(on_event, "tool_result", {
        "tool": "analyze_drawing",
        "result": {
            "dimension_count": len(extraction.dimensions),
            "gdt_count":       len(extraction.gdt_callouts),
            "bom_items":       len(extraction.bom_items),
            "material":        extraction.material,
            "part_number":     extraction.part_number,
        },
    })
    await safe_emit(on_event, "status", {
        "title":     "GD&T Extraction",
        "message":   "Drawing analysis complete",
        "completed": True,
    })
    return extraction
