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

import logging
import time

from ...core.events import OnEvent, OnThinking, safe_emit, safe_emit_thinking
from ...core.schemas import DrawingExtraction
from ...core.settings import get_settings
from .merger import merge_pages, resolve_dimension_unit
from .page_analyzer import analyze_one_page
from .rasterizer import file_to_base64_pages

logger = logging.getLogger("cncserver.engines.extraction_2d")


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
    for i, page_b64 in enumerate(pages_b64):
        await safe_emit(on_event, "status", {
            "title":   "GD&T Extraction",
            "message": f"Drawing page {i + 1}/{total}…",
        })

        async def _forward(chunk: str) -> None:
            await safe_emit_thinking(on_thinking, chunk)

        try:
            parsed, outcome = await analyze_one_page(page_b64, on_thinking=_forward)
            if parsed and not parsed.get("raw_model_output"):
                all_parsed.append(parsed)
            logger.info(
                "engine_2d: page %d/%d outcome=%s keys=%s",
                i + 1, total, outcome,
                list(parsed.keys())[:8] if parsed else [],
            )
        except Exception as exc:
            logger.warning("engine_2d: page %d/%d failed: %s", i + 1, total, exc)

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
        part_number = tb.get("part_number") or ""
        revision    = tb.get("revision") or ""
        description = tb.get("description") or tb.get("title") or ""

    extraction = DrawingExtraction(
        part_number    = part_number,
        revision       = revision,
        description    = description,
        material       = merged.get("material") or "",
        surface_finish = merged.get("surface_finish") or None,
        dimension_unit = unit,
        title_block    = tb if isinstance(tb, dict) and tb else None,
        bom_items      = merged.get("bom") or [],
        drawing_notes  = merged.get("notes") or [],
        dimensions     = merged.get("dimensions") or [],
        gdt_callouts   = merged.get("gdt") or [],
        threads        = merged.get("threads") or [],
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
