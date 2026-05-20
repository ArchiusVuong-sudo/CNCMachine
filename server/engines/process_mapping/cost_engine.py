"""
cost_engine.py Per-component CNC cost calculation backed by Supabase.

Catalog tables queried (single shared catalog, no per-user scoping):
    a4_labor_rates    : id, role_name, hourly_rate_usd, is_active
    a4_machines       : id, machine_name, machine_type,
                        max_spindle_rpm, max_feed_mm_per_min, max_rapid_mm_per_min,
                        tool_change_time_sec, hourly_rate_usd, is_active
    a4_tooling        : id, tool_name, tool_type, diameter_mm, tool_dimensions,
                        recommended_rpm_min/max, recommended_feed_min/max_mm_per_min,
                        max_depth_of_cut_mm, tool_life_minutes, cost_usd, is_active
    a4_material_stock : id, material_name, material_form, length/width/height/diameter/...
                        cost_per_stock_usd, machinability_rating, recommended_sfm, ...

Cost formula per component:
  raw_material_usd     = stock.cost_per_stock_usd / stock.qty_per_stock
  setup_time_min       = 5.0 + 2.0 * feature_count
  setup_usd            = (setup_time_min/60) * (machinist + programmer*0.5) / batch_size
  machining_usd_*      = per process: (cycle_time/60) * (machinist + machine_rate) + tool_amortisation
  deburr_time_min      = 0.5 + 0.1 * feature_count
  deburr_usd           = (deburr_time_min/60) * (deburrer + deburr_station_rate)
  inspection_time_min  = 0.25 if gdt_count <= 3 else 1.0 + 0.1 * gdt_count
  inspection_usd       = (inspection_time_min/60) * inspector
  total_usd            = sum of all above

Public API:
    async def compute_cost(components, processes_per_component,
                           batch_size, supabase_client, catalog=None) -> dict

    async def fetch_shop_catalog(supabase_client) -> dict
        Pre-fetch labor/machine/tool/material catalogs. Returns:
          {"labor": {role: rate}, "machines": {id: row},
           "tools": {id: row}, "materials": {name_lower: row}}
        Pass to compute_cost via `catalog=` to avoid N+1 queries.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("cncserver.engines.process_mapping.cost_engine")


_DEFAULT_BLENDED_RATE_USD_PER_HR = 30.0  # quote-shop rate when no machine catalog


def _blended_rate_usd_per_hr() -> float:
    """Read A4_BLENDED_RATE_USD_PER_HR env var.

    When set to a positive number, compute_cost() uses a single flat rate
    (labor + machine combined) for every routing row instead of the
    labor-role + machine-hourly split. Useful for matching quote-shop
    blended rates (~$30â€“$45/hr) rather than fully-loaded shop rates.
    """
    try:
        v = float(os.environ.get("A4_BLENDED_RATE_USD_PER_HR") or 0)
        return v if v > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _effective_blended_rate(catalog: dict) -> float:
    """Pick the blended rate to apply (0 = disabled, use role+machine split).

    Priority:
      1. Explicit A4_BLENDED_RATE_USD_PER_HR env var (user override).
      2. Empty machine catalog â†’ auto-use _DEFAULT_BLENDED_RATE_USD_PER_HR so
         we don't double-charge labor + default machine rate ($65 + $45 = $110/hr)
         and end up 3-4Ã— over a quote-shop baseline.
      3. Otherwise 0 â€” the existing role-based + per-machine split applies.
    """
    explicit = _blended_rate_usd_per_hr()
    if explicit > 0:
        return explicit
    if not (catalog.get("machines") or {}):
        return _DEFAULT_BLENDED_RATE_USD_PER_HR
    return 0.0

# ---------------------------------------------------------------------------
# Default / fallback rates (USD/hr) used when DB query returns nothing
# ---------------------------------------------------------------------------
_DEFAULT_RATES = {
    "machinist":       65.0,
    "programmer":      80.0,
    "deburrer":        35.0,
    "inspector":       50.0,
    "setup_technician":45.0,
    "welder":          55.0,
    "assembler":       40.0,
    "machine":         45.0,   # generic CNC machine hourly rate
    "deburr_station":  15.0,   # bench/pedestal deburr tools (Slide 8: deburr uses machine rate too)
}


# Fallback unit prices for purchased hardware when BOM has no `unit_price`.
# Keyed by a keyword present in the part name/description. First-match wins,
# so order matters: more-specific keywords must come before more-general ones.
_HARDWARE_FALLBACK_PRICES_USD = [
    ("helicoil",      2.50),
    ("heli-coil",     2.50),
    ("keenserts",     3.50),
    ("dowel",         0.35),
    ("pin",           0.25),
    ("rivet",         0.05),
    ("nut",           0.15),
    ("washer",        0.08),
    ("o-ring",        0.30),
    ("o ring",        0.30),
    ("gasket",        1.50),
    ("bearing",       8.00),
    ("bushing",       3.00),
    ("spring",        1.00),
    ("screw",         0.25),
    ("bolt",          0.35),
    ("insert",        2.00),
    ("stud",          0.75),
]
_HARDWARE_DEFAULT_PRICE_USD = 1.00


def _hardware_unit_price(comp: dict) -> float:
    """Return a per-unit USD price for a purchased hardware item.
    Order: explicit BOM `unit_price_usd` â†’ BOM `unit_cost_usd` â†’ keyword fallback."""
    for key in ("unit_price_usd", "unit_cost_usd", "purchase_price_usd"):
        v = comp.get(key)
        if v is not None:
            try:
                fv = float(v)
                if fv > 0:
                    return fv
            except (TypeError, ValueError):
                pass
    label = " ".join([
        str(comp.get("name") or ""),
        str(comp.get("description") or ""),
        str(comp.get("bom_description") or ""),
    ]).lower()
    for kw, price in _HARDWARE_FALLBACK_PRICES_USD:
        if kw in label:
            return price
    return _HARDWARE_DEFAULT_PRICE_USD


# ---------------------------------------------------------------------------
# Catalog pre-fetch (eliminates N+1 Supabase queries in the process loop)
# ---------------------------------------------------------------------------

async def fetch_shop_catalog(supabase_client: Any) -> dict:
    """
    Pre-fetch the shared shop catalog once per analysis run.

    Returns
    -------
    {
      "labor":     {role_name_lower: hourly_rate_usd},
      "machines":  {machine_id: machine_row},
      "tools":     {tool_id:    tool_row},
      "materials": {material_name_lower: material_stock_row},
    }

    Missing roles are back-filled with _DEFAULT_RATES so downstream callers
    can use dict-get without guards.  If supabase_client is None, returns
    defaults only.
    """
    catalog: dict[str, Any] = {
        "labor":     dict(_DEFAULT_RATES),
        "machines":  {},
        "tools":     {},
        "materials": {},
    }

    if supabase_client is None:
        logger.info("fetch_shop_catalog: no supabase_client - using default rates only")
        return catalog

    try:
        rows = (
            supabase_client.from_("a4_labor_rates")
            .select("*").eq("is_active", True).execute().data
        ) or []
        for r in rows:
            role = (r.get("role_name") or "").lower().strip()
            rate = float(r.get("hourly_rate_usd") or 0)
            if role and rate > 0:
                catalog["labor"][role] = rate
    except Exception as exc:
        logger.warning("fetch_shop_catalog: labor query failed - using defaults (%s)", exc)

    try:
        rows = (
            supabase_client.from_("a4_machines")
            .select("*").eq("is_active", True).execute().data
        ) or []
        for r in rows:
            mid = r.get("id")
            if mid:
                catalog["machines"][mid] = r
    except Exception as exc:
        logger.warning("fetch_shop_catalog: machines query failed (%s)", exc)

    try:
        rows = (
            supabase_client.from_("a4_tooling")
            .select("*").eq("is_active", True).execute().data
        ) or []
        for r in rows:
            tid = r.get("id")
            if tid:
                catalog["tools"][tid] = r
    except Exception as exc:
        logger.warning("fetch_shop_catalog: tooling query failed (%s)", exc)

    try:
        rows = (
            supabase_client.from_("a4_material_stock")
            .select("*").eq("is_active", True).execute().data
        ) or []
        for r in rows:
            name = (r.get("material_name") or "").lower().strip()
            if name:
                catalog["materials"].setdefault(name, []).append(r)
    except Exception as exc:
        logger.warning("fetch_shop_catalog: material_stock query failed (%s)", exc)

    logger.info(
        "fetch_shop_catalog: labor=%d machines=%d tools=%d materials=%d",
        len(catalog["labor"]), len(catalog["machines"]),
        len(catalog["tools"]), len(catalog["materials"]),
    )
    return catalog


def _tokens(s: str) -> set[str]:
    """Lowercase word/digit tokens, stripped of punctuation."""
    import re
    return {t for t in re.split(r"[^a-z0-9]+", s.lower()) if t}


def _pick_stock(comp: dict, catalog: dict) -> dict | None:
    """Find the cheapest stock row that matches the component's material.

    Match scoring uses token overlap (case-insensitive, punctuation-stripped),
    so 'AISI 1018 Steel' matches a stock named 'Steel 1018', and
    'VICTREX PEEK 450G NATURAL' matches 'PEEK'. Falls back to None when no
    catalog material shares any meaningful tokens with comp.material.

    Returns the cheapest matching row with stock_id/material_name/
    cost_per_stock_usd/qty_per_stock populated. qty_per_stock defaults to 1
    (one part per stock) since we don't run nest-fitting here.
    """
    mat = (comp.get("material") or "").strip()
    if not mat:
        return None

    comp_tokens = _tokens(mat)
    if not comp_tokens:
        return None

    materials = catalog.get("materials") or {}
    best_rows: list[dict] = []
    best_overlap = 0

    for name, group in materials.items():
        overlap = len(comp_tokens & _tokens(name))
        if overlap > best_overlap:
            best_overlap = overlap
            best_rows = list(group)

    if not best_rows:
        return None

    best = min(best_rows, key=lambda r: float(r.get("cost_per_stock_usd") or 1e12))
    return {
        "stock_id":            best.get("id"),
        "material_name":       best.get("material_name"),
        "size_label":          best.get("material_form"),
        "cost_per_stock_usd":  float(best.get("cost_per_stock_usd") or 0.0),
        "qty_per_stock":       1,
    }


# ---------------------------------------------------------------------------
# Per-row accessors (memory lookup against pre-fetched catalog)
# ---------------------------------------------------------------------------

def _machine_rate_from_catalog(machine_id: str | None, catalog: dict) -> float:
    if not machine_id:
        return _DEFAULT_RATES["machine"]
    row = catalog["machines"].get(machine_id)
    if not row:
        return _DEFAULT_RATES["machine"]
    return float(row.get("hourly_rate_usd") or _DEFAULT_RATES["machine"])


def _tool_amortised_cost(tool_id: str | None, cycle_time_min: float, catalog: dict) -> float:
    """
    Tool amortisation = cost_usd Ã— (cycle_time / tool_life_minutes).
    Returns 0.0 when tool_id unknown or tool_life absent.
    """
    if not tool_id or cycle_time_min <= 0:
        return 0.0
    row = catalog["tools"].get(tool_id)
    if not row:
        return 0.0
    cost = float(row.get("cost_usd") or 0.0)
    life = float(row.get("tool_life_minutes") or 0.0)
    if cost <= 0 or life <= 0:
        return 0.0
    return cost * (cycle_time_min / life)


# ---------------------------------------------------------------------------
# Public compute_cost
# ---------------------------------------------------------------------------

async def compute_cost(
    components: list[dict],
    processes_per_component: list[list[dict]],
    batch_size: int,
    supabase_client: Any,
    catalog: dict | None = None,
) -> dict:
    """
    Compute full cost breakdown for all components.

    Parameters
    ----------
    components              : list of component dicts (mutated to add "cost" key)
    processes_per_component : outer list matches components; inner list = process dicts
    batch_size              : production batch size (divides setup cost)
    supabase_client         : Supabase Python client (None - fallback rates only)
    catalog                 : Optional pre-fetched dict from fetch_shop_catalog().
                              If None, this function calls fetch_shop_catalog()
                              itself (one extra round-trip).

    Returns
    -------
    {
        "total_usd": float,
        "breakdown_by_component": [{"component_index": int, "total_usd": float}, ...]
    }
    """
    if batch_size < 1:
        batch_size = 1

    if catalog is None:
        catalog = await fetch_shop_catalog(supabase_client)

    labor = catalog["labor"]
    machinist_rate   = labor.get("machinist",        _DEFAULT_RATES["machinist"])
    programmer_rate  = labor.get("programmer",       _DEFAULT_RATES["programmer"])
    deburrer_rate    = labor.get("deburrer",         _DEFAULT_RATES["deburrer"])
    inspector_rate   = labor.get("inspector",        _DEFAULT_RATES["inspector"])
    assembler_rate   = labor.get("assembler",        _DEFAULT_RATES["assembler"])
    deburr_station   = labor.get("deburr_station",   _DEFAULT_RATES["deburr_station"])  # Bug D: now honours catalog

    # Map routing labor_role â†’ hourly rate (used only for routing-style processes).
    _ROLE_RATE = {
        "machinist":  machinist_rate,
        "programmer": programmer_rate,
        "deburrer":   deburrer_rate,
        "inspector":  inspector_rate,
        "assembler":  assembler_rate,
    }

    blended = _effective_blended_rate(catalog)
    blended_source = (
        "env"    if _blended_rate_usd_per_hr() > 0
        else "auto-empty-catalog" if blended > 0
        else "-"
    )
    logger.info(
        "cost_engine START: components=%d batch_size=%d mode=%s blended_src=%s",
        len(components), batch_size,
        ("blended" if blended > 0 else "role-based"),
        blended_source,
    )
    logger.info(
        "cost_engine RATES: machinist=$%.2f/hr programmer=$%.2f deburrer=$%.2f "
        "inspector=$%.2f assembler=$%.2f deburr_station=$%.2f blended=$%.2f",
        machinist_rate, programmer_rate, deburrer_rate, inspector_rate,
        assembler_rate, deburr_station, blended,
    )
    logger.info(
        "cost_engine CATALOG: machines=%d tools=%d materials=%d",
        len(catalog.get("machines") or {}),
        len(catalog.get("tools") or {}),
        len(catalog.get("materials") or {}),
    )

    breakdown_by_component: list[dict] = []
    grand_total = 0.0

    for comp_idx, comp in enumerate(components):
        processes = (
            processes_per_component[comp_idx]
            if comp_idx < len(processes_per_component)
            else []
        )
        stock = comp.get("stock") or {}
        if not stock and (comp.get("part_type") or "").lower() != "hardware":
            picked = _pick_stock(comp, catalog)
            if picked:
                stock = picked
                comp["stock"] = picked
        features    = comp.get("features") or []
        gdt_entries = comp.get("pmi_annotations") or []

        feature_count = len(features)
        gdt_count     = len(gdt_entries)

        part_type = (comp.get("part_type") or "").lower()
        if part_type == "hardware":
            bom_price = _hardware_unit_price(comp)
            bom_qty   = max(int(comp.get("bom_qty") or 1), 1)
            hw_total  = round(bom_price * bom_qty, 4)
            cost_obj = {
                "raw_material_usd":         hw_total,
                "setup_usd":                0.0,
                "machining_usd_by_process": {},
                "machining_total_usd":      0.0,
                "deburr_usd":               0.0,
                "inspection_usd":           0.0,
                "total_usd":                hw_total,
                "cost_source":              "hardware_purchase",
            }
            comp["cost"] = cost_obj
            grand_total += hw_total
            breakdown_by_component.append({
                "component_index": comp.get("component_index", comp_idx),
                "total_usd":       hw_total,
                "cost":            cost_obj,
            })
            logger.info(
                "cost_engine COMP[%d] %s HARDWARE: unit_price=$%.4f Ã— qty=%d = $%.2f",
                comp_idx, comp.get("name", "?"), bom_price, bom_qty, hw_total,
            )
            continue

        cost_per_stock = float(stock.get("cost_per_stock_usd") or 0.0)
        qty_per_stock  = max(int(stock.get("qty_per_stock") or 1), 1)
        raw_material_usd = cost_per_stock / qty_per_stock
        logger.info(
            "cost_engine COMP[%d] %s START: part_type=%s material=%s stock=%s "
            "cost_per_stock=$%.2f parts_per_stock=%d â†’ raw_material=$%.3f | features=%d gdt=%d processes=%d",
            comp_idx, comp.get("name", "?"), part_type,
            (stock.get("material_name") or comp.get("material") or "-")[:24],
            stock.get("size_label") or stock.get("stock_size") or "-",
            cost_per_stock, qty_per_stock, raw_material_usd,
            feature_count, gdt_count, len(processes),
        )


        routing_style = any(
            p.get("labor_role") is not None or p.get("setup_min_per_lot") is not None
            for p in processes
        )

        if routing_style:
            setup_usd = 0.0  # setup is amortised inside each routing row's cycle_time_min
        else:
            setup_time_min = 5.0 + 2.0 * feature_count
            setup_usd = (
                (setup_time_min / 60.0)
                * (machinist_rate + programmer_rate * 0.5)
                / batch_size
            )

        machining_by_process: dict[str, float] = {}
        machining_total = 0.0

        for proc in processes:
            proc_type    = str(proc.get("process_type") or proc.get("category") or "cnc_milling")
            ct_min       = float(proc.get("cycle_time_min") or 0.0)
            machine_id   = (proc.get("machine_ref") or {}).get("machine_id")
            tool_id      = (proc.get("tooling_ref") or {}).get("tool_id")
            role         = str(proc.get("labor_role") or "machinist").lower()

            tool_cost    = _tool_amortised_cost(tool_id, ct_min, catalog)

            if blended > 0:
                # Flat blended-rate mode: single USD/hr covers labor + machine.
                # Tool amortisation still applies on top (actual consumable cost).
                labor_rate   = blended
                machine_rate = 0.0
            else:
                labor_rate   = _ROLE_RATE.get(role, machinist_rate)
                machine_rate = _machine_rate_from_catalog(machine_id, catalog)
                # Deburr and assembly/inspection rows aren't on a CNC, so skip the
                # CNC machine rate; use the deburr-station rate for deburrers.
                if role == "deburrer":
                    machine_rate = deburr_station
                elif role in ("inspector", "assembler"):
                    machine_rate = 0.0  # bench work â€” no machine burden

            labor_cost = (ct_min / 60.0) * labor_rate
            mach_cost  = (ct_min / 60.0) * machine_rate
            proc_cost  = max(labor_cost + mach_cost + tool_cost, 0.0)

            key = proc_type.lower().replace(" ", "_")
            machining_by_process[key] = machining_by_process.get(key, 0.0) + proc_cost
            machining_total += proc_cost

            proc["labor_cost_usd"]    = round(labor_cost, 4)
            proc["machine_cost_usd"]  = round(mach_cost,   4)
            proc["tool_cost_usd"]     = round(tool_cost,   4)
            proc["total_cost_usd"]    = round(proc_cost,   4)

            logger.info(
                "cost_engine COMP[%d] PROC %s: ct=%.3fmin role=%s labor=$%.2f/hr mach=$%.2f/hr "
                "tool=$%.3f â†’ labor=$%.3f mach=$%.3f total=$%.3f",
                comp_idx, key, ct_min, role, labor_rate, machine_rate,
                tool_cost, labor_cost, mach_cost, proc_cost,
            )

        if routing_style:
            deburr_usd = 0.0
            inspection_usd = 0.0
        else:
            deburr_time_min = 0.5 + 0.1 * feature_count
            deburr_usd = (deburr_time_min / 60.0) * (deburrer_rate + deburr_station)
            inspection_time_min = (
                0.25 if gdt_count <= 3
                else 1.0 + 0.1 * gdt_count
            )
            inspection_usd = (inspection_time_min / 60.0) * inspector_rate

        total_usd = (
            raw_material_usd
            + setup_usd
            + machining_total
            + deburr_usd
            + inspection_usd
        )
        total_usd = max(round(total_usd, 4), 0.0)

        cost_obj = {
            "raw_material_usd":         round(raw_material_usd,  4),
            "setup_usd":                round(setup_usd,          4),
            "machining_usd_by_process": {k: round(v, 4) for k, v in machining_by_process.items()},
            "machining_total_usd":      round(machining_total,   4),
            "deburr_usd":               round(deburr_usd,         4),
            "inspection_usd":           round(inspection_usd,     4),
            "total_usd":                total_usd,
            "cost_source":              "routing" if routing_style else "legacy",
        }

        comp["cost"] = cost_obj
        grand_total += total_usd
        breakdown_by_component.append({
            "component_index": comp.get("component_index", comp_idx),
            "total_usd":       total_usd,
            "cost":            cost_obj,
        })

        logger.info(
            "cost_engine COMP[%d] %s TOTAL (%s-mode): raw=$%.3f + setup=$%.3f + mach=$%.3f "
            "(%s) + deburr=$%.3f + insp=$%.3f = $%.2f",
            comp_idx, comp.get("name", "?"),
            "routing" if routing_style else "legacy",
            raw_material_usd, setup_usd, machining_total,
            ", ".join(f"{k}:${v:.2f}" for k, v in sorted(machining_by_process.items(), key=lambda kv: -kv[1])),
            deburr_usd, inspection_usd, total_usd,
        )

    grand_total = round(grand_total, 2)
    logger.info(
        "cost_engine DONE: %d component(s) batch=%d grand_total=$%.2f",
        len(components), batch_size, grand_total,
    )

    return {
        "total_usd":              grand_total,
        "breakdown_by_component": breakdown_by_component,
    }
