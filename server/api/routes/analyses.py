"""History / detail endpoints for prior analyses.

Backed by the per-analysis JSON files written under
``KNOWLEDGE_BASE/_research/notes/`` by:

  * the orchestrator       — full ``results`` envelope (engine-neutral);
  * each engine's writeback — compact diagnostic note (engine-specific).

Two file kinds:

  * ``<id>.json``        — compact diagnostic note (one per analysis).
  * ``<id>_full.json``   — full orchestrator ``results`` envelope
    (written immediately before the ``final_answer`` SSE frame, via
    :mod:`server.core.writeback`).

Endpoints:
  * ``GET    /v1/analyses``         — paginated list (newest first).
  * ``GET    /v1/analyses/{id}``    — full envelope, or compact fallback.
  * ``DELETE /v1/analyses/{id}``    — remove both files (missing is OK).

Design notes:
  * **Listing is filesystem-only**, no DB. We scan ``*.json`` and skip
    ``*_full.json`` so each analysis maps to one row.
  * **Summaries are enriched** from the full file when present so the
    history table can show file name + total minutes; older analyses
    that only have a compact note still list, just with fewer fields.
  * **Path-traversal safe** — IDs are validated against the same regex
    that the writeback layer uses on the write path.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from ...core.writeback import _ANALYSIS_ID_RE, _NOTES_DIR

logger = logging.getLogger("cncserver.api.analyses")

router = APIRouter(prefix="/v1", tags=["analyses"])


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

class AnalysisSummary(BaseModel):
    """One row in the history list. Fields are best-effort; older notes
    won't have file_name / total_minutes."""

    model_config = ConfigDict(extra="allow")

    id: str
    file_name: str | None = None
    assembly_name: str | None = None
    total_usd: float | None = None
    total_minutes: float | None = None
    n_components: int | None = None
    created_at: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_id_or_400(analysis_id: str) -> str:
    if not analysis_id or not _ANALYSIS_ID_RE.match(analysis_id):
        raise HTTPException(status_code=400, detail="invalid analysis_id")
    return analysis_id


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("analyses: failed to read %s — %s", path, exc)
        return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _sum_total_minutes(components: list) -> float | None:
    """Sum run+setup minutes across components; None if nothing usable.

    Reads from the ``agentic`` planner meta dict the engine attached.
    Historical rows may carry a legacy ``rag`` block — fall back to it so
    old analyses still render.
    """
    minutes = 0.0
    saw_value = False
    for comp in components or []:
        comp = comp or {}
        meta = comp.get("agentic") or comp.get("rag") or {}
        run = _coerce_float(meta.get("total_run_min_per_part"))
        setup = _coerce_float(meta.get("setup_min_per_lot"))
        if run is not None:
            minutes += run
            saw_value = True
        if setup is not None:
            minutes += setup
            saw_value = True
    return round(minutes, 2) if saw_value else None


def _build_summary(compact_path: Path, full_data: dict | None) -> AnalysisSummary | None:
    """Combine compact-note + (optional) full-result into one row."""
    compact = _read_json(compact_path)
    if not compact:
        return None

    analysis_id = compact.get("analysis_id") or compact_path.stem
    created_at = float(compact.get("written_at_epoch") or 0.0)
    summary_block = compact.get("summary") or {}

    total_usd = _coerce_float(summary_block.get("total_usd"))
    n_components = summary_block.get("n_components")
    file_name: str | None = None
    assembly_name: str | None = None
    total_minutes: float | None = None

    if full_data:
        file_name = (
            full_data.get("file_name")
            or full_data.get("drawing_name")
            or full_data.get("source_file")
        )
        assembly_name = (
            full_data.get("assembly_name")
            or full_data.get("name")
        )
        cost_block = full_data.get("cost") or {}
        if total_usd is None:
            total_usd = _coerce_float(cost_block.get("total_usd"))
        components = full_data.get("components") or []
        if components:
            total_minutes = _sum_total_minutes(components)
            if n_components is None:
                n_components = len(components)

    return AnalysisSummary(
        id=analysis_id,
        file_name=file_name,
        assembly_name=assembly_name,
        total_usd=total_usd,
        total_minutes=total_minutes,
        n_components=n_components,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/analyses")
def list_analyses(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """Paginated, newest-first list of summaries."""
    if not _NOTES_DIR.exists():
        return {"data": [], "total": 0}

    try:
        compact_files = [
            p for p in _NOTES_DIR.glob("*.json")
            if not p.name.endswith("_full.json")
        ]
    except OSError as exc:
        logger.warning("analyses: glob failed — %s", exc)
        raise HTTPException(status_code=500, detail="failed to scan notes dir") from exc

    compact_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    total = len(compact_files)
    window = compact_files[offset : offset + limit]

    rows: list[AnalysisSummary] = []
    for path in window:
        full_path = path.with_name(f"{path.stem}_full.json")
        full = _read_json(full_path) if full_path.exists() else None
        row = _build_summary(path, full)
        if row is not None:
            rows.append(row)

    rows.sort(key=lambda r: r.created_at, reverse=True)
    return {"data": [r.model_dump() for r in rows], "total": total}


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    """Return the full results envelope, or fall back to the compact note."""
    safe = _safe_id_or_400(analysis_id)
    full_path = _NOTES_DIR / f"{safe}_full.json"
    if full_path.exists():
        data = _read_json(full_path)
        if data is not None:
            return data
    compact_path = _NOTES_DIR / f"{safe}.json"
    if compact_path.exists():
        data = _read_json(compact_path)
        if data is not None:
            return data
    raise HTTPException(status_code=404, detail=f"analysis {safe} not found")


@router.delete("/analyses/{analysis_id}")
def delete_analysis(analysis_id: str) -> dict:
    """Remove both the compact and full files for one analysis."""
    safe = _safe_id_or_400(analysis_id)
    removed: list[str] = []
    for suffix in ("_full.json", ".json"):
        path = _NOTES_DIR / f"{safe}{suffix}"
        if path.exists():
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                logger.warning("analyses: delete failed for %s — %s", path, exc)
    return {"ok": True, "removed": removed}
