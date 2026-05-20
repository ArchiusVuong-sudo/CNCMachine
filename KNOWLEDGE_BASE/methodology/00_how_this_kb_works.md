# How This Knowledge Base Works (read me second)

Built per **Anthropic, "Effective context engineering for AI agents."** The point of
this KB is to let a future agent estimate CNC time & cost **without loading the whole
corpus into context**. It applies that article's principles literally:

- **Smallest set of high-signal tokens.** Raw files (635 PDFs, 219 NC, 54 xlsx, big
  `.mcam`) are *never* bulk-read. Knowledge is distilled into compact Markdown +
  machine-readable CSV. The agent reads the distilled layer; it touches raw files only
  to verify a specific number.
- **Just-in-time retrieval.** The KB stores lightweight identifiers (file paths in
  `parts/*.md`, `parts/INDEX.md`) and **reusable tools** (`_tools/*.py`) so any raw
  fact can be re-derived on demand instead of being pre-loaded.
- **Structured note-taking as memory.** `_research/RESEARCH_LOG.md` is the durable
  working memory and recovery anchor; `parts/*.md` and `extracted/*.csv` are persistent
  externalized findings that survive context resets.
- **Sub-agent fan-out.** Bulk extraction (Phase 3) is done by sub-agents, one per part,
  each with its own context window; they return only a filled record, never raw dumps.
- **Right altitude.** `AGENT.md` and `methodology/04` give heuristics + a fallback
  ladder, not brittle if-else lookup. Generalization is the goal.

## Layout & reading order
1. `_research/RESEARCH_LOG.md` — what's known, what's where, progress (recovery anchor).
2. `README.md` — the map.
3. `methodology/` — `00` this · `01` CNC primer · `02` data sources · `03` cost/time
   model · `04` estimating unseen parts.
4. `reference/` — stable facts: `data_dictionary`, `materials`, `machines`, `tooling`,
   `cutting_parameters`, `operations_and_sequencing`.
5. `parts/` — `INDEX.md` + one record per part (the case library / analogues).
6. `extracted/` — CSVs: `parts`, `operations`, `tools`, `jobcost` (the model dataset).
7. `patterns/` — synthesized predictive rules (Phase 4): tool selection, cutting
   parameters, cycle-time calibration, cost.
8. `_tools/` — extraction scripts (the token-efficient interface to raw data).

## Maintenance contract
- New data → run `_tools/` scripts → add a `parts/<part>.md` + CSV rows → update
  `parts/INDEX.md` and, if a rule changes, the relevant `patterns/` doc + RESEARCH_LOG.
- Keep docs at the right altitude; push specifics to CSV, keep prose to rules & why.
- Every estimate must cite which `parts/*` analogues and which `patterns/*` rule it used.
