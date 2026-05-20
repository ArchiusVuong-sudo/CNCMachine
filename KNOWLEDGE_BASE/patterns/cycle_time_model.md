# Pattern — Cycle-Time Calibration & Setup Model

Source: `extracted/operations.csv` (nc_calib_k = JobCost-actual ÷ nc_analyze-est),
`extracted/jobcost.csv` setup/run hrs. Turns the NC physics estimate (lower bound,
no accel/decel/air) into a realistic per-piece run time.

## 1. Calibration factor k by machine class  (Run_actual = k × NC_estimate)
| Machine class | k (median) | range / n | Use |
|---|---|---|---|
| 3-axis VMC CNCV FAN L | **1.11** | 1.02–1.16 (n=5) | **best-behaved; trust** |
| 4-axis VMC DNM 5700 4X | **1.10** | 0.72–1.30 (n=5) | trust; exemplar OP20 1.3 |
| 3-axis VMC CNCV FAN M | 1.27 | 1.05–4.5 (n=9) | use 1.2–1.3; drop outliers |
| Router CNCR EXACT/EXXACT | 1.0–1.4 | 0.38–3.2 (n≈14) | use **1.3**; flat-plate ~1.0 |
| 3-axis VMC CNCV FAN V | 1.58 | 1.00–2.06 (n=5) | multi-pc transforms inflate |
| 3-axis VMC CNCV MAK | 1.9 | 1.1–2.8 (n=8) | wide; prefer analogue |
| 5-axis DVF 5000 | unreliable | 0.39–1.05 | **don't trust NC**; analogue |
| Turn-mill / lathe `.MAC`/G95 | unreliable | – | **don't trust NC**; analogue |

**Default if class unknown: k = 1.25.** Generalization: well-formed 3-/4-axis
milling G-code → **k ≈ 1.1–1.3**. The looser the kinematics (5-axis, turn-mill)
or the more the post-processor repeats/duplicates blocks, the less usable NC is.

## 2. Hard pre-conditions before applying k (don't skip)
- **Multi-piece programs:** filename/comment tokens `-2PC-`, `4PC`, `-5PC-`,
  `-NPC-` mean the program cuts N parts per cycle → **divide NC time by N first**,
  then ×k (exemplar OP20: 56.8 min/2 ≈ 28 → ×1.3 ≈ 36 actual). Vacuum-fixture
  "transform" programs (CNCV FAN V/MAK) are the common N-up case.
- **Lathe `.MAC` / G95 (feed mm/rev) / G96 (CSS):** `nc_analyze.py` mis-integrates
  these (gives absurd 1 000s of min, or F=1 init). **Do not derive k**; estimate
  the lathe op by analogue (similar Ø×L turned part) or analytically.
- **Short face-only programs** (single facing pass) give wild k (3–4×); ignore for
  calibration, they're not representative of the op's real content.
- Only `.NC/.nc/.min/.eia/.tap/.MAC`-as-text Fanuc milling code is reliable.

## 3. Cycle-time fallback ladder (state the rung used)
1. **Near analogue:** same family/part → reuse its measured Run_min_pc, scale by
   the differing governing dim (volume, depth, #features, qty). Best accuracy.
2. **Feature analogy:** sum per-feature cut-min from a similar part's
   `operations.csv`/`tools.csv` rows for matching features.
3. **NC physics:** `nc_analyze.py` on the real G-code ÷N ×k(class). Use when
   G-code exists and is well-formed (milling, not MAC/5-axis).
4. **Analytical:** `methodology/03 §2` primitives (vol/MRR for roughing,
   path-len/feed for finishing, peck model for drilling) ×k. The only rung for
   parts with no NC and no close analogue (common — ~1/3 of parts lack usable NC).
Triangulate ≥2 rungs; expect ~25 % agreement; investigate divergence.

## 4. Setup-hour model (per job, amortized over qty)
From `jobcost.csv` setup_hr by op & class:
- **Simple part:** total setup **median 2.25 hr/job** (range 0.2–9.1). Typical
  CNC op setup **0.5 hr**; repeat/proven jobs run **0.2–0.3 hr**.
- **Complex part:** total setup **median 4.45 hr/job** (0.33–7.7). Typical
  complex CNC op **1.5 hr/op**; 5-axis & first-article higher.
- **First-article / prove-out blow-ups are routine:** new-fixture or new-engrave
  ops over-run estimate 3–11× (0022-27201 lathe 0.5→3.75 hr; 1157-776-01 OP50
  0.3→3.3 hr; 0020-46358 2.9→9.1 hr on rev change). For a NEW (never-run) part,
  use the **estimate-level** setup but widen the upper confidence band markedly.
- Per-piece setup impact = Σ Setup_hr × (rate_machine+labor) ÷ qty. At low qty
  this is large; **always show it explicitly** (AGENT.md hard rule).
- Non-machining steps (DEBUR, INSPECT, ASSY, PKG) carry their own setup ≈0.10 hr
  and run min/pc; they routinely over-run estimate (deburr 3–5×, inspect up to
  20× on quality events) — include them and flag as a risk band, not point value.

## 5. Output per op (contract)
`op · machine(class,rate) · Run_min_pc = (NC÷N ×k | analogue | analytical) ·
Setup_hr/qty · ladder rung · ±band`. Roll to part via `machine_rates_and_cost.md`.
