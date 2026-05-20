# Parts Case Library — Analogue Index

39 extracted parts. This is the entry point for the estimator's **"find analogues"**
step (AGENT.md, `methodology/04`). Filter here → open the 2–3 closest
`parts/<part>.md` → reuse their measured tools/params/time/cost, scaled by the
differing governing dimension. Numbers are RM; Cost/EA shown is **Actual** (or
Estimate where the job never ran — marked ✱). Regenerate after re-extraction
(`_tools/merge_shards.py` then read `extracted/parts.csv`).

## How to pick an analogue (fallback ladder rung 1→2)
1. Match **part_type** (cnc_lathe / cnc_lathe_milling / cnc_milling / assembly) —
   this fixes the machine class & rate (`patterns/machine_rates_and_cost.md`).
2. Match **material family** (PEEK / PEEK-GL30 / PP) — fixes params & $/volume.
3. Match **stock form** (ROD / PLATE / SHEET / SLAB / BLOCK) — fixes the material
   cost model and roughing strategy.
4. Within that cell, pick the nearest by **governing dimension** (Ø×L or L×W×T,
   removal_cc, #features, qty). Scale time≈by removal/feature count, material≈by
   stock volume, setup≈by class, cost via the roll-up.
5. No cell match → drop to feature analogy (reuse per-feature rows from
   `extracted/tools.csv`/`operations.csv`) → analytical (`methodology/03`) →
   bounding by the Simple/Complex percentiles in `patterns/setup_and_material.md`.
   Always state the rung used.

Legend: Stock = primary form · Qty = order qty · R/pc = run min/pc (machining) ·
✱ = Estimate (no actuals; quoting data only) · loss = price<costAct.

## COMPLEX — PEEK
| Part · rev | Stock (Ø/​LxWxT) | Qty | R/pc | Cost/EA | Price | Machines | Use as analogue for |
|---|---|---|---|---|---|---|---|
| **713-187739-236 · B** ★EXEMPLAR | ROD Ø90 ×66.7 | 60 | 75.3 | 638.66 | 623.61 | CNCV MAK + DNM5700-4X | Complex PEEK prismatic, 4-axis VMC, rod, helicoil, **real loss** |
| 713-323740-001 · A | ROD Ø57 ×47 | 147 | 20.0 | 174.82 | 309.15 | LYNX2100 LYSB (lathe) | Stepped seal ring, dual-spindle lathe, k≈1.0 |
| 0020-64722 · 03 | ROD Ø19 ×34.5 | 203 | 12.5 | 73.81 | 166.47 | LYNX26Y+CNCV FAN M+DNM4X | Turned finger/arm, V-groove, multi-OP turn-mill |
| 0022-09112 · 04 | ROD Ø70 ×28 | 18 | 22.0 | 238.72 | 286.43 | CNCTM TAK (Takisawa) | Disc/ring, tight bore ±0.02, low qty turn-mill |
| 0200-02605 · 06 | ROD Ø12.7 ×24 | 42 | 17.0 | 111.62 | 89.38 | CNCTM TAK NEX-108Y | Small hex nozzle, ext+int thread, **loss −20 %** |
| 0021-53926 · 07 | PLATE 369×51×16 | 40 | 197.8 | 1021.92 | 1205.19 | CNCV FAN L (5 OP) | Long flat bracket, single-machine, **best k≈1.09** |
| 713-226789-201 · C | PLATE 85×75×38 | 56 | 55.0 | 576.08 | 829.36 | CNCV FAN M + DVF5000-5X | Drafted boss, 5-axis, M5/M4 helicoils |
| 0041-62474 · 03 | SHEET 0.625″ ~645² | 20 | 50.0 | 4154.29✱ | 14206.21 | CNCR BARNY+MAK+TAK | Huge PEEK panel, 21× helicoil, material ≈83 % |
| 0042-15176 · 01 | SHEET Ø259 ×12.7 | 6 | 180.8 | 2200.06 | 1076.55 | CNCV FAN V vacuum-chuck | Annular ring, **severe loss −51 %**, qty 6 |

## COMPLEX — PP (NPP/WPP; several are weld/fusion assemblies)
| Part · rev | Stock | Qty | R/pc | Cost/EA | Price | Machines | Use as analogue for |
|---|---|---|---|---|---|---|---|
| 839-297424-004 · C | PLATE 0.5/0.75″ | 6 | ~225 | 9715.48 | 9520.04 | CNCR EXACT+FAN M+DNM6700 | Large PP weldment, hardware-heavy, **loss −2 %** |
| 16-408773-00 · A | PLATE+SHEET | 27 | ~135 | 1292.79 | (internal) | CNCV FAN V+CNCR EXACT | Multi-item PP body + weld, dovetail |
| 16-455529-00 · B | ROD Ø57 + PLATE | 7 | ~40 | 606.19✱ | 1066.70 | CNCL TAK+DVF5000+DNM6700 | 2-item rotary arm, 5-axis, qty 7 |
| 839-A05168-102 · C | PIPE 32 + sheet/rod | 4 | ~200 | 3379.95 | 4409.84 | GF-fusion + DNM5700-4X | GF-fused PP pipe assy + machined plates |
| 839-A07950-001 · B | SHEET+ROD+PIPE | – | ~22 | n/a | n/a | DNM6700 (post-assy) | Welded NPP drum; **no job cost** (geom only) |

## SIMPLE — PEEK
| Part · rev | Stock | Qty | R/pc | Cost/EA | Price | Machines | Use as analogue for |
|---|---|---|---|---|---|---|---|
| 0022-42142 · 02 | ROD Ø15.9 | 56 | 3.0 | 19.11 | 70.04 | CNCL TAK NEX-110Y | Tiny stepped actuator pin, pure lathe |
| 0022-75931 · 02 | ROD Ø15.9 ×10 | 267 | 3.5 | 13.86 | 20.86 | CNCL TAK | Ring spacer, high qty, lathe-only |
| 713-142958-001 · A | ROD Ø25.4 ×18 | 168 | 3.0 | 22.32 | 202.99 | CNCL NAK | Roller ring (pair w/ -142960), spec-priced |
| 713-142960-001 · A | ROD Ø19 ×9 | 224 | 2.28 | 9.36 | 187.38 | CNCL NAK | Cap disc (pair w/ -142958), smallest cost/pc |
| 713-201706-001 · A | ROD Ø19 ×60 | 150 | 8.53 | 56.80 | 107.76 | CNCTM TAK | Stepped pin, M10+M6 tap, 2-OP |
| 713-344410-010 · A | ROD Ø25.4 ×75 | 156 | 10.0 | 81.57 | 133.89 | LYNX21 LYSB | Mushroom standoff, bore+chamfer, k≈1.0 |
| 713-A05592-003 · B | ROD Ø57 ×36 | 28 | 18.0 | 175.85 | 175.43 | CNCTM TAK NEX-110Y | HV insulator cup, ID thread+groove, ~break-even |
| 0022-27201 · 03 | ROD Ø10 ×20 | 102 | 10.0 | 45.37 | 115.04 | CNCL TAK + CNCV MAK | Snap pin, slitting-saw slots, fixture batch |
| 0022-63955 · 02 | ROD Ø44 ×47 | 30 | 22.0 | 169.41 | 329.14 | LYNX21 LYSB | Adaptor shaft, Y+sub-spindle, NRE fixtures |
| 1157-776-01 · A | ROD Ø160 ×58 | 25 | 76.0 | 608.88 | 2390.37 | CNCL NAK+CNCV MAK+SAW | Big cover-flange, material 95 % of cost |
| 0021-55284 · 04 | ROD Ø80 (GL30) | 44 | 29.0 | 269.04 | 456.37 | CNCL TAK + CNCV FAN M | **Glass-filled PEEK** arc clamp (separate band) |
| 0022-26284 · 03 | SLAB 220×116×16 | 10 | 12.0 | 121.07 | 236.51 | CNCV FAN V (10-up vac) | Thin align jig plate, k≈1.7 multi-up |
| 0022-42143 · 02 | SLAB 0.5″ sheet | 36 | 12.8 | 89.55 | 135.33 | Anderson+FAN V+Robodrill | Actuator cover, near-pair w/ -42142 |
| 0022-49255 · 04 | PLATE 0.625″ | 72 | 12.0 | 90.13 | 212.62 | CNCR STRAT+CNCV FAN V | Small panel, router cut + VMC, 6-up |

## SIMPLE — PP (NPP natural / WPP white)
| Part · rev | Stock | Qty | R/pc | Cost/EA | Price | Machines | Use as analogue for |
|---|---|---|---|---|---|---|---|
| 15-395585-00 · A | ROD Ø15 | 53 | 3.0 | 17.97 | (internal) | CNCL TAK | Tiny PP collar, lathe-only |
| 0023-12637 · 03 | ROD Ø100 ×175 | 16 | 20.0 | 111.63 | 132.12 | CNCL NAK + CNCTM TAK | Ø100 disk, radial live-mill leaders |
| 1241-714-01 · A | ROD Ø80 | 20 | 26.0 | 156.03 | 222.95 | LYNX26Y + CNCV MAK | Conical bush/flange, engraved ribs, NRE |
| 839-219206-002 · C | ROD Ø100 ×71 | 56 | 48.0 | 358.52 | 5143.21 | CNCV FAN M + 5-AXIS | Turned nozzle mount, **spec-priced +1900 %** |
| 713-A51655-001 · A | SHEET 0.5″ strip | 25 | 3.35 | 59.01 | 96.87 | CNCR EXACT + FAN M | Small L-bracket, 20-up strip fixture |
| 0020-46358 · 06 | SHEET 60 mm | 49 | 65.4 | 234.80 | 243.79 | CNCR EXACT + CNCV FAN M | Dovetail+NPT-thread block, scallop surf |
| 0041-14421 · 01 | SHEET 0.25+0.375″ | 18 | 10.0 | 160.83 | 134.55 | CNCR EXACT + WELD | 2-sheet welded bracket, **loss −22/pc** |
| 15-137820-00 · B | SHEET 12 mm | 80 | 23.3 | 119.59 | 181.37 | CNCR EXACT | Skid pad plate, 20-up router batch |
| 713-A42978-022 · A | SHEET 12 mm 820² | 36 | 175.0 | 901.80 | 872.00 | CNCR EXACT + HAAS L | Large flat plate Ø410 bore, **loss −2 %** |
| 839-A29596-001 · B | BLOCK 60×72×72 | 20 | 38.0 | 500.67 | 1060.72 | CNCV FAN M + 5-AXIS | Nozzle bracket, 2× NPT thread-mill |
| 839-232763-002 · C | BLOCK+ROD+SHEET | 10 | varies | 747.95 | 1002.78 | DVF5000+CNCV MAK+CNCL | 3-item welded DO-probe housing, 50 % weld scrap |

## Cross-cutting analogue notes
- **Near-pairs / families** (reuse directly, scale by size): 0022-42142↔0022-42143
  (actuator); 713-142958↔713-142960 (Ichor guide-pin); 839-A29596↔839-219206
  (PP nozzle, 5-axis); 0026/49255/42143 (small PEEK router panels).
- **Spec/IP-priced** (don't infer cost from price): 713-142958/-142960,
  839-219206-002, 1157-776-01, 713-187739-236-class.
- **Loss-makers** (model must reproduce): 0042-15176, 0200-02605, 713-187739-236,
  839-297424-004, 0041-14421, 713-A42978-022.
- **Best NC calibration anchors:** 0021-53926 (CNCV FAN L k≈1.09), 713-187739-236
  (DNM4X k≈1.3 on -2PC-), 713-323740-001 & 713-344410-010 (lathe k≈1.0).
- **No usable NC** (use analytical/analogue): all `.MAC`/G95 lathe parts, 5-axis,
  0041-62474, 713-A42978-022, 839-219206-002, 839-A07950-001 (also no job cost).
