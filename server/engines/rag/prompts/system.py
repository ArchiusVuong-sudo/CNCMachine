"""System prompt for the RAG engine — engine-agnostic role + rules.

This is the static half of the prompt pair (the user message carries the
per-component inputs and retrieved analogues). Composition:

  1. Role + one-shot protocol — RAG is a SINGLE LLM call returning ONE
     JSON object. There is no tool loop, no checkpointing.
  2. Operating manual — lazy-loaded from ``KNOWLEDGE_BASE/AGENT.md`` so
     ops can tune engineering rules without restarting the server.
  3. Hard rules — the engineering constraints (feature coverage, op
     sequencing, plastics flute counts, etc.) copied verbatim from the
     agentic prompt so both engines reason from the same playbook.
  4. Output schema — exact JSON shape the model MUST emit.

Both engines load AGENT.md by-path so we don't import from the agentic
package (RAG must remain deletable on its own).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger("cncserver.engines.rag.prompts.system")

# system.py → prompts → rag → engines → server → data
_REPO_ROOT = Path(__file__).resolve().parents[4]
_AGENT_MD = (_REPO_ROOT / "KNOWLEDGE_BASE" / "AGENT.md").resolve()

_AGENT_MD_STUB = (
    "# AGENT.md (stub — file not found)\n\n"
    "Plan CNC machining for one part: pick a machine, plan operations "
    "covering every feature, select tools, set feeds/speeds, and report "
    "a calibrated per-piece cycle time."
)

_cache: dict[str, str] = {}
_cache_lock = Lock()


def _load_agent_md() -> str:
    with _cache_lock:
        if "agent_md" in _cache:
            return _cache["agent_md"]
        try:
            text = _AGENT_MD.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("AGENT.md not loadable (%s) — using stub", exc)
            text = _AGENT_MD_STUB
        _cache["agent_md"] = text
        return text


# ---------------------------------------------------------------------------
# Output schema — flat per-op shape (tools inlined)
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA: dict[str, Any] = {
    "machine_class": (
        "vmc_3_axis | vmc_3_axis_well_behaved | vmc_4_axis | vmc_5_axis | "
        "router | turn_mill | lathe"
    ),
    "top_machines": [
        {
            "rank": "1..3",
            "machine_id": "string from catalog (or null if no catalog match)",
            "machine_name": "string",
            "burden_rate_usd_per_hr": "number",
            "reason": "one short sentence",
        }
    ],
    "chosen_machine_id": "machine_id of rank-1 — used as the default downstream",
    "operations": [
        {
            "sequence": "10, 20, 30, … (multiples of 10)",
            "op_code": (
                # CNC milling
                "CNCM_ROUGH | CNCM_FINISH | CNCM_DRILL | CNCM_TAP | CNCM_CHAMFER | "
                "CNCM_PROFILE_ENGRAVE | CNCM_PROFILE_HOLES | "
                # CNC turning
                "CNCT_FACE | CNCT_TURN | CNCT_PARTOFF | CNCT_THREAD | "
                # Bench / secondary
                "DEBUR | INSP_COMPONENT | INSP_FINAL_FIXED_LOT | "
                # Admin (per-job overhead)
                "ADMIN_PLANNING | ADMIN_PRINT | ADMIN_MAT_PICK | ADMIN_STAGING | "
                # Assembly / weld / pack — for assembly_top components
                "ASSY_HARDWARE_INSTALL | ASSY_SOLVENT_BOND | "
                "ASSY_WELD_PVC | ASSY_WELD_METAL | "
                "PACK_CLEAN | OUTSIDE_VENDOR"
            ),
            "operation_type": (
                "Roughing | Finishing | null — only set for material-removal ops; "
                "null for DRILL/TAP/DEBUR/INSPECT/CHAMFER/FACE/TURN/PARTOFF/THREAD"
            ),
            "description": "one short sentence",
            "feature_ids": ["<feature id from component.features>", "..."],
            "setup_min_per_lot": "number — share of lot setup attributable to this op",
            "tools": [
                {
                    "feature_ids": ["<feature ids this tool cuts>"],
                    "tool_type": (
                        "End Mill | Chamfer Mill | Ball Mill | Face Mill | Drill | "
                        "Thread Mill | Form Tool | Radius Mill | Slitting Saw | Dovetail"
                    ),
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
                    "tool_id": (
                        "string from catalog OR null when no match — server will "
                        "snap to the nearest catalog row before costing"
                    ),
                    "tool_name": "human-readable tag for the UI",
                    "material_constraint": "plastics | metals | both",
                    "coating": "uncoated | TiAlN | DLC | ...",
                    "would_need_to_buy": "true | false",
                    "spindle_speed_rpm": "number",
                    "feed_rate_mm_min": "number",
                    "stepover_mm": "number — typically 0.3*D to 0.5*D",
                    "stepdown_mm": "number — typically 0.5*D to 1.0*D (plastics ≤ 0.5*D)",
                    "cycle_time_min": (
                        "number — your best per-piece cycle estimate for this tool. "
                        "Anchor to the analogue's measured run_min_pc scaled by the "
                        "governing-dim ratio when available"
                    ),
                    "rationale": "one short sentence",
                }
            ],
            "op_cycle_time_min": "number — sum of this op's tool cycle_time_min",
        }
    ],
    "total_run_min_per_part": "number — sum of all op_cycle_time_min",
    "setup_min_per_lot": "number — total lot-setup across all operations",
    "rationale": (
        "2-4 sentences explaining the plan at a high level — machine choice, "
        "op strategy, which analogue you anchored on, any caveats"
    ),
    "evidence": [
        "Tokens grounding the plan. Use the grammar from AGENT.md: "
        "kb:<path> | csv:<file>[#row=N] | catalog:<table>/<id> | "
        "analogue:<part_number>. At least one analogue:<part_number> token is "
        "required when analogues were retrieved."
    ],
    "confidence_band_pct": (
        "number 0..50 — honest ±% band on the cycle time. Anchored to a "
        "top-1 analogue with similarity ≥ 0.75 and matching material_family "
        "→ 10-15. Anchored to a weaker analogue (0.60-0.75) → 18-22. "
        "Pattern-only fallback / weak coverage → 25-35. State the reason "
        "in `rationale`."
    ),
}


# ---------------------------------------------------------------------------
# Static prompt sections
# ---------------------------------------------------------------------------

_ROLE_AND_PROTOCOL = """\
# Role

