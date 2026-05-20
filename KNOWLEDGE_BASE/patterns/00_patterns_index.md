# Patterns — Synthesized Predictive Rules (Phase 4)

Derived from the full 39-part dataset (`extracted/{parts,jobcost,tools,operations}.csv`,
309 job-cost rows, 513 tool rows). Provenance snapshot: `_research/PHASE4_AGGREGATES.txt`
(regenerate with `python _tools/analyze.py`). These are the rules the estimator
applies after finding analogues; cite the specific pattern file behind each number.

## The five headline findings (memorize these)
1. **Machine burden rate is a step-function of machine CLASS, not the part.** It
   barely varies within a class across 39 parts → `machine_rates_and_cost.md`.
   Tiers (RM/hr): 5-axis ≈274 · router ≈181 · turn-mill/lathe-Y ≈180 · 4-axis VMC
   ≈157 · 3-axis VMC ≈123 · 2-axis lathe ≈113 · debur/saw ≈72. Labor ≈ RM 20–24/hr
   on top. **Machine burden + material are ~80–95 % of Cost/EA.**
2. **Cost is dominated by (a) material for big PEEK/PP billets, (b) machine-hours
   for small dense parts.** Material/pc spans RM 0.05→4 238. PEEK ≫ PP. Stock form
   ranks cost: SHEET/large-PLATE ≫ ROD ≫ thin SHEET → `setup_and_material.md`.
3. **Quote ≠ true cost. ~1 in 5 jobs lose money** (7/36), margin ranges −51 %→
   +1900 %. Spec/IP parts are priced far above machining cost; large complex PEEK
   parts can run a real loss. Always output **both** quote-style and true-cost
   → `machine_rates_and_cost.md` §Profit.
4. **NC cycle time needs a machine-specific calibration k = actual ÷ NC-estimate.**
   Well-posed 3-/4-axis milling k ≈ 1.1–1.3; multi-piece `-NPC-` programs must be
   ÷N first; lathe `.MAC`/G95 and 5-axis NC are unreliable → use analogue/analytical
   → `cycle_time_model.md`.
5. **Plastics machining params cluster tightly by material × tool type.** PP runs
   faster/higher-RPM than PEEK; both use 2–3-flute sharp uncoated tools, high RPM,
   heat-limited. Bands in `cutting_parameters.md`; tool choice in `tool_selection.md`.

## Files
- `machine_rates_and_cost.md` — burden-rate tiers, labor, GA, cost roll-up, loss reality.
- `cycle_time_model.md` — NC→actual calibration k by machine, multi-piece divisor,
  setup-hour model, the time fallback ladder.
- `tool_selection.md` — feature→tool family by material, observed tool inventory.
- `cutting_parameters.md` — feed/speed/RPM bands by material × tool type (+ derate rules).
- `setup_and_material.md` — material RM/pc by family×form, removal scaling, setup hr,
  Simple-vs-Complex envelopes.

## How the estimator uses these (ties to AGENT.md / methodology/04)
Find analogues (`parts/INDEX.md`) → feature→ops (`reference/operations_and_sequencing.md`)
→ tools (`tool_selection.md`) → params (`cutting_parameters.md`) → cycle time ×k
(`cycle_time_model.md`) → setup amortized (`setup_and_material.md`) → cost roll-up
with class rate (`machine_rates_and_cost.md`) → output quote + true cost + ladder
rung + ±band (`methodology/03 §6`). Expect analogy/analytical/NC to agree ~25 %;
investigate if they don't.
