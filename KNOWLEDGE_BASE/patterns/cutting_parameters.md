# Pattern — Cutting Parameters (Feed / Speed / Step) by Material × Tool

Source: `extracted/tools.csv` feed_mm_min / speed_rpm, grouped by material family
× tool_type (full table in `_research/PHASE4_AGGREGATES.txt`). These are the
machine-input bands for the Parameter-Setting step (→ FreeCAD feed, spindle,
stepover, stepdown). Interpolate **within** a band; flag extrapolation.

## 1. Headline material behaviour
- **PP runs faster & hotter-tolerant than PEEK.** PP end-mill F median ≈1000
  (up to 7000) at S≈6000 (1400–13500); PEEK end-mill F≈1000–2500 at S≈6000–10000
  but with **smaller Ø → higher RPM, lower feed**. PEEK glass-filled (450GL30,
  450G) is more abrasive → treat like PEEK but bias to the **low** feed end and
  expect more tool wear (track GL30 separately, it costs more too).
- Both: **2–3 flute, sharp uncoated, high RPM, climb, keep tool moving** (heat-
  sensitive; no dwelling — `reference/materials.md`). Coolant/air blast for chips.

## 2. Bands by material × tool type (median [min..max], n)
### PEEK (incl. 450G / 450GL30 / natural / virgin)
| Tool type | Feed mm/min | Speed rpm |
|---|---|---|
| end mill (rough/general) | 1000 [ -¹ .. 2500] | 6000 [3000..10000] |
| finish end mill | 900–1500 | 8000 |
| facemill | 800 | 5000 |
| chip-breaker rough EM Ø20 | 2500 | 10000 |
| drill | 150–200 [88..200] | 1000–3500 |
| spot drill | 200 [100..1500] | 1500 [600..8000] |
| reamer | 88 [25..150] | 400 [300..500] |
| tap | feed=pitch×rpm (≈190) | 300–400 |
| thread mill | 250–350 [198..381] | 3000–3500 |
| ball mill / engrave (Ø0.8) | 200 | 6000–8000 |
| slitting saw (Ø45) | 50–75 | 1500 |
| OD/ID turning insert | (mm/rev 0.05–0.25) | 1000–1500 surface-lim |
| parting blade | 150 | 800–1000 |

### PP (NPP natural / WPP white UL94)
| Tool type | Feed mm/min | Speed rpm |
|---|---|---|
| end mill (rough/general) | 1000 [800..7000] | 6000 [1400..13500] |
| face mill / facemill | 1000–2000 | 5000 |
| ball nose / ball mill | 635–1500 | 5000 [3000..8000] |
| chamfer mill | 1000 [150..2000] | 8000 [4000..11000] |
| drill | 175 [70..635] | 1500 [1000..4000] |
| spot drill | 600 | 5000 [3500..12000] |
| thread mill | 375 [300..600] | 3250 [2000..4500] |
| tap | 650 | 4000 |
| lathe OD (insert) | 200 [200..1200] | 1000–13500 surface-lim |
¹ a few rows show negative/zero feed = parse noise (G1 with no F on that line);
ignore the sign, use the positive cluster.

## 3. Stepover / stepdown (ae / ap)
Rarely tabulated in setup sheets (mostly blank in data) → use rules:
- **Roughing ap (stepdown):** plastics tolerate deep cuts — chip-breaker EM up to
  **1.0–1.5 × Ø** axial; standard EM 0.5–1.0 × Ø. ae (stepover) 0.4–0.6 × Ø.
- **Finishing:** ae **0.1–0.2 × Ø**, ap full depth (≤ flute length) in one pass
  for walls; floors 0.2–0.5 mm.
- **Drilling peck:** d/Ø>3 → peck q ≈ 0.5–1 × Ø, full retract every ~3× Ø (PEEK
  gummy chips). Reaming: 0.1–0.2 mm stock, low S, steady feed.
- These feed cycle-time primitives in `methodology/03 §2`.

## 4. Derate / cap rules (don't silently extrapolate — AGENT.md)
- **Cap at machine limit:** spindle max (router/VMC ≤ 12–18 k; lathe surface-speed
  limited). If computed S > machine cap, clamp and raise feed proportionally only
  up to the band max.
- **Long/thin tool (stick-out/Ø > 4) or small Ø < 2 mm:** derate F and S by
  30–50 %; single-flute for PP micro tools.
- **Glass-filled PEEK / abrasive:** bias to band low end, expect wear; not the
  same as natural PEEK — separate analogue.
- **Out-of-band request** (tool Ø, depth/Ø, material, machine, size beyond observed
  ranges): proceed with the nearest band but **label it extrapolation** and widen
  the confidence band; prefer an analogue if one exists.
- Sanity-check final F/S against the nearest part's `tools.csv` rows and the NC
  (`nc_analyze.py` prints actual programmed F/S) before committing.
