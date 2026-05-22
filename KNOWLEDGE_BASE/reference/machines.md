# Machines & Work-Center Rates

The shop's real machines live in the Supabase **`a4_machines`** catalog, read at
runtime via `catalog_lookup("machines", …)`. **That catalog — not this page — is the
source of truth** for which machines exist and what they cost. This page documents the
catalog's columns and bridges each machine to its cycle-time calibration class.

## Live catalog — `a4_machines` columns (what `catalog_lookup("machines")` returns)

Filter on **any** column (`{col: value}` exact, or `{col: {eq|contains|min|max: …}}`):

| Column | Meaning / use |
|---|---|
| `model`, `machine_name`, `manufacturer` | identity, e.g. `Doosan` / `DNM5700` |
| `machine_type` | normalized class — **primary selector**. One of `router`, `3_axis_mill`, `4_axis_mill`, `5_axis_mill`, `mill_turn`, `lathe` |
| `capability` | `3-axis` / `4-axis` / `5-axis` (null on pure lathes) |
| `work_center` | shop-cell code — **bridges to the k-table below** (e.g. `DNM 5700 (4axis)`, `CNCV FAN V (Vacuum)`) |
| `work_x_mm`, `work_y_mm`, `work_z_mm` | table envelope mm (null on turning) — size-screen here |
| `max_spindle_rpm` | spindle cap (up to 24000 on routers/Robodrills) — Phase-D RPM clamp |
| `tool_holder`, `tool_collet` | spindle interface (`BT40`, `BT30`, `HSK63F`; chuck `8inch`/`65mm` on lathes) |
| `hourly_rate_usd` | **machine-hour overhead** the cost engine charges ON TOP of machinist labor. Equals `machine_burden`. |
| `setup_labor_rate`, `run_labor_rate` | operator $/hr for setup vs run (informational) |
| `labor_burden`, `machine_burden`, `ga_burden` | rate-card tiers USD/hr. `machine_burden` = machine-only OH (→ `hourly_rate_usd`); `ga_burden` = fully-loaded sell-rate reference |

**Rate semantics — don't double-count.** `cost_engine.compute_cost` charges
`run_hr × (labor_rate + hourly_rate_usd)`, where `labor_rate` comes separately from
`a4_labor_rates` and `hourly_rate_usd` is the **machine** burden only. Do **not** add
`ga_burden` on top — it already folds in labor + OH and is a sell-side reference, not a
stacking cost. Quote machine OH from `hourly_rate_usd`/`machine_burden`.

## Selecting a machine, then reading its k

1. Coarse class from the part's axis needs:
   `catalog_lookup("machines", {"machine_type": "4_axis_mill"})` (or `{"capability": "5-axis"}`).
2. Screen by envelope (`work_x_mm`/`work_y_mm` ≥ part bbox) and `max_spindle_rpm`.
3. Read the chosen row's **`work_center`** and map it via the bridge below to the
   `compute_cycle_time` class → `k`.

`part_type` (from `kb_find_analogues`) → eligible `machine_type`:
`cnc_lathe`→`lathe` · `cnc_lathe_milling`→`mill_turn` ·
`cnc_milling`→`router`/`3_axis_mill`/`4_axis_mill`/`5_axis_mill` (agent/UI picks within).

## Work-center → cycle-time class → k  (the bridge)

`work_center` ties a catalog machine to the empirical calibration in
`patterns/cycle_time_model.md §1`. Use `machine_type` for the coarse class; when
`work_center` matches a named cell, prefer its cell-specific note.

