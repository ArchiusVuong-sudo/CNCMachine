"""Per-component user-message builder.

The system message is static; this file packages the dynamic inputs:

  1. **Inputs** — the target component (material, features, envelope).
  2. **Retrieved analogues** — top-K rows from ``rag_part_embeddings``,
     rendered as a compact human-readable block (NOT raw JSON — the
     model is better at structured prose).
  3. **Pattern chunks** (optional) — only included when analogue
     coverage is weak.
  4. **Catalog summary** — available machines, common tools, labor
     rates. Compact form, not the full table.
  5. **Output reminder** — the model is told (again) to emit one JSON.

We keep the analogue rendering deterministic so the prompt is stable
across reruns of the same component (helpful when comparing engines).
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("cncserver.engines.rag.prompts.user")


# ---------------------------------------------------------------------------
# Component projection (same fields the agentic prompt uses)
# ---------------------------------------------------------------------------

def _component_summary(component: dict) -> dict:
    """Project the component dict down to the fields the LLM needs."""
    bbox = component.get("bbox") or component.get("bounding_box") or {}
    features = component.get("features") or []
    feature_type_counts: dict[str, int] = {}
    for f in features:
        ft = (f or {}).get("type") or (f or {}).get("feature_type") or "unknown"
        feature_type_counts[ft] = feature_type_counts.get(ft, 0) + 1
    summary = {
        "component_index":      component.get("component_index"),
        "name":                 component.get("name"),
        "part_type":            component.get("part_type"),
        "bom_part_type":        component.get("bom_part_type"),
        "component_role":       component.get("component_role"),
        "component_role_reason": component.get("component_role_reason"),
        "orientation":          component.get("orientation"),
        "instance_count":       component.get("instance_count", 1),
        "volume_mm3":           component.get("volume_mm3"),
        "envelope_mm":          bbox if isinstance(bbox, dict) else None,
        "n_features":           len(features),
        "feature_type_counts":  feature_type_counts,
        "features":             features,
    }
    if component.get("assembly_hint"):
        summary["assembly_hint"] = component["assembly_hint"]
    return summary


# ---------------------------------------------------------------------------
# Analogue rendering
# ---------------------------------------------------------------------------

def _fmt_money(value: Any, currency: str | None) -> str:
    if value is None:
        return "—"
    try:
        return f"{currency or 'USD'} {float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_min(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f} min/pc"
    except (TypeError, ValueError):
        return "—"


def _fmt_hr(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f} hr/lot"
    except (TypeError, ValueError):
        return "—"


def _fmt_op_row(row: dict) -> str:
    """One short line per op row from a retrieved analogue's operations_json."""
    op_id = (row.get("op") or "?").strip() if isinstance(row.get("op"), str) else row.get("op") or "?"
    machine = (row.get("machine") or "").strip()
    op_type = (row.get("operation_type") or "").strip()
    feature = (row.get("feature") or "").strip()
    run_act = (row.get("run_min_pc_act") or "").strip() if isinstance(row.get("run_min_pc_act"), str) else row.get("run_min_pc_act")
    run_est = (row.get("run_min_pc_est") or "").strip() if isinstance(row.get("run_min_pc_est"), str) else row.get("run_min_pc_est")
    n_tools = (row.get("n_tools") or "").strip() if isinstance(row.get("n_tools"), str) else row.get("n_tools")

    parts = [f"OP{op_id}"]
    if machine:
        parts.append(f"@ {machine}")
    if op_type and str(op_type).lower() not in ("", "none"):
        parts.append(f"({op_type})")
    if feature:
        parts.append(f"— {feature}")
    if run_act:
        parts.append(f"[{run_act} min/pc act]")
    elif run_est:
        parts.append(f"[{run_est} min/pc est]")
    if n_tools:
        parts.append(f"{n_tools} tools")
    return " ".join(str(p) for p in parts)


