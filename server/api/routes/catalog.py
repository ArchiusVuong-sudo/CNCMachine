"""CRUD endpoints for the shop catalog (machines, tooling, labor, materials).

The pipeline reads these tables via
:func:`server.engines.process_mapping.cost_engine.fetch_shop_catalog`
to cost a quote. This router exposes the same tables to the FE so the
operator can calibrate pricing from the UI instead of editing Supabase
directly.

Design notes:
  * **Single shared catalog** — the cost engine treats every row as global
    (no per-user scoping); this router does the same. ``user_id`` is not a
    request parameter and inserts leave it ``None``.
  * **Soft-delete by default** — DELETE flips ``is_active`` to false so
    historical analyses can still resolve their machine/tool refs. Pass
    ``?hard=true`` to actually remove the row.
  * **Schema-drift tolerant** — Pydantic models use ``extra="allow"`` so
    new Supabase columns (migration 006 added a bunch) pass through.
  * **Graceful when Supabase missing** — handlers return HTTP 503 with a
    clear message instead of crashing; the FE shows a banner.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...infra.supabase import get_supabase_client

logger = logging.getLogger("cncserver.api.catalog")

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _client_or_503() -> Any:
    """Return a live Supabase client or raise 503."""
    client = get_supabase_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="catalog unavailable — Supabase not configured",
        )
    return client


def _list_rows(table: str, *, active_only: bool, order_by: str) -> list[dict]:
    client = _client_or_503()
    try:
        q = client.from_(table).select("*")
        if active_only:
            q = q.eq("is_active", True)
        resp = q.order(order_by).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: %s list failed (%s)", table, exc)
        raise HTTPException(status_code=502, detail=f"upstream query failed: {exc}") from exc
    return list(resp.data or [])


def _insert_row(table: str, body: dict) -> dict:
    client = _client_or_503()
    try:
        resp = client.from_(table).insert(body).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: %s insert failed (%s)", table, exc)
        raise HTTPException(status_code=502, detail=f"insert failed: {exc}") from exc
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=502, detail="insert returned no row")
    return rows[0]


def _update_row(table: str, row_id: str, patch: dict) -> dict:
    if not patch:
        raise HTTPException(status_code=400, detail="patch body is empty")
    client = _client_or_503()
    try:
        resp = client.from_(table).update(patch).eq("id", row_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: %s update failed (%s)", table, exc)
        raise HTTPException(status_code=502, detail=f"update failed: {exc}") from exc
    rows = resp.data or []
    if not rows:
        raise HTTPException(status_code=404, detail=f"{table} row {row_id} not found")
    return rows[0]


def _delete_row(table: str, row_id: str, *, hard: bool) -> dict:
    client = _client_or_503()
    try:
        if hard:
            resp = client.from_(table).delete().eq("id", row_id).execute()
        else:
            resp = client.from_(table).update({"is_active": False}).eq("id", row_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: %s delete failed (%s)", table, exc)
        raise HTTPException(status_code=502, detail=f"delete failed: {exc}") from exc
    return {"ok": True, "hard": hard, "rows_affected": len(resp.data or [])}


# ---------------------------------------------------------------------------
# Pydantic shapes — purposefully loose; the Supabase row dictates the truth
# ---------------------------------------------------------------------------

class _Permissive(BaseModel):
    """Base model that accepts unknown fields so DB schema drift never 500s."""

    model_config = ConfigDict(extra="allow")


class MachineCreate(_Permissive):
    machine_name: str
    machine_type: str = "3_axis_mill"
    hourly_rate_usd: float = 75.0
    is_active: bool = True


class ToolingCreate(_Permissive):
    tool_name: str
    tool_type: str = "end_mill"
    is_active: bool = True


class LaborRateCreate(_Permissive):
    role_name: str
    hourly_rate_usd: float
    is_active: bool = True


class MaterialStockCreate(_Permissive):
    material_name: str
    material_form: str = "plate"
    is_active: bool = True


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------

@router.get("/machines")
def list_machines(active_only: bool = Query(False, alias="active")) -> list[dict]:
    return _list_rows("a4_machines", active_only=active_only, order_by="machine_name")


@router.post("/machines")
def create_machine(body: MachineCreate) -> dict:
    return _insert_row("a4_machines", body.model_dump(exclude_unset=False))


@router.patch("/machines/{row_id}")
def update_machine(row_id: str, patch: dict) -> dict:
    return _update_row("a4_machines", row_id, patch)


@router.delete("/machines/{row_id}")
def delete_machine(row_id: str, hard: bool = Query(False)) -> dict:
    return _delete_row("a4_machines", row_id, hard=hard)


# ---------------------------------------------------------------------------
# Tooling
# ---------------------------------------------------------------------------

@router.get("/tooling")
def list_tooling(active_only: bool = Query(False, alias="active")) -> list[dict]:
    return _list_rows("a4_tooling", active_only=active_only, order_by="tool_name")


@router.post("/tooling")
def create_tooling(body: ToolingCreate) -> dict:
    return _insert_row("a4_tooling", body.model_dump(exclude_unset=False))


@router.patch("/tooling/{row_id}")
def update_tooling(row_id: str, patch: dict) -> dict:
    return _update_row("a4_tooling", row_id, patch)


@router.delete("/tooling/{row_id}")
def delete_tooling(row_id: str, hard: bool = Query(False)) -> dict:
    return _delete_row("a4_tooling", row_id, hard=hard)


# ---------------------------------------------------------------------------
# Labor rates
# ---------------------------------------------------------------------------

@router.get("/labor-rates")
def list_labor_rates(active_only: bool = Query(False, alias="active")) -> list[dict]:
    return _list_rows("a4_labor_rates", active_only=active_only, order_by="role_name")


@router.post("/labor-rates")
def create_labor_rate(body: LaborRateCreate) -> dict:
    return _insert_row("a4_labor_rates", body.model_dump(exclude_unset=False))


@router.patch("/labor-rates/{row_id}")
def update_labor_rate(row_id: str, patch: dict) -> dict:
    return _update_row("a4_labor_rates", row_id, patch)


@router.delete("/labor-rates/{row_id}")
def delete_labor_rate(row_id: str, hard: bool = Query(False)) -> dict:
    return _delete_row("a4_labor_rates", row_id, hard=hard)


# ---------------------------------------------------------------------------
# Material stock
# ---------------------------------------------------------------------------

@router.get("/material-stock")
def list_material_stock(active_only: bool = Query(False, alias="active")) -> list[dict]:
    return _list_rows("a4_material_stock", active_only=active_only, order_by="material_name")


@router.post("/material-stock")
def create_material_stock(body: MaterialStockCreate) -> dict:
    return _insert_row("a4_material_stock", body.model_dump(exclude_unset=False))


@router.patch("/material-stock/{row_id}")
def update_material_stock(row_id: str, patch: dict) -> dict:
    return _update_row("a4_material_stock", row_id, patch)


@router.delete("/material-stock/{row_id}")
def delete_material_stock(row_id: str, hard: bool = Query(False)) -> dict:
    return _delete_row("a4_material_stock", row_id, hard=hard)
