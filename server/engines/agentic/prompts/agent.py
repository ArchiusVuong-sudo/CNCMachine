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
                "PACK_CLEAN | OUTSIDE_VENDOR"
            ),
            "operation_type": (
                "Roughing | Finishing | null — only set for material-removal ops; "
                "null for DRILL/TAP/DEBUR/INSPECT/CHAMFER/FACE/TURN/PARTOFF/THREAD/"
                "ADMIN_*/ASSY_*/INSP_*/PACK_*/OUTSIDE_VENDOR"
            ),
            "description": "one short sentence",
            "feature_ids": ["<feature id from component.features>", "..."],
            "machine_class": "echoed from top-level machine_class",
            "setup_min_per_lot": "number — total lot-setup time amortized later",
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
    "setup_min_per_lot": "number — total lot-setup across all operations",
    "rationale": (
        "2-4 sentences explaining the plan at a high level — machine choice, "
        "op strategy, and any caveats (e.g. plastic heat limits, tool length derate)"
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


def _component_summary(component: dict) -> dict:
    """Project the component dict down to the fields the agent actually needs.

    Keeps the user message small and focused. Pulls in the full feature
    list (the agent needs every feature_id to satisfy the cover-every-
    feature rule) but drops noisy debug fields.
    """
    bbox = component.get("bbox") or component.get("bounding_box") or {}
    features = component.get("features") or []
    feature_type_counts: dict[str, int] = {}
    for f in features:
        ft = (f or {}).get("type") or (f or {}).get("feature_type") or "unknown"
        feature_type_counts[ft] = feature_type_counts.get(ft, 0) + 1
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
        "features": features,
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
    """
    inputs = {
        "material": drawing.get("material"),
        "part_number": drawing.get("part_number"),
        "qty_per_lot": batch_size,
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

Begin now.
"""


__all__ = ["OUTPUT_SCHEMA", "build_agent_user_message"]
