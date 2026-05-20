# RESEARCH LOG — CNC Time & Cost Estimation Knowledge Base

> **This is the working-memory / recovery anchor.** If context is lost, READ THIS FIRST,
> then `KNOWLEDGE_BASE/README.md`. It records what was learned, what is where, what is
> validated, and what remains. Built per Anthropic "Effective context engineering for AI
> agents": persist findings to files, retrieve just-in-time, use sub-agents for fan-out.

Last updated: 2026-05-20 (Phase 1–4 complete: 39 parts extracted, patterns synthesized; Phase 5 finalizing)

---

## 1. THE GOAL (do not lose sight of this)

Build a knowledge base that lets a future agent **estimate machining TIME and COST per
feature** for a CNC part — *including parts/features that are NOT in this dataset*, by
applying patterns learned here. Pipeline the estimator plugs into:

Feature Recognition → **Machine Type Selection** → **Machine Routing/Sequencing** →
**Tooling Selection** → **Machine Parameter Setting** → **TIME & COST ESTIMATION (our job)**.

The estimator must generalize: given (feature type, dimensions, material, part_type,
orientation) → predict (operation sequence, tools, feeds/speeds, cycle time, cost),
even when the exact part has never been seen.

## 2. WHAT THE DATA IS

A precision CNC job-shop's raw data: **FORESIGHT ASIA PACIFIC SDN BHD** (Malaysia, costs
in RM), machining plastic parts (PEEK, Delrin/POM, Polypropylene) mostly for **Lam
Research** (semiconductor equipment). Two OneDrive dumps under `E:\data`:

- `OneDrive_2026-05-08/SETUP SHEET/` — 6 PDFs, the reference part's setup+tool sheets.
- `OneDrive_2026-05-14/Fine Tuning Raw Data/` — the main corpus:
  - `713-187739-236/` — duplicate of the canonical reference part (top level).
  - `Complex Part (PEEK,DELRIN,PP)/{PEEK,Polypropylene (PP)}/<part>/`
  - `Simple Part (PEEK,DELRIN,PP)/{PEEK,Polypropylene (PP)}/<part>/`

~37 distinct parts. Split **Simple vs Complex** × **PEEK vs PP** (Delrin appears in
naming but folders are PEEK/PP). File-type counts: 635 pdf, 219 nc, 131 mcam, 54 xlsx,
28 xls, plus stp/sldprt/jt/igs CAD, msg (RFQ emails), pptx (fab instructions).

### Per-part folder anatomy (consistent)
- `<part>.pdf` (and `<part>-1.pdf`…) → **Job Cost - Detail** report = COST/TIME GROUND TRUTH.
- `ORIGINAL FILES/` → customer drawing PDF, STEP/JT/SLDPRT CAD, `BOM_*.csv`, RFQ `.msg`.
- `MODEL/` → CAD, `SPECIAL TOOLS/` (custom tool drawings + purchase requisition xlsx).
- `PROGRAMMING/`
  - `GEO/` → Mastercam `.mcam` (large binary CAM project — DO NOT parse, too big).
  - `NC/` → Fanuc G-code `.nc` (often `OBSOLETE/`, `OK-1PC/`, dated subfolders).
  - `NC/SETUP` or `SETUP SHEET/` → **Setup Sheet** xls/xlsx/pdf = ROUTING/TOOLING/PARAMS.
  - `Tool List` pdf/xls; `CNC Program checklist.xlsx` (QC).

## 3. THE FIVE DATA SOURCES (validated extraction methods)

