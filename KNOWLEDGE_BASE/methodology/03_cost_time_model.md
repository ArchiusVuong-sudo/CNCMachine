# Cost & Time Model

The estimation model, derived from the **Job Cost - Detail** reports (the shop's own
accounting truth) and the **NC toolpaths** (physics). Read with
`reference/machines.md` (rates) and `patterns/cycle_time_model.md` (calibration).

---

## 1. Cost decomposition (exactly how this shop costs a job)

Per **job** (order of `Qty` pieces), from every Job Cost - Detail:

```
Total Cost = Material
           + Labor$            (Σ work-centers: hours × labor rate)
           + Labor Burden      (overhead applied on labor)
           + Machine Burden    (machine occupancy: burden_hours × machine_rate)
           + GA Burden         (general & admin overhead)
Cost/EA    = Total Cost / Qty
Price/EA   = Unit Price        (what the customer pays)
Profit     = (Price − Cost/EA) × Qty
```

Per **piece**, the practical estimator form:

```
Cost_pc =  Material_pc
         + Σ_ops [ (Run_min_pc/60) × MachineRate_RM_hr(work_center) ]
         + Σ_ops [ (Run_min_pc/60) × LaborRate_RM_hr ]
         + Setup_cost_pc
         + Tooling_pc
         + GA_and_margin
```

where (calibrated from reference job 10102R18 and to be refined per part in Phase 4):

- `MachineRate_RM_hr` — from the **Burden** table: `Burden$ ÷ Burden Hours`.
  Reference values: **DNM 5700 4X ≈ RM 157/hr**, CNCV MAK ≈ RM 123/hr,
  SAW MCH ≈ RM 72/hr, DEBUR ≈ RM 72/hr. (Full evolving table → `reference/machines.md`.)
- `LaborRate_RM_hr` ≈ **RM 20/hr** (Labor$ 750 ÷ 37.5 hr on the reference job).
- `Setup_cost_pc = Setup_hr × (MachineRate+LaborRate) ÷ Qty` — setup is **amortized
  over the lot**, so it dominates small lots and vanishes on large ones.
- `Tooling_pc` — perishable-tool wear + any **special tool** (SPECIAL TOOLS folder;
  purchase-requisition xlsx gives the one-off price, amortized over the lot/expected life).
- `GA_and_margin` — GA Burden in the data is sizeable (reference: GA RM 6,037 ≈ 16% of
  revenue). Treat as a % uplift on (material+labor+machine).

> **Two target columns, two lessons.** *Estimate* = how the shop **quotes** (use to learn
> quoting heuristics & the customer-facing number). *Actual* = realized cost/time (use as
> the **physical ground truth** to calibrate the time model). Always capture both.

## 2. Time decomposition

```
Job time per work-center = Setup_hr (once per job)  +  Run_min_pc × Qty
```

`Run_min_pc` per machining operation is what we predict from features. It is the sum
over the operation's tool passes:

```
Run_min_pc ≈ Σ_passes ( CuttingLength / Feed )            # feed time
           + Σ ( RapidLength / RapidRate )                 # air/positioning
           + n_toolchanges × t_toolchange                  # ~0.1 min each
           + n_holes × (approach+dwell+retract)            # drilling
           + probing/inspection-in-cycle
```

Two ways to get it, in order of preference:

1. **From the NC program** — `_tools/nc_analyze.py` walks every G0/G1/G2/G3 move,
   integrates distance/Feed, adds tool-change & dwell. This is geometry-exact for a
   *known* program. It under-counts because it ignores accel/decel and dwell ramps →
   multiply by a **calibration factor** `k_machine` (derive in Phase 4 by regressing
   NC-estimate vs Job Cost Run; reference data suggests k ≈ 1.2–1.5; remember
   filenames like `-2PC-` machine N pieces per cycle → divide by N).
2. **From feature geometry** (for *unseen* parts, no NC yet) — analytical MRR/area
   model in `methodology/04_estimation_for_new_parts.md`.

### Per-feature cutting-time primitives (metric)
Let Ø = tool dia (mm), z = flutes, n = RPM, fz = feed/tooth (mm), F = feed (mm/min) =
fz·z·n, ae = radial stepover (mm), ap = axial stepdown (mm).

- **Face / fly cut**: passes = ⌈Width / (Ø·0.7)⌉; length ≈ passes × cut-length;
  `t = length / F`.
