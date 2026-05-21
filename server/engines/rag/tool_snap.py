"""Snap LLM-proposed tools to per-user catalog entries.

The RAG generator sees a compact summary of the shop tool catalog inside
the user prompt, but the model can still emit a ``tool_id`` that points
nowhere (typo, hallucination) — or omit it entirely with
``would_need_to_buy: true``. Either way the cost engine needs a real
catalog row to compute tool amortization, so we snap here.

Match policy (highest-confidence first):

  1. Exact ``tool_id`` hit in the catalog → keep as-is.
  2. Same ``tool_type`` + diameter within tolerance (mm). Prefer the
     closest diameter; break ties by preferring the smaller-cost row so
     amortization isn't gamed by mis-snapping to an expensive line.
  3. Same ``tool_type`` only (no diameter info or no near match)
     → leave ``tool_id`` null and mark ``would_need_to_buy=True``.

Diameter tolerance bands are by tool type so a 6 mm end mill snaps to
the 6 mm catalog entry instead of the 6.35 mm (1/4") one when both
exist, while drills (which often come in 0.05 mm steps) snap more
forgivingly.

This is intentionally lightweight — it doesn't try to validate flutes,
length, or coating against the catalog. Those are advisory in
``a4_tooling`` (often null) and the cost engine ignores them.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("cncserver.engines.rag.tool_snap")


# Snap tolerance bands (mm) keyed by tool_type. "default" is the fallback.
_DIAMETER_TOLERANCE_MM: dict[str, float] = {
    "End Mill":     0.10,
    "Ball Mill":    0.10,
    "Radius Mill":  0.10,
    "Face Mill":    1.00,   # face mills are sized coarsely
    "Chamfer Mill": 0.50,
    "Drill":        0.05,
    "Thread Mill":  0.10,
    "Slitting Saw": 0.30,
    "Form Tool":    0.30,
    "Dovetail":     0.30,
    "default":      0.20,
}


def _flatten_catalog_tools(catalog: dict | None) -> list[dict]:
    """Return a flat list of tool rows from the cost-engine catalog.

    ``fetch_shop_catalog`` returns ``catalog["tools"]`` as a dict keyed
    by tool_id; older paths used a list. Accept both.
    """
    if not catalog:
        return []
    rows_in = catalog.get("tools") or catalog.get("tooling") or {}
    rows: list[dict] = []
    if isinstance(rows_in, dict):
        for tid, row in rows_in.items():
            if isinstance(row, dict):
                rows.append({**row, "_id": tid})
    elif isinstance(rows_in, list):
        for row in rows_in:
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _row_id(row: dict) -> str | None:
    for col in ("_id", "tool_id", "id"):
        v = row.get(col)
        if v not in (None, ""):
            return str(v)
    return None


def _diameter(row: dict) -> float | None:
    """Best-effort diameter (mm) from a catalog row."""
    for col in ("diameter_mm", "diameter"):
        v = row.get(col)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def _index_by_type(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        ttype = str(r.get("tool_type") or "").strip()
        if not ttype:
            continue
        out.setdefault(ttype, []).append(r)
    return out


def _snap_one(
    tool: dict,
    catalog_by_id: dict[str, dict],
    catalog_by_type: dict[str, list[dict]],
) -> tuple[dict, str]:
    """Return ``(snapped_tool, reason)``.

    ``reason`` is short: ``exact_id`` | ``type+dia`` | ``type_only`` |
    ``no_match`` | ``no_type``. Used in logs + the rationale stash.
    """
    out = dict(tool)
    proposed_id = out.get("tool_id")
    if proposed_id and str(proposed_id) in catalog_by_id:
        # Trust the model — merge canonical fields (name + cost + life)
        row = catalog_by_id[str(proposed_id)]
        if not out.get("tool_name"):
            out["tool_name"] = row.get("tool_name") or row.get("name") or out.get("tool_name")
        out.setdefault("would_need_to_buy", False)
        return out, "exact_id"

    ttype = str(out.get("tool_type") or "").strip()
    if not ttype:
        out["tool_id"] = None
        out["would_need_to_buy"] = True
        return out, "no_type"

    candidates = catalog_by_type.get(ttype) or []
    if not candidates:
        out["tool_id"] = None
        out["would_need_to_buy"] = True
        return out, "no_match"

    # Pull the LLM's proposed diameter.
    proposed_dia: float | None = None
    dims = out.get("dimensions")
    if isinstance(dims, dict):
        for col in ("diameter_mm", "diameter"):
            v = dims.get(col)
            if v is None:
                continue
            try:
                proposed_dia = float(v)
                break
            except (TypeError, ValueError):
                continue

    tolerance = _DIAMETER_TOLERANCE_MM.get(ttype, _DIAMETER_TOLERANCE_MM["default"])

    if proposed_dia is None:
        # No diameter to match on — pick the catalog's cheapest of this type
        # so we at least amortize something, but flag it.
        pick = min(candidates, key=lambda r: float(r.get("cost_usd") or 1e12))
        out["tool_id"] = _row_id(pick)
        out["tool_name"] = out.get("tool_name") or pick.get("tool_name") or pick.get("name")
        out["would_need_to_buy"] = False
        return out, "type_only"

    # Score by absolute diameter delta, tie-break by lower cost.
    def _score(row: dict) -> tuple[float, float]:
        d = _diameter(row)
        if d is None:
            return (1e9, 1e9)
        return (abs(d - proposed_dia), float(row.get("cost_usd") or 1e9))

    best = min(candidates, key=_score)
    best_dia = _diameter(best)
    if best_dia is None or abs(best_dia - proposed_dia) > tolerance:
        out["tool_id"] = None
        out["would_need_to_buy"] = True
        return out, "no_match"

    out["tool_id"] = _row_id(best)
    out["tool_name"] = out.get("tool_name") or best.get("tool_name") or best.get("name")
    out["would_need_to_buy"] = False
    return out, "type+dia"


def snap_plan_to_catalog(plan: dict, catalog: dict | None) -> dict:
    """Walk the plan's operations, snapping each tool to a catalog row.

    Mutates ``plan`` (and returns it) — caller is the per-component
    planner which owns the dict. Counters land on
    ``plan["_tool_snap_stats"]`` for the trace.
    """
    rows = _flatten_catalog_tools(catalog)
    catalog_by_id = {_row_id(r): r for r in rows if _row_id(r)}
    catalog_by_type = _index_by_type(rows)

    stats = {
        "exact_id":   0,
        "type+dia":   0,
        "type_only":  0,
        "no_match":   0,
        "no_type":    0,
        "total":      0,
    }

    ops = plan.get("operations") if isinstance(plan, dict) else None
    if not isinstance(ops, list):
        plan["_tool_snap_stats"] = stats
        return plan

    for op in ops:
        if not isinstance(op, dict):
            continue
        tools = op.get("tools")
        if not isinstance(tools, list):
            continue
        new_tools: list[dict] = []
        for t in tools:
            if not isinstance(t, dict):
                new_tools.append(t)
                continue
            snapped, reason = _snap_one(t, catalog_by_id, catalog_by_type)
            stats[reason] = stats.get(reason, 0) + 1
            stats["total"] += 1
            new_tools.append(snapped)
        op["tools"] = new_tools

    plan["_tool_snap_stats"] = stats
    logger.info(
        "snap_plan_to_catalog: total=%d exact=%d type+dia=%d type_only=%d "
        "no_match=%d no_type=%d",
        stats["total"], stats["exact_id"], stats["type+dia"],
        stats["type_only"], stats["no_match"], stats["no_type"],
    )
    return plan


# ---------------------------------------------------------------------------
# Machine snap — analogous logic for chosen_machine_id
# ---------------------------------------------------------------------------

def _flatten_catalog_machines(catalog: dict | None) -> list[dict]:
    if not catalog:
        return []
    rows_in = catalog.get("machines") or {}
    rows: list[dict] = []
    if isinstance(rows_in, dict):
        for mid, row in rows_in.items():
            if isinstance(row, dict):
                rows.append({**row, "_id": mid})
    elif isinstance(rows_in, list):
        for r in rows_in:
            if isinstance(r, dict):
                rows.append(r)
    return rows


def snap_machine_to_catalog(plan: dict, catalog: dict | None) -> dict:
    """If chosen_machine_id is missing from the catalog, pick the
    cheapest catalog machine whose ``machine_type`` matches the plan's
    ``machine_class``. Mirrors the agentic engine's permissiveness —
    missing IDs are filled in best-effort, not raised.
    """
    if not isinstance(plan, dict):
        return plan
    rows = _flatten_catalog_machines(catalog)
    by_id = {_row_id(r): r for r in rows if _row_id(r)}

    chosen = plan.get("chosen_machine_id")
    if chosen and str(chosen) in by_id:
        return plan

    machine_class = (plan.get("machine_class") or "").lower().strip()
    if not machine_class or not rows:
        return plan

    same_class = [
        r for r in rows
        if str(r.get("machine_type") or "").lower().strip() == machine_class
        or str(r.get("machine_class") or "").lower().strip() == machine_class
    ]
    if not same_class:
        return plan

    pick = min(same_class, key=lambda r: float(r.get("hourly_rate_usd") or 1e12))
    plan["chosen_machine_id"] = _row_id(pick)
    # Also update top_machines rank-1 if the LLM left it null.
    top = plan.get("top_machines")
    if isinstance(top, list) and top and isinstance(top[0], dict):
        if not top[0].get("machine_id"):
            top[0]["machine_id"] = plan["chosen_machine_id"]
            top[0]["machine_name"] = top[0].get("machine_name") or pick.get("machine_name") or pick.get("name")
    logger.info("snap_machine_to_catalog: snapped chosen_machine_id → %s (class=%s)",
                plan["chosen_machine_id"], machine_class)
    return plan


__all__ = ["snap_plan_to_catalog", "snap_machine_to_catalog"]