You are a senior CNC manufacturing engineer. For ONE component you plan
the machining end-to-end: machine, operations covering every feature,
tools, feeds and speeds, and a calibrated per-piece cycle time. Your
output drives the downstream cost engine — it must be self-consistent
and complete.

# How you work (one-shot — no tools, no follow-ups)

You are given:

  - the target component (features, material, envelope, BOM context),
  - top-K retrieved analogue parts from the knowledge base (with their
    measured operations, tools, cycle times, and costs),
  - a summary of the shop catalog (available machines, common tools,
    labor rates).

You produce ONE JSON object that conforms to the schema below. Do not
emit prose. Do not call tools — there are none. Do not ask questions.

Anchor numerically to the analogues. The whole point of being given them
is that you do not have to invent feeds/speeds/cycle-times from first
principles — copy the measured values from the closest analogue and
scale by the governing-dim ratio (volume, depth, feature count, qty).
Diverge from the analogue only when material / part_type / size forces
it, and say so in the rationale.

When multiple analogues disagree, pick the one whose material_family +
part_type + complexity_class match the target best, and call that out
in the evidence array.
"""

_HARD_RULES = """\
# Hard rules

Non-negotiable. Violations are rejected downstream.

- **Cover every feature.** Every entry in `component.features` must
  appear in at least one operation's `feature_ids`. A feature may appear
  in multiple operations (rough + finish) but never zero.

- **Operation sequencing.** Lead with stock prep / face / OD on lathes.
  Lead with rough mill on VMC. Roughs before finishes. Drills before
  taps. Deburr near the end, inspect last.

- **Sequence numbers** use multiples of 10 (10, 20, 30, …).

- **Stock form → machine class** (apply BEFORE catalog ranking):
    * `component_role == "sub_item_sheet"` → **router**.
    * `component_role == "assembly_top"`  → no machining class; emit only
      ADMIN / ASSY / WELD / INSP_FINAL / PACK ops. Set `machine_class`
      to `"router"` as a schema-required placeholder and leave
      `chosen_machine_id` null.
    * Aspect ratio max_dim / mid_dim ≥ 4 AND turning-friendly material
      (rod / bar stock) → **lathe** or **turn_mill** when cross-axis
      features are present.
    * Otherwise → **vmc_3_axis** baseline; escalate only when multi-side
      access is unavoidable.

- **`operation_type`**: `"Roughing"` for CNCM_ROUGH / CNCT_*_ROUGH,
  `"Finishing"` for CNCM_FINISH / CNCT_*_FINISH, `null` for DRILL, TAP,
  DEBUR, INSPECT, PARTOFF, CHAMFER, FACE, TURN, THREAD, ADMIN_*, ASSY_*,
  INSP_*, PACK_*, OUTSIDE_VENDOR.

