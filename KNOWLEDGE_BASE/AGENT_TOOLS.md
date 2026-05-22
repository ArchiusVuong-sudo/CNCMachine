# AGENT_TOOLS.md — Tool reference for the estimation agent

This is the agent's own reference for the five tools it can call from the
ReAct loop. Pull this file when the system-prompt summary isn't enough.

All tools return JSON dicts. Errors come back as `{"error": "..."}` —
never thrown. Pick a different tool / args; don't retry the same call.

Tool budget per phase: **8 calls**. Spend them in this order:
1. `kb_find_analogues` (once) — gets you the analogue spine.
2. `kb_read("parts/<analogue>.md")` (1–2 reads) — measured tools, times.
3. `kb_read("patterns/<phase>.md")` (once if unsure of the rules).
4. `catalog_lookup` (per phase) — actual shop machines / tools.
5. `compute_cycle_time` (per tool in Phase D).

---

## 1. `kb_read(path, max_chars=24000)`

Read a markdown/text file from `KNOWLEDGE_BASE/`.

**When**: pulling the operating manual sections, patterns, or one
analogue's full part page.

**Args**:
- `path` — relative under `KNOWLEDGE_BASE/`, e.g. `patterns/tool_selection.md`.
- `max_chars` — truncate; default 24000.

**Returns**: `{path, content, truncated, total_chars}` or `{error}`.

**Examples**:
```json
{"tool": "kb_read", "args": {"path": "patterns/cycle_time_model.md"}}
{"tool": "kb_read", "args": {"path": "parts/0022-09112.md"}}
{"tool": "kb_read", "args": {"path": "reference/machines.md", "max_chars": 8000}}
```

Common paths:
- `AGENT.md` — the manual (already in system prompt; only re-read if cache invalidated).
- `parts/INDEX.md` — analogue catalog by family.
- `parts/<part>.md` — per-part page with measured tools/feeds/times.
- `patterns/cycle_time_model.md` — NC calibration `k`-table.
- `patterns/cutting_parameters.md` — feed/RPM bands by material & tool.
- `patterns/tool_selection.md` — feature → tool-family rules.
- `patterns/setup_and_material.md` — setup-hour medians, stock rules.
- `reference/machines.md` — `a4_machines` catalog columns + work_center→k bridge + rate semantics.
- `reference/operations_and_sequencing.md` — op-order rules.

---

## 2. `kb_find_analogues(part_type, material, n_features?, complexity?, top_k=3)`

Rank analogue parts from `extracted/parts.csv` by similarity.

**When**: first call of EVERY phase. Establishes the analogue spine.

**Scoring** (higher = closer):
- material family match (PEEK / PP / aluminum / stainless): +3
- `part_type` exact match: +3
- `complexity` match (Simple / Complex): +2
- `n_features` within ±2: +2 graded by distance

**Args**:
- `part_type` — `cnc_lathe` | `cnc_lathe_milling` | `cnc_milling`.
- `material` — free text; we bucket by family.
- `n_features` — optional; component's feature count.
- `complexity` — optional; `Simple` or `Complex`.
- `top_k` — default 3.

**Returns**: `{query, analogues: [{score, part_number, ...row}], total_scored}`.

**Example**:
```json
{"tool": "kb_find_analogues",
 "args": {"part_type": "cnc_milling", "material": "PEEK", "n_features": 12, "complexity": "Complex", "top_k": 3}}
```

After this returns, `kb_read("parts/<best_match>.md")` to see the full
measured page.

---

## 3. `kb_query_csv(file, filters?, limit=50)`

Filter rows from a CSV under `KNOWLEDGE_BASE/extracted/`. Restricted to
that directory.

**When**: you want a slice from `operations.csv`, `tools.csv`, or
`jobcost.csv` without reading the whole table.

**Files & columns**:
- `extracted/parts.csv` — `part_number, rev, class, material, part_type, machines, order_qty, job, envelope_mm, stock_form, stock_size, removal_cc, n_ops, n_tools, n_features, unit_price_rm, cost_ea_rm_est, cost_ea_rm_act, total_run_min_pc, total_setup_hr, source_folder, notes`
- `extracted/operations.csv` — `part_number, op, machine, feature, operation_type, seq_index, run_min_pc_est, run_min_pc_act, nc_est_min, nc_calib_k, n_tools, notes`
- `extracted/tools.csv` — `part_number, op, seq, feature_or_op, tool_name, tool_type, dia_mm, flutes, cut_len_mm, tool_len_mm, zmin_mm, feed_mm_min, feed_mm_rev, speed_rpm, stepover_mm, stepdown_mm, material, machine, source`
- `extracted/jobcost.csv` — `part_number, job, op, work_center, machine, setup_hr_est, setup_hr_act, run_hr_est, run_hr_act, run_min_pc_act, labor_rm_est, labor_rm_act, burden_hr, burden_rm, rate_rm_hr, qty, date`

**Filter syntax**:
- `{col: "value"}` — case-insensitive exact match.
- `{col: {"eq": "value"}}` — explicit exact.
- `{col: {"contains": "fragment"}}` — substring.
- `{col: {"min": 1.5, "max": 6.0}}` — numeric range.