def _render_analogue(row: dict, rank: int) -> str:
    """Render one analogue row as a markdown block.

    The row is what comes back from ``rag_search_parts`` — same columns
    as ``rag_part_embeddings`` plus a ``similarity`` float.
    """
    pn = row.get("part_number") or "?"
    rev = row.get("rev")
    sim = row.get("similarity")
    fallback = row.get("_filter_fallback")

    header = f"### Analogue {rank} — part {pn}"
    if rev:
        header += f" rev {rev}"
    if sim is not None:
        try:
            header += f" · cosine similarity {float(sim):.3f}"
        except (TypeError, ValueError):
            pass
    if fallback:
        header += " · (filter fallback — material/part-type filter relaxed)"

    bullets: list[str] = []

    cls_bits = [
        row.get("complexity_class") or "?",
        row.get("material") or "?",
    ]
    fam = row.get("material_family")
    if fam and fam != "unknown":
        cls_bits.append(f"({fam})")
    pt = row.get("part_type")
    if pt:
        cls_bits.append(pt)
    bullets.append("class · material · type: " + " · ".join(str(b) for b in cls_bits if b))

    env_bits = []
    if row.get("envelope_mm"):
        env_bits.append(f"envelope {row['envelope_mm']}")
    if row.get("bbox_volume_mm3"):
        try:
            env_bits.append(f"~{float(row['bbox_volume_mm3']):,.0f} mm³ bbox")
        except (TypeError, ValueError):
            pass
    if row.get("stock_form"):
        env_bits.append(f"stock {row['stock_form']}")
    if env_bits:
        bullets.append("geometry: " + "; ".join(env_bits))

    fp_bits = []
    if row.get("n_features") is not None:
        fp_bits.append(f"{row['n_features']} features")
    if row.get("n_ops") is not None:
        fp_bits.append(f"{row['n_ops']} ops")
    if row.get("n_tools") is not None:
        fp_bits.append(f"~{row['n_tools']} tools")
    if fp_bits:
        bullets.append("footprint: " + ", ".join(fp_bits))

    econ_bits = [
        f"cycle {_fmt_min(row.get('total_run_min_pc'))}",
        f"setup {_fmt_hr(row.get('total_setup_hr'))}",
        f"actual cost {_fmt_money(row.get('cost_ea_act'), row.get('currency'))}/pc",
        f"quoted {_fmt_money(row.get('unit_price'), row.get('currency'))}/pc",
    ]
    bullets.append("economics: " + " · ".join(econ_bits))

    # Operations from operations_json. Cap at 8 lines so prompt stays bounded.
    ops = row.get("operations_json") or []
    if isinstance(ops, list) and ops:
        bullets.append("routing:")
        for op_row in ops[:8]:
            if isinstance(op_row, dict):
                bullets.append("  - " + _fmt_op_row(op_row))
        if len(ops) > 8:
            bullets.append(f"  - … ({len(ops) - 8} more ops)")

    # MD-derived description — short.
    desc = (row.get("description") or "").strip()
    if desc:
        # Already a multi-line descriptor — strip and indent.
        first_para = desc.split("\n\n", 1)[0]
        bullets.append("descriptor: " + first_para.replace("\n", " ")[:600])

    return header + "\n" + "\n".join(f"- {b}" for b in bullets)


def _render_pattern(row: dict, rank: int) -> str:
    """Render one pattern chunk from ``rag_search_patterns``."""
    kb = row.get("kb_path") or "?"
    section = row.get("section_heading") or ""
    sim = row.get("similarity")
    header = f"### Pattern {rank} — {kb}"
    if section:
        header += f" :: {section}"
    if sim is not None:
        try:
            header += f" · sim {float(sim):.3f}"
        except (TypeError, ValueError):
            pass
    content = (row.get("content") or "").strip()
    return header + "\n\n" + content[:2000]


# ---------------------------------------------------------------------------
# Catalog summary
# ---------------------------------------------------------------------------

