# Data Sources — what each file is & how to extract it

The five high-signal sources and the exact tool to read each (all in `_tools/`; run with
`python KNOWLEDGE_BASE/_tools/<tool> ...`). Field meanings → `reference/data_dictionary.md`.
Skip `.mcam` (huge binary CAM project) and large `.zip/.rar` unless a specific need.

| # | Source | Path pattern | Tool / command | Yields |
|---|---|---|---|---|
| 1 | **Job Cost - Detail** | `<part>/<part>*.pdf` (root) | `jobcost.py rows "<pdf>"` | Setup/Run hrs & Labor$ Est-vs-Act per work-center; Burden$/hr; Material$ & stock; Unit Price; Cost/EA; Profit |
| 2 | **Setup Sheet** | `…/PROGRAMMING/**/SETUP*/…xls(x)` or `.pdf` | `xls_dump.py "<xls>"`; PDF→`pdf_tool.py crop` | machine, jaws, clamp, cycle/setup time + tool table (Ø, flutes, cut/tool len, op, seq N#, feed, speed) |
| 3 | **NC G-code** | `…/PROGRAMMING/NC/**/*.nc` (prefer non-OBSOLETE, latest date) | `nc_analyze.py "<nc>" [rapid] [tc_s]` | tools, per-op feed/speed/depth, toolpath length, **estimated cycle time** |
| 4 | **Customer drawing** | `ORIGINAL FILES/*_<rev>*.PDF` | `pdf_tool.py text`; then `crop <pg> x0 y0 x1 y1 300 <out> tag` for title block/notes/views | material note, envelope dims, tolerances, finish, engraving, critical dims |
| 5 | **BOM** | `ORIGINAL FILES/BOM_*.csv` | `bom.py "<csv>"` | purchased hardware/inserts/specs (not raw stock) |

Supporting (read only if needed): `SPECIAL TOOLS/*.pdf` + `PURCHASE REQUISITION*.xlsx`
(custom-tool price → tooling cost); `ORIGINAL FILES/*.msg` (RFQ email — quoted price &
qty context); `*.pptx` (fabrication instructions / quality cases); `CNC Program
checklist.xlsx` (QC, confirms ops). CAD `.stp/.sldprt/.jt` → geometry/volume if a
STEP reader is added later (not required for the model).

## Extraction order per part (Phase 3 recipe)
1. `jobcost.py rows` on every root `<part>*.pdf` → cost/time truth (capture **both**
   Estimate & Actual; note Qty; if multiple PDFs they're separate jobs/revisions).
2. `pdf_tool.py text` the customer drawing; `crop` the title block + notes region
   @300 dpi (full page is too faint) → material, stock, tolerance class, special notes.
3. `xls_dump.py` each Setup Sheet (latest, non-OBSOLETE) → routing/tooling/params per OP.
4. `nc_analyze.py` the matching latest `.nc` per OP → independent cycle-time + feeds.
5. `bom.py` the BOM → hardware per piece.
6. Write `parts/<part>.md` (template in README) + append rows to `extracted/*.csv`.

## Gotchas (learned)
- Many folders have `OBSOLETE/`, `OK-1PC/`, dated dirs, REV duplicates → pick the
  **latest validated** (prefer `OK-1PC`/proven, newest date in filename); record which.
- NC filenames may say `-2PC-`/`4PC` = N parts per cycle → divide cycle time by N.
- `.xls` = old BIFF (use xlrd path in `xls_dump.py`); `.xlsx` = openpyxl path (auto).
- BOM CSV is **UTF-16** with wide-spaced glyphs — only `bom.py` decodes it right.
- Drawing PDFs are vector & faint: text layer often only has document-control; the real
  dims are graphical → must render/crop and read with vision.
- Job Cost text via plain extraction is positionally scrambled → **use `jobcost.py
  rows`** (Y-coordinate clustering), not `pdf_tool.py text`.
- Currency mostly **RM**; special tools/NRE sometimes **USD ($)** — keep the symbol.
