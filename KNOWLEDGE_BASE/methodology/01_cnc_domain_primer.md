# CNC Machining Domain Primer (for the estimator)

Just enough machining theory to reason about time & cost. Shop = Foresight Asia Pacific;
parts = semiconductor plastic components (PEEK/POM/PP) for Lam Research.

## Process flow of a job
`PLANNING → SAW (cut billet) → CNC OP10/OP20/OP30… (each = one fixturing/setup) →
DEBUR → INSPECT → ASSY (press helicoils/inserts) → CLEAN → PACKAGE`. Each CNC "OP" is a
**setup**: part re-fixtured in a new orientation; has its own Setup Sheet + NC program.

## Machine types (→ "Machine Type Selection")
- **CNC lathe** (turning): rotates the part; for round/axisymmetric → `part_type=cnc_lathe`.
- **Turn-mill** (lathe + driven tools, Y/C axis): turned part with milled features →
  `part_type=cnc_lathe_milling` (e.g. DOOSAN 2600Y, NEX-110Y in this data).
- **CNC mill / VMC** (3/4/5-axis vertical machining center): prismatic parts →
  `part_type=cnc_milling` (e.g. DOOSAN **DNM 5700**, 4-axis here).
- **Router**: large/thin plate work, lighter cuts; also `cnc_milling` candidate.
Selection: lathe→lathe only; lathe-milling→turn-mill only; milling→router **or** VMC
(choose by size, precision, qty — let the user pick in UI).

## Operations & features
- **Facing / fly cut** — flatten top; large face/fly mill.
- **Roughing** — bulk material removal; large/“chip-breaker” end mills, big stepdown.
- **Finishing** — final walls/floors/profile to tolerance; small stepover, sharp tool.
- **Pocket / slot / contour / profile** — 2.5D milled features.
- **Drilling** — holes; spot → drill → (peck for deep) → ream/bore if tight.
- **Tapping / thread-milling** — threads; here often **M5 helicoil** (thread-mill +
  insert pressed in ASSY).
- **Chamfer / deburr / fillet / corner-radius** — edge breaks (drawing note: R0.05–0.30).
- **Turning ops** (lathe): OD/ID rough & finish, grooving, threading, **parting/cut-off**.
- **Engraving** — part number + revision (mandatory on Lam parts).

## Cutting fundamentals (drives time)
- `Vc` cutting speed (m/min) → spindle `n = 1000·Vc/(π·D)` RPM.
- `fz` feed/tooth (mm); table feed `F = fz·z·n` (mm/min), z = flutes.
- `ap` axial depth (stepdown), `ae` radial width (stepover).
- **Material Removal Rate** `MRR = ae·ap·F` (mm³/min). Rough = max MRR; finish = surface
  quality. Cutting time ≈ volume/MRR (rough) or area·passes/F (finish).
- Plastics specifics: low cutting force but **heat-sensitive** (PEEK melts ~343 °C, PP
  soft & gummy, POM good machinability). Use sharp **uncoated** tools, **2–3 flutes**
  (chip evacuation), high RPM, climb milling, air/mist. Thin walls & long reach →
  chatter/deflection → lighter cuts, longer time.

## Workholding & setup
Soft vs **hard jaws**, vises, custom fixtures (NRE FIXTURE line in Job Cost). Clamping
force noted (e.g. 100 psi). More setups (OPs) = more total setup hours & re-fixture
risk. Setup is **per-job, amortized over lot Qty** — dominant for small lots.

## Tolerances & quality (cost multipliers)
Tight tolerances/finish → extra semi-finish & finish passes, slower feeds, inspection
(INSPECTIPQ/INSPECTASY work centers), possible rework (REWORK files seen). Lam specs:
cleanliness, packaging, engraving, go/no-go thread gauging — all add labor work-centers.

## Key terms
OP = operation/setup · WCS/G54 = work offset · CL/TL/NL = cut/tool/neck length ·
FL = flutes · EM = end mill · DOC = depth of cut · MRR = material removal rate ·
NRE = non-recurring engineering (fixtures/special tools) · FA = first article.
