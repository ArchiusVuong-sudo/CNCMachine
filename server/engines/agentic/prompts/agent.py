"""Unified user-message builder for the single-loop agentic engine.

Replaces the four phase-specific prompts. The system message
(:func:`server.engines.agentic.prompts.system.build_system_prompt`)
carries the role, protocol, workspace contract, hard rules, and tool
catalog. This file only carries the *per-component* inputs and the full
output schema.

Resume hint
-----------
The coordinator does a ``workspace_list()`` before invoking the agent
and passes the result into the prompt so the agent's first turn can
distinguish "fresh component" from "resuming after interrupt".
"""
from __future__ import annotations

import json
from typing import Any

OUTPUT_SCHEMA: dict[str, Any] = {
    "machine_class": (
        "vmc_3_axis | vmc_3_axis_well_behaved | vmc_4_axis | vmc_5_axis | "
        "router | turn_mill | lathe"
    ),
    "top_machines": [
        {
            "rank": "1..3",
            "machine_id": "string from catalog",
            "machine_name": "string",
            "score": "0.0..1.0",
            "burden_rate_usd_per_hr": "number",
            "reason": "one short sentence",
        }
    ],
    "chosen_machine_id": "machine_id of rank-1 — used as the default downstream",
    "operations": [
        {
            "sequence": "10, 20, 30, ... (multiples of 10)",
            "op_code": (
                # CNC milling (subtractive — features-driven)
                "CNCM_ROUGH | CNCM_FINISH | CNCM_DRILL | CNCM_TAP | CNCM_CHAMFER | "
                "CNCM_PROFILE_ENGRAVE | CNCM_PROFILE_HOLES | "
                # CNC turning
                "CNCT_FACE | CNCT_TURN | CNCT_PARTOFF | CNCT_THREAD | "
                # Bench / secondary
                "DEBUR | INSP_COMPONENT | INSP_FINAL_FIXED_LOT | "
                # Admin (per-job overhead; runs once at quote-tier setup)
                "ADMIN_PLANNING | ADMIN_PRINT | ADMIN_MAT_PICK | ADMIN_STAGING | "
                # Assembly / weld / pack — for assembly_top components
                "ASSY_HARDWARE_INSTALL | ASSY_SOLVENT_BOND | "
                "ASSY_WELD_PVC | ASSY_WELD_METAL | "
                # Part marking (ink/laser/rubber-stamp/silkscreen/serialize —
                # a bench secondary op, NOT the CNC feature CNCM_PROFILE_ENGRAVE)
                "MARK_PART | "
                "PACK_CLEAN | OUTSIDE_VENDOR"
            ),
            "operation_type": (
                "Roughing | Finishing | null — only set for material-removal ops; "
                "null for DRILL/TAP/DEBUR/INSPECT/CHAMFER/FACE/TURN/PARTOFF/THREAD/"
                "ADMIN_*/ASSY_*/MARK_PART/INSP_*/PACK_*/OUTSIDE_VENDOR"
            ),
            "description": "one short sentence",
            "feature_ids": ["<feature id from component.features>", "..."],
            "machine_class": "echoed from top-level machine_class",
            "setup_min_per_lot": "0 — setup is a fixed system constant; do not model it",
            "run_min_per_part": (
                "number — per-piece run minutes for this op. REQUIRED for "
                "non-CNC ops (admin/assy/insp/pack/vendor) because they don't "
                "have feeds/speeds. For CNC ops, this can be 0 and will be "
                "computed from tool cycle times in parameters_per_operation."
            ),
            "fixed_hrs_per_lot": (
                "number — for INSP_FINAL_FIXED_LOT only: the lot-fixed hours "
                "block amortized across qty. Leave null for everything else."
            ),
            "notes": "optional",
        }
    ],
    "tools_per_operation": [
        {
            "op_sequence": "echoed from operations[].sequence",
            "tools": [
                {
                    "feature_ids": ["<feature ids this tool cuts>"],
                    "tool_type": "End Mill | Chamfer Mill | Ball Mill | Face Mill | Drill | Thread Mill | Form Tool | Radius Mill | Slitting Saw | Dovetail",
                    "dimensions": {
                        "diameter_mm": "number — governing dim",
                        "length_mm": "number or null",
                        "width_mm": "number or null (Slitting Saw / Form Tool / Dovetail only)",
                        "height_mm": "number or null (Slitting Saw / Form Tool / Dovetail only)",
                        "corner_radius_mm": (
                            "number or null — Ball Mill = diameter/2, Radius Mill = "
                            "user-spec'd R, 0 for sharp End Mill, null otherwise"
                        ),
                    },
                    "flute_no": "integer — plastics 2-3, aluminum 3, steel 4 default",
                    "tool_id": "string from catalog OR null when no match",
                    "tool_name": "human-readable tag for the UI",
                    "material_constraint": "plastics | metals | both",
                    "coating": "uncoated | TiAlN | DLC | ...",
                    "would_need_to_buy": "true | false",
                    "reason": "one short sentence",
                }
            ],
        }
    ],
    "parameters_per_operation": [
        {
            "op_sequence": "echoed from operations[].sequence",
            "machine_class": "echoed from top-level machine_class",
            "operation_type": "echoed from operations[].operation_type",
            "tools": [
                {
                    "feature_ids": ["<echoed>"],
                    "tool_id": "<echoed from tools_per_operation>",
                    "tool_type": "<echoed>",
                    "dimensions": "<echoed full dimensions dict>",
                    "flute_no": "<echoed>",
                    "spindle_speed_rpm": "number",
                    "feed_rate_mm_min": "number",
                    "stepover_mm": "number — typically 0.3*D to 0.5*D",
                    "stepdown_mm": "number — typically 0.5*D to 1.0*D (plastics <= 0.5*D)",
                    "nc_minutes_raw_est": "number — raw NC-estimator minutes before calibration",
                    "cycle_time_min_calibrated": "number — output of compute_cycle_time",
                    "rationale": "one short sentence",
                }
            ],
            "op_cycle_time_min": "number — sum of this op's tool cycle times",
        }
    ],
    "total_run_min_per_part": "number — sum of all op_cycle_time_min",
    "setup_min_per_lot": "0 — fixed system constant; not modeled by the agent",
    "rationale": (
        "2-4 sentences explaining the plan at a high level — machine choice, "
        "op strategy, and any caveats (e.g. plastic heat limits, tool length derate)"
    ),
    "family_coverage": (
        "object mapping each of {PLANNING, PRINT, MATPICK, MACHINING, DEBUR, "
        "ASSY, MARKING, INSP, PACK} to either a comma-separated list of "
        "operation sequence numbers covering that family, or the string "
        "\"MISSING\". Required — see Pre-submission op-family checklist in the "
        "user message."
    ),
    "family_coverage_reasons": (
        "object — for each family marked MISSING above, a one-line reason. "
        "Omit for families that are covered."
    ),
    "evidence": [
        (
            "Tokens grounding the plan. Use the grammar from AGENT.md: "
            "kb:<path> | csv:<file>[#row=N] | catalog:<table>/<id> | "
            "analogue:<part_number>. At least one analogue:<part_number> "
            "token is required whenever you called kb_adopt_routing or "
            "kb_find_analogues; one or more kb: tokens otherwise."
        )
    ],
    "confidence_band_pct": (
        "number 0..50 — your honest ±% band on the cycle time. Anchored to "
        "an analogue with score ≥ 5 → 10-15. Anchored to a weaker analogue "
        "(score 3-4) → 18-22. No analogue used (first-principles only) → "
        "25-35. State the reason in `rationale`."
    ),
}