def _summarize_catalog(catalog: dict | None) -> dict:
    """Compress the per-user shop catalog to a model-friendly summary.

    The catalog dict is the one assembled by
    ``server/engines/process_mapping/cost_engine.py::fetch_shop_catalog``
    — every top-level key is a dict (id-keyed) not a list, so flatten as
    we go.
    """
    if not catalog:
        return {"available": False, "note": "no per-user catalog — use defaults"}

    machines_in = catalog.get("machines") or {}
    tools_in    = catalog.get("tools") or catalog.get("tooling") or {}
    labor_in    = catalog.get("labor") or catalog.get("labor_rates") or {}
    materials_in = catalog.get("materials") or {}

    # Normalize machines (dict→list of rows w/ id, sort by rate asc).
    machines_list: list[dict] = []
    if isinstance(machines_in, dict):
        for mid, row in machines_in.items():
            if isinstance(row, dict):
                machines_list.append({**row, "_id": mid})
    elif isinstance(machines_in, list):
        machines_list = [r for r in machines_in if isinstance(r, dict)]

    def _mach_row(m: dict) -> dict:
        return {
            "machine_id":             m.get("_id") or m.get("id") or m.get("machine_id"),
            "name":                   m.get("machine_name") or m.get("name") or m.get("display_name"),
            "machine_type":           m.get("machine_type") or m.get("machine_class"),
            "hourly_rate_usd_per_hr": m.get("hourly_rate_usd") or m.get("hourly_rate_usd_per_hr"),
            "max_spindle_rpm":        m.get("max_spindle_rpm") or m.get("max_rpm"),
            "max_feed_mm_per_min":    m.get("max_feed_mm_per_min"),
        }
    machines_sm = [_mach_row(m) for m in machines_list]
    machines_sm.sort(key=lambda r: (r.get("hourly_rate_usd_per_hr") or 1e9))

    # Tools: group by tool_type, keep a few examples per type.
    tools_list: list[dict] = []
    if isinstance(tools_in, dict):
        for tid, row in tools_in.items():
            if isinstance(row, dict):
                tools_list.append({**row, "_id": tid})
    elif isinstance(tools_in, list):
        tools_list = [r for r in tools_in if isinstance(r, dict)]

    by_type: dict[str, list[dict]] = {}
    for t in tools_list:
        ttype = str((t.get("tool_type") or t.get("type") or "Other")).strip()
        by_type.setdefault(ttype, []).append({
            "tool_id":       t.get("_id") or t.get("id") or t.get("tool_id"),
            "tool_name":     t.get("tool_name") or t.get("name"),
            "diameter_mm":   t.get("diameter_mm"),
            "flute_count":   t.get("flute_count") or t.get("flute_no"),
            "tool_dimensions": t.get("tool_dimensions"),
            "rpm_min":       t.get("recommended_rpm_min"),
            "rpm_max":       t.get("recommended_rpm_max"),
            "feed_min":      t.get("recommended_feed_min_mm_per_min"),
            "feed_max":      t.get("recommended_feed_max_mm_per_min"),
            "cost_usd":      t.get("cost_usd"),
            "tool_life_min": t.get("tool_life_minutes") or t.get("tool_life_min"),
        })
    # Sort examples within each type by diameter ASC for predictability.
    for ttype, rows in by_type.items():
        rows.sort(key=lambda r: (r.get("diameter_mm") or 1e9))
    tools_sm = {
        ttype: {
            "count":    len(rows),
            "examples": rows[:8],
        }
        for ttype, rows in sorted(by_type.items())
    }

    # Materials: dict {name→[rows]} or list — flatten to a short list.
    materials_flat: list[dict] = []
    if isinstance(materials_in, dict):
        for name, group in materials_in.items():
            if isinstance(group, list):
                for row in group:
                    if isinstance(row, dict):
                        materials_flat.append({**row, "_name": name})
            elif isinstance(group, dict):
                materials_flat.append({**group, "_name": name})
    elif isinstance(materials_in, list):
        materials_flat = [r for r in materials_in if isinstance(r, dict)]

    materials_sm = [
        {
            "material_id":         m.get("id") or m.get("material_id"),
            "name":                m.get("material_name") or m.get("name") or m.get("_name"),
            "form":                m.get("material_form") or m.get("stock_form"),
            "cost_per_stock_usd":  m.get("cost_per_stock_usd") or m.get("cost_usd_per_kg"),
        }
        for m in materials_flat
    ][:30]

    return {
        "available":   True,
        "machines":    machines_sm,
        "tool_types":  tools_sm,
        "labor_rates": labor_in,
        "materials":   materials_sm,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_user_prompt(
    drawing: dict,
    component: dict,
    *,
    analogues: list[dict],
    patterns: list[dict] | None = None,
    catalog: dict | None = None,
    batch_size: int = 1,
) -> str:
    """Assemble the per-component user message.

    Parameters
    ----------
    drawing:
        ``DrawingExtraction.as_dict()`` from Engine 1.
    component:
        One entry from ``AssemblyData.components`` (BOM-mapped).
    analogues:
        Rows from :func:`server.engines.rag.retriever.retrieve_analogues`.
    patterns:
        Optional rows from :func:`retrieve_patterns`. Only include when
        analogues are weak — the prompt gets noisy otherwise.
    catalog:
        Per-user shop catalog dict from ``fetch_shop_catalog``.
    batch_size:
        Lot size — affects setup amortization downstream.
    """
    inputs = {
        "material":     drawing.get("material"),
        "part_number":  drawing.get("part_number"),
        "qty_per_lot":  batch_size,
        "component":    _component_summary(component),
    }

    if analogues:
        analogue_block = "\n\n".join(
            _render_analogue(row, i + 1) for i, row in enumerate(analogues)
        )
        # Quick coverage note so the model knows whether to trust them.
        target_fam = (component.get("material_family") or "").lower()
        target_pt = (component.get("part_type") or "").lower()
        same_fam = sum(
            1 for r in analogues
            if str(r.get("material_family") or "").lower() == target_fam and target_fam
        )
        same_pt = sum(
            1 for r in analogues
            if str(r.get("part_type") or "").lower() == target_pt and target_pt
        )
        fallback_count = sum(1 for r in analogues if r.get("_filter_fallback"))
        coverage = (
            f"_{len(analogues)} analogue(s) retrieved · "
            f"{same_fam} same material_family · "
            f"{same_pt} same part_type"
        )
        if fallback_count:
            coverage += f" · {fallback_count} via filter-fallback (lower confidence)"
        analogue_section = (
            "## Retrieved analogues (top-K by descriptor cosine similarity)\n\n"
            + coverage + "\n\n"
            + analogue_block
        )
    else:
        analogue_section = (
            "## Retrieved analogues\n\n"
            "_No analogues were retrieved — flag this in your rationale and "
            "use the pattern chunks / your training prior. Lower confidence "
            "expected._"
        )

    if patterns:
        pattern_block = "\n\n".join(
            _render_pattern(row, i + 1) for i, row in enumerate(patterns)
        )
        pattern_section = "## Pattern chunks (used because analogue coverage is weak)\n\n" + pattern_block
    else:
        pattern_section = ""

    catalog_summary = _summarize_catalog(catalog)
    catalog_section = (
        "## Per-user shop catalog (use these machines & tools when picking IDs)\n\n"
        "```json\n"
        + json.dumps(catalog_summary, indent=2, default=str)
        + "\n```"
    )

    sections = [
        "# Plan the manufacturing for one component",
        "## Inputs\n\n```json\n" + json.dumps(inputs, indent=2, ensure_ascii=False, default=str) + "\n```",
        analogue_section,
    ]
    if pattern_section:
        sections.append(pattern_section)
    sections.append(catalog_section)
    sections.append(
        "## Reminder\n\n"
        "Respond with exactly one JSON object conforming to the schema in "
        "the system message. No prose. No markdown fence. Every feature in "
        "`inputs.component.features` MUST appear in at least one operation's "
        "`feature_ids`. Begin now."
    )

    return "\n\n".join(sections)


__all__ = ["build_user_prompt"]
