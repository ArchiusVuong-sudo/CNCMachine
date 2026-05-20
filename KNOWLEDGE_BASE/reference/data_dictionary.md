# Data Dictionary

Every field seen in the corpus, its meaning, units, and where it comes from. Units are
**metric** (mm, mm/min, RPM) unless noted. Currency = **RM** (Malaysian Ringgit);
occasional **$** (USD) on special-tool/NRE lines.

---

## A. Setup Sheet — metadata block

| Field | Meaning | Notes |
|---|---|---|
| Date | sheet authored date | |
| Machine Group / OP | operation number | OP10, OP20, OP30… = setup/fixturing sequence |
| Part Number | part + revision | e.g. `713-A05592-003 REV-B` |
| NC File Number | program O-number | matches `O####` in the `.nc` |
| WCS | work coordinate system | G54/G55… (which fixture offset) |
| Programmer | CAM programmer name | |
| Z stock | stock length/allowance on Z | mm or "N/A" |
| **Machine Name** | the physical machine | e.g. `DOOSAN 2600Y(TURNMILL)`, `DOOSAN DNM5700`, `NEX-110Y` → drives machine-type & rate |
| Clamping Force | workholding pressure | e.g. `100psi` |
| jaws type | soft/hard jaws / vise / fixture | affects setup time & rigidity |
| **Total cycle time** | per-piece machining time for this OP | e.g. `7MIN` — compare to NC est & Job Cost Run |
| **Setup time** | one-time fixturing/proving time | e.g. `1.0Hrs` — compare to Job Cost Setup |

## B. Setup Sheet — tool table (the core "training" rows)

Columns A–P (use `_tools/xls_dump.py`, column letters preserved):

| Col | Field | Meaning / units | Used for |
|---|---|---|---|
| A | Port NO | turret/carousel station # | |
| B | TI Manufacturor | tool/insert maker (Mitsubishi, WARK, ZCCT, SUMITOMO, TUNGALOY, DURA, GET…) | tooling cost source |
| C | Holder Mill | milling holder id | |
| D | Holder Lathe | lathe holder id (DCLNR2020K12, ER16, A05.0020…) | |
| E | Insert | insert designation (e.g. `CNGG120404-MJ HTi10`) | tooling cost; ISO insert code |
| F | Tool Name | descriptive (OD Turn 80°, PARTING, ID FINISH, DRILL BIT, END MILL…) | feature/op map |
| G | **Tool Dia.** | cutting Ø, mm | → FreeCAD; tool selection |
| H | **Cut length** | flute/cutting length, mm | reach; tool selection |
| I | **Tool Length** | total/stick-out length, mm | reach; rigidity |
| J | **Tool Flute** | # flutes/teeth | → FreeCAD; feed = fz·z·rpm |
| K | Z-min | deepest Z reached, mm (neg) | depth of feature |
| L | Operation type | op + sequence token `N#-<op>` (e.g. `N2-OD rough`) | **routing/sequence** |
| M | Comment | free text | |
| N | **FeedRate Mill** | milling feed, **mm/min** | parameter setting |
| O | **Feedrate Lathe** | turning feed, **mm/rev** | parameter setting |
| P | **Spindle speed** | RPM (turning: may be CSS) | parameter setting |

> Sequence: the `N#` numbers in L/M define machining order within the OP
> (`N1` first). This is the "Seq + Feature Type" the routing model learns from.

## C. NC G-code (`.nc`, Fanuc / Mastercam post)

