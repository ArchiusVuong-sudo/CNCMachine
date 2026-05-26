"""Analogue-adoption tool — convert a KB part page into agent OUTPUT_SCHEMA.

The agent looks up nearby analogues with :func:`kb_find_analogues` and, if
a good match exists, *adopts* that part's routing rather than reasoning a
new one from scratch. This file parses the markdown table in
``KNOWLEDGE_BASE/parts/<part_number>.md`` into the
``{operations: [...], total_run_min_per_part, setup_min_per_lot}`` shape
the agent emits as its final answer.

Parsing is intentionally tolerant — KB pages are hand-curated and have
small format variations (column order, blank cells, ranges, FixedHrs vs
Min/Part vs Hrs/Part). The tool extracts what it can and surfaces gaps
in ``warnings`` so the agent can patch them.

Returns ``{"error": "..."}`` on any failure (file missing, no routing
table found) so the agent loop can keep going.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from .citation import citation_hint_for_kb
from .kb import KB_ROOT, _safe_kb_path, build_holdout_set, normalize_part_id

logger = logging.getLogger("cncserver.engines.agentic.tools.analogue")


# ---------------------------------------------------------------------------
# OP-row → canonical op_code (matches the expanded vocabulary in
# server.engines.agentic.coordinator)
# ---------------------------------------------------------------------------

# Order matters: more-specific keywords first.
_OP_CODE_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"weld(?:ing)?.*pvc|pvc.*weld",                  re.I), "ASSY_WELD_PVC"),
    (re.compile(r"weld(?:ing)?",                                 re.I), "ASSY_WELD_METAL"),
    (re.compile(r"bond",                                         re.I), "ASSY_SOLVENT_BOND"),
    # Hardware-install ops. Includes named fasteners that carry no generic
    # "install hardware"/"insert" token (helicoil, trisert/speedsert, keensert,
    # captive screw) plus "<fastener> install" / "install <fastener>" phrasings.
    # Unambiguous hardware names match anywhere; bare dowel/pin/screw/stud only
    # count as assembly when paired with an install verb (so "drill dowel holes"
    # stays a machining op).
    (re.compile(r"install\s+hardware|hardware\s+install|\binsert\b|"
                r"helicoil|heli-coil|tri-?sert|speed-?sert|keen-?sert|pem-?sert|"
                r"captive\s*screw|"
                r"install\b.*\b(?:dowel|pin|screw|stud|standoff|fastener|bushing)|"
                r"\b(?:dowel|pin|screw|stud|standoff|fastener|bushing)\b.*\binstall",
                re.I), "ASSY_HARDWARE_INSTALL"),
    # Generic assembly / sub-assembly that isn't weld / bond / hardware-install
    # (e.g. "Window assembly" on machine ASSY2). Must follow the specific
    # assembly patterns above so they win, and precede the CNC fallbacks below
    # so a bare "assembly" row doesn't drop into the CNCM_FINISH catch-all.
    (re.compile(r"\bassembl|sub-?assembl|\bassy\d*\b",           re.I), "ASSY_GENERAL"),
    (re.compile(r"deburr|debur",                                 re.I), "DEBUR"),
    (re.compile(r"final\s+insp",                                 re.I), "INSP_FINAL_FIXED_LOT"),
    (re.compile(r"component\s+insp|inspect",                     re.I), "INSP_COMPONENT"),
    (re.compile(r"plann?ing",                                    re.I), "ADMIN_PLANNING"),
    (re.compile(r"print\s*trav|update.*program",                 re.I), "ADMIN_PRINT"),
    (re.compile(r"pick\s*material|mat\s*pick",                   re.I), "ADMIN_MAT_PICK"),
    (re.compile(r"stag(?:e|ing)|wip",                            re.I), "ADMIN_STAGING"),
    (re.compile(r"clean.*pack|\bpack",                           re.I), "PACK_CLEAN"),
    (re.compile(r"outside\s+vendor|outsource",                   re.I), "OUTSIDE_VENDOR"),
    # Part marking (bench secondary) — must precede the CNC-engrave pattern so
    # an explicit "part mark"/"stamp"/"silkscreen"/"serialize" row is tagged
    # MARK_PART, while a bare "engrave" feature still maps to CNCM_PROFILE_ENGRAVE.
    (re.compile(r"part\s*mark|\bmark(?:ing)?\b|rubber\s*stamp|ink\s*stamp|"
                r"silk\s*screen|silkscreen|laser\s*mark|vibro|serial(?:ize)?",
                re.I), "MARK_PART"),
    (re.compile(r"mill.*profile.*engrave|engrave",               re.I), "CNCM_PROFILE_ENGRAVE"),
    (re.compile(r"mill.*profile.*(?:slot|hole)|profile.*hole",   re.I), "CNCM_PROFILE_HOLES"),
    (re.compile(r"\bturn(?:ing)?|\block",                        re.I), "CNCT_TURN"),
    (re.compile(r"\btap(?:ping)?",                               re.I), "CNCM_TAP"),
    (re.compile(r"drill(?:ing)?",                                re.I), "CNCM_DRILL"),
    (re.compile(r"chamfer",                                      re.I), "CNCM_CHAMFER"),
    (re.compile(r"finish(?:ing)?",                               re.I), "CNCM_FINISH"),
    (re.compile(r"rough(?:ing)?",                                re.I), "CNCM_ROUGH"),
    (re.compile(r"mill(?:ing)?",                                 re.I), "CNCM_FINISH"),  # last-resort mill
]


def _op_code_for_description(description: str, machine: str = "") -> str:
    """Best-guess op_code from a description + machine column."""
    blob = f"{description}  {machine}"
    for pat, code in _OP_CODE_KEYWORDS:
        if pat.search(blob):
            return code
    return "CNCM_FINISH"  # generic CNC fallback


def _to_float(s: str) -> float | None:
    """Parse a number that may be ``"0.50"``, ``"25.00"``, ``"0.10 hr"`` etc."""
    if not s:
        return None
    s = str(s).strip()
    if s in ("", "-", "—", "_not in quote_", "_unknown_"):
        return None
    # Pull the first number out (handles "0.10 hr", "25.00 min/part").
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _parse_routing_table(md_block: str) -> list[dict[str, Any]]:
    """Parse a markdown routing table into a list of op rows.

    Expects a header line containing at least: OP, Machine, Setup, Run,
    Unit, Description (in any column order). Tolerant of extra columns
    (op_id) and missing cells.
    """
    lines = [ln.rstrip() for ln in md_block.splitlines() if ln.strip()]
    if len(lines) < 3:
        return []

    # Find a header row: must contain "OP" and "Setup" (case-insensitive).
    header_idx = None
    for i, ln in enumerate(lines):
        cells = [c.strip().lower() for c in ln.strip("|").split("|")]
        if "op" in cells and any("setup" in c for c in cells):
            header_idx = i
            break
    if header_idx is None or header_idx + 2 >= len(lines):
        return []

    headers = [c.strip().lower() for c in lines[header_idx].strip("|").split("|")]
    # Skip the separator row (header_idx+1).
    rows: list[dict[str, Any]] = []
    for ln in lines[header_idx + 2:]:
        if not ln.startswith("|"):
            break
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < len(headers):
            cells = cells + [""] * (len(headers) - len(cells))
        row = dict(zip(headers, cells))
        rows.append(row)
    return rows


def _routing_blocks(md_text: str) -> dict[str, str]:
    """Split a parts/<pn>.md into named routing sections.

    Returns a dict mapping section-title → raw markdown text. The "main"
    routing is keyed as "main". Sub-item routings (under `### Item X`)
    are keyed by the heading text.
    """
    # Coarse split on `### ` headings then `## Routing`.
    out: dict[str, str] = {}
    # Find `## Routing` (the top routing) — capture until the next `## ` heading.
    m = re.search(r"^##\s+Routing[^\n]*\n(.+?)(?=^##\s+[A-Z]|\Z)", md_text,
                  re.S | re.M)
    if m:
        out["main"] = m.group(1)
    # Sub-item routings: `### Item N` … inside `## Sub-item routings`.
    sub = re.search(r"^##\s+Sub-item routings.*?\n(.+?)(?=^##\s+[A-Z]|\Z)",
                    md_text, re.S | re.M)
    if sub:
        for m2 in re.finditer(r"^###\s+(?P<title>[^\n]+)\n(?P<body>.+?)(?=^###\s+|\Z)",
                              sub.group(1), re.S | re.M):
            out[m2.group("title").strip()] = m2.group("body")
    return out


def _row_to_op(
    row: dict[str, str],
    sequence: int,
    machine_class_hint: str | None = None,
) -> dict[str, Any]:
    """Project a parsed table row into one OUTPUT_SCHEMA op dict."""
    desc = row.get("description", "") or row.get("desc", "") or ""
    machine = row.get("machine (work_center)", "") or row.get("machine", "")
    op_label = row.get("op", "") or row.get("op_id", "")
    setup_hr = _to_float(row.get("setup hr") or row.get("setup_hr") or row.get("setup"))
    rate     = _to_float(row.get("run rate") or row.get("run_rate") or row.get("rate"))
    unit     = (row.get("unit") or "").strip().lower()

    op_code = _op_code_for_description(desc, machine)
    setup_min = (setup_hr * 60) if setup_hr is not None else 0.0

    run_min_per_part: float = 0.0
    fixed_hrs_per_lot: float | None = None
    if rate is not None:
        if "fixedhrs" in unit or "fixed" in unit or "hrs/lot" in unit:
            fixed_hrs_per_lot = rate
        elif "hrs/part" in unit or "hr/part" in unit:
            run_min_per_part = rate * 60.0
        else:
            run_min_per_part = rate

    return {
        "sequence":          sequence,
        "op_code":           op_code,
        "operation_type":    None,  # set by coordinator fallback
        "description":       desc,
        "feature_ids":       [],
        "machine_class":     machine_class_hint or "router",
        "setup_min_per_lot": round(setup_min, 2),
        "run_min_per_part":  round(run_min_per_part, 3),
        "fixed_hrs_per_lot": fixed_hrs_per_lot,
        "notes":             f"adopted from analogue · op_label={op_label!r} · machine={machine!r}",
    }


def kb_adopt_routing(part_number: str, role: str | None = None) -> dict[str, Any]:
    """Load ``parts/<part_number>.md`` and return its routing in agent shape.

    Parameters
    ----------
    part_number:
        The analogue part identifier — must match a file under
        ``KNOWLEDGE_BASE/parts/<part_number>.md``.
    role:
        Optional hint: ``"main"`` (default) for the top-level routing,
        ``"sub_item_sheet"`` to return the most-detailed sub-item routing,
        ``"all"`` to return every routing block flattened together.

    Returns
    -------
    Dict with keys ``operations`` (list), ``total_run_min_per_part``,
    ``setup_min_per_lot``, ``citations`` (list of citation hints),
    ``warnings`` (list of strings), plus ``analogue_part_number`` and
    ``role_returned`` so the agent knows what it got.
    """
    safe = _safe_kb_path(f"parts/{part_number}.md")
    if safe is None or not safe.exists():
        return {"error": f"no analogue page for part_number={part_number!r}"}
    try:
        md = safe.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"parts/{part_number}.md read failed: {exc}"}

    blocks = _routing_blocks(md)
    if not blocks:
        return {"error": f"no routing tables found in parts/{part_number}.md"}

    role_norm = (role or "main").lower()
    has_sub_items = any(k.lower() != "main" for k in blocks)
    # Explicit "give me the whole quote" roles. A weldment/assembly page
    # prices the WHOLE part: its top-assembly routing PLUS each sub-item's
    # own machining routing. Adopting only the top table under-counts by the
    # sub-item machining (the 0042-83323 failure). These roles return the
    # complete routing so the assembly owner copies the entire known quote
    # verbatim in one call.
    #
    # NOTE: the bare "assembly_top" role still returns main-only (below) so
    # this change does not alter existing pipeline behavior. Switching the
    # assembly owner to "assembly_complete" must land TOGETHER with the
    # coordinator gate that suppresses the separately-decomposed sub-item
    # components — otherwise the sub-item machining is double-counted.
    _COMPLETE_ROLES = ("all", "everything", "assembly_complete", "complete")
    if role_norm in _COMPLETE_ROLES:
        chosen = list(blocks.values())
        title = "assembly_complete" if has_sub_items else "main"
    elif role_norm in ("sub_item_sheet", "sub", "subitem", "item"):
        non_main = {k: v for k, v in blocks.items() if k.lower() != "main"}
        if non_main:
            title, body = next(iter(non_main.items()))
            chosen = [body]
        else:
            chosen = [blocks["main"]]
            title = "main"
    else:
        chosen = [blocks.get("main") or next(iter(blocks.values()))]
        title = "main"

    operations: list[dict[str, Any]] = []
    seq = 10
    warnings: list[str] = []
    for body in chosen:
        rows = _parse_routing_table(body)
        if not rows:
            warnings.append("table parse returned 0 rows")
            continue
        for r in rows:
            op = _row_to_op(r, seq)
            operations.append(op)
            seq += 10

    if not operations:
        return {"error": f"could not parse any operations from parts/{part_number}.md"}

    total_run = round(sum(o.get("run_min_per_part") or 0 for o in operations), 3)
    total_setup = round(sum(o.get("setup_min_per_lot") or 0 for o in operations), 2)
    total_fixed_hr = round(
        sum(o.get("fixed_hrs_per_lot") or 0 for o in operations), 3
    )

    return {
        "analogue_part_number": part_number,
        "role_returned": title,
        "operations": operations,
        "total_run_min_per_part": total_run,
        "setup_min_per_lot": total_setup,
        "per_lot_fixed_hr_total": total_fixed_hr,
        "warnings": warnings,
        "citations": [
            citation_hint_for_kb(f"parts/{part_number}.md"),
        ],
    }


def kb_weldment_complete_routing(part_number: str) -> dict[str, Any] | None:
    """Return the COMPLETE routing for a known multi-item weldment, or None.

    Deterministic gate helper for the coordinator. A weldment/assembly KB
    page prices the WHOLE part on one sheet: the top-assembly routing PLUS one
    representative machining routing per sub-item *type* (e.g. 0042-83323
    de-dupes its four physical PVC solids into "Item 1" + "Items 2,3,4,5").
    Engine 2, by contrast, decomposes the STEP into one solid per physical
    sub-item — so left alone each sub-item solid bills its own routing and the
    weldment double-counts its machining.

    This helper returns the page's complete routing (``kb_adopt_routing`` with
    ``role='assembly_complete'``) ONLY when ``parts/<pn>.md`` exists AND carries
    a ``## Sub-item routings`` section. It returns ``None`` for a missing page
    or a single-base part (e.g. 839-323453-001, a weldment whose page has no
    sub-item routings) so the coordinator gate stays inert there.
    """
    safe = _safe_kb_path(f"parts/{part_number}.md")
    if safe is None or not safe.exists():
        return None
    try:
        md = safe.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    blocks = _routing_blocks(md)
    has_sub_items = any(k.lower() != "main" for k in blocks)
    if not has_sub_items:
        return None
    result = kb_adopt_routing(part_number, role="assembly_complete")
    if result.get("error"):
        return None
    return result


def make_holdout_aware_adopt_routing(
    holdout_part_number: str | None,
):
    """Holdout-filtered version of :func:`kb_adopt_routing`.

    Refuses to adopt the in-flight test fixture's own routing so the eval
    harness can measure pattern generalization rather than the agent
    finding its own answer key in the analogue corpus.
    """
    holdout_set = build_holdout_set(holdout_part_number)
    if not holdout_set:
        return kb_adopt_routing
    holdout = ",".join(sorted(holdout_set))  # display string for messages

    def _holdout_kb_adopt_routing(
        part_number: str, role: str | None = None,
    ) -> dict[str, Any]:
        if normalize_part_id(part_number) in holdout_set:
            return {
                "error": (
                    f"holdout: part_number={part_number!r} maps to a "
                    f"held-out test fixture (holdout set: {holdout}) — "
                    f"refusing to adopt the answer key. Pick a different analogue."
                ),
                "holdout_part_number": holdout,
            }
        return kb_adopt_routing(part_number, role)

    return _holdout_kb_adopt_routing


ANALOGUE_TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "kb_adopt_routing",
            "description": (
                "Load an analogue's routing from parts/<part_number>.md and "
                "project it into the agent's operations[] schema. Use AFTER "
                "kb_find_analogues returns a high-scoring match — copy the "
                "analogue rather than reasoning a new routing from scratch. "
                "Returns operations with op_code, setup_min_per_lot, "
                "run_min_per_part, and fixed_hrs_per_lot pre-filled. COPY "
                "these run_min_per_part values VERBATIM into your final plan "
                "— they are measured shop times. Do NOT rescale them by "
                "feature counts or governing-dim ratios; rescaling is the "
                "single largest source of cost error. Only add a brand-new op "
                "(with your own estimate) if THIS part has a feature the "
                "analogue genuinely lacks; otherwise keep every adopted "
                "number unchanged."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "Analogue part number (file under KNOWLEDGE_BASE/parts/).",
                    },
                    "role": {
                        "type": "string",
                        "description": (
                            "'main' (default) = top-level routing only; "
                            "'sub_item_sheet' = one sub-item routing; "
                            "'assembly_complete' (or 'all') = the COMPLETE "
                            "routing for a multi-item weldment/assembly — "
                            "top-assembly ops PLUS every sub-item's machining "
                            "routing, summed into one plan."
                        ),
                    },
                },
                "required": ["part_number"],
            },
        },
    },
]


__all__ = ["kb_adopt_routing", "kb_weldment_complete_routing", "ANALOGUE_TOOL_SPECS"]
