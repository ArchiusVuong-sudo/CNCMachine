"""Per-user shop-catalog tool for the agentic engine.

The orchestrator pre-fetches the per-user catalog
(``{labor, machines, tools, materials}``) once per analysis. We expose it
to the agent through :func:`make_catalog_lookup`, which binds the dict
and returns a function matching the LLM tool signature.

Binding-by-factory keeps the catalog out of the agent's context — the
model only sees the filtered rows it asks for, never the full table.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from .citation import citation_hint_for_catalog

logger = logging.getLogger("cncserver.engines.agentic.tools.catalog")

_VALID_TABLES: tuple[str, ...] = ("machines", "tools", "materials", "labor")

# Per-table fallback id columns — first column present wins.
_ID_COLUMNS: dict[str, tuple[str, ...]] = {
    "machines":  ("machine_id", "id", "name"),
    "tools":     ("tool_id", "id", "name", "key"),
    "materials": ("material_code", "code", "key", "id"),
    "labor":     ("role", "labor_id", "id", "key"),
}


def _row_id(table: str, row: dict) -> str | None:
    """Best-effort identifier for a catalog row — used in citation tokens."""
    for col in _ID_COLUMNS.get(table, ()):
        val = row.get(col)
        if val not in (None, ""):
            return str(val)
    return None


def _filter_rows(rows: list[dict], filters: dict | None) -> list[dict]:
    """Apply ``{col: value}`` / ``{col: {eq|contains|min|max}}`` predicates."""
    if not filters:
        return list(rows)
    out: list[dict] = []
    for row in rows:
        ok = True
        for col, spec in filters.items():
            cell = row.get(col)
            if isinstance(spec, dict):
                if "eq" in spec and str(cell) != str(spec["eq"]):
                    ok = False
                    break
                if "contains" in spec and str(spec["contains"]).lower() not in str(cell or "").lower():
                    ok = False
                    break
                if "min" in spec:
                    try:
                        if float(cell) < float(spec["min"]):
                            ok = False
                            break
                    except (TypeError, ValueError):
                        ok = False
                        break
                if "max" in spec:
                    try:
                        if float(cell) > float(spec["max"]):
                            ok = False
                            break
                    except (TypeError, ValueError):
                        ok = False
                        break
            else:
                if str(cell).lower() != str(spec).lower():
                    ok = False
                    break
        if ok:
            out.append(row)
    return out


def _normalize_rows(rows: Any) -> list[dict]:
    """Coerce catalog payload into a list of dicts.

    ``materials`` may arrive as a dict keyed by material code; flatten so
    the agent gets a uniform shape across tables.
    """
    if rows is None:
        return []
    if isinstance(rows, dict):
        return [
            {"key": k, **(v if isinstance(v, dict) else {"value": v})}
            for k, v in rows.items()
        ]
    if isinstance(rows, list):
        return [r if isinstance(r, dict) else {"value": r} for r in rows]
    return []


def make_catalog_lookup(catalog: dict[str, Any] | None) -> Callable[..., dict[str, Any]]:
    """Bind ``catalog`` and return the tool function for the LLM loop.

    The returned ``catalog_lookup(table, filters, limit)`` reads from the
    bound dict so the agent cannot reach across analyses or users.
    """
    catalog = catalog or {}

    def catalog_lookup(
        table: str,
        filters: dict | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        if table not in _VALID_TABLES:
            return {"error": f"table must be one of {list(_VALID_TABLES)}", "got": table}
        rows = _normalize_rows(catalog.get(table))
        filtered = _filter_rows(rows, filters)
        cap = max(1, int(limit))
        capped = filtered[:cap]
        annotated = [
            {**r, "citation_hint": citation_hint_for_catalog(table, _row_id(table, r))}
            for r in capped
        ]
        return {
            "table": table,
            "filters": filters or {},
            "rows": annotated,
            "count": len(annotated),
            "total_matched": len(filtered),
            "total_in_catalog": len(rows),
            "citation_hint": citation_hint_for_catalog(table, None),
        }

    return catalog_lookup


CATALOG_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "catalog_lookup",
            "description": (
                "Query the per-user shop catalog. "
                "Tables: 'machines', 'tools', 'materials', 'labor'. "
                "Use this to enumerate the shop's actual capabilities before recommending a machine, tool, or stock."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": list(_VALID_TABLES)},
                    "filters": {
                        "type": "object",
                        "description": "{col: value} or {col: {eq|contains|min|max: value}}.",
                    },
                    "limit": {"type": "integer", "description": "Default 25."},
                },
                "required": ["table"],
            },
        },
    },
]
