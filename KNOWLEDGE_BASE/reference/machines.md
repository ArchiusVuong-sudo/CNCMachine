# Machines & Work-Center Rates

Drives **Machine Type Selection** and the **machine_rate** in the cost model. Rates come
from the Job Cost **Burden** table: `rate = Burden$ ÷ Burden Hours` for that work
center. Seed values below from reference job 10102R18 — **widen into a table over all
parts in Phase 4** (rates may vary by job/date).

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
