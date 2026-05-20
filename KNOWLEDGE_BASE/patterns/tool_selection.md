# Pattern — Tool Selection by Feature & Material

Source: `extracted/tools.csv` (513 rows, 43 parts) cross-referenced with
`reference/operations_and_sequencing.md` feature→op chains. Supports the Tooling-
Selection pipeline step: (Machine, Material, Feature, Dim, Op) → tool family +
Ø + flutes + cut/tool length. Output `diameter_mm` and `flute_no` for FreeCAD.

## 1. Observed tool inventory (what the shop actually uses)
End mills dominate (≈220/513 rows). Plastics → **2–3 flute, sharp, uncoated**
(single-flute for small Ø PP); high helix; coatings rare.

| Feature / op | Tool family | Ø band mm | flutes | Notes |
|---|---|---|---|---|
| Top/datum face, fly | face mill / facemill | **45–80** | 3–6 | Ø80 45° on big rod (exemplar); Ø50 typical |
| Bulk roughing | chip-breaker end mill | **12–20** | 3 | high MRR; "GET" custom on PEEK |
| Rough pocket/profile | square end mill | **6–10** | 2–3 | leave 0.2–0.5 for finish |
| Finish wall/floor/profile | finish end mill | **6–10** | 2 | sharp, light ae, higher S |
| Small/detail features | end mill | **1.0–4** | 2 | derate (see cutting_parameters) |
| Corner / fillet | bull / corner-radius | 4–10 (R0.3–R2) | 4 | after finish |
| Chamfer / edge-break | chamfer mill / spot | **3** (3–20) | 1–4 | R0.05–0.30 note; 45°/50° special |
| Simple hole | jobber drill | **= hole Ø** (0.9–16) | – | spot Ø3–12 first |
| Deep hole d/Ø>3 | peck drill | = hole Ø | – | spot → peck (G83) |
| Precision bore/ID | drill→bore bar/ream | reamer **1–6** | – | ream 0.1–0.2 over drill |
| Tapped hole | tap-drill → tap | tap **M2.8–M6** | – | feed = pitch×rpm |
| Helicoil/STI hole | tap-drill → STI thread-mill | thread-mill **2.2–4.2** | 3 | insert at ASSY |
| Threaded hole (milled) | thread mill | **3.1–12.7** | 3 | preferred over tap on PEEK |
| Engrave P/N+rev | ball / engrave mill | **0.8** (0.8–10) | 2 | mandatory when drawing says so |
| Slot | slot/end mill or slitting saw | EM 3–10; saw **45** | 2–3 | thin slots → slitting saw |
| Dovetail / vise groove | straight EM relief → dovetail | dovetail **12–16** | 4 | relief first |
| OD/ID turn | turning insert (CNGG/DCGT) | – | – | rough then finish insert |
| Groove / face-groove | groove/parting blade | width **1.5–3** | – | |
| Cut-off (lathe) | parting blade | 3 | – | **last** op |

## 2. Selection rules (apply in order)
1. **Feature type → family** from the table (and the feature→op chain in
   `reference/operations_and_sequencing.md`; each feature may need spot+drill+ream
   etc., not one tool).
2. **Ø from the governing dimension:** hole tools = hole Ø; pocket/slot rougher ≤
   (smallest internal corner radius × 2) and ≤ pocket width; facer Ø ≈ 0.7–1.0 ×
   stock width (Ø80 on Ø90 rod). Finish EM ≤ rougher.
3. **Flutes by material:** PEEK/PP → 2–3 (use 2 for finish, 3 for chip-breaker
   rough; 1 for <Ø2 in PP). Never high-flute (chip packing, heat).
4. **Length by depth:** cut length ≥ feature depth; tool length minimal. **If
   stick-out/Ø > ~4 → derate feed/speed** (`cutting_parameters.md`) and flag as a
   long-tool extrapolation (AGENT.md rule).
5. **Reuse the analogue's exact tool** when a near part exists (scale Ø by the
   differing governing dim); only synthesize from this table when no analogue.
6. **Specials are real:** custom chip-breakers ("GET"), 45°/50° chamfer, corner-
   radius R0.5, dovetail, slitting saw appear on complex PEEK — include a special-
   tool line + its lead-cost note when geometry demands (see SPECIAL TOOLS PRs).

## 3. Count tools for complexity/setup proxies
`n_tools` per op drives setup time and tool-change cycle adders. Observed: Simple
lathe op ≈ 3–15 tools; Simple VMC op ≈ 5–8; Complex 4-axis op ≈ 24–26 (exemplar
OP20=26). Use distinct-tool count as a Complex/Simple discriminator and to size
the `tc_s` tool-change time in `cycle_time_model.md`.

→ Parameters for each chosen tool: `cutting_parameters.md`. Time: `cycle_time_model.md`.