| Token | Meaning |
|---|---|
| `O####` | program number (= Setup Sheet "NC File Number") |
| `(MACHINE NAME - …)` | target machine (e.g. `DOOSAN DNM5700 FANUC 4 AXIS VMC`) |
| `( T# \| H# \| D# \|<name>\|Z DEPTH: z)` | TOOL LIST header: tool#, len-offset, dia-offset, **tool description**, max depth |
| `( <TEXT> )` before a tool change | **operation/feature name** (ROUGH FLY SURFACE, FINISH PROFILE, DRILL5.2 FOR M5 HELICOIL…) |
| `T# M6` | tool change to T# |
| `S####` | spindle speed (RPM) |
| `F###.` | feed (mm/min in G94; mm/rev in G95) |
| `G0` | rapid move; `G1` linear feed; `G2/G3` CW/CCW arc |
| `G43 H#` | tool-length comp on |
| `G81/82/83/73` … `G80` | drilling canned cycle … cancel |
| `G54..G59` | work offset (which fixturing/part on table) |
| `M3/M4/M5` | spindle on CW/CCW/off; `M8/M9` coolant |
| `G91 G28/G30` | return to home (between ops) |

Tool-name grammar (milling): `<C|P>-<RF|F>-<dia> MM X <fluteLen>-<#FL>-<coat/brand>-<TYPE>`
where C=carbide, P=?, RF=rough, F=finish, e.g. `C-RF-10 MM X 35-2FL-UNC-END MILL` =
carbide rough 10 mm Ø, 35 mm flute, 2 flutes, uncoated, end mill. Also seen: `CL`=cut
length, `TL`=tool length, `NL`=neck length, `R`=corner radius (`10XR1`=Ø10 corner-R1
bull mill), drills as `9.6MMCARBIDE DRILL CL45TL90`. → `reference/tooling.md`.

## D. Job Cost - Detail (`<part>*.pdf`) — calibration ground truth

Header: Job, Part, Rev, Customer, Description, Order/Make Qty, **Unit Price** (RM/each),
Status. Then sections:

**Labor** — per Work Center / Operation row:
`St | Work Center | Operation | Setup Hours Est | Setup Act | Run Hours Est | Run Act |
Labor$ Est | Labor$ Act | Variance | QtyRun | Scrap`
- Setup/Run **Hours are TOTAL for the job** → ÷ Order Qty for per-piece.
- Work centers seen: PLANNING, PRINT, MAT PICK, SAW MCH, **CNCV MAK**, **DNM 5700 4X**,
  DEBUR, INSPECTIPQ, ASSY1, INSPECTASY, PKG CLN10K, ROUTER, etc.

**Burden** — per Work Center: `Hours Est/Act | Burden$ Est/Act`. **Burden$ ÷ Hours =
machine/work-center hourly rate.** Split totals: Labor Burden, Machine Burden, GA Burden.

**Material** — per line: `St | Description | PO | Type(H=hardware,R=raw) | Buy/Pick |
Est$ | Act$ | Variance | EstQty | ActQty | UoM(ft, each…)`. Raw stock line e.g.
`PEEK 450G NAT 90MM ROD … RM23,232.00 … 13.12 ft` (for the whole job).

**Summary**: Total Cost, Cost/EA, Revenue, Profit, Profit%. Estimate vs Actual columns.

## E. BOM (`BOM_*.csv`, UTF-16)

Bill of purchased items: BOM Level, Line Item, PART Number, Part Name, Rev, Qty, UoM,
Critical flag, Material Group, MFG name/part#. Lists **inserts/fasteners/spec docs**
(e.g. `INSR,M5 X.8 THD … NITRONIC 60`), **not** the raw machined billet.

## F. Derived / computed fields (we produce these)

| Field | Definition |
|---|---|
| `cycle_time_pc_min` | per-piece machining time (Setup Sheet stated, or NC-analyzed ×calib) |
| `run_min_pc` | Job Cost Run Hours ÷ Order Qty × 60 — **actual truth** |
| `setup_hr` | Job Cost Setup Hours (per job, not per pc) |
| `machine_rate_rm_hr` | Burden$ ÷ Burden Hours for that work center |
| `material_cost_pc` | raw-stock line Act$ ÷ Order Qty (+ hardware) |
| `stock` | shape+size: `ROD Ø90 × L`, `PLATE a×b×c` (drawing/Job Cost) |
| `n_tools`, `n_ops` | tool & operation counts (NC / setup sheet) |
| `complexity` | folder label Simple/Complex + quantitative proxies |
| `removal_cc` | (stock volume − part volume), cm³ — MRR basis |