- **Pocket / volume rough**: `t ≈ Volume_mm3 / MRR`, `MRR = ae·ap·F` (mm³/min). Add a
  finish wall+floor pass: `t_finish ≈ (perimeter·depth/ (ap·F)) + (area/(ae·F))`.
- **Profile / contour**: `t = (perimeter × n_depth_steps) / F`, `n_depth_steps =
  ⌈depth/ap⌉`.
- **Slot**: `t = (length × ⌈depth/ap⌉) / F`.
- **Drill (peck)**: `t = depth/F_plunge × peck_factor (≈1.3) + retract`; per hole, ×count.
- **Tap / thread-mill**: tap `t≈2·depth/(pitch·n)`; thread-mill ≈ 1–2 helical revs.
- **Turning (lathe)**: `t = L / (f_mmrev × n) ` per pass; passes = ⌈DOC_total/ap⌉.
  Facing/parting similar with radial travel.
- Always add a **rapid/air + approach allowance** (≈ 15–30 % of cutting) and
  **tool-change** (≈ 0.1 min × #tools).

## 3. Setup time

`Setup_hr` (Job Cost) ≈ Setup Sheet "Setup time". Drivers seen: number of OPs
(separate fixturings), jaw/fixture type (soft-jaw cut, custom fixture, vise), part size,
qty (proving more pieces), first-article. Typical observed: simple OP ≈ 0.1–0.5 hr;
complex multi-tool VMC OP ≈ 1.0–2.5 hr. Model as a base per machine + increments per
(#tools, custom fixture, first-article). Refine in `patterns/cost_model.md`.

## 4. Material cost

```
Material_pc = StockVolume_or_Length × UnitPrice_material × (1 + scrap/kerf)  + hardware_pc
```
- Stock shape from drawing/Job Cost: **ROD** (Ø × length) for round/turned parts;
  **PLATE/BLOCK** (L×W×T) for prismatic. Add saw kerf + facing + grip allowance to part
  envelope (reference: 66.7 mm of Ø90 rod for a part far shorter — generous parting/grip).
- Unit price from Job Cost Material line (e.g. PEEK 450G Ø90 rod ≈ RM 23,232 / 13.12 ft).
  Per-material price & density → `reference/materials.md`.
- Hardware (helicoils, inserts, dowels) from BOM × per-piece qty.

## 5. Worked calibration — reference job 10102R18 (713-187739-236, PEEK, qty 60)

| Work center | OP | Setup hr (E/A) | Run hr (E/A) | Run min/pc (A) | Burden$/hr |
|---|---|---|---|---|---|
| SAW MCH | 800 | 0.10/0 | 3.30/3.30 | 3.30 | ~72 |
| CNCV MAK | 10 | 0.08/0.80 | 3.30/3.30 | 3.30 | ~123 |
| DNM 5700 4X | 20 | 1.50/1.50 | 36.0/36.0 | 36.0 | **157** |
| DNM 5700 4X | 30 | 1.50/2.50 | 36.0/36.0 | 36.0 | **157** |
| DEBUR | 810 | 0.10/0 | 3.0/2.29 | ~2.3 | ~72 |
| ASSY1 | 820 | 0.10/0 | 3.0/3.95 | ~4.0 | – |

Material RM 387/pc (PEEK rod) + RM 9.8/pc (M5 helicoil ×2). Cost/EA RM 638.66, Unit
Price RM 623.61 → **−RM 15/pc** (the model must be able to reproduce this, incl. the
loss — a good estimator predicts true cost, not just the quote). NC `nc_analyze.py`
gave OP10 ≈ 3.0 min vs actual 3.3 → calibration k≈1.1 there; OP20 program is `-2PC-`
(56.8 min/2 ≈ 28 vs 36 actual → k≈1.3 with accel/decel). Lock k per machine in Phase 4.

## 6. Estimator output contract (what we must produce per part)

Per feature → per operation → per part:
`feature → op(s) → machine, tool(Ø,flutes,len), feed, speed, stepover, stepdown,
passes, cut_time_min`. Aggregate → per-OP Run_min_pc + Setup_hr → Cost_pc breakdown
(material, machine, labor, burden, tooling, GA, margin) → **Price suggestion** + a
confidence/assumptions note. Template in `methodology/04_estimation_for_new_parts.md`.