| Source | Holds | Tool (in `_tools/`) | Status |
|---|---|---|---|
| **Customer drawing** PDF | geometry, dims, **material note**, tolerances, finish, engraving | `pdf_tool.py crop` @300dpi (full page too faint) | ✅ |
| **BOM** `*.csv` | purchased hardware/inserts/specs (NOT raw stock) | `bom.py` (UTF-16) | ✅ |
| **Setup Sheet** xls/xlsx/pdf | per-OP machine, jaws, clamp, cycle/setup time + **tool table** | `xls_dump.py`; pdf via crop | ✅ |
| **NC G-code** `.nc` | exact tools, feeds(F), speeds(S), depths, toolpaths → cycle time | `nc_analyze.py` | ✅ |
| **Job Cost - Detail** PDF | **Setup/Run hrs & Labor$ Est-vs-Actual per work-center; Burden $/hr; Material$; Unit Price** | `jobcost.py rows` | ✅ |

All tools tested on reference part 713-187739-236. `jobcost.py rows` reconstructs the
positional table via Y-clustering — works perfectly. `nc_analyze.py` cycle time tracks
Job Cost actuals (OP10 est 3.0 min vs actual 3.3 min/pc) modulo a calibration factor
(no accel/decel; multi-piece programs note "2PC" in filename → divide).

## 4. KEY SCHEMA — SETUP SHEET TOOL TABLE (the "training data set")

Template "Setup Sheet" (xlsx, e.g. 713-A05592-003, 0022-42142). Header row then tools:

`A Port NO | B TI Manufacturor | C Holder Mill | D Holder Lathe | E Insert |
F Tool Name | G Tool Dia. | H Cut length | I Tool Length | J Tool Flute |
K Z-min | L Operation type | M Comment | N FeedRate Mill | O Feedrate Lathe | P Spindle speed`

Metadata block: Date, Machine Group (OP10/20…), Part Number, NC File #, WCS (G54…),
Programmer, Z stock, **Machine Name** (e.g. "DOOSAN 2600Y(TURNMILL)"), Clamping Force,
jaws type, **Total cycle time**, **Setup time**. Sequence encoded as `N1,N2,…` in the
Operation/Comment cell (e.g. `N1-STOPPER, N2-OD rough, …, N11-Parting`). Older
"CNC MILL" template (2017, e.g. 0041-62474) stores tools as embedded image → use vision.

→ Full field definitions: `reference/data_dictionary.md`.

## 5. KEY FINDING — COST MODEL STRUCTURE (from Job Cost - Detail)

Per-piece cost = **Material + Labor$ + Labor Burden + Machine Burden + GA Burden**.
The **Burden** table gives **machine hourly rates directly**. Reference part 10102R18:

- WC **DNM 5700 4X** (Doosan VMC): 37.5 burden-hr → RM5,887.50 ⇒ **RM157/hr**.
  Run 36.0 hr / 60 pc = **36 min/pc** for OP20 and OP30 each.
- SAW MCH RM72/hr; CNCV MAK RM123/hr; DEBUR RM72/hr (labor-type WCs).
- Labor rate ≈ RM20/hr (Labor$ 750 / 37.5 hr).
- Material: "PEEK 450G NAT 90MM ROD" RM23,232 / 60 pc = **RM387/pc** (13.12 ft / 60 ≈
  66.7 mm of Ø90 rod per piece); + M5 Nitronic helicoil insert RM9.80/pc.
- Cost/EA RM638.66 vs Unit Price RM623.61 → slight loss (real quoting data!).
- Columns: **Estimate = the shop's original quote; Actual = realized.** Both are gold:
  Estimate teaches "how they quote"; Actual teaches "true time/cost".

→ Full model & rate table: `methodology/03_cost_time_model.md`, `reference/machines.md`.

## 6. REFERENCE PART — 713-187739-236 (the canonical example)

"MT, CLAMP, PULL DOWN, DBL ACT, SQR", Lam Research, **Victrex PEEK 450G natural**,
Ø90 mm rod stock, qty 60, job 10102R18. Complex prismatic part. Route: PLANNING → SAW
→ CNCV MAK (OP10: fly face, outline, dovetail, slot) → DNM5700 4X (OP20 & OP30: faces,
drills, pockets, bores, M5 helicoil threads, fillets, chamfers — ~26 tools) → DEBUR →
INSPECT → ASSY (install helicoils) → PKG. NC OP20 uses facemill, end mills 4/6/10/12 mm
(2/3/4FL), 20 mm 3FL chip-breaker rougher, carbide drills 4.2/5/5.2/9.6 mm, M5x0.8
thread mill, corner-radius/bull mills, spot drills. Tool-name grammar decoded in
`reference/tooling.md`.

