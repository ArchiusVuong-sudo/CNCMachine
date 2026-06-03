"""History / detail endpoints for prior analyses.

**DB-only.** These endpoints read straight from Supabase via
:mod:`server.infra.analyses_repo`. The database is the single source of
truth, so saved-run history survives a redeploy to a different host with
nothing local to sync (the pipeline already persists every run to the
``a4_*`` tables on the write path).

Endpoints:
  * ``GET    /v1/analyses``         — paginated list (newest first).
  * ``GET    /v1/analyses/{id}``    — full results envelope.
  * ``DELETE /v1/analyses/{id}``    — remove the row (children cascade).

Response shapes are byte-compatible with what the pipeline streams in its
``final_answer`` frame, so the FE renders a saved run exactly like a live one.

Path-traversal / id-shape is validated against the same regex the writeback
layer uses, so a malformed id is rejected with 400 before any DB call.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ...core.writeback import _ANALYSIS_ID_RE
from ...infra import analyses_repo

logger = logging.getLogger("cncserver.api.analyses")

router = APIRouter(prefix="/v1", tags=["analyses"])


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class AnalysisSummary(BaseModel):
    """One row in the history list. Fields are best-effort; older runs may
    not carry part_number / total_minutes."""

    model_config = ConfigDict(extra="allow")

    id: str
    file_name: str | None = None
    assembly_name: str | None = None
    part_number: str | None = None
    revision: str | None = None
    material: str | None = None
    total_usd: float | None = None
    total_minutes: float | None = None
    n_components: int | None = None
    created_at: float


class PartInfoPatch(BaseModel):
    """Editable Part-Information fields (a4_2d_extraction columns)."""

    model_config = ConfigDict(extra="ignore")

    part_number: str | None = None
    revision: str | None = None
    description: str | None = None
    material: str | None = None
    dimension_unit: str | None = None


class ComponentPatch(BaseModel):
    """One BoM row's display overrides (merged into a4_components.ui_overrides)."""

    model_config = ConfigDict(extra="ignore")

    component_index: int
    overrides: dict


class AnalysisPatch(BaseModel):
    """Inline user corrections to a stored run (Part Info + BoM editors)."""

    model_config = ConfigDict(extra="ignore")

    part_info: PartInfoPatch | None = None
    components: list[ComponentPatch] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_id_or_400(analysis_id: str) -> str:
    if not analysis_id or not _ANALYSIS_ID_RE.match(analysis_id):
        raise HTTPException(status_code=400, detail="invalid analysis_id")
    return analysis_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/analyses")
def list_analyses(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated, newest-first list of summaries (from Supabase)."""
    page = analyses_repo.list_analyses_page(limit=limit, offset=offset)
    # Validate each row through the response model so the FE contract holds,
    # then hand back plain dicts.
    rows = [AnalysisSummary(**r).model_dump() for r in page.get("data", [])]
    return {"data": rows, "total": page.get("total", len(rows))}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    """Return the full results envelope reassembled from Supabase."""
    safe = _safe_id_or_400(analysis_id)
    try:
        envelope = analyses_repo.get_analysis_envelope(safe)
    except Exception as exc:  # noqa: BLE001 — transient store error ≠ "not found"
        logger.warning("analyses: get %s failed — %s", safe, exc)
        raise HTTPException(
            status_code=503, detail="history store temporarily unavailable",
        ) from exc
    if envelope is None:
        raise HTTPException(status_code=404, detail=f"analysis {safe} not found")
    return envelope


@router.patch("/analyses/{analysis_id}")
def patch_analysis(analysis_id: str, body: AnalysisPatch) -> dict:
    """Persist inline user corrections to a stored run (overwrites in place).

    Used by the Part Information double-click editor (``part_info`` → updates
    ``a4_2d_extraction``) and the Bill-of-Material inline editor (``components``
    → merges into ``a4_components.ui_overrides``). Reloading the run reflects the
    saved values.
    """
    safe = _safe_id_or_400(analysis_id)
    part_info = body.part_info.model_dump(exclude_none=True) if body.part_info else None
    components = [c.model_dump() for c in body.components] if body.components else None
    if not part_info and not components:
        return {"ok": True, "noop": True}
    try:
        ok = analyses_repo.patch_analysis(safe, part_info=part_info, components=components)
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyses: patch failed for %s — %s", safe, exc)
        raise HTTPException(status_code=502, detail="update failed") from exc
    if not ok:
        raise HTTPException(status_code=503, detail="history store unavailable")
    return {"ok": True}


@router.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: str) -> dict:
    """Remove one analysis row. FK CASCADE handles the child tables
    (`a4_components`, `a4_features`, `a4_processes`, `a4_2d_extraction`,
    `a4_cam_runs`, `a4_gcode`, `a4_feedback`)."""
    safe = _safe_id_or_400(analysis_id)
    try:
        ok = analyses_repo.delete_analysis(safe)
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyses: delete failed for %s — %s", safe, exc)
        raise HTTPException(status_code=502, detail="delete failed") from exc
    if not ok:
        raise HTTPException(status_code=503, detail="history store unavailable")
    return {"ok": True, "removed": [f"supabase:a4_analyses:{safe}"]}
