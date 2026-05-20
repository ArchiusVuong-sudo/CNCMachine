# Phase 3 — Part Extraction Brief (read this fully before starting)

You are a Phase-3 extraction sub-agent for the CNC Time & Cost Estimation KB.
Your job: turn an assigned set of part folders into (a) one filled
`parts/<part>.md` record each, and (b) appended rows in your **own** CSV shards.
Work factually, cite source files for non-obvious numbers, units metric, currency RM.

## 0. Orient first (read these once)
- `E:\data\KNOWLEDGE_BASE\AGENT.md` — estimator operating manual (the *why*).
- `E:\data\KNOWLEDGE_BASE\methodology\03_cost_time_model.md` — cost/time formulas.
- `E:\data\KNOWLEDGE_BASE\methodology\02_data_sources.md` — the 5 sources & extraction.
- `E:\data\KNOWLEDGE_BASE\reference\data_dictionary.md` — every field/column meaning.
- `E:\data\KNOWLEDGE_BASE\parts\_TEMPLATE.md` — the record schema you must fill.
- `E:\data\KNOWLEDGE_BASE\parts\713-187739-236.md` — **gold-standard worked example**.
  Match its altitude, compactness, and table style exactly.

## 1. The 5 data sources (per part folder) & where they hide
Part folders live under
`E:\data\OneDrive_2026-05-14\Fine Tuning Raw Data\{Complex|Simple} Part (PEEK,DELRIN,PP)\{PEEK|Polypropylene (PP)}\<part>\`.

| Source | What it gives | Typical location | Tool |
|---|---|---|---|
| **Job Cost - Detail** PDF | cost & time GROUND TRUTH (Setup/Run hrs E/A, Labor$, Burden$, Material, qty, price) | `<part>\<part>.pdf` (folder root) | `jobcost.py rows` |
| **Setup Sheet** xls/xlsx (preferred) or PDF | routing, tool list, feeds/speeds, sequence Nx | `PROGRAMMING\...\SETUP\*.xls*`, `MODEL\Setup Sheet\*`, or `*SETUP*.pdf` / `*TOOL LIST*.pdf` near NC | `xls_dump.py`; PDF→`pdf_tool.py` |
| **NC G-code** | physics cycle time, real F/S, toolpath | `PROGRAMMING\NC\*.NC/.nc/.min/.eia/.MAC/.tap` | `nc_analyze.py` |
| **Customer drawing** PDF | geometry, material, tolerances, finish, engraving | `ORIGINAL FILES\*<part>*<rev>*.pdf` (NOT the BOM) | `pdf_tool.py text` then `crop`/`render` + VISION |
| **BOM** csv | purchased hardware (helicoils/inserts), specs | `ORIGINAL FILES\BOM_*.csv` | `bom.py` |

**Heterogeneity warnings (data is messy — expect gaps):**
- Job Cost PDF is the most reliable; it is almost always present. Start there.
- Setup sheets may be `.xls` (old BIFF), `.xlsx`, or only scanned PDFs. Some parts
  have none — then derive routing from Job Cost ops + NC + drawing.
- NC: only raw text G-code works. **Skip `.mcam`, `.X_T`, `.stp`, `.zip`, `.sldprt`.**
  **Ignore any path containing `OBSOLETE`, `OLD`, `BACKUP`, `do not use`, `rejected`.**
  Some parts have no usable G-code → record NC as "not available", rely on Job Cost.
- Pick the drawing matching the part number & the Job Cost Rev. Read it with VISION
  (render/crop at 300 dpi); title block + notes give material, stock, tol, engraving.
- Customer may not be Lam Research (e.g. Ultra Clean) — record the actual customer.

## 2. Exact tool commands (Bash tool; tools in `E:\data\KNOWLEDGE_BASE\_tools`)
```
python E:/data/KNOWLEDGE_BASE/_tools/jobcost.py rows "<part.pdf>"
python E:/data/KNOWLEDGE_BASE/_tools/jobcost.py summary "<part.pdf>"
python E:/data/KNOWLEDGE_BASE/_tools/xls_dump.py "<setup.xls>" 200
python E:/data/KNOWLEDGE_BASE/_tools/nc_analyze.py "<file.nc>"
python E:/data/KNOWLEDGE_BASE/_tools/pdf_tool.py text "<draw.pdf>" 12000
python E:/data/KNOWLEDGE_BASE/_tools/pdf_tool.py render "<draw.pdf>" "E:/data/KNOWLEDGE_BASE/_research/_imgwork/<part>" 300 <tag>
python E:/data/KNOWLEDGE_BASE/_tools/pdf_tool.py crop "<draw.pdf>" <page0> 0.0 0.0 0.5 0.5 300 "E:/data/KNOWLEDGE_BASE/_research/_imgwork/<part>" <tag>_tl
```
Then **Read** the produced PNG to actually see faint drawings/setup sheets. Always
pass an explicit existing outdir (use the `_imgwork/<part>` path above). Crop quadrants
(tl/tr/bl/br as 0–1 fractions) when full-page text is faint or vector-only.
To find files, use Glob/Grep, not manual ls of huge trees. Quote paths (spaces).

## 3. What to pull from each source (minimum bar)
- **Job Cost (must):** part/rev/desc, customer, job#, order qty, completed qty,
  unit price, per-OP work-center + Setup hrs (E/A) + Run hrs (E/A) → per-piece run
  min = RunHrs_Act/qty*60; Labor$ E/A; Burden hrs & $ per work center → rate RM/hr =
  Burden$ ÷ Burden hr; Material line (description = stock form/size!) E/A and qty;
  Labor/Machine/GA burden totals; Cost/EA if shown else derive; date/status.
- **Setup sheet:** machine, OP, every tool row (seq Nx, tool name, Ø, flutes, cut
  len, tool len, Z-min, feed mm/min or mm/rev, speed RPM, stepover, stepdown),
  feature/op per tool, work-offsets. Old BIFF `.xls` → `xls_dump.py` keeps columns.
- **NC:** per-op tool, F, S, toolpath length, estimated cycle min; note any
  `-2PC-`/`4PC`/`-NPC-` multi-piece divisor; sum est min vs Job Cost actual → k.
- **Drawing (VISION):** envelope L×W×T or Ø×L, material spec, stock if noted, key
  tolerances, surface finish, engraving P/N+rev, cleanliness/packaging specs,
  feature inventory (pockets/holes/tapped/bores/slots/threads/profile counts).
- **BOM:** helicoil/insert P/N & qty per piece, any special hardware → hardware/pc.

Derive: removal volume (stock envelope − rough part volume estimate), per-machine
rate, per-piece material cost (Material$ ÷ qty), profit/loss (UnitPrice − Cost/EA).
Compute Cost/EA = (Labor$ + LaborBurden + MachineBurden + GABurden + Material) ÷ qty
(use Actual where present; also note Estimate). Cross-check with any printed Cost/EA.

## 4. Write your per-part record
Create `E:\data\KNOWLEDGE_BASE\parts\<part>.md` using `_TEMPLATE.md`'s exact
section order, styled like the `713-187739-236.md` exemplar (compact tables, cite
source paths in "Sources used", state Confidence/gaps honestly). One file per part.

## 5. Append to YOUR shard CSVs (never the merged files)
Write to `E:\data\KNOWLEDGE_BASE\extracted\_shards\<BATCH>_{parts,tools,operations,jobcost}.csv`
where `<BATCH>` is the batch letter you were given. **Create these 4 files** (with
the header rows below) if absent, then append. Do NOT touch `extracted\*.csv`
(the parent merges shards later). One row discipline = one CSV line, comma-sep,
wrap any field containing a comma in double quotes.

Headers (exact):
- parts.csv: `part_number,rev,class,material,part_type,machines,order_qty,job,envelope_mm,stock_form,stock_size,removal_cc,n_ops,n_tools,n_features,unit_price_rm,cost_ea_rm_est,cost_ea_rm_act,material_pc_rm,total_run_min_pc,total_setup_hr,source_folder,notes`
- jobcost.csv: `part_number,job,op,work_center,machine,setup_hr_est,setup_hr_act,run_hr_est,run_hr_act,run_min_pc_act,labor_rm_est,labor_rm_act,burden_hr,burden_rm,rate_rm_hr,qty,date`
- tools.csv: `part_number,op,seq,feature_or_op,tool_name,tool_type,dia_mm,flutes,cut_len_mm,tool_len_mm,zmin_mm,feed_mm_min,feed_mm_rev,speed_rpm,stepover_mm,stepdown_mm,material,machine,source`
- operations.csv: `part_number,op,machine,feature,operation_type,seq_index,run_min_pc_est,run_min_pc_act,nc_est_min,nc_calib_k,n_tools,notes`
Leave a cell blank (still keep the comma) when a value is genuinely unavailable;
never invent. Put short caveats in `notes`.

## 6. Quality bar & what to return
- Triangulate: Job Cost (truth) vs Setup sheet (plan) vs NC (physics) vs drawing
  (geometry). Flag disagreements in the record's notes, don't hide them.
- If a source is missing, say so and proceed (Job Cost alone still yields a record).
- Keep raw dumps OUT of your final message. Return ONLY: per part — one line with
  part#, class/material, qty, job, unit price, Cost/EA (E/A), key stock/feature
  facts, NC k if found, and confidence. Then list any parts with serious data gaps.
  This concise summary is all the parent needs.
