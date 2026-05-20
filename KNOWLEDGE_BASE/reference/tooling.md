# Tooling Reference & Naming Grammar

Supports **Tooling Selection**. Tools appear in (a) Setup Sheet tool table (cols B–J),
(b) NC `TOOL LIST` header. Decode names → (type, Ø, flute length, #flutes, corner R,
coating) for selection & cost.

## Milling tool-name grammar (NC TOOL LIST / Setup Sheet)
`<C|P>-<RF|F>-<DIA> MM X <FLUTE_LEN>-<n>FL-<COAT/BRAND>-<TYPE>`
- `C` = carbide, `P` = (PCD/poly or alt substrate — verify per case).
- `RF` = rough, `F` = finish.
- `DIA` mm, `FLUTE_LEN` mm, `nFL` = flutes, `UNC` = uncoated.
- TYPE ∈ {END MILL, BALL MILL, BULL MILL, FACEMILL, CHAMFER MILL, SPOT DRILL,
  CORNER RADIUS, THREAD MILL, DRILL}.
- Examples:
  - `C-RF-80 MM-45DEG LEAD-FACEMILL` → carbide rough Ø80 45° lead face mill.
  - `C-F-10 MM X 35-2FL-UNC-END MILL` → carbide finish Ø10, 35 flute len, 2FL, uncoated.
  - `10XR1 MM X 25-4FL-BULL MILL` → Ø10 corner-radius 1 mm, 25 len, 4FL bull mill.
  - `R0.5 -TIP 1.5 CORNERRADIUS TOOL 4MM` → corner-radius/fillet tool R0.5.
  - `9.6MMCARBIDE DRILL CL45TL90` → Ø9.6 carbide drill, cut-len 45, tool-len 90.
  - `M5X0.8 D3.9CL10ND2.7NL25 … THREAD MILL FULL PITCH` → M5×0.8 thread mill.
- Suffixes: `CL`=cut length, `TL`=tool length, `NL`=neck length, `ND`=neck dia,
  `R`=corner radius.

## Lathe tooling (turn-mill Setup Sheets)
Holders e.g. `DCLNR2020K12` (ISO turning holder), `SVJCR-2525M-11`, `ER16` (collet),
`MGSR/MGIVR` (grooving), `CTER…` (parting). Inserts ISO-coded e.g.
`CNGG120404-MJ HTi10`, `VCGX110302-LC`, `DGM 3-020-15R AH725`. Names in col F:
OD Turn 80°, OD finish, ID rough/finish, ID groove, ID thread, PARTING, DRILL BIT,
STOPPER. Manufacturers: Mitsubishi, WALTER, ZCCT, SUMITOMO, TUNGALOY, WARK, DURA, GET.

## Feature → tool selection heuristics (seed; refine in patterns/tool_selection.md)
| Feature | Typical tool | Sizing rule |
|---|---|---|
| Top face / fly | face/fly mill Ø50–80 | as large as fits face; ae≈0.7Ø |
| Bulk pocket rough | "chip breaker" EM Ø12–20, 3FL | largest that clears smallest internal R; deep ap |
| Rest-rough / re-rough | EM Ø4–10, 2FL | reaches corners the rougher missed |
| Wall/floor finish | EM Ø6–10, 2FL finish | Ø ≤ 2× min concave radius; light ae |
| Corner fillet | bull/corner-radius tool, R = fillet | R matches drawing fillet |
| Slot / dovetail / groove | width-matched EM / form tool | tool = slot width (dovetail = form tool) |
| Hole | spot drill → twist drill (carbide) | drill Ø = hole Ø (or tap-drill); peck if depth/Ø>3 |
| Tapped/helicoil | spot → tap-drill → thread mill (or tap) | tap-drill per thread spec; +insert in ASSY |
| Chamfer / edge break | chamfer mill (90°/120°) / spot | per note R0.05–0.30 |
| Engrave part # | small ball/engrave Ø0.8–2 | mandatory (Lam Note 6) |
| Turning OD/ID | turn insert (CNMG/VCGX…) + holder | by part Ø & access |
| Part-off | parting blade | groove/parting holder |

Reach rule: pick shortest tool with `tool_length ≥ feature_depth + clearance`; if
`depth/Ø > ~4` use necked/long tool and derate feed & speed (see cutting_parameters).
Plastics → prefer **2–3 flutes** for chip clearance; more flutes only for finishing.

## Tooling cost
- Perishable wear cost per part ≈ small; estimate as % of machine cost or per-edge life.
- **Special/custom tools**: `MODEL/SPECIAL TOOLS/` drawings + `PURCHASE REQUISITION
  FORM*.xlsx` → one-off price (USD/RM); amortize over lot or expected tool life; appears
  as NRE / tooling line. Capture price in `extracted/tools.csv` when present.