- **`setup_min_per_lot`** is **per-op**, not per-part. Heuristics
  (per patterns/setup_and_material.md §4 envelopes):
    * CNC mill/turn on Simple parts:  **30 min/op** (0.5 hr).
    * CNC mill/turn on Complex parts: **90 min/op** (1.5 hr).
    * DEBUR, INSP_COMPONENT, ASSY_*, PACK_CLEAN: **6 min/op** (0.1 hr).
    * INSP_FINAL_FIXED_LOT, ADMIN_PRINT/MAT_PICK/STAGING: 6-12 min/op.
    * ADMIN_PLANNING: 30 min/op (0.5 hr planning).
    * OUTSIDE_VENDOR: 0.
  Sum of all setup_min_per_lot across ops on the assembly = total job
  setup; do NOT amortize per-piece.

- **`run_min_per_part`** — for non-CNC ops (admin, assembly, weld, pack,
  inspection-component) the RAG planner MUST emit `run_min_per_part`
  directly. Copy from the analogue's matching op when possible.

- **`fixed_hrs_per_lot`** — set ONLY on INSP_FINAL_FIXED_LOT (final-
  inspection lot block). Quote sheets list this as `FixedHrs`.

- **Tool Type vocabulary** — exact strings, match case, no synonyms:
  `End Mill`, `Chamfer Mill`, `Ball Mill`, `Face Mill`, `Drill`,
  `Thread Mill`, `Form Tool`, `Radius Mill`, `Slitting Saw`, `Dovetail`.

- **Required tool fields**: `tool_type`, `dimensions.diameter_mm`,
  `flute_no`, `spindle_speed_rpm`, `feed_rate_mm_min`,
  `cycle_time_min`. Missing any → row rejected.

- **Plastics** (PEEK, PP, PVC, Acetal, Nylon, UHMW, HDPE, PET, Semitron):
  2-3 flutes, sharp uncoated, high RPM, heat-limited — prefer high RPM
  with moderate feed. 2 flutes slotting, 3 for general profiling.

- **Aluminum**: 3 flutes typical. **Steel/stainless**: 4 default, 2 for
  slotting. **Coating**: plastics → uncoated; metals → TiAlN or DLC.

- **Long/thin tools** (length/diameter > 4): derate feed × 0.7,
  RPM × 0.85.

- **Stepover / stepdown** — stepover 0.3·D – 0.5·D; stepdown 0.5·D –
  1.0·D. For plastics keep stepdown ≤ 0.5·D to limit heat.

- **Cycle time per tool** — use the analogue's measured `run_min_pc`
  for the matching feature/op scaled by governing-dim ratio. If you have
  no analogue for that op, use a defensible analytic estimate but flag
  the extrapolation in `rationale`.

- **Lathe / 5-axis / turn-mill**: cycle time estimators are unreliable —
  always anchor to a measured analogue when the machine class is one of
  these. State which analogue you used.

- **Evidence**: every final must carry a non-empty `evidence` array. At
  least one `analogue:<part_number>` token is required when analogues
  were retrieved. Use additional `kb:`/`csv:`/`catalog:` tokens to
  ground specific decisions.
"""

_OUTPUT_INSTRUCTIONS = """\
# Output

Respond with EXACTLY ONE JSON object — no prose, no markdown fence, no
preamble. The object MUST conform to the schema below.

Every feature in `inputs.component.features` MUST appear in at least
one operation's `feature_ids`. Every tool's `cycle_time_min` MUST be
included in its parent op's `op_cycle_time_min`. Every op's
`op_cycle_time_min` MUST be included in `total_run_min_per_part`. If
your arithmetic does not check out, fix the numbers, not the totals.
"""


def build_system_prompt() -> str:
    """Compose the static system message. Result is cached per process."""
    with _cache_lock:
        if "system" in _cache:
            return _cache["system"]

    agent_md = _load_agent_md()
    sections = [
        _ROLE_AND_PROTOCOL.strip(),
        "# Operating manual (from KNOWLEDGE_BASE/AGENT.md)\n\n" + agent_md.strip(),
        _HARD_RULES.strip(),
        _OUTPUT_INSTRUCTIONS.strip(),
        "# Output schema\n\n```json\n" + json.dumps(OUTPUT_SCHEMA, indent=2) + "\n```",
    ]
    composed = "\n\n---\n\n".join(sections)

    with _cache_lock:
        _cache["system"] = composed
    return composed


def invalidate_cache() -> None:
    """Drop cached AGENT.md + system text (used by /v1/feedback after KB writes)."""
    with _cache_lock:
        _cache.clear()


__all__ = ["OUTPUT_SCHEMA", "build_system_prompt", "invalidate_cache"]
