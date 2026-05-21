"""Build the natural-language descriptor we embed for each analogue part.

One vector per part. The descriptor is the only thing the retriever
matches against, so it has to capture the part's machining signature in
~200-300 tokens.

Composition order
-----------------
  1. One-line identity      (part_number, rev, material, part_type)
  2. Geometry / stock       (envelope, stock form, removal volume)
  3. Footprint              (n_features, n_ops, n_tools)
  4. Routing                (per-op summary from operations.csv)
  5. Economics              (cycle time, setup hours, cost/quote)
  6. Analogue notes         (verbatim from parts/<pn>.md when present)
  7. Free-form operator notes from parts.csv

The block is deliberately structured-prose rather than JSON — embedding
models like cohesive sentences more than key/value soup.
"""
from __future__ import annotations

import logging

from .parts_loader import PartRecord, extract_md_section

logger = logging.getLogger("cncserver.engines.rag.ingestion.descriptors")


def _fmt_money(value, currency: str) -> str:
    if value is None:
        return "—"
    return f"{currency} {value:.2f}"


def _fmt_min(value) -> str:
    if value is None:
        return "—"
    return f"{value:.1f} min/pc"


def _fmt_hr(value) -> str:
    if value is None:
        return "—"
    return f"{value:.2f} hr/lot"


def _op_line(row: dict) -> str:
    """One line per operation row from operations.csv."""
    seq = (row.get("seq_index") or row.get("op") or "?").strip() if isinstance(row.get("seq_index"), str) else row.get("seq_index") or row.get("op") or "?"
    op_id = row.get("op", "")
    machine = (row.get("machine") or "").strip()
    feature = (row.get("feature") or "").strip()
    op_type = (row.get("operation_type") or "").strip()
    run_act = (row.get("run_min_pc_act") or "").strip()
    run_est = (row.get("run_min_pc_est") or "").strip()
    n_tools = (row.get("n_tools") or "").strip()
    parts = [f"OP{op_id}"]
    if machine:
        parts.append(f"@ {machine}")
    if op_type and op_type.lower() not in ("", "none"):
        parts.append(f"({op_type})")
    if feature:
        parts.append(f"— {feature}")
    if run_act:
        parts.append(f"[{run_act} min/pc act]")
    elif run_est:
        parts.append(f"[{run_est} min/pc est]")
    if n_tools:
        parts.append(f"{n_tools} tools")
    return " ".join(parts)


def build_descriptor(record: PartRecord) -> str:
    """Compose the embedded descriptor for one part.

    Caps each section so the overall blob stays ~1500-2500 chars (well
    under any embedding-model token cap).
    """
    row = record.parts_row
    lines: list[str] = []

    # 1. Identity
    title = f"Part {record.part_number}"
    if record.rev:
        title += f" rev {record.rev}"
    desc = (row.get("notes") or "").strip()
    if desc:
        title += " — " + desc.split(";")[0].strip()[:120]
    lines.append(title)

    # 2. Classification
    cls_bits = [
        record.complexity_class or "?",
        record.material or "?",
        f"({record.material_family})" if record.material_family != "unknown" else "",
        record.part_type or "?",
    ]
    lines.append("Class/material/type: " + " · ".join(b for b in cls_bits if b))

    # 3. Geometry
    geom_bits = []
    if record.envelope_mm:
        geom_bits.append(f"envelope {record.envelope_mm}")
    if record.bbox_volume_mm3:
        geom_bits.append(f"~{record.bbox_volume_mm3:,.0f} mm³ bbox")
    if record.stock_form:
        geom_bits.append(f"stock {record.stock_form}")
    if row.get("stock_size"):
        geom_bits.append(f"({row['stock_size'].strip()})")
    if row.get("removal_cc"):
        geom_bits.append(f"removal {row['removal_cc'].strip()} cc")
    if geom_bits:
        lines.append("Geometry: " + "; ".join(geom_bits))

    # 4. Footprint
    fp_bits = []
    if record.n_features is not None:
        fp_bits.append(f"{record.n_features} features")
    if record.n_ops is not None:
        fp_bits.append(f"{record.n_ops} ops")
    if record.n_tools is not None:
        fp_bits.append(f"~{record.n_tools} tools")
    machines = (row.get("machines") or "").strip()
    if machines:
        fp_bits.append(f"on [{machines}]")
    if fp_bits:
        lines.append("Footprint: " + ", ".join(fp_bits))

    # 5. Routing — one line per op (capped to 8 ops to keep size sane)
    if record.operations:
        lines.append("Routing:")
        for op_row in record.operations[:8]:
            lines.append("  - " + _op_line(op_row))
        if len(record.operations) > 8:
            lines.append(f"  - … ({len(record.operations) - 8} more ops)")

    # 6. Economics
    econ_bits = [
        f"cycle {_fmt_min(record.total_run_min_pc)}",
        f"setup {_fmt_hr(record.total_setup_hr)}",
        f"actual cost {_fmt_money(record.cost_ea_act, record.currency)}/pc",
        f"quote {_fmt_money(record.unit_price, record.currency)}/pc",
    ]
    lines.append("Economics: " + " · ".join(econ_bits))

    # 7. Analogue notes from the MD
    if record.markdown:
        notes = extract_md_section(record.markdown, "analogue notes", max_chars=600)
        if notes:
            lines.append("Analogue notes: " + _flatten(notes))
        else:
            identity = extract_md_section(record.markdown, "identity", max_chars=400)
            if identity:
                lines.append("Identity (MD): " + _flatten(identity))

    # 8. Operator notes from CSV
    op_notes = (row.get("notes") or "").strip()
    if op_notes:
        lines.append("Operator notes: " + op_notes[:400])

    return "\n".join(lines)


def _flatten(text: str) -> str:
    """Collapse markdown bullets + line breaks into a single line of prose."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or line.startswith("```"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        out.append(line)
    return " ".join(out)[:700]


__all__ = ["build_descriptor"]
