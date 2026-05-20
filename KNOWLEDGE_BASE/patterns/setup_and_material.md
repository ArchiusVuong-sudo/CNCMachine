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
- **Setup:** Simple ≈ 0.5 hr per CNC op (0.2–0.3 if a proven repeat); Complex ≈
  1.5 hr/op; +0.1 hr each for DEBUR/INSPECT/ASSY/PKG. Sum → total_setup_hr,
  amortize over qty: `setup_pc = Σ setup_hr × (rate_machine+labor) ÷ qty`.
- **First-article risk:** never-run parts over-run setup 3–11× (new fixture/
  engrave). Quote at estimate level but set the **upper** confidence bound high.
- **Qty leverage:** low qty (≤10–20) makes setup/pc dominate; high qty (>100)
  makes run-time/material dominate. State the qty sensitivity in the estimate.
- **Class signal:** #ops, #tools/op (Complex 4-axis op ≈24–26 vs Simple ≈3–8),
  multi-axis machine, helicoils, engraving, tight tol (±0.02–0.05), removal_cc,
  multi-item/weld assembly → Complex. Drives setup, rate tier, and k choice.

## 5. Estimating a NEW part — material+setup checklist
1. Stock form+size from drawing/feature-rec → volume → Material/pc via §2 (anchor
   on same family+form analogue's $/volume). 2. + Hardware/pc from BOM.
3. Classify Simple/Complex (§4 signals) → setup hr → amortize over qty.
4. Combine with machine-hour cost (`machine_rates_and_cost.md`) and cycle time
   (`cycle_time_model.md`). 5. Compare Cost/EA to nearest `parts/INDEX.md` analogue
   (~25 % agreement expected); report ladder rung + ±band + quote-vs-truth.
