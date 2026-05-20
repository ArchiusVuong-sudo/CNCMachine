# Estimating Time & Cost for NEW / Unseen Parts & Features

> The core requirement: **new parts will contain features/parts not in this knowledge
> base.** We must estimate them by *generalizing the patterns*, not by lookup. This is
> the operating procedure for that. It is deliberately written at "the right altitude":
> firm heuristics + a fallback ladder, not brittle lookup tables.

The estimator receives, from the Feature Recognition Engine: `part_type`
(`cnc_lathe` | `cnc_lathe_milling` | `cnc_milling`), `orientation`, and a **feature
list** (each with type + dimensions), plus the **material** and **stock**. It must
output the full time & cost breakdown of §6 in `03_cost_time_model.md`.

---

## Step 0 — Normalize inputs
- Map material → `reference/materials.md` (density, machinability class, RM/unit).
- Map `part_type` → candidate machines (`reference/machines.md`, "Machine Type Selection"):
  - `cnc_lathe` → lathe; `cnc_lathe_milling` → turn-mill (e.g. DOOSAN 2600Y, NEX-110Y);
  - `cnc_milling` → router **and** VMC (e.g. DNM 5700) — pick by size/precision/qty.
- Compute stock: bounding box (+ grip/kerf/face allowance, see `03 §4`) → shape ROD/PLATE.
- Compute `removal_volume = stock_vol − part_vol` (from CAD/STEP if available, else
  approx from envelope − feature volumes).

## Step 1 — Decompose into features → operations
For each recognized feature, assign the operation chain using
`reference/operations_and_sequencing.md`. Each feature type has a canonical op recipe,
e.g.:
- through/blind **hole** → (spot) → drill → (ream/bore if tight tol) → (chamfer);
- **tapped hole / helicoil** → spot → drill tap-drill → thread-mill or tap → (+insert);
- **pocket** → rough (chip-breaker/large EM) → rest-rough (smaller EM) → semi → wall
  finish → floor finish → corner/fillet (bull/corner-radius);
- **profile/outline** → rough → finish (often after a roughing stock of ~0.2–0.5 mm);
- **face/top** → fly/face mill;
- **slot/dovetail/groove** → dedicated form/EM tool;
- **OD/ID turn, thread, part-off** (lathe) per the turn-mill sequence pattern;
- **engraving / part-mark** (always present on Lam parts — Note 6) → small ball/engrave.

## Step 2 — Select tools by ANALOGY + rules (not lookup)
Pick the tool the shop *would* pick (`patterns/tool_selection.md`,
`reference/tooling.md`):
1. Match on (feature_type, material, governing dimension). The governing dimension caps
   tool Ø: pocket corner radius / slot width / hole Ø / wall height vs reach.
2. Heuristics distilled from the data:
   - Tool Ø ≈ the largest that fits the smallest internal radius / narrowest passage;
     finish corners with Ø = 2 × min internal radius.
   - Flutes by material: **plastics (PEEK/PP/Delrin) → 2–3 FL** (chip clearance, low
     cutting force), more flutes only for finishing/rigidity.
   - Reach: `tool_length` ≳ feature depth + clearance; if depth/Ø > ~4 use necked/long
     tool and **derate feed/speed** (see Step 3).
   - Roughers: "chip breaker" 3FL Ø12–20 for bulk; finish with 2FL Ø4–10.
   - Drills: nearest standard Ø ≥ required (carbide for PEEK; tap-drill from thread).
3. If no analogue exists, fall back to a generic tool sized by the rule above and flag
   `tool_assumed=true`.

## Step 3 — Set cutting parameters (feed / speed / stepover / stepdown)
Use `reference/cutting_parameters.md` + `patterns/cutting_parameters.md`. The robust,
generalizable form is **per-tooth feed + surface speed by material**, scaled to the tool:

```
RPM   n   = (1000 · Vc) / (π · Ø)          # cap at machine max (≈10–12k here)
Feed  F   = fz · z · n        (mm/min)     # milling
ae (stepover) = k_ae · Ø        ;  ap (stepdown) = k_ap · Ø
```
with material bands (start values; refine from extracted data in Phase 4):

| Material | Vc (m/min) | fz/tooth (mm) | k_ae rough/finish | k_ap rough |
|---|---|---|---|---|
| PEEK 450G | 200–400 | 0.05–0.12 | 0.5 / 0.1 | 1.0–2.0×Ø |
| Delrin/POM | 250–500 | 0.05–0.15 | 0.5 / 0.1 | 1.0–2.0×Ø |
| Polypropylene | 300–600 | 0.05–0.15 | 0.6 / 0.1 | 1.0–2.0×Ø |

Plastics are speed-limited by **melting/heat & rigidity**, not tool wear → high RPM,
moderate fz, climb mill, sharp uncoated tools, air/coolant. Long/thin tool → reduce ap
and fz (×0.3–0.6). Validate the chosen F,S against the closest NC examples; the NC
feeds/speeds in the corpus are the empirical anchor.

## Step 4 — Compute cycle time per feature
Apply the per-feature primitives in `03_cost_time_model.md §2` using the geometry from
feature recognition (volume, area, perimeter, depth, hole count). Sum to `Run_min_pc`
per OP; add air/approach allowance and tool-change. Then apply the machine
**calibration factor** `k_machine` from `patterns/cycle_time_model.md` so the analytical
number matches realized Job-Cost run-time behaviour.

## Step 5 — Setup time & lot effects
`Setup_hr` from `03 §3` model (base per machine + #tools + fixture + first-article).
Amortize over the order **Qty**. Small qty → setup dominates; this is the single biggest
swing in `Cost/EA` and must be surfaced.

## Step 6 — Roll up cost
Feed `Run_min_pc`, `Setup_hr`, material, tooling into the cost formula
(`03_cost_time_model.md §1`) with rates from `reference/machines.md`. Add GA% and a
margin. Produce **both** an "estimate-style" number (how the shop would quote) and a
"true-cost" number (what it likely actually costs), plus assumptions & confidence.

## The Fallback Ladder (always know which rung you're on; record it)
1. **Exact/near analogue** — same family in `parts/INDEX.md` (same material, similar
   features/size). Scale its measured Run/Setup/Cost by the differing driver
   (volume, #features, depth). Highest confidence.
2. **Feature analogy** — no whole-part match, but each feature resembles features seen
   elsewhere → use that feature's measured tool/params/time, scaled by dimension.
3. **Pattern model** — no close feature → analytical Step 2–4 with material bands &
   geometry. Medium confidence.
4. **Bounding heuristic** — insufficient geometry → bracket with similar-complexity
   parts (Simple/Complex × material) from `extracted/` percentiles; wide confidence band.

Always: state the rung, the analogues used, the assumptions, and a ± confidence range.
Prefer interpolation within observed ranges; **flag extrapolation beyond the data**
(tool Ø, depth/Ø, material, machine, size) rather than silently trusting it.

## Sanity checks before returning an estimate
- Per-feature MRR within material band? Feed/speed within machine limits & NC-observed?
- `Cost/EA` between this dataset's min/max for that material & complexity?
- Setup amortization reflected for the given Qty?
- Material_pc ≈ stock_volume × density × RM/kg + hardware? cross-check Job-Cost-style.
- Does total `Run_min_pc` ≈ Σ feature times ≈ NC-analyzer estimate × k? Triangulate the
  three independent paths (analogy, analytical, NC) — they should agree within ~25%.
