# Pattern — Material Cost, Stock & Setup, by Class

Source: `extracted/parts.csv` (39 parts) material_pc_rm by family×form, plus class
envelopes. Material is the other half of the cost (the machine-burden half is in
`machine_rates_and_cost.md`).

## 1. Material RM/pc by family × stock form (median [min..max], n)
| Family | Form | RM/pc | n | Read |
|---|---|---|---|---|
| **PEEK** | SHEET (large panel) | **2955** | 2 | [1672..4238] dominates cost of big flat parts |
| PEEK | PLATE | 289 | 3 | [51..489] |
| PEEK | SLAB | 40 | 2 | [34..45] pre-cut small block |
| PEEK | ROD | 32 | 16 | **[1.45..583]** — spans 400× by Ø×L |
| **PP** | PIPE+PLATE+ROD (assy) | 2726 | 1 | multi-stock weldment |
| PP | PLATE+SHEET | 150 | 1 | |
| PP | BLOCK | 120 | 1 | |
| PP | ROD+PLATE | 68 | 1 | |
| PP | ROD | 21 | 4 | [0.05..143] |
| PP | SHEET | 20 | 5 | [1.07..195] |

Takeaways: **PEEK ≫ PP** per unit. **Stock form ranks material cost:** large
SHEET/PLATE ≫ ROD ≫ thin SHEET. The ROD spread is huge → material is **not** a
constant; it is a function of stock volume (below).

## 2. Material-cost model (use this, not the medians, for a new part)
`Material/pc = stock_volume_cc × ρ × price_per_kg / yield`, or directly from the
job-cost **Material line** of the nearest analogue scaled by stock volume.
- Densities: PEEK ≈ **1.32 g/cm³** (GL30 ≈ 1.51), PP ≈ **0.905 g/cm³**.
- Stock volume from envelope + form: ROD = π(D/2)²·L_per_pc; PLATE/SHEET/BLOCK =
  L·W·T (cut size on drawing/setup sheet/job-cost Material desc — e.g. "PEEK 1000
  16X51X369MM", "PP 0.625\" sheet").
- Back-solve price/kg from analogues: e.g. PEEK 450G Ø90 rod RM 387/pc at ~0.58 kg
  ⇒ ~RM 670/kg; PEEK plate RM 476/pc (0021-53926); PP rod RM ≈ low tens/kg.
  Prefer the **same family+form** analogue's $/volume over a generic number.
- Add a **cut/saw + facing allowance** to length (≈3–6 mm/pc, plus saw kerf) and a
  yield <1 for rod drops; large sheet parts buy area per nest, not per piece.
- **Hardware/pc** (helicoils, inserts, dowel pins, GF/socket fittings) from BOM
  (`bom.py`) or the job-cost Material sub-lines: e.g. M5 Nitronic helicoil
  ≈RM 4.9 ea (2/pc on exemplar), socket-fuse PP fittings RM 110–130/pc. Add it.

## 3. Removal volume / time link
Run time scales with **material removed**, not stock size: removal_cc ≈
stock_vol − finished_part_vol. Rod→prismatic parts remove most of the billet
(exemplar: large). Use removal_cc with MRR (`methodology/03 §2`) for the roughing
time primitive; #features and finish-path length drive the finishing primitive.
Big-stock parts are simultaneously material-heavy **and** time-heavy → highest cost.

## 4. Setup hours & Simple-vs-Complex envelopes (medians)
| Metric | Simple (n=25) | Complex (n=13) |
|---|---|---|
| order qty | 44 [10..267] | 27 [4..203] |
| total setup hr/job | **2.25** [0.2..9.1] | **4.45** [0.33..7.7] |
| total run min/pc | 12.4 [2.3..175] | 52.5 [12.5..225] |
| material RM/pc | 29 [0.05..583] | 220 [2.3..4238] |
| Cost/EA RM (act) | 120 [9..902] | 607 [0..9715] |
| Unit price RM | 187 [0..5143] | 829 [0..14206] |

Rules of thumb for a NEW part once classified:
- **Setup is NOT modeled.** It is a fixed system constant (a flat
  20 min/batch the pipeline applies automatically) and is **excluded**
  from cost-accuracy scoring. Emit `setup_min_per_lot: 0` on every op;
  whatever value is emitted is overwritten downstream. Do not size setup
  by op weight, do not amortize a setup schedule. Spend the effort on
  `run_min_per_part` instead — that is the only quantity scored.
- **Class signal drives RUN time, not setup:** #ops, #tools/op (Complex
  4-axis op ≈24–26 vs Simple ≈3–8), multi-axis machine, helicoils,
  engraving, tight tol (±0.02–0.05), removal_cc, multi-item/weld assembly
  → Complex. A Complex part's per-piece run time (median 52.5 min) is
  ~4× a Simple part's (12.4 min) — use the class to pick the calibration
  `k` and to sanity-check the run-time magnitude.
- **Qty leverage (run/material):** low qty makes the (un-modeled) fixed
  setup dominate cost; high qty makes run-time + material dominate. This
  affects cost framing only — it does not change the run-min/part you
  quote.

## 4a. Per-lot overhead rows — `ADMIN_*`, `INSP_FINAL_*`, `PACK_*`

