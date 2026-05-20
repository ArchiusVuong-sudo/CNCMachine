# Pattern — Machine Burden Rates & Cost Roll-up

Source: `extracted/jobcost.csv` (rate_rm_hr = Burden$ ÷ Burden hr per work center,
309 rows, 39 parts); `extracted/parts.csv`. The strongest, most reusable pattern
in the KB: **burden rate ≈ a constant per machine class**, so once you pick the
machine (Machine-Type Selection step) the rate is essentially known.

## 1. Burden-rate tiers (RM/hr) — use the class median
Names are written many ways across job-cost PDFs; normalize to class
(`reference/machines.md`), then apply the rate. Spread within a class is ~0.

| Class (normalized) | Rate RM/hr | Aliases seen in data (n) |
|---|---|---|
| **5-axis machining** | **274** | DVF 5000, HAAS UMC-750, "CNC 5-AXIS" (n≈6) |
| Router – large gantry | 229 | CNCR BARNY (n=2) |
| **Router / waterjet-style 3X** | **181** | CNCR EXACT, EXXACT 1616, STRATOS, Anderson 3X (n≈20) |
| **Turn-mill / Y-axis lathe** | **180** | LYNX 26Y, LYNX 2600Y, LYNX21LYSB, NEX-108Y, Takisawa TM (n≈10) |
| HAAS lathe (L) | 179 | CNC HAAS L (n=2) |
| **4-axis VMC** | **157** | DOOSAN DNM 5700 4X, DNM 6700 (n≈10) |
| GF/socket fusion (PP weld prep) | 142–162 | GF FUS, SOCKET FUS, WELD (n≈16) |
| **3-axis VMC** | **123** | CNCV FAN M/L/V, CNCV MAK, Makino, FANUC Robodrill (n≈45) |
| **2-axis lathe** | **113** | CNCL TAK, CNCL NAK, NEX-110Y, Nakamura SC-300 (n≈25) |
| Inspection | 99 | INSPECT*, LEAK TEST (n≈50) |
| Debur / Saw / Assy1 | 72 | DEBUR (n=56), SAW MCH, ASSY1 |
| Packaging | 63–139 | PKG (63), PKG CLN10K cleanroom (139) |
| Planning | 115 | PLANNING |

Rule: **rate = f(machine class) only.** If Feature-Recognition→Machine-Type gives
`cnc_lathe`→113, `cnc_lathe_milling`/turn-mill→180, `cnc_milling` 3-axis→123,
4-axis→157, 5-axis→274, router→181. Cleanroom pack (Lam/AMAT) →139 not 63.

## 2. Labor & GA (on top of machine burden)
- Direct **labor ≈ RM 20–24/hr** (operator), separate from machine burden;
  Labor$ in job cost ≈ labor_rate × run+setup hr. Use **RM 22/hr** default.
- Burden splits into **Labor Burden + Machine Burden + GA Burden** (job-cost
  "Burden" section). Observed split on complex jobs ≈ Labor 20 % / Machine 45 % /
  **GA 35 %** of total burden (ref 713-187739-236; GA can be the single largest
  line on low-material parts, e.g. 0200-02605 GA ≈ RM 59/pc).
- Practical roll-up (per piece), matches `methodology/03 §1`:
  `Cost/EA = Material/pc + Hardware/pc + Σ_op[(rate_machine+rate_labor)
  × (Setup_hr/qty + Run_min_pc/60)] × (1+GA%)`, GA% ≈ 0.30–0.45.
  Cross-check against job-cost printed Cost/EA when present.

## 3. What dominates cost (where to spend estimation effort)
- **Material + machine burden = 80–95 % of Cost/EA** every time. Tooling and
  labor are minor; GA is a fixed uplift.
- Big PEEK/PP **SHEET/PLATE** parts → material-dominated (e.g. 0041-62474 material
  ≈83 %; 0042-15176 ≈76 %; 713-A42978-022). Get stock size right first.
- Small dense **ROD** parts with many ops → machine-hour-dominated (e.g.
  713-187739-236 DNM hours, 0021-53926 197 min/pc). Get cycle time × k right.
- Setup is a per-job lump amortized over qty — material in §`setup_and_material.md`.

## 4. Profit / loss reality (the model must reproduce it)
36 priced parts: **29 profitable, 7 loss-making (~19 %)**, margin (price−costAct)/costAct
median **+58 %**, range **−51 % … +1900 %**.
- **Real losses** cluster in large/complex PEEK where actual machining over-ran the
  quote: 0042-15176 (−51 %), 713-187739-236 (−2 %, exemplar), 839-297424-004
  (−2 %), 713-A42978-022, 0041-14421. Drivers: setup/run actual ≫ estimate,
  quality re-work (INSPECT 20×, DEBUR 3–5× over), 5-axis/weld overruns.
- **Huge "profits"** are spec/IP-priced parts where price is set by the customer's
  part value, not machining cost (e.g. 839-219206-002 +1900 %, 713-142960-001
  +90 %, 1157-776-01). Do **not** infer cost from price for these.
- Therefore always emit two numbers: **quote-style** (what the shop would bid,
  estimate columns) and **true cost** (actual columns / your physics build).
  Flag when they diverge >15 % and state the likely driver.

## 5. Estimating a NEW part's cost (procedure)
1. Machine class per op → rate from §1. 2. Run_min_pc per op (`cycle_time_model.md`)
×k, + Setup_hr/qty (`setup_and_material.md`). 3. Material/pc from stock
(`setup_and_material.md`) + hardware from BOM. 4. Sum (machine+labor)·hr + material
+ hardware; ×(1+GA). 5. Compare to nearest analogue's Cost/EA in `parts/INDEX.md`;
they should agree ~25 %. 6. Add margin for quote; report ladder rung + ±band.