def _slim_feature(f: dict) -> dict:
    """Compact per-feature projection for the prompt.

    Keeps only the fields the agent needs to (a) cover the feature in an
    operation's ``feature_ids`` and (b) size a tool / route a finish-vs-rough
    op: ``feature_id``, ``type``, governing ``dimensions``, the tolerance
    band, and thread info. Drops bulky / redundant fields — ``key_face_ids``,
    ``perimeter_mm``, ``location``, ``gdt_callouts`` (already aggregated into
    the component-level GD&T digest), ``operations``, and provenance
    (``source`` / ``confidence`` / ``count``). On feature-heavy parts (100+
    features) the full dicts blew the user message past the 32K context
    window; this roughly halves per-feature size while preserving every
    ``feature_id`` so the cover-every-feature rule still holds.
    """
    ff = f or {}
    out: dict[str, Any] = {
        "feature_id": ff.get("feature_id"),
        "type": ff.get("type") or ff.get("feature_type"),
    }
    dims = ff.get("dimensions")
    if dims is not None:
        out["dimensions"] = dims
    for k in ("tolerance_plus", "tolerance_minus", "is_threaded", "thread_spec"):
        v = ff.get(k)
        if v is not None:
            out[k] = v
    return out


def _component_summary(component: dict) -> dict:
    """Project the component dict down to the fields the agent actually needs.

    Keeps the user message small and focused. Carries every feature (slimmed
    to its essential fields via :func:`_slim_feature` so the agent still has
    every feature_id for the cover-every-feature rule) plus the aggregated
    tolerance / GD&T / thread digests, and drops noisy debug fields.
    """
    bbox = component.get("bbox") or component.get("bounding_box") or {}
    features = component.get("features") or []
    feature_type_counts: dict[str, int] = {}
    # Brief Page 4 — "Specs & Tolerances" and "GD&T" are mandatory factors
    # the AI Model must consider. Aggregate them into a structured digest
    # the agent can scan in O(1) instead of crawling every feature dict.
    tightest_tol_mm: float | None = None
    n_features_toleranced = 0
    n_features_gdt = 0
    n_features_threaded = 0
    gdt_symbols: list[str] = []
    thread_specs: list[str] = []
    for f in features:
        ff = f or {}
        ft = ff.get("type") or ff.get("feature_type") or "unknown"
        feature_type_counts[ft] = feature_type_counts.get(ft, 0) + 1
        tp, tm = ff.get("tolerance_plus"), ff.get("tolerance_minus")
        tol_band: float | None = None
        if isinstance(tp, (int, float)) and isinstance(tm, (int, float)):
            tol_band = float(tp) + float(tm)  # full bilateral band
        elif isinstance(tp, (int, float)):
            tol_band = float(tp)
        elif isinstance(tm, (int, float)):
            tol_band = float(tm)
        if tol_band is not None:
            n_features_toleranced += 1
            if tightest_tol_mm is None or tol_band < tightest_tol_mm:
                tightest_tol_mm = tol_band
        gdt = ff.get("gdt_callouts") or []
        if gdt:
            n_features_gdt += 1
            for c in gdt:
                if isinstance(c, str) and c.strip():
                    gdt_symbols.append(c.strip())
        if ff.get("is_threaded") or ff.get("thread_spec"):
            n_features_threaded += 1
            ts = ff.get("thread_spec")
            if isinstance(ts, str) and ts.strip():
                thread_specs.append(ts.strip())
    # Fold in component-level fallbacks (dim_tagger writes here when a
    # GD&T / thread callout did NOT match any feature geometrically — eg
    # composite position true-position callouts with no nominal value).
    for c in component.get("gdt_callouts") or []:
        if isinstance(c, str) and c.strip():
            gdt_symbols.append(c.strip())
    for t in component.get("threads") or []:
        if isinstance(t, dict):
            spec = t.get("spec") or t.get("label")
            if isinstance(spec, str) and spec.strip():
                thread_specs.append(spec.strip())
                n_features_threaded += 1
    summary = {
        "component_index": component.get("component_index"),
        "name": component.get("name"),
        "part_type": component.get("part_type"),
        "bom_part_type": component.get("bom_part_type"),
        "component_role": component.get("component_role"),
        "component_role_reason": component.get("component_role_reason"),
        "orientation": component.get("orientation"),
        "instance_count": component.get("instance_count", 1),
        "volume_mm3": component.get("volume_mm3"),
        "envelope_mm": bbox if isinstance(bbox, dict) else None,
        "n_features": len(features),
        "feature_type_counts": feature_type_counts,
        # Brief Page 4 — Specs & Tolerances digest. Tightest band drives
        # process selection (finish vs rough), inspector burden, and
        # machine class (router vs VMC). Counts surface scope.
        "tolerances": {
            "n_features_toleranced": n_features_toleranced,
            "tightest_total_band_mm": (
                round(tightest_tol_mm, 4) if tightest_tol_mm is not None else None
            ),
        },
        # Brief Page 4 — GD&T digest. Symbols verbatim so the agent can
        # spot position/profile/perpendicularity etc. and book INSP burden.
        "gdt": {
            "n_features_with_gdt": n_features_gdt,
            "callouts": gdt_symbols[:20],  # cap to keep prompt small
        },
        # Brief Page 5 mitigation — thread mapping. Surface thread specs
        # so Phase B routes a TAPPING op and Phase C picks the tap.
        "threads": {
            "n_threaded_features": n_features_threaded,
            "specs": list(dict.fromkeys(thread_specs))[:20],
        },
        "features": [_slim_feature(f) for f in features],
    }
    # Synthetic assembly_top components carry an assembly_hint block that
    # tells the agent which sub-items / hardware to plan ADMIN + ASSY + WELD
    # + INSP_FINAL + PACK ops around. Pass it through verbatim.
    if component.get("assembly_hint"):
        summary["assembly_hint"] = component["assembly_hint"]
    return summary


