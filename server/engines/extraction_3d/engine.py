"""Public Engine 2 entry point: STEP bytes in, :class:`AssemblyData` out.

Two cooperating subprocesses:

  1. OCC recognizer (cadquery-ocp) — XDE decomposition, geometry analysis,
     rule-based feature recognition, part-type classification, PMI extract.
     Runs in :mod:`.subprocess_runner` so OCP segfaults can't take the
     parent FastAPI server down.
  2. FreeCAD welding detector — pairwise component-contact analysis via
     ``distToShape``. Runs in :mod:`.welding`; FreeCAD-absent is treated
     as "no contacts found" rather than an error.

We additionally drop "COMPOUND" wrapper components on multi-component
assemblies — some SolidWorks exports surface a top-level TopoDS_Compound
as a sibling of the real solids, and its full-assembly bbox makes every
downstream cost / cycle-time estimate double-count the same material.
"""
from __future__ import annotations

import logging
import time

from ...core.events import OnEvent, safe_emit
from ...core.schemas import AssemblyData
from .subprocess_runner import analyze_step_assembly
from .welding import detect_welding_contacts

logger = logging.getLogger("cncserver.engines.extraction_3d")


async def run(
    step_bytes: bytes,
    *,
    filename: str = "",
    on_event: OnEvent = None,
) -> AssemblyData:
    """Run Engine 2 on raw STEP bytes.

    Parameters
    ----------
    step_bytes : raw STEP file bytes (AP203 / AP214 / AP242).
    filename   : original filename, used only for logging.
    on_event   : async callback receiving SSE events.

    Returns
    -------
    :class:`AssemblyData` — schema-validated. On total OCC failure
    returns an empty assembly with ``ok=False`` (never raises).
    """
    t0 = time.monotonic()
    logger.info(
        "engine_3d START: file=%s bytes=%dKB",
        filename or "-", len(step_bytes) // 1024,
    )
    await safe_emit(on_event, "status", {
        "title":   "3D Feature Recognition",
        "message": "Running OCC subprocess…",
    })

    # ── OCC recognizer subprocess ─────────────────────────────────────────
    t_step = time.monotonic()
    try:
        assembly = await analyze_step_assembly(step_bytes)
    except Exception as exc:
        logger.exception("engine_3d: OCC recognizer raised")
        await safe_emit(on_event, "tool_result", {
            "tool":   "analyze_step_assembly",
            "result": {"error": str(exc)},
        })
        return AssemblyData.empty(error=str(exc))

    components = assembly.get("components") or []

    # Drop "COMPOUND" wrapper components on multi-component assemblies. Some
    # STEP files (welded sub-assemblies exported from SolidWorks) surface a
    # top-level TopoDS_Compound as a leaf node alongside the real solids; its
    # bbox spans the whole assembly and its volume is mostly air, so cost
    # estimates run against it double-count material. Single-compound files
    # keep the wrapper as the only entry.
    if len(components) > 1:
        before = len(components)
        components = [
            c for c in components
            if str(c.get("name") or "").strip().upper() != "COMPOUND"
        ]
        dropped = before - len(components)
        if dropped:
            logger.info(
                "engine_3d: dropped %d COMPOUND wrapper(s) — kept %d real components",
                dropped, len(components),
            )
            for new_idx, c in enumerate(components):
                c["component_index"] = new_idx

    step_elapsed = time.monotonic() - t_step
    logger.info(
        "engine_3d: OCC done in %.2fs — ok=%s components=%d total_vol=%.1fmm³ pmi=%s err=%s",
        step_elapsed,
        assembly.get("ok"),
        len(components),
        assembly.get("total_volume_mm3") or 0.0,
        assembly.get("pmi_available"),
        (assembly.get("_error") or "")[:80] or "-",
    )
    for _c in components:
        _bb = _c.get("bbox") or {}
        _feats = _c.get("features") or []
        _ft_counts: dict = {}
        for _f in _feats:
            _ft = str((_f or {}).get("feature_type") or "").lower() or "unknown"
            _ft_counts[_ft] = _ft_counts.get(_ft, 0) + 1
        logger.info(
            "engine_3d COMP[%d] %s: part_type=%s conf=%.2f instances=%d vol=%.1f "
            "bbox=%.1fx%.1fx%.1f features=%d [%s] pmi=%d",
            _c.get("component_index", -1), _c.get("name", "?"),
            _c.get("part_type", "?"), _c.get("part_type_confidence", 0.0),
            _c.get("instance_count", 1), _c.get("volume_mm3") or 0.0,
            _bb.get("length_mm") or 0.0, _bb.get("width_mm") or 0.0, _bb.get("height_mm") or 0.0,
            len(_feats),
            ", ".join(f"{k}:{v}" for k, v in sorted(_ft_counts.items(), key=lambda kv: -kv[1])[:8]),
            len(_c.get("pmi_annotations") or []),
        )

    await safe_emit(on_event, "tool_result", {
        "tool":   "analyze_step_assembly",
        "result": {
            "component_count":  len(components),
            "total_volume_mm3": assembly.get("total_volume_mm3", 0),
            "pmi_available":    assembly.get("pmi_available", False),
            "error":            assembly.get("_error"),
        },
    })

    # ── Welding detection ─────────────────────────────────────────────────
    await safe_emit(on_event, "status", {
        "title":   "Welding Detection",
        "message": "Detecting component contacts…",
    })
    t_weld = time.monotonic()
    try:
        welding_contacts = await detect_welding_contacts(step_bytes, components)
    except Exception as exc:
        logger.warning("engine_3d: welding detection failed: %s", exc)
        welding_contacts = []
    logger.info(
        "engine_3d: welding detection in %.2fs — %d contact(s)",
        time.monotonic() - t_weld, len(welding_contacts),
    )
    await safe_emit(on_event, "tool_result", {
        "tool":   "detect_welding",
        "result": {"contact_count": len(welding_contacts)},
    })

    extraction = AssemblyData(
        ok                = bool(assembly.get("ok", True)),
        assembly_name     = assembly.get("assembly_name") or "",
        file_name         = assembly.get("file_name") or filename or "",
        component_count   = len(components),
        total_volume_mm3  = float(assembly.get("total_volume_mm3") or 0.0),
        pmi_available     = bool(assembly.get("pmi_available", False)),
        components        = components,
        welding_contacts  = welding_contacts,
        error             = assembly.get("_error"),
    )

    logger.info(
        "engine_3d DONE in %.2fs — components=%d welding=%d ok=%s",
        time.monotonic() - t0,
        extraction.component_count,
        len(extraction.welding_contacts),
        extraction.ok,
    )
    await safe_emit(on_event, "status", {
        "title":     "3D Feature Recognition",
        "message":   "Assembly analysis complete",
        "completed": True,
    })
    return extraction
