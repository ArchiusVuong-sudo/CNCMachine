"""Read-side repository for analysis history — queries Supabase directly.

This is the DB-backed counterpart to :mod:`server.infra.persistence` (the
write side). The history endpoints (``GET /v1/analyses`` and
``GET /v1/analyses/{id}``) call into here so the FE always reflects the
database, independent of which host served the pipeline.

**Single source of truth.** There is deliberately no filesystem fallback:
saved-run history lives in Supabase only, so it survives redeploys to a new
host (RunPod today, somewhere else tomorrow) with nothing to sync.

Shapes returned here are byte-compatible with what the pipeline streamed in
its ``final_answer`` frame, so the FE renders a saved run exactly like a live
one. The reassembly mirrors the orchestrator's results envelope:

    a4_analyses        → top-level totals + sources + activity log
    a4_2d_extraction   → ``vlm_extraction``
    a4_components      → ``components[]`` (+ planner / cost / stock)
      a4_features      →   component ``features[]``
      a4_processes     →   component ``manufacturing_processes[]``

All calls are synchronous against the supabase-py client (PostgREST is
HTTP-only). FastAPI runs the sync route handlers in a threadpool, so these
blocking calls don't stall the event loop.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from .supabase import get_supabase_client

logger = logging.getLogger("cncserver.infra.analyses_repo")

# Supabase (PostgREST over the pooler) can throw a transient error or briefly
# return nothing right after a heavy write — the persist of a 9-component run
# writes hundreds of rows, and a read landing in that window must not surface a
# freshly-saved run as "not found". Retry transient failures a few times.
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_S = 0.4


def _retry(thunk: Callable[[], Any], *, what: str) -> Any:
    """Run ``thunk`` with a few retries on exception. Raises the last error if
    all attempts fail (callers decide whether that's fatal or degradable)."""
    last: Exception | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            return thunk()
        except Exception as exc:  # noqa: BLE001 — transient PostgREST/pooler errors
            last = exc
            logger.warning(
                "analyses_repo: %s failed (attempt %d/%d) — %s",
                what, attempt + 1, _RETRY_ATTEMPTS, exc,
            )
            if attempt < _RETRY_ATTEMPTS - 1:
                time.sleep(_RETRY_BACKOFF_S * (attempt + 1))
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Scalar coercion helpers
# ---------------------------------------------------------------------------

def _epoch(ts: Any) -> float:
    """Parse a PostgREST timestamp (ISO-8601 string) → epoch seconds."""
    if ts is None:
        return 0.0
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        return float(ts)
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _f(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _first_str(*vals: Any) -> str | None:
    for v in vals:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _parse_storage(url: str | None) -> tuple[str | None, str | None]:
    """Parse ``<bucket>/<path>`` out of a Supabase signed storage URL.

    The FE re-signs these durable refs (``resignStoragePaths``) to render the
    3D/2D viewers, so expired original signed URLs don't matter.
    """
    if not url or "/object/sign/" not in url:
        return None, None
    tail = url.split("/object/sign/", 1)[1].split("?", 1)[0]
    bucket, _, path = tail.partition("/")
    return (bucket or None), (path or None)


# ---------------------------------------------------------------------------
# Row → envelope-fragment mappers (mirror the orchestrator's projection)
# ---------------------------------------------------------------------------

def _bbox(c: dict) -> dict | None:
    L, W, H = c.get("bbox_length_mm"), c.get("bbox_width_mm"), c.get("bbox_height_mm")
    if L is None and W is None and H is None:
        return None
    return {"length_mm": L, "width_mm": W, "height_mm": H}


def _feature(f: dict) -> dict:
    return {
        "feature_index":   f.get("feature_index"),
        "feature_type":    f.get("feature_type"),
        "feature_id":      f.get("feature_id"),
        "key_face_ids":    f.get("key_face_ids") or [],
        "count":           f.get("count"),
        "confidence":      f.get("confidence"),
        "source":          f.get("source"),
        "dimensions":      f.get("dimensions"),
        "perimeter_mm":    f.get("perimeter_mm"),
        "location":        f.get("location"),
        "tolerance_plus":  f.get("tolerance_plus"),
        "tolerance_minus": f.get("tolerance_minus"),
        "gdt_callouts":    f.get("gdt_callouts") or [],
        # dim_tagger enrichment (migration 009).
        "tolerance_class": f.get("tolerance_class"),
        "is_threaded":     f.get("is_threaded"),
        "thread_spec":     f.get("thread_spec"),
        "operations":      f.get("operations") or [],
    }


def _routing_row(p: dict) -> dict:
    """Map an a4_processes row to the RoutingRow shape the FE reads."""
    return {
        "sequence":          p.get("sequence_order"),
        "op_code":           p.get("op_code"),
        "op_id":             p.get("op_id"),
        "process_type":      p.get("process_type"),
        "category":          p.get("category"),
        "operation_type":    p.get("operation_type"),
        "description":       p.get("description"),
        "feature_ids":       p.get("feature_ids") or [],
        "operation_count":   p.get("operation_count"),
        "machine_id":        p.get("machine_id"),
        "tool_type":         p.get("tool_type"),
        "tool_dimensions":   p.get("tool_dimensions"),
        "spindle_rpm":       p.get("spindle_rpm"),
        "feed_mm_per_min":   p.get("feed_mm_per_min"),
        "depth_of_cut_mm":   p.get("depth_of_cut_mm"),
        "cut_length_mm":     p.get("cut_length_mm"),
        "cycle_time_min":    p.get("cycle_time_min"),
        "setup_min_per_lot": p.get("setup_min_per_lot"),
        "run_min_per_part":  p.get("run_min_per_part"),
        "labor_role":        p.get("labor_role"),
        "work_center":       p.get("work_center"),
        "labor_cost_usd":    p.get("labor_cost_usd"),
        "machine_cost_usd":  p.get("machine_cost_usd"),
        "total_cost_usd":    p.get("total_cost_usd"),
        "notes":             p.get("notes"),
    }


def _component(c: dict, feats: list[dict], procs: list[dict]) -> dict:
    planner = c.get("agentic_plan")
    return {
        "component_index":      c.get("component_index"),
        "name":                 c.get("name"),
        "description":          c.get("description"),
        "instance_count":       c.get("instance_count"),
        "part_type":            c.get("part_type"),
        "part_type_confidence": c.get("part_type_confidence"),
        "volume_mm3":           c.get("volume_mm3"),
        "surface_area_mm2":     c.get("surface_area_mm2"),
        "bbox":                 _bbox(c),
        "material":             c.get("material"),
        "mapped_to_bom_item":   c.get("mapped_to_bom_item"),
        "mapping_method":       c.get("mapping_method"),
        "cycle_time_min":       c.get("cycle_time_min"),
        "cost":                 c.get("cost_breakdown"),
        "chosen_machine_id":    c.get("chosen_machine_id"),
        "machine_class":        c.get("machine_class"),
        "pmi_annotations":      c.get("pmi_annotations") or [],
        "gdt_callouts":         c.get("gdt_callouts") or [],
        "stock":                c.get("stock_json"),
        "features":             feats,
        "manufacturing_processes": procs,
        "planner":              planner,
        "agentic":              planner,
        # User display corrections from the BoM inline editor (PATCH endpoint).
        "ui_overrides":         c.get("ui_overrides") or None,
    }


# ---------------------------------------------------------------------------
# Summary (one history-list row)
# ---------------------------------------------------------------------------

def _summary(a: dict, ext: dict | None) -> dict:
    ext = ext or {}
    return {
        "id":            str(a.get("id")),
        "file_name":     a.get("file_name") or a.get("assembly_name"),
        "assembly_name": a.get("assembly_name"),
        "part_number":   _first_str(ext.get("part_number")),
        "revision":      _first_str(ext.get("revision")),
        "material":      _first_str(ext.get("material")),
        "total_usd":     _f(a.get("total_usd")),
        "total_minutes": _f(a.get("total_minutes")),
        "n_components":  a.get("component_count"),
        "created_at":    _epoch(a.get("created_at")),
    }


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------

def list_analyses_page(limit: int, offset: int) -> dict:
    """Newest-first page of history summaries. ``{"data": [...], "total": N}``.

    Returns an empty page (not an error) when Supabase is unconfigured or
    unreachable, so the dashboard degrades to "no projects yet" rather than
    breaking.
    """
    client = get_supabase_client()
    if client is None:
        logger.warning("analyses_repo: no supabase client; returning empty history")
        return {"data": [], "total": 0}

    try:
        resp = _retry(lambda: (
            client.table("a4_analyses")
            .select(
                "id,file_name,assembly_name,total_usd,total_minutes,"
                "component_count,created_at",
                count="exact",
            )
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        ), what="list query")
    except Exception as exc:  # noqa: BLE001 — history must never 500 the dashboard
        logger.warning("analyses_repo: list query failed after retries — %s", exc)
        return {"data": [], "total": 0}

    rows = resp.data or []
    total = getattr(resp, "count", None)
    total = int(total) if total is not None else len(rows)

    ids = [r["id"] for r in rows if r.get("id")]
    ext_by_aid: dict[str, dict] = {}
    if ids:
        try:
            ext_resp = _retry(lambda: (
                client.table("a4_2d_extraction")
                .select("analysis_id,part_number,revision,material")
                .in_("analysis_id", ids)
                .execute()
            ), what="2d-extraction enrich")
            for e in ext_resp.data or []:
                ext_by_aid[e["analysis_id"]] = e
        except Exception as exc:  # noqa: BLE001 — enrich is optional
            logger.warning("analyses_repo: 2d-extraction enrich failed after retries — %s", exc)

    data = [_summary(r, ext_by_aid.get(r["id"])) for r in rows]
    return {"data": data, "total": total}


def get_analysis_envelope(analysis_id: str) -> dict | None:
    """Reassemble the full results envelope for one run, or ``None`` if absent.

    Raises nothing for a missing row (returns ``None``); the route maps that to
    404. Supabase being unconfigured also yields ``None``.
    """
    client = get_supabase_client()
    if client is None:
        return None

    # Main row: retry transient failures, then let the error propagate — the
    # route maps an exception to 503 so a momentary blip never reads as a 404
    # for a run that actually exists.
    a_resp = _retry(lambda: (
        client.table("a4_analyses").select("*").eq("id", analysis_id).limit(1).execute()
    ), what=f"analysis fetch {analysis_id}")

    a_rows = a_resp.data or []
    if not a_rows:
        return None  # genuinely absent → 404
    a = a_rows[0]

    # 2D extraction → vlm_extraction (strip bookkeeping columns)
    try:
        e_rows = _retry(lambda: (
            client.table("a4_2d_extraction").select("*")
            .eq("analysis_id", analysis_id).limit(1).execute()
        ), what=f"2d fetch {analysis_id}").data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyses_repo: 2d fetch failed for %s — %s", analysis_id, exc)
        e_rows = []
    ext = e_rows[0] if e_rows else {}
    vlm = {
        k: v for k, v in ext.items()
        if k not in ("analysis_id", "created_at", "updated_at", "id")
    }

    # components (+ features + processes), batched to avoid N+1
    try:
        comp_rows = _retry(lambda: (
            client.table("a4_components").select("*")
            .eq("analysis_id", analysis_id).order("component_index").execute()
        ), what=f"components fetch {analysis_id}").data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyses_repo: components fetch failed for %s — %s", analysis_id, exc)
        comp_rows = []

    comp_ids = [c["id"] for c in comp_rows if c.get("id")]
    feats_by_cid: dict[str, list[dict]] = {}
    procs_by_cid: dict[str, list[dict]] = {}
    if comp_ids:
        try:
            for f in (_retry(lambda: (
                client.table("a4_features").select("*")
                .in_("component_id", comp_ids).execute()
            ), what=f"features fetch {analysis_id}").data or []):
                feats_by_cid.setdefault(f["component_id"], []).append(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning("analyses_repo: features fetch failed for %s — %s", analysis_id, exc)
        try:
            for p in (_retry(lambda: (
                client.table("a4_processes").select("*")
                .in_("component_id", comp_ids).execute()
            ), what=f"processes fetch {analysis_id}").data or []):
                procs_by_cid.setdefault(p["component_id"], []).append(p)
        except Exception as exc:  # noqa: BLE001
            logger.warning("analyses_repo: processes fetch failed for %s — %s", analysis_id, exc)

    components: list[dict] = []
    processes_per_component: list[list[dict]] = []
    for c in comp_rows:
        cid = c.get("id")
        raw_feats = sorted(
            feats_by_cid.get(cid, []),
            key=lambda f: (f.get("feature_index") if f.get("feature_index") is not None else 1e9),
        )
        raw_procs = sorted(
            procs_by_cid.get(cid, []),
            key=lambda p: (p.get("sequence_order") if p.get("sequence_order") is not None else 1e9),
        )
        feats = [_feature(f) for f in raw_feats]
        procs = [_routing_row(p) for p in raw_procs]
        components.append(_component(c, feats, procs))
        processes_per_component.append(procs)

    step_bucket, step_path = _parse_storage(a.get("step_url"))
    draw_bucket, draw_path = _parse_storage(a.get("drawing_url"))
    total_usd = _f(a.get("total_usd"))
    batch = int(a.get("batch_size") or 1)
    total_min = a.get("total_minutes")
    if total_min is None:
        total_min = round(sum(float(c.get("cycle_time_min") or 0) for c in comp_rows), 3)

    envelope = {
        "analysis_id":     str(a.get("id")),
        "approach":        "modular_monolith",
        "engine":          "agentic",
        "batch_size":      batch,
        "assembly_name":   a.get("assembly_name"),
        "file_name":       a.get("file_name"),
        "sources": {
            "bucket":       step_bucket or draw_bucket,
            "step_path":    step_path,
            "drawing_path": draw_path,
            "file_name":    a.get("file_name"),
        },
        "step_url":        a.get("step_url"),
        "drawing_url":     a.get("drawing_url"),
        "total_minutes":   total_min,
        "total_usd":       total_usd,
        "elapsed_seconds": a.get("elapsed_seconds"),
        "vlm_extraction":  vlm,
        "assembly_data":   a.get("assembly_data") or {
            "assembly_name":    a.get("assembly_name"),
            "component_count":  a.get("component_count"),
            "total_volume_mm3": a.get("total_volume_mm3"),
            "pmi_available":    a.get("pmi_available"),
            "welding_contacts": a.get("welding_contacts") or [],
        },
        "components":              components,
        "processes_per_component": processes_per_component,
        "cost":                    {"total_usd": total_usd},
        "cost_summary": {
            "total_usd_per_piece": total_usd,
            "total_usd_per_lot":   round((total_usd or 0) * batch, 4),
            "batch_size":          batch,
            "confidence_band_pct": None,
        },
        "cycle_time":   {"total_minutes": total_min},
        "cam":          {"ok": False, "by_component": []},
        "messages":     a.get("messages_json") or [],
        "status":       a.get("status"),
        "_source":      "supabase",
    }
    return envelope


def delete_analysis(analysis_id: str) -> bool:
    """Delete one analysis row (children cascade via FK). Best-effort.

    Returns True if the delete call was issued, False if there was no client.
    """
    client = get_supabase_client()
    if client is None:
        return False
    client.table("a4_analyses").delete().eq("id", analysis_id).execute()
    return True


# ---------------------------------------------------------------------------
# Write side — inline user corrections (PATCH /v1/analyses/{id})
# ---------------------------------------------------------------------------

# Part-Information fields the user may edit, mapped 1:1 to a4_2d_extraction
# columns. Anything outside this allow-list is ignored (no arbitrary column
# writes from the client).
_PART_INFO_COLS = {"part_number", "revision", "description", "material", "dimension_unit"}


def patch_analysis(
    analysis_id: str,
    *,
    part_info: dict | None = None,
    components: list[dict] | None = None,
) -> bool:
    """Apply user display-corrections to a stored run (overwrites in place).

    - ``part_info``: partial dict of a4_2d_extraction columns (Part Information
      card edits). Only allow-listed, non-None keys are written.
    - ``components``: list of ``{"component_index": int, "overrides": {...}}``.
      Each component's ``ui_overrides`` JSON is read-merged with the delta so a
      single-cell edit never clobbers other corrections on the same row. The FE
      applies these overrides on top of the computed BoM row for display.

    Returns True if a client was available and the writes were issued.
    """
    client = get_supabase_client()
    if client is None:
        return False

    if part_info:
        patch = {k: v for k, v in part_info.items() if k in _PART_INFO_COLS and v is not None}
        if patch:
            _retry(
                lambda: client.table("a4_2d_extraction").update(patch)
                .eq("analysis_id", analysis_id).execute(),
                what=f"patch 2d {analysis_id}",
            )

    for cp in components or []:
        ci = cp.get("component_index")
        delta = cp.get("overrides")
        if ci is None or not isinstance(delta, dict) or not delta:
            continue
        # Read-merge the override JSON so concurrent single-cell edits compose.
        rows = _retry(
            lambda ci=ci: client.table("a4_components").select("ui_overrides")
            .eq("analysis_id", analysis_id).eq("component_index", ci).limit(1).execute(),
            what=f"patch comp read {analysis_id}/{ci}",
        ).data or []
        existing = (rows[0].get("ui_overrides") or {}) if rows else {}
        # Drop keys explicitly cleared (empty string / null) so a blank edit
        # reverts to the computed value rather than persisting an empty string.
        merged = {**existing}
        for k, v in delta.items():
            if v is None or v == "":
                merged.pop(k, None)
            else:
                merged[k] = v
        _retry(
            lambda ci=ci, m=merged: client.table("a4_components")
            .update({"ui_overrides": m}).eq("analysis_id", analysis_id)
            .eq("component_index", ci).execute(),
            what=f"patch comp write {analysis_id}/{ci}",
        )

    return True