def build_agent_user_message(
    drawing: dict,
    component: dict,
    *,
    batch_size: int = 1,
    workspace_files: list[str] | None = None,
    assembly_top_present: bool = False,
    is_only_planned_component: bool = True,
) -> str:
    """Build the per-component user message.

    Parameters
    ----------
    drawing:
        ``DrawingExtraction.as_dict()`` from Engine 1.
    component:
        One entry from ``AssemblyData.components`` (already enriched with
        BOM mapping by the coordinator).
    batch_size:
        Lot size — affects setup amortization downstream.
    workspace_files:
        Result of ``workspace.list_files()`` from the coordinator. If
        non-empty, the prompt flags it as a resume scenario so the
        agent's first move is to read the checkpoints rather than start
        from scratch.
    assembly_top_present:
        True when the coordinator has synthesized an ``assembly_top``
        component. Combined with ``is_only_planned_component`` and
        ``component_role`` this tells the agent whether it owns the
        assembly-scope ops (ADMIN_*, PACK_CLEAN, INSP_FINAL_FIXED_LOT,
        ASSY_*) or must stay silent on them. See the "Assembly-scope
        ops" rule in the system prompt.
    is_only_planned_component:
        True when exactly ONE component in this job goes through the
        agent (others were short-circuited as hardware/outside_vendor
        and no assembly_top was synthesized). Lets the lone machining
        component own ADMIN_PLANNING + PACK_CLEAN without duplication.
    """
    inputs = {
        "material": drawing.get("material"),
        "part_number": drawing.get("part_number"),
        # Brief Page 3 OCR outputs — drawing-level "category" (weldment /
        # assembly_bolted / sheet_metal / cnc_milling / ...) and "mfg spec"
        # (assembly_method = welded / bolted / riveted / bonded). Drives
        # whether the planner routes through ASSY_WELD_* / ASSY_SOLVENT_BOND
        # / ASSY_HARDWARE_INSTALL on the top assembly node.
        "drawing_part_category": drawing.get("part_category"),
        "drawing_assembly_method": drawing.get("assembly_method"),
        "qty_per_lot": batch_size,
        "dispatch": {
            "assembly_top_present":       bool(assembly_top_present),
            "is_only_planned_component":  bool(is_only_planned_component),
            "component_role":             component.get("component_role"),
        },
        "component": _component_summary(component),
    }

    files = workspace_files or []
    if files:
        resume_block = (
            "## Resume hint\n\n"
            "An earlier run wrote these files into your workspace — you are "
            "RESUMING, not starting fresh:\n\n"
            "```json\n"
            f"{json.dumps(files, indent=2)}\n"
            "```\n\n"
            "Your FIRST action must be to `workspace_read` each file and "
            "rehydrate your state before any other tool calls."
        )
    else:
        resume_block = (
            "## Resume hint\n\n"
            "Your workspace is empty — fresh component. Begin by inspecting "
            "the inputs below; consult the shop catalog and KB analogues as "
            "needed; checkpoint to the workspace after each major decision."
        )

    return f"""\
# Plan the manufacturing for one component

## Inputs

```json
{json.dumps(inputs, indent=2, ensure_ascii=False, default=str)}
```

{resume_block}

## Output

When the plan is complete, respond with one JSON object using the `final`
shape. The value of `final` MUST conform to this schema:

```json
{json.dumps(OUTPUT_SCHEMA, indent=2)}
```

Every feature in `inputs.component.features` MUST appear in at least one
operation's `feature_ids`. Every tool in `tools_per_operation` MUST be
echoed in `parameters_per_operation` with its feeds/speeds set.

## Pre-submission op-family checklist

Before you emit `final`, walk this 9-family checklist. For each family,
either point to the `sequence` number(s) you emit for it, or — only if
truly inapplicable — set `family_coverage[<family>] = "MISSING"` AND
write a one-line reason in `family_coverage_reasons[<family>]`. A
`MISSING` entry is allowed, but must be justified; silent omissions are
the most common v3 failure mode.

The 9 families (customer shop convention — see
`KNOWLEDGE_BASE/patterns/setup_and_material.md` §4a):

  1. **PLANNING**  → `ADMIN_PLANNING`
  2. **PRINT**     → `ADMIN_PRINT`
  3. **MATPICK**   → `ADMIN_MAT_PICK`
  4. **MACHINING** → any `CNCM_*` / `CNCT_*` op (or `OUTSIDE_VENDOR` for
                     waterjet / laser / outside processes)
  5. **DEBUR**     → `DEBUR`
  6. **ASSY**      → any `ASSY_*` op (hardware install / bonding / weld).
                     If the BOM or `material` string lists installed
                     hardware (insert, helicoil, dowel pin, captive screw,
                     PEM/press insert, standoff), emit
                     `ASSY_HARDWARE_INSTALL` with run ≈2–4 min per piece
                     (minimum 6). **If `component_role == "assembly_top"`**:
                     first `kb_adopt_routing` a measured weldment/assembly
                     analogue and carry its ASSY/WELD run-minutes; if
                     `assembly_hint.welding_required` is true you MUST emit a
                     weld op (`ASSY_WELD_PVC`/`ASSY_WELD_METAL`) — it may NOT
                     be `MISSING`. A welded assembly that ships with zero
                     weld/assembly run-minutes is the dominant under-quote.
  7. **MARKING**   → `MARK_PART` — emit ONLY when the part is marked for
                     identification: part-marking, serialization, ink/laser/
                     rubber-stamp, silkscreen, or vibro-peen. If your adopted
                     analogue routing has a part-mark / stamp / engrave-ID
                     row, KEEP it as `MARK_PART`. Most parts have no marking
                     op → `MISSING` is the common, acceptable case here.
                     (Do NOT confuse with `CNCM_PROFILE_ENGRAVE`, which is a
                     CNC-milled engraved feature counted under MACHINING.)
  8. **INSP**      → `INSP_COMPONENT` (inspect this part) and
                     `INSP_FINAL_FIXED_LOT` (always — the lot final-
                     inspection block, owned by the assembly_top owner).
  9. **PACK**      → `PACK_CLEAN`

Default expectation: every shipped part touches every family. Common
genuine `MISSING` cases (acceptable justifications):
- PLANNING / PRINT / MATPICK / STAGING / INSP_FINAL / PACK on a
  sub-component when `assembly_top_present == true` and your
  `component_role != "assembly_top"` (assembly-scope ops are owned by
  the assembly_top owner — see the assembly-scope-ops rule).
- ASSY on a singleton with **zero** BOM hardware and no inserts/dowels.
  (If ANY installed hardware is present, ASSY is required — not MISSING.)
- MARKING on any part whose drawing/analogue routing shows no part-mark,
  serialize, stamp, or silkscreen step (the common case).
- DEBUR on a bought-stock part with no machined edges (rare).

**Run-time reminder (before `final`):** `setup_min_per_lot` is a fixed
system constant — set it to 0 and do not reason about it. Spend your
effort on `run_min_per_part`: the per-feature machining time plus the
non-CNC run (admin, assembly, weld, inspection, pack). Anchor it to a
measured analogue whenever one is available.

Emit the checklist as two top-level fields next to `rationale`:

```json
"family_coverage": {{
  "PLANNING": "10", "PRINT": "20", "MATPICK": "30",
  "MACHINING": "40,50", "DEBUR": "60",
  "ASSY": "MISSING", "MARKING": "MISSING", "INSP": "70", "PACK": "80"
}},
"family_coverage_reasons": {{
  "ASSY": "Singleton PEEK spacer, BOM has no hardware",
  "MARKING": "Drawing specifies no part-marking or serialization"
}}
```

Begin now.
"""


__all__ = ["OUTPUT_SCHEMA", "build_agent_user_message"]
