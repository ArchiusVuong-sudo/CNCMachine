# CNC Time & Cost Estimation — Knowledge Base

Distilled knowledge from a precision plastic-machining job-shop's raw data (Foresight
Asia Pacific; PEEK/POM/PP parts for Lam Research), built so an agent can **estimate
machining time & cost per feature for any part — including parts/features never seen
before** — by applying learned patterns. Designed per Anthropic *Effective context
engineering for AI agents*: read the distilled layer, retrieve raw data just-in-time.

## Where the estimator sits
`Feature Recognition → Machine-Type Selection → Routing/Sequencing → Tooling Selection
→ Parameter Setting → ⮕ TIME & COST ESTIMATION (this KB) ⮕ Price`

## Read in this order
1. **`_research/RESEARCH_LOG.md`** — working memory & recovery anchor (what's known, where, progress).
2. **`methodology/00_how_this_kb_works.md`** — the context-engineering design.
3. **`methodology/01_cnc_domain_primer.md`** — machining concepts.
4. **`methodology/02_data_sources.md`** — the 5 sources & how to extract each.
5. **`methodology/03_cost_time_model.md`** — the cost & time formulas (core).
6. **`methodology/04_estimation_for_new_parts.md`** — generalizing to unseen parts (core).
7. **`reference/`** — `data_dictionary`, `materials`, `machines`, `tooling`,
   `cutting_parameters`, `operations_and_sequencing`.
8. **`parts/INDEX.md`** + `parts/<part>.md` — the case library (analogues).
9. **`extracted/`** — `parts.csv`, `operations.csv`, `tools.csv`, `jobcost.csv` (dataset).
10. **`patterns/`** — synthesized predictive rules (Phase 4).
11. **`_tools/`** — extraction scripts (token-efficient raw-data interface).

## To produce an estimate (quick path)
Read `methodology/04` → find analogues in `parts/INDEX.md` → apply
`patterns/*` rules + `reference/*` bands → roll up with `methodology/03` →
output the §6 breakdown with assumptions, the fallback-ladder rung used, and a ±range.

## The 5 data sources (per part folder)
Job Cost - Detail PDF (cost/time truth) · Setup Sheet xls/pdf (routing/tooling/params) ·
NC G-code (physics cycle time) · Customer drawing PDF (geometry/material/tol) · BOM csv
(hardware). Tools: `_tools/{jobcost,xls_dump,nc_analyze,pdf_tool,bom}.py`.

## Status
Phase 1 (recon) ✅ · Phase 2 (schema/methodology) ✅ · Phase 3 (39 parts extracted) ✅ ·
Phase 4 (patterns synthesized) ✅ · Phase 5 (finalize) ✅. KB is **estimation-ready**:
39 part records, `extracted/*.csv` dataset, `patterns/*` rules, `parts/INDEX.md`
analogue index. See RESEARCH_LOG for detail.
