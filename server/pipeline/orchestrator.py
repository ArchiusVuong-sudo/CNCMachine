"""Four-engine SSE pipeline.

Phase layout::

  Phase 0: Download STEP + drawing from storage URLs (or accept raw bytes).
  Phase 1: Engines 1 + 2 + catalog fetch run concurrently.
            - Engine 1 (VLM 2D extraction)            on a 600s deadline.
            - Engine 2 (OCC 3D feature recognition)   no cap.
            - fetch_shop_catalog                       no cap.
           Heartbeats are emitted while we wait.
  Phase 2: Engine 3 (process planning + cost) consumes outputs from 1 & 2.
  Phase 3: Engine 4 (CAM / FreeCAD G-code) consumes the ProcessPlan from
           Phase 2 plus the STEP bytes from Phase 0. Best-effort — a CAM
           failure doesn't kill the pipeline (the plan is still useful
           without ``.nc`` files), so it bubbles up as ``cam`` payload in
           the final_answer.
  Phase 4: Assemble ``final_answer`` payload + ``done`` summary.

Engine outputs are Pydantic models (:class:`DrawingExtraction`,
:class:`AssemblyData`, :class:`ProcessPlan`, :class:`CAMOutput`);
``model_dump(mode="json")`` makes them safe to emit through the SSE
final_answer wire.

Tracing is inline: every step is dumped to stdout via the standard
logger (``cncserver.pipeline.trace`` at INFO) so the operator can watch
each engine's output during the run. No files are written.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, AsyncGenerator
from urllib.parse import unquote, urlsplit

from ..core.events import EventBridge
from ..core.http import download_bytes
from ..core.schemas import AssemblyData, DrawingExtraction, ProcessPlan
from ..core.settings import get_settings
from ..core.tracing import finalize_trace, record_step, start_trace
from ..engines.cam import run as engine_generate_gcode
from ..engines.process_mapping.cost_engine import fetch_shop_catalog
from ..infra.persistence import (
    persist_analysis_complete,
    persist_analysis_failed,
    persist_analysis_start,
)

logger = logging.getLogger("cncserver.pipeline")


# ---------------------------------------------------------------------------
# Engine dispatch resolution
# ---------------------------------------------------------------------------

# Supported planner engines. The orchestrator never imports these at module
# load time — the engine package is opaque until a request actually asks
# for it. That's what keeps ``server/engines/<name>/`` deletable.
_SUPPORTED_ENGINES = ("agentic",)


def _resolve_engine_dispatch(engine_name: str):
    """Lazy-import the planner ``dispatch`` for ``engine_name``.

    Raises :class:`ValueError` if the name is unknown or the engine
    package fails to import — the caller (orchestrator) surfaces this as
    an ``error`` SSE frame so the request doesn't 500.
    """
    name = (engine_name or "").strip().lower()
    if name == "agentic":
        from ..engines.agentic import dispatch as engine_plan_processes  # noqa: PLC0415
        return engine_plan_processes
    raise ValueError(
        f"unknown engine {name!r}; supported: {', '.join(_SUPPORTED_ENGINES)}"
    )


# ---------------------------------------------------------------------------
# Engine 1 (drawing extraction) + Engine 2 (3D feature recognition) registry
# ---------------------------------------------------------------------------
#
# Same lazy-import seam as the planner above. Each registry is a tuple of
# supported names and ``_resolve_*_engine`` returns the matching ``run``
# callable; the orchestrator never imports the engine packages at module load.
# Swapping in an external engine is now a single registry edit + an env var
# (``EXTRACTION_2D_ENGINE`` / ``EXTRACTION_3D_ENGINE``) rather than touching
# the imports at the top of this file.

_SUPPORTED_2D_ENGINES = ("default",)
_SUPPORTED_3D_ENGINES = ("default",)


def _resolve_2d_engine(name: str | None):
    """Resolve the 2D drawing-extraction ``run`` callable for ``name``.

    Defaults to the in-house Qwen3-VL pipeline at ``engines.extraction_2d``.
    External engines plug in here — any callable matching the same async
    signature ``(drawing_bytes, *, filename, max_pages, on_event, on_thinking)
    -> DrawingExtraction`` is drop-in.
    """
    n = (name or "default").strip().lower()
    if n in ("default", "vlm", "qwen3-vl", "extraction_2d"):
        from ..engines.extraction_2d import run as run_2d  # noqa: PLC0415
        return run_2d
    raise ValueError(
        f"unknown 2D engine {n!r}; supported: {', '.join(_SUPPORTED_2D_ENGINES)}"
    )


def _resolve_3d_engine(name: str | None):
    """Resolve the 3D feature-recognition ``run`` callable for ``name``.

    Defaults to the in-house OCC subprocess at ``engines.extraction_3d``.
    External engines plug in here — any callable matching the same async
    signature ``(step_bytes, *, filename, on_event) -> AssemblyData`` is
    drop-in.
    """
    n = (name or "default").strip().lower()
    if n in ("default", "occ", "cadquery", "extraction_3d"):
        from ..engines.extraction_3d import run as run_3d  # noqa: PLC0415
        return run_3d
    raise ValueError(
        f"unknown 3D engine {n!r}; supported: {', '.join(_SUPPORTED_3D_ENGINES)}"
    )


# ---------------------------------------------------------------------------
# Storage reference parsing
# ---------------------------------------------------------------------------

# Supabase Storage URL shapes we may receive as step_url / drawing_url:
#   .../storage/v1/object/sign/<bucket>/<path>?token=...      (signed, expiring)
#   .../storage/v1/object/public/<bucket>/<path>              (public)
#   .../storage/v1/object/authenticated/<bucket>/<path>       (authenticated)
#   .../storage/v1/object/<bucket>/<path>                     (bare)
# We extract the *durable* (bucket, object-path) pair so the results
# envelope can carry it. The FE re-signs from this pair whenever its
# localStorage source cache misses (different browser / cleared cache),
# which is what makes reopened runs render geometry everywhere.
_STORAGE_RE = re.compile(
    r"/storage/v1/object/(?:sign/|public/|authenticated/)?(?P<bucket>[^/]+)/(?P<path>[^?]+)"
)


def _parse_storage_ref(url: str | None) -> tuple[str | None, str | None]:
    """Return ``(bucket, object_path)`` parsed from a Supabase storage URL.

    Returns ``(None, None)`` for non-storage URLs (arbitrary HTTPS, or the
    raw-bytes upload path where there is no URL at all), so the caller can
    simply omit the source when nothing durable exists.
    """
    if not url:
        return (None, None)
    try:
        path = urlsplit(url).path
    except (ValueError, AttributeError):
        return (None, None)
    match = _STORAGE_RE.search(path)
    if not match:
        return (None, None)
    bucket = match.group("bucket") or None
    obj = unquote(match.group("path") or "") or None
    return (bucket, obj)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def run_pipeline(
    analysis_id: str,
    *,
    drawing_url: str | None = None,
    step_url: str | None = None,
    drawing_bytes: bytes | None = None,
    step_bytes: bytes | None = None,
    file_name: str = "",
    user_id: str | None = None,
    batch_size: int = 1,
    supabase_client: Any = None,
    forced_assembly_part_type: str | None = None,
    engine: str | None = None,
    model: str | None = None,
) -> AsyncGenerator[tuple[str, dict], None]:
    """Run the three-engine SSE pipeline.

    Accept either remote URLs (``drawing_url`` / ``step_url``) or raw
    bytes (``drawing_bytes`` / ``step_bytes``) — bytes win when both are
    supplied. The orchestrator yields ``(event_type, data)`` tuples that
    the FastAPI route formats as SSE frames.

    Yields
    ------
    ('status' | 'tool_call' | 'tool_result' | 'thinking' | 'heartbeat' |
     'final_answer' | 'error' | 'done', data)

    The last event is always ``done``. ``error`` is emitted if the
    pipeline cannot proceed; the engines themselves never raise — they
    surface partial failures through their result payload.
    """
    t0 = time.monotonic()
    settings = get_settings()

    # Resolve which planner engine handles Phase 2 for this request.
    # Per-request override wins; otherwise fall back to the env default.
    engine_name = (engine or settings.engine.default or "agentic").strip().lower()
    # Default model for Engine 3 when the caller doesn't specify one.
    # Precedence: explicit request model → agent backend (Kimi, when
    # AGENT_LLM_URL is configured) → local vLLM (Qwen) default.
    resolved_model = (
        model
        or settings.llm.agent_default_model
        or ""
    ).strip() or None

    logger.info(
        "=" * 80 + "\n"
        "PIPELINE START analysis_id=%s file=%s batch=%d user=%s engine=%s model=%s\n"
        + "=" * 80,
        analysis_id, file_name, batch_size, user_id or "-",
        engine_name, resolved_model or "<vllm-default>",
    )

    trace = start_trace(
        analysis_id,
        file_name=file_name,
        user_id=user_id,
        batch_size=batch_size,
        extra={
            "approach": "modular_monolith",
            "engine":   engine_name,
            "model":    resolved_model or "<vllm-default>",
        },
    )
    record_step(trace, "pipeline_start", {
        "analysis_id": analysis_id,
        "file_name":   file_name,
        "batch_size":  batch_size,
        "user_id":     user_id or "",
        "engine":      engine_name,
        "model":       resolved_model or "",
        "step_url":    (step_url or "")[:200],
        "drawing_url": (drawing_url or "")[:200],
    })

    yield ("status", {
        "title":   "Starting analysis",
        "message": (
            f"3-engine pipeline: 2D VLM + 3D Feature Recognition + "
            f"Process Planning ({engine_name})"
        ),
    })

    # Resolve the planner dispatch up-front so an unknown engine name fails
    # the request before we burn time on Phase 0 downloads.
    try:
        engine_plan_processes = _resolve_engine_dispatch(engine_name)
    except (ValueError, ImportError) as exc:
        logger.error("PIPELINE: engine resolution failed: %s", exc)
        yield ("error", {"message": f"Engine '{engine_name}' unavailable: {exc}"})
        finalize_trace(trace, status="error", error=str(exc),
                       elapsed_seconds=time.monotonic() - t0)
        yield ("done", {"total_minutes": 0, "total_usd": 0,
                        "elapsed_seconds": round(time.monotonic() - t0, 1)})
        return

    # Reserve the analyses row up-front so the dashboard can show the
    # in-flight run. Best-effort; pipeline keeps going if it fails.
    try:
        await persist_analysis_start(
            supabase_client,
            analysis_id=analysis_id,
            file_name=file_name,
            step_url=step_url,
            drawing_url=drawing_url,
            user_id=user_id,
            batch_size=batch_size,
        )
    except Exception as exc:
        logger.warning("persist_analysis_start failed (continuing): %s", exc)

    # ── Phase 0: resolve input bytes ────────────────────────────────────────
    yield ("status", {"title": "Loading files", "message": "Fetching STEP and drawing…"})
    t_dl = time.monotonic()
    try:
        if step_bytes is None:
            if not step_url:
                raise ValueError("step_url or step_bytes is required")
            step_bytes = await download_bytes(step_url)
        if drawing_bytes is None:
            if not drawing_url:
                raise ValueError("drawing_url or drawing_bytes is required")
            drawing_bytes = await download_bytes(drawing_url)
    except Exception as exc:
        logger.exception("PHASE 0: file fetch failed")
        yield ("error", {"message": f"Could not retrieve uploaded files: {exc}"})
        finalize_trace(trace, status="error", error=str(exc),
                       elapsed_seconds=time.monotonic() - t0)
        try:
            await persist_analysis_failed(
                supabase_client,
                analysis_id=analysis_id,
                error_message=f"phase0: {exc}",
                elapsed_seconds=time.monotonic() - t0,
            )
        except Exception:
            logger.exception("persist_analysis_failed (phase0) failed")
        yield ("done", {"total_minutes": 0, "total_usd": 0,
                        "elapsed_seconds": round(time.monotonic() - t0, 1)})
        return

    logger.info(
        "PHASE 0 DONE: downloads in %.2fs — step=%dKB drawing=%dKB",
        time.monotonic() - t_dl, len(step_bytes) // 1024, len(drawing_bytes) // 1024,
    )
    record_step(trace, "phase0_files", {
        "download_seconds": round(time.monotonic() - t_dl, 2),
        "step_bytes":       len(step_bytes),
        "drawing_bytes":    len(drawing_bytes),
    })
    yield ("status", {
        "title":     "Files ready",
        "message":   f"STEP {len(step_bytes)//1024}KB | Drawing {len(drawing_bytes)//1024}KB",
        "completed": True,
    })

    # ── Phase 1: engines 1 + 2 + catalog in parallel ────────────────────────
    bridge = EventBridge()
    on_event_cb     = bridge.as_callback()
    on_thinking_cb  = bridge.as_thinking_callback()

    yield ("tool_call", {
        "tool":      "analyze_drawing",
        "iteration": 1,
        "label":     "2D VLM Extraction (title block, BOM, GD&T)",
    })
    yield ("tool_call", {
        "tool":      "analyze_step_assembly",
        "iteration": 1,
        "label":     "XDE Assembly Decomposition + Feature Recognition",
    })

    t_phase1 = time.monotonic()
    logger.info("PHASE 1 START: engine1 (VLM) + engine2 (OCC) + catalog launching concurrently")

    # Resolve via registry so external engines can be plugged in without
    # touching this file. Defaults to the in-house implementations.
    engine_extract_2d  = _resolve_2d_engine(settings.engine.extraction_2d)
    engine_recognize_3d = _resolve_3d_engine(settings.engine.extraction_3d)

    engine1_task = asyncio.create_task(engine_extract_2d(
        drawing_bytes,
        filename=file_name,
        on_event=on_event_cb,
        on_thinking=on_thinking_cb,
    ))
    engine2_task = asyncio.create_task(engine_recognize_3d(
        step_bytes,
        filename=file_name,
        on_event=on_event_cb,
    ))
    catalog_task = asyncio.create_task(fetch_shop_catalog(supabase_client))

    vlm_deadline = time.monotonic() + settings.extraction.vlm_phase_deadline_sec
    vlm_timed_out = False
    while not (engine1_task.done() and engine2_task.done()):
        try:
            ev = await asyncio.wait_for(bridge._queue.get(), timeout=1.0)
            yield ev
        except asyncio.TimeoutError:
            yield ("heartbeat", {})
        if not engine1_task.done() and time.monotonic() > vlm_deadline:
            logger.warning(
                "PHASE 1: VLM exceeded %.0fs — cancelling engine1_task",
                settings.extraction.vlm_phase_deadline_sec,
            )
            engine1_task.cancel()
            vlm_timed_out = True
            break

    async for ev in bridge.drain_until([engine1_task, engine2_task]):
        yield ev

    # ── Resolve engine 1 (VLM) ──────────────────────────────────────────────
    try:
        vlm_extraction = await engine1_task
    except (asyncio.CancelledError, asyncio.TimeoutError):
        logger.warning("PHASE 1: VLM cancelled/timed out — continuing with empty extraction")
        vlm_extraction = DrawingExtraction.empty()
        if vlm_timed_out:
            yield ("status", {
                "title":     "GD&T Extraction",
                "message":   "VLM timed out — continuing without drawing data",
                "completed": True,
            })
    except Exception as exc:
        logger.exception("PHASE 1: engine1 (VLM) raised: %s", exc)
        vlm_extraction = DrawingExtraction.empty()

    logger.info(
        "STEP 1 RESULT (VLM 2D): part=%s rev=%s material=%r unit=%s "
        "bom=%d notes=%d dims=%d gdt=%d threads=%d",
        vlm_extraction.part_number or "-",
        vlm_extraction.revision or "-",
        vlm_extraction.material or "-",
        vlm_extraction.dimension_unit,
        len(vlm_extraction.bom_items),
        len(vlm_extraction.drawing_notes),
        len(vlm_extraction.dimensions),
        len(vlm_extraction.gdt_callouts),
        len(vlm_extraction.threads),
    )
    record_step(trace, "step1_vlm_extraction", vlm_extraction.as_dict())

    # ── Resolve engine 2 (OCC) ──────────────────────────────────────────────
    try:
        assembly_data = await engine2_task
    except Exception as exc:
        logger.exception("PHASE 1: engine2 (3D recognizer) raised: %s", exc)
        assembly_data = AssemblyData.empty(error=str(exc))

    logger.info(
        "STEP 2 RESULT (3D OCC): assembly=%r components=%d total_volume=%.1fmm³ "
        "pmi=%s welding_contacts=%d",
        assembly_data.assembly_name or "-",
        assembly_data.component_count,
        assembly_data.total_volume_mm3,
        assembly_data.pmi_available,
        len(assembly_data.welding_contacts),
    )
    record_step(trace, "step2_3d_geometry", assembly_data.as_dict())

    # ── Wait for catalog ─────────────────────────────────────────────────────
    t_cat = time.monotonic()
    try:
        catalog = await catalog_task
    except Exception as exc:
        logger.warning("PHASE 1: catalog fetch failed: %s — using defaults", exc)
        catalog = await fetch_shop_catalog(None)
    logger.info(
        "PHASE 1: shop catalog ready in %.2fs — labor=%d machines=%d tools=%d materials=%d",
        time.monotonic() - t_cat,
        len(catalog.get("labor") or {}),
        len(catalog.get("machines") or {}),
        len(catalog.get("tools") or {}),
        len(catalog.get("materials") or {}),
    )
    logger.info("PHASE 1 TOTAL: %.2fs", time.monotonic() - t_phase1)
    record_step(trace, "step3_shop_catalog", {
        "labor":     catalog.get("labor")     or {},
        "machines":  catalog.get("machines")  or {},
        "tools":     catalog.get("tools")     or {},
        "materials": catalog.get("materials") or {},
    })

    # ── Phase 2: engine 3 (process planning) ────────────────────────────────
    t_phase2 = time.monotonic()
    logger.info(
        "PHASE 2 START: engine3 (process planning) — %d component(s) batch=%d",
        assembly_data.component_count, batch_size,
    )

    engine3_task = asyncio.create_task(engine_plan_processes(
        vlm_extraction,
        assembly_data,
        step_bytes,
        batch_size=batch_size,
        user_id=user_id,
        supabase_client=supabase_client,
        catalog=catalog,
        on_event=on_event_cb,
        forced_assembly_part_type=forced_assembly_part_type,
        analysis_id=analysis_id,
        model=resolved_model,
    ))

    async for ev in bridge.drain_until([engine3_task]):
        yield ev

    try:
        plan = await engine3_task
    except Exception as exc:
        logger.exception("PHASE 2: engine3 raised: %s", exc)
        # Use the schema-owned sentinel so the fallback shape stays in
        # sync with ProcessPlan's defaults — the orchestrator no longer
        # has to know the planner's empty-payload construction details.
        plan = ProcessPlan.empty(
            components=list(assembly_data.components),
            catalog=catalog,
            error=f"{exc.__class__.__name__}: {exc}",
        )

    components              = list(plan.components)
    cost_result             = plan.cost.model_dump(by_alias=True) if hasattr(plan.cost, "model_dump") else dict(plan.cost)
    processes_per_component = plan.processes_per_component or []
    category_decisions      = plan.category_decisions or []
    logger.info("PHASE 2 DONE: in %.2fs", time.monotonic() - t_phase2)

    record_step(trace, "step4_routing", {
        "processes_per_component": processes_per_component,
        "total_routing_rows":      sum(len(p) for p in processes_per_component),
    })
    record_step(trace, "step5_cost", cost_result)

    # ── Phase 3: engine 4 (CAM — FreeCAD G-code generation) ─────────────────
    # Best-effort: a CAM failure does not block the response. The plan is
    # still valid without .nc output (operator can re-trigger via the
    # POST /v1/generate-gcode endpoint once FreeCAD is reachable).
    t_phase3 = time.monotonic()
    logger.info("PHASE 3 START: engine4 (CAM / FreeCAD)")
    yield ("tool_call", {
        "tool":      "generate_gcode",
        "iteration": 1,
        "label":     "FreeCAD CAM — G-code Generation",
    })
    try:
        cam_output = await engine_generate_gcode(
            step_bytes, plan,
            analysis_id=analysis_id,
            on_event=on_event_cb,
        )
    except Exception as exc:
        logger.exception("PHASE 3: engine4 raised: %s", exc)
        cam_output = None
    if cam_output is not None:
        logger.info(
            "PHASE 3 DONE: ok=%s components=%d files=%d in %.2fs",
            cam_output.ok, len(cam_output.by_component),
            cam_output.total_files, time.monotonic() - t_phase3,
        )
        record_step(trace, "step6_cam", cam_output.as_dict())
    cam_dump = cam_output.as_dict() if cam_output is not None else {
        "ok": False, "error": "CAM engine raised", "by_component": [],
    }

    # ── Phase 4: assemble final payload ─────────────────────────────────────
    elapsed       = round(time.monotonic() - t0, 1)
    total_minutes = round(
        sum(float((c if isinstance(c, dict) else c.model_dump()).get("cycle_time_min") or 0)
            for c in components),
        3,
    )
    total_usd     = float(cost_result.get("total_usd") or 0.0)
    total_usd_per_lot = round(total_usd * max(batch_size, 1), 4)

    components_dump = [
        c if isinstance(c, dict) else c.model_dump(mode="json")
        for c in components
    ]

    # Roll up per-component confidence + evidence into an assembly-level
    # band. Use the WORST (max ±%) confidence as the headline so the UI
    # doesn't paint over weak components, and concatenate evidence
    # tokens (de-duplicated) so a reviewer can audit grounding.
    confidence_bands: list[float] = []
    evidence_tokens: list[str] = []
    for c in components_dump:
        # Prefer the engine-agnostic `planner` key; fall back to the legacy
        # `agentic` key for runs persisted before the rename.
        for engine_block in (c.get("planner") or c.get("agentic") or {},):
            band = engine_block.get("confidence_band_pct")
            try:
                if band is not None:
                    confidence_bands.append(float(band))
            except (TypeError, ValueError):
                pass
            for tok in engine_block.get("evidence") or []:
                if isinstance(tok, str) and tok not in evidence_tokens:
                    evidence_tokens.append(tok)
    rollup_confidence_band_pct = (
        round(max(confidence_bands), 1) if confidence_bands else None
    )
    processes_dump = [
        [r if isinstance(r, dict) else r.model_dump(mode="json") for r in rows]
        for rows in processes_per_component
    ]
    decisions_dump = [
        d if isinstance(d, dict) else d.model_dump(mode="json")
        for d in category_decisions
    ]

    # Durable storage refs so the FE can re-sign viewer URLs for this run
    # on any browser/machine even when its localStorage cache is empty.
    # Parsed from the (possibly already-expired) signed URLs we were given;
    # all-None when the request came in as raw bytes (local dev), in which
    # case the FE simply keeps using its localStorage source cache.
    _step_bucket, _step_path = _parse_storage_ref(step_url)
    _draw_bucket, _draw_path = _parse_storage_ref(drawing_url)
    sources_block = {
        "bucket":       _step_bucket or _draw_bucket,
        "step_path":    _step_path,
        "drawing_path": _draw_path,
        "file_name":    file_name or None,
    }

    results = {
        "analysis_id":     analysis_id,
        "approach":        "modular_monolith",
        "engine":          engine_name,
        "batch_size":      batch_size,
        "assembly_name":   assembly_data.assembly_name or file_name,
        "file_name":       file_name,
        "sources":         sources_block,
        "total_minutes":   total_minutes,
        "total_usd":       total_usd,
        "elapsed_seconds": elapsed,
        "vlm_extraction":  vlm_extraction.as_dict(),
        "assembly_data": {
            "component_count":  assembly_data.component_count,
            "total_volume_mm3": assembly_data.total_volume_mm3,
            "pmi_available":    assembly_data.pmi_available,
            "welding_contacts": [
                w if isinstance(w, dict) else w.model_dump(mode="json")
                for w in assembly_data.welding_contacts
            ],
        },
        "components":         components_dump,
        "processes_per_component": processes_dump,
        "category_decisions": decisions_dump,
        "cost":               cost_result,
        "cost_summary": {
            "total_usd_per_piece":     round(total_usd, 4),
            "total_usd_per_lot":       total_usd_per_lot,
            "batch_size":              batch_size,
            "confidence_band_pct":     rollup_confidence_band_pct,
            "evidence":                evidence_tokens,
        },
        "cycle_time": {
            "total_minutes": total_minutes,
            "breakdown_by_component": [
                {
                    "component_index": c.get("component_index", i),
                    "total_minutes":   round(c.get("cycle_time_min") or 0, 3),
                }
                for i, c in enumerate(components_dump)
            ],
        },
        "cam": cam_dump,
    }

    summary = (
        f"Analysis complete: {len(components)} component(s)  "
        f"{total_minutes:.1f} min  ${total_usd:.2f}  ({elapsed}s)"
    )
    logger.info(
        "=" * 80 + "\n"
        "PIPELINE DONE analysis_id=%s — %s\n"
        + "=" * 80,
        analysis_id, summary,
    )

    finalize_trace(
        trace,
        total_minutes=total_minutes,
        total_usd=total_usd,
        elapsed_seconds=elapsed,
        status="ok",
    )

    # History is DB-only: the run is persisted to Supabase below (and the
    # activity log via _capture_and_persist_messages). No local note file.
    yield ("final_answer", {"results": results, "summary": summary})

    # Persist after final_answer so the user sees results immediately;
    # DB lags by a few hundred ms. Best-effort.
    try:
        await persist_analysis_complete(
            supabase_client,
            analysis_id=analysis_id,
            status="completed",
            extraction_2d=vlm_extraction.as_dict(),
            assembly_data={
                "assembly_name":    assembly_data.assembly_name,
                "component_count":  assembly_data.component_count,
                "total_volume_mm3": assembly_data.total_volume_mm3,
                "pmi_available":    assembly_data.pmi_available,
                "welding_contacts": [
                    w if isinstance(w, dict) else w.model_dump(mode="json")
                    for w in assembly_data.welding_contacts
                ],
            },
            components=components_dump,
            components_processes=processes_dump,
            cam_output=cam_dump,
            elapsed_seconds=elapsed,
            trace=trace,
        )
    except Exception as exc:
        logger.exception("persist_analysis_complete failed: %s", exc)

    yield ("done", {
        "total_minutes":   total_minutes,
        "total_usd":       total_usd,
        "elapsed_seconds": elapsed,
    })