## 7. METHODOLOGY DECISIONS (context engineering)

- **Sub-agents for fan-out (Phase 3):** one agent per part-folder; it runs `_tools/`
  scripts, returns ONLY a filled per-part record (`parts/<part>.md`) + appends CSV rows
  to `extracted/`. Detailed file reading stays in the sub-agent's context, not mine.
- **Just-in-time:** KB stores compact records + indexes + the reusable scripts; raw
  files are re-queried on demand, never bulk-loaded.
- **Structured memory:** this log + `parts/*.md` + `extracted/*.csv` are durable memory.
- **Right altitude:** `AGENT.md` gives the future estimator heuristics + where to look,
  not brittle if-else.

## 8. PROGRESS / NEXT

- [x] Phase 1 recon (reference part, all source types, tools built & validated)
- [x] Phase 2 schema + methodology docs (this log, data_sources, data_dictionary,
      cost_time_model, estimation_for_new_parts, domain primer, reference/*)
- [x] Phase 3 — extracted **all 39 parts** via 10 parallel sub-agent batches
      (A–J + Z exemplar) → `parts/*.md` (39) + `extracted/_shards/*` merged by
      `_tools/merge_shards.py` into `extracted/{parts,jobcost,tools,operations}.csv`
      (39/309/513/135 rows). Brief: `_research/PHASE3_EXTRACTION_BRIEF.md`.
- [x] Phase 4 — `_tools/analyze.py` → `_research/PHASE4_AGGREGATES.txt`; wrote
      `patterns/{00_patterns_index,machine_rates_and_cost,cycle_time_model,
      tool_selection,cutting_parameters,setup_and_material}.md` and `parts/INDEX.md`.
- [ ] Phase 5 — README/AGENT status refresh, cross-reference validation, optional
      non-destructive file foldering (in progress).

### Open questions — RESOLVED in Phase 3/4 (see patterns/*)
- Calibration k (NC→actual): by machine class; 3-/4-axis milling k≈1.1–1.3,
  multi-pc ÷N first, lathe-MAC/5-axis unreliable → `patterns/cycle_time_model.md`.
- Per-material params: PEEK vs PP feed/speed bands by tool type →
  `patterns/cutting_parameters.md` (PP faster/higher-RPM; GL30 separate).
- Setup drivers: Simple ≈0.5 hr/op (2.25 hr/job), Complex ≈1.5 hr/op (4.45 hr/job);
  first-article 3–11× blow-ups → `patterns/setup_and_material.md`.
- Stock→material cost: volume×ρ×$/kg by family×form; anchor on same-form analogue
  → `patterns/setup_and_material.md` §2.
- Simple vs Complex boundary: #tools/op (≈3–8 vs 24–26), #ops, multi-axis,
  helicoil/engrave, removal_cc → `patterns/setup_and_material.md` §4.
- Machine-type→rate is a step-function of class → `patterns/machine_rates_and_cost.md`.

### Residual data gaps (carry forward; documented per part)
- ~1/3 of parts have no usable NC (`.MAC`/G95 lathe, 5-axis, mcam-only) → those
  rely on Job Cost actual + analogue, not NC physics.
- 839-A07950-001 has no Job Cost PDF (geometry/tooling only — no cost truth).
- 0041-62474 / 16-455529-00 estimate-only (job not run): quoting data, not truth.
- Work-center label noise (e.g. "CNCV FAN M/L/V") normalized by class in patterns;
  raw strings kept in `extracted/jobcost.csv` for traceability.