These customer routing-skeleton rows (`ADMIN_PLANNING`, `ADMIN_PRINT`,
`ADMIN_MAT_PICK`, `ADMIN_STAGING`, `INSP_FINAL_FIXED_LOT`, `PACK_CLEAN`)
carry **~0 run-min/part** and only ever carried *setup* time. Since setup
is now a fixed system constant (§4) and is excluded from scoring, these
rows **do not move the cost-accuracy score**. You may emit them for
routing-skeleton completeness, but spend **zero** effort tuning their
values — they are cosmetic for accuracy. Focus on the run-bearing
families instead (MACHINING, DEBUR, ASSY, INSP_COMPONENT).

## 4b. ADD-work floors that are silently dropped (one-directional under-bias)

The agent's reasoned-from-CNC-path estimate systematically *drops*
non-CNC work bands that the customer bills. These are **one-directional**
(always under, never over), so adding them only helps the bias. They are
floors, not multipliers — never scale an existing op, add the missing op.

### 4b-i. Installed hardware → `ASSY_HARDWARE_INSTALL` is mandatory
If **installed hardware** is present — helicoil, keensert, speedsert,
trisert, threaded insert, press / PEM insert, standoff, dowel pin,
captive screw, vendor-installed fitting — the shop must physically
install it. That work is **never** captured by the milling/drill/tap
path; it is its own routing op.

> **Where to see it:** the drawing `bom` field is often empty, but the
> `material` / stock-description string usually lists the hardware after a
> `+` — e.g. `"PET-P 20MM... + 1084-4EN060 Helicoil + Dowel Pins"`,
> `"... + 4007JS16-16SS Trisert"`, `"... + Captive Screw M5x0.8"`. Parse
> the material string for these tokens; do not assume "no BOM ⇒ no
> hardware".

- Emit `ASSY_HARDWARE_INSTALL` (family ASSY). It is **REQUIRED** whenever
  hardware is present — it may **not** be marked `MISSING`.
- Run-time floor: **≈2–4 min per installed hardware piece**, with a
  **6 min/lot minimum**. (Helicoil tang break + gauge ≈3 min; press
  insert ≈2 min; dowel ream-and-press ≈4 min.) Count pieces from the BOM
  qty-per-assembly, not unique part lines. (Setup is not modeled — §4.)
- This is a one-directional run-time under-bias observed across the eval
  corpus — multiple hardware-bearing parts dropped ASSY entirely and
  under-quoted their run time as a result.

### 4b-ii. Under-scoped weldment / multi-item assembly floor
The 3D model sometimes contains **only the primary solid** ("item 1")
while the drawing BOM lists many fabricated sub-items. Pricing only the
modeled solids then drops the bulk of the fab + inspection + joining
work. Detect and floor it:

- **Trigger (either):** the drawing title contains `WLDMT` / `WELDMENT`
  / `ASSEMBLY` / `ASSY`; **or** the BOM lists **≥4 fabricated stock-form
  sub-items** (PLATE / SHEET / TUBE / ROD / BAR / MESH / ANGLE / PIPE).
- **Under-scope guard (must also hold):** the count of **modeled
  components/solids** in the 3D model is **fewer** than the count of BOM
  fabricated sub-items. If the model already has one solid per fab item,
  it is fully scoped — do **not** apply the floor (avoids over-billing
  fully-modeled weldments).
- **Floor when under-scoped:** bill **each** fabricated sub-item its own
  band — milling/cut-to-size run-time, a multi-stage inspection touch,
  hardware install scaled by its insert count, and the weld/bond op that
  joins it. Anchor each band to the nearest single-item analogue rather
  than to the (under-sized) modeled-solid volume.

### 4b-iii. Part marking → `MARK_PART` when the part is identified
If the drawing or the adopted analogue routing calls for **part marking,
serialization, ink / laser / rubber-stamp, silkscreen, or vibro-peen**,
that is a bench secondary op the CNC path never captures. It is the
MARKING family — distinct from `CNCM_PROFILE_ENGRAVE` (a CNC-milled
engraved *feature*, which stays under MACHINING).

- Emit `MARK_PART` (family MARKING) **only** when marking is actually
  specified — most parts have none, so `MARKING = MISSING` is the common,
  acceptable case. Do not invent it.
- When an adopted analogue's routing has a mark / stamp / engrave-ID row,
  KEEP it (`kb_adopt_routing` now tags it `MARK_PART`); copy its measured
  run-min rather than re-deriving. Absent a measured row, floor it at
  **≈1–3 min/pc** (a quick stamp/laser pass).
- One-directional: the engine historically emitted **zero** marking ops,
  so any genuinely-marked part was fully dropped (−100% on that family).

## 5. Estimating a NEW part — material + run checklist
1. Stock form+size from drawing/feature-rec → volume → Material/pc via §2 (anchor
   on same family+form analogue's $/volume). 2. + Hardware/pc from BOM.
3. Classify Simple/Complex (§4 signals) → pick the cycle-time `k` and
   sanity-check run-min/part magnitude (Simple ~12 / Complex ~52 min/pc).
   Setup is the fixed system constant — not modeled, not amortized.
4. Combine with machine-hour cost (`machine_rates_and_cost.md`) and cycle time
   (`cycle_time_model.md`). 5. Compare Cost/EA to nearest `parts/INDEX.md` analogue
   (~25 % agreement expected); report ladder rung + ±band + quote-vs-truth.