| `work_center` (catalog) | `machine_type` | `compute_cycle_time` class | k | note |
|---|---|---|---|---|
| `CNCV FAN M (Vise)` | 3_axis_mill | `vmc_3_axis` | 1.27 | well-characterized |
| `CNCV FAN V (Vacuum)` | 3_axis_mill | `vmc_3_axis` | 1.27–1.58 | vacuum/transform → divide out N-up first |
| `DNM4500 (3Axis)`, `DNM 6700 (Vacuum)`, `CNC HAAS L` | 3_axis_mill | `vmc_3_axis` | 1.27 | |
| `CNCV MAK (Vise)` | 3_axis_mill | `vmc_3_axis` | ~1.9 (wide) | prefer analogue |
| `DNM 5700 (4axis)` | 4_axis_mill | `vmc_4_axis` | 1.10 | exemplar 4-axis |
| `CNCV FAN 4X`, `CNC HMC`, `KITAMURA`, `NHP 5000 (Hmc)`, `HAAS VF4X` | 4_axis_mill | `vmc_4_axis` | 1.10 | |
| `CNCR EXXACT`, `CNCR EXXACT 1616`, `CNCR STRAT`, `ROUT EX 5X` | router | `router` | 1.30 | flat-plate ~1.0 |
| `CNCV FAN Y (HRVA)`, `DVF 5000 (5axis)`, `DVF6500 (5axis)`, `CNC 5-AXIS` | 5_axis_mill | `vmc_5_axis` | — | **NC unreliable → analogue** |
| `LYNX…`, `CNCTM TAK` | mill_turn | `turn_mill` | — | **NC unreliable → analogue** |
| `CNCL TAK`, `CNCL NAK` | lathe | `lathe` | — | **NC unreliable → analogue** |

Default if `work_center` doesn't match a named cell: pick class by `machine_type`
(`vmc_3_axis` 1.27 / `vmc_4_axis` 1.10 / `router` 1.30 / 5-axis & turning unreliable),
else k=1.25. Rates above are USD/hr from the shop rate card (`Database_Machine.xlsx`,
loaded into `a4_machines`).

---

## Legacy job-cost seed model (historical — RM, ref job 10102R18)

_Superseded by the live `a4_machines` catalog above for actual rate values; kept for how
the original burden model was derived._ Drives **Machine Type Selection** and the
**machine_rate** in the cost model. Rates come from the Job Cost **Burden** table:
`rate = Burden$ ÷ Burden Hours` for that work center. Seed values below from reference
job 10102R18 — rates may vary by job/date.

## Machine-type selection (from Feature Recognition `part_type`)
| part_type | Eligible machine types | Examples in data |
|---|---|---|
| `cnc_lathe` | lathe only | (turning-only jobs) |
| `cnc_lathe_milling` | turn-mill only | **DOOSAN 2600Y (TURNMILL)**, **NEX-110Y (TURNMILL)** |
| `cnc_milling` | router **and** milling/VMC (user picks in UI) | **DOOSAN DNM 5700** (4-axis VMC), router, CNCV MAK |
Pick within type by part size, precision, qty, available tooling.

## Work centers seen (Job Cost) & seed rates
| Work center | Role | Burden RM/hr (seed) | Notes |
|---|---|---|---|
| PLANNING | process planning | (labor only) | ~0.5 hr/job fixed |
| PRINT / MAT PICK | paperwork / kitting | ~0 | negligible |
| **SAW MCH** | billet cut-off | ~72 | run ∝ stock cross-section/length; ~3.3 min/pc ref |
| **CNCV MAK** | CNC (Makino-class) small ops | ~123 | OP10-type light milling |
| **DNM 5700 4X** | Doosan 4-axis VMC (main milling) | **~157** | bulk of cycle time on complex parts |
| ROUTER | router milling | _Phase 4_ | large/plate parts |
| DEBUR | manual deburr | ~72 | ~2–3 min/pc; ∝ edge length & feature count |
| INSPECTIPQ / INSPECTASY | inspection (in-process / assembly) | _Phase 4_ | ∝ # critical dims, tolerances |
| ASSY1 | install helicoils/inserts | (labor) | ∝ # inserts |
| PKG CLN10K | cleanroom pack | _Phase 4_ | per Lam packaging spec |

Labor rate ≈ **RM 20/hr** (Labor$ ÷ hours, ref job). Machine Burden + Labor Burden + GA
Burden are separate uplifts (ref job GA Burden ≈ RM 6,037 ≈ 16% of revenue).

## Machine capability assumptions (for parameter capping)
- VMC/turn-mill spindle max ≈ **10,000–12,000 RPM** (NC shows S up to 10000).
- Rapid traverse ≈ **30,000–36,000 mm/min** (used in `nc_analyze.py`; tune per machine).
- Tool change ≈ **5–8 s** (`tc_s` arg). 4th axis (A) present on DNM 5700.

## Rate table to build in Phase 4
For every part's Job Cost, append: `part, job, work_center, burden_hr, burden_rm,
rate_rm_hr, run_min_pc, setup_hr, date` to `extracted/jobcost.csv`. Then median
rate per work center + trend → authoritative rates here.