**Example**:
```json
{"tool": "kb_query_csv",
 "args": {"file": "extracted/tools.csv",
          "filters": {"part_number": "0022-09112", "tool_type": {"contains": "endmill"}},
          "limit": 10}}
```

---

## 4. `catalog_lookup(table, filters?, limit=25)`

Query the per-user shop catalog (NOT the KB — this is the customer's
machines/tools/materials).

**Tables**: `machines` | `tools` | `materials` | `labor`.

**`machines` columns you can filter on** (from `a4_machines`; see
`reference/machines.md` for the full table + rate semantics):
- `machine_type` — **primary selector**: `router`, `3_axis_mill`, `4_axis_mill`,
  `5_axis_mill`, `mill_turn`, `lathe`.
- `capability` — `3-axis` / `4-axis` / `5-axis`.
- `work_center` — shop-cell code (`DNM 5700 (4axis)`, `CNCV FAN V (Vacuum)`, …);
  **maps to the cycle-time `k` class** via `reference/machines.md`.
- `manufacturer`, `model`, `work_x_mm`, `work_y_mm`, `max_spindle_rpm`,
  `tool_holder`, `hourly_rate_usd` (machine OH; labor is added separately).

**When**:
- Phase A — list shop's actual machines of the chosen class (`machine_type` /
  `capability`), then read the picked row's `work_center` for its `k`.
- Phase C — list shop's tools in a Ø band before deciding "would_need_to_buy".
- Phase D — read `max_spindle_rpm` of the chosen machine to clamp speeds.

**Args**:
- `table` — one of the four above.
- `filters` — same syntax as `kb_query_csv` (`{col: value}` exact, or
  `{col: {eq|contains|min|max: …}}`). Unknown columns simply match nothing.
- `limit` — default 25.

**Returns**: `{table, filters, rows, count, total_matched, total_in_catalog}`.

**Examples**:
```json
{"tool": "catalog_lookup",
 "args": {"table": "machines", "filters": {"machine_type": "4_axis_mill"}}}

{"tool": "catalog_lookup",
 "args": {"table": "machines",
          "filters": {"capability": "5-axis", "work_x_mm": {"min": 500}}}}

{"tool": "catalog_lookup",
 "args": {"table": "machines", "filters": {"work_center": {"contains": "DNM 5700"}}}}

{"tool": "catalog_lookup",
 "args": {"table": "tools",
          "filters": {"family": "endmill", "diameter_mm": {"min": 5.5, "max": 6.5}, "flute_no": {"min": 2, "max": 3}}}}
```

If a shop has fewer than 3 machines of the chosen class, list what it
HAS and flag the gap in `rationale` — don't invent missing inventory.

---

## 5. `compute_cycle_time(nc_minutes_raw, machine_class, n_pieces_per_program=1)`

Calibrate raw NC-estimator minutes into per-piece cycle time.

**Math**: `calibrated = (nc_minutes_raw / n_pieces_per_program) * k`

**k by machine class** (verbatim from `patterns/cycle_time_model.md`):

| machine_class                | k     | reliability               |
|------------------------------|-------|----------------------------|
| `vmc_3_axis`                 | 1.27  | calibrated                |
| `vmc_3_axis_well_behaved`    | 1.11  | calibrated                |
| `vmc_4_axis`                 | 1.10  | calibrated                |
| `router`                     | 1.30  | calibrated                |
| `vmc_5_axis`                 | 1.00  | **unreliable** — use analogue |
| `turn_mill`                  | 1.00  | **unreliable** — use analogue |
| `lathe`                      | 1.00  | **unreliable** — use analogue |
| (unknown)                    | 1.25  | default                   |

**When**: Phase D, once per tool entry. For lathe/5-axis/turn-mill, the
`source` field returns `"calibrated_unreliable_prefer_analogue"` —
override the result with the analogue's measured `run_min_pc` scaled by
the differing governing dimension.

**Multi-piece NC** (`-2PC-`, `-4PC-` in the program name): pass the
divisor as `n_pieces_per_program`.

**Example**:
```json
{"tool": "compute_cycle_time",
 "args": {"nc_minutes_raw": 12.4, "machine_class": "vmc_3_axis", "n_pieces_per_program": 1}}
```
→ `{"per_piece_raw_min": 12.4, "k": 1.27, "calibrated_min": 15.748, "source": "calibrated"}`

---

## Anti-patterns

- **Don't** call `kb_read("AGENT.md")` — it's already in your system prompt.
- **Don't** retry the same `kb_read` with a slightly different path; if
  it 404'd, the file isn't there.
- **Don't** invent machine_ids or tool_ids; if `catalog_lookup` returns
  empty, set `would_need_to_buy: true` (Phase C) or flag the gap (Phase A).
- **Don't** skip stating your fallback-ladder rung inside `thought` — the
  schema validator looks for it.
- **Don't** call `compute_cycle_time` for `lathe`/`5_axis`/`turn_mill` and
  trust the output; the `source` field tells you to prefer the analogue.
