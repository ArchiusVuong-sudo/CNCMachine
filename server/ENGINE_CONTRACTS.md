# ENGINE_CONTRACTS.md — Pipeline data contracts (server ⇄ UI)

**Purpose.** This is the single, authoritative reference for the data each
engine **produces** and **consumes**, the `final_answer` envelope the UI
renders, and the exact fields the front-end reads for every screen.

Use it when you **replace an engine** (the agentic planner is the first to go,
but the 2D / 3D / mapping engines may follow). If your new engine emits the
shapes documented here, the rest of the pipeline — cost engine, persistence,
and the whole UI — keeps working with **zero** changes elsewhere.

> **Golden rule.** The UI never talks to an engine. It renders exactly one
> object: the **`final_answer.results` envelope** (§3). A saved run round-trips
> through Supabase and comes back as the *same* envelope (§4). So "what an
> engine must produce" always reduces to "what fields end up on the envelope."

Authoritative source files (keep this doc in sync if they change):

| Concern | File |
|---|---|
| Engine 1 contract | `server/core/schemas/drawing.py` |
| Engine 2 contract | `server/core/schemas/assembly.py`, `features.py`, `pmi.py`, `geometry.py` |
| Engine 3 contract | `server/core/schemas/plan.py` |
| Enums (controlled vocab) | `server/core/schemas/enums.py` |
| Envelope assembly | `server/pipeline/orchestrator.py` (`results = {...}`, ~line 597) |
| Agentic projection → RoutingRow | `server/engines/agentic/coordinator.py` (`_build_routing_rows`) |
| Cost engine | `server/engines/process_mapping/cost_engine.py` |
| Persistence (write) | `server/infra/persistence.py` |
| Persistence (read / reassembly) | `server/infra/analyses_repo.py` |
| **FE wire types** | `frontend/src/lib/api/types.ts` |
| FE read-model (selectors) | `frontend/src/lib/domain/{selectors,bom-model,cost-model,part-info-model}.ts` |

Everything is **Pydantic v2 with `extra="allow"`** (server) and loose
interfaces with `[key: string]: unknown` (FE). **Extra fields pass through
untouched** — you can attach new data without touching the schema, and the FE
won't crash on missing fields. Declared fields are the *minimum* contract.

---

## 1. Pipeline at a glance

```
            ┌──────────────┐   DrawingExtraction
  PDF  ───► │ Engine 1 2D  │ ──────────────┐
            └──────────────┘               │
            ┌──────────────┐   AssemblyData │   ┌───────────────┐   ┌────────────┐
  STEP ───► │ Engine 2 3D  │ ──(components[])──►│ Mapping engine│──►│ Engine 3   │
            └──────────────┘               │   │ bom↔comp,     │   │ planner    │
                                           └──►│ dim_tagger,   │   │ (routing)  │
            ┌──────────────┐                   │ reconciler    │   └─────┬──────┘
  catalog ─►│ Supabase fetch│──────────────────┴───────────────┘         │
            └──────────────┘                                             ▼
                                                                 ┌────────────┐
                                          components decorated   │ Cost engine│
                                          with routing + cost ◄──┤ (USD/min)  │
                                                                 └─────┬──────┘
                                                                       ▼
                                                  SSE `final_answer.results`  ──►  UI
                                                  (also persisted to Supabase)
```

**Phases** (orchestrator):
- **Phase 0** download STEP + drawing (or accept raw bytes).
- **Phase 1** (parallel): Engine 1 (2D VLM) · Engine 2 (3D OCC subprocess) · catalog pre-fetch.
- **Mapping** `bom_mapper` + `dim_tagger` + `category_reconciler` decorate components.
- **Phase 2**: Engine 3 plans each component → routing rows on each component.
- **Phase 3**: Cost engine joins routing × catalog → per-component USD + cycle.
- **Phase 4**: Assemble `final_answer.results`; persist to Supabase.

**The crash contract.** Engines **never raise** into the orchestrator. On
irrecoverable failure they return a schema-valid empty sentinel
(`DrawingExtraction.empty()`, `AssemblyData.empty(error=...)`,
`ProcessPlan.empty(error=...)`). A failed component is marked failed and the
assembly continues — there is **no rule-based fallback** for the planner
("agent only, no fallback").

---

## 2. Per-engine contracts

### 2.1 Engine 1 — 2D drawing extraction → `DrawingExtraction`

- **Input:** drawing bytes (PDF/PNG/JPG/TIFF) or a Supabase signed URL.
- **Output:** `DrawingExtraction` (`core/schemas/drawing.py`).
- **Consumed by:** mapping engine (BOM match), Engine 3 (prompt input), and the
  UI's **Part Information** card, **Bill of Material** (part number +
  description per line), and **Extraction** tabs.
- **Lands on envelope as:** `results.vlm_extraction`.

| Field | Type | Notes / UI use |
|---|---|---|
| `part_number` | `str` | Part Info → PART NUMBER; BoM level-0 row |
| `revision` | `str` | Part Info → REVISION |
| `description` | `str` | Part Info → PART DESCRIPTION; BoM level-0 + sole-machined description |
| `material` | `str` | Part Info → MATERIAL |
| `dimension_unit` | `"mm"\|"in"` | Part Info → DIMENSION UNIT |
| `surface_finish` | `str?` | (not shown today) |
| `assembly_method` | `welded\|bolted\|riveted\|bonded\|null` | drives `part_category`; planner routing |
| `part_category` | `str?` | drawing-level family (weldment / assembly_* / sheet_metal / …) |
| `title_block` | `TitleBlock?` | fallback source for the identity fields above |
| `bom_items[]` | `BomItem[]` | **BoM PART NUMBER + DESCRIPTION per component** (joined by `mapped_to_bom_item`) |
| `drawing_notes[]` | `str[]` | Part Info → NOTES list |
| `dimensions[]` | `DimensionRow[]` | Extraction → Tolerances tab (drawing-level) |
| `gdt_callouts[]` | `GdtCallout[]` | Extraction → GD&T tab (drawing-level) |
| `threads[]` | `ThreadSpec[]` | Extraction → Threads tab (drawing-level) |

`BomItem`: `{ item_no, part_number, description?, qty?, tengc?, material?, part_type?, unit_price? }`
— **`item_no` is the join key** the mapping engine writes into each
component's `mapped_to_bom_item`. (`item_no` may arrive as a string; coerce to
number — the FE does `Number(item_no)`.)

### 2.2 Engine 2 — 3D STEP recognition → `AssemblyData`

- **Input:** STEP bytes or signed URL (runs in a child Python process so OCC
  segfaults can't kill FastAPI).
- **Output:** `AssemblyData` with `components[]` (`core/schemas/assembly.py`).
- **Consumed by:** mapping engine, Engine 3 (**decorates `components` in place**),
  cost engine, and the UI's **3D viewer** (bbox), **BoM** (one row per
  component), **Extraction** tabs (per-feature), **Manufacturing Plan**
  (complexity).
- **Lands on envelope as:** `results.components[]` (after decoration) +
  `results.assembly_data` (counts + welding contacts).

`AssemblyData`: `{ ok, assembly_name, file_name, component_count, total_volume_mm3, pmi_available, components[], welding_contacts[], error? }`

**`Component`** (the central object — Engines 2→3→cost all write to it):

| Field | Written by | Type | UI use |
|---|---|---|---|
| `component_index` | E2 | `int` | identity / selection key everywhere |
| `name` | E2 | `str` | (internal STEP id, e.g. `TC2-…`) — **not** shown as part number |
| `description` | E2 | `str` | BoM description fallback |
| `instance_count` | E2 | `int` | BoM → QTY |
| `part_type` | E2 (`PartType`) | enum str | BoM → TYPE badge; cost routing; `hardware`/`outside_vendor` skip planner |
| `part_type_confidence` | E2 | `0..1` | — |
| `volume_mm3`, `surface_area_mm2` | E2 | `float` | — |
| `bbox` | E2 | `BoundingBox` | **3D viewer dimension overlay** (`length_mm/width_mm/height_mm`) |
| `features[]` | E2 (+ dim_tagger) | `SimpleFeature[]` | Extraction tabs; complexity |
| `pmi_annotations[]` | E2 | `PMIAnnotation[]` | Extraction GD&T (component-level) |

`BoundingBox`: `{ x_min..z_max, length, width, height }` (mm). The FE reads
`bbox.length_mm / width_mm / height_mm` — **emit those keys** (the orchestrator
maps `length→length_mm` on the way out via the component dict).

`Feature` (envelope shape, after mapping enrichment):
`{ feature_index, feature_type, feature_id, key_face_ids[], count, confidence,
source, dimensions{}, perimeter_mm, location, tolerance_plus, tolerance_minus,
gdt_callouts[], tolerance_class, is_threaded, thread_spec, operations[] }`.
Controlled vocab for `feature_type` is `enums.FeatureType` (19 values + `unknown`).

### 2.3 Mapping engine (bom_mapper · dim_tagger · category_reconciler)

Not a model — three in-place decorators between Engine 2 and Engine 3. **May
also be replaced**, so its outputs are part of the contract:

- **`bom_mapper`** sets on each component: `mapped_to_bom_item` (int → `bom_items[].item_no`),
  `material` (resolved string), `mapping_method` (`"description"|"tengc"|"unknown"`).
  → BoM PART NUMBER + DESCRIPTION + MATERIAL columns depend on this join.
- **`dim_tagger`** enriches each `feature` with `tolerance_plus/minus`,
  `tolerance_class`, `gdt_callouts[]`, `is_threaded`, `thread_spec`, `operations[]`.
  → Extraction Tolerances / GD&T / Threads tabs.
- **`category_reconciler`** emits `results.category_decisions[]` and may flip a
  component's `part_type`. → not shown in the main UI today (trace only).

### 2.4 Engine 3 — process planner (the one being replaced)

- **Input:** the drawing dict + **one** decorated component + the per-user
  catalog (`labor`/`machines`/`tools`/`materials`).
- **Output (canonical):** the component is decorated with the four things below;
  the orchestrator also mirrors the routing into `processes_per_component[i]`.

| Decoration on `component` | Type | Drives which UI |
|---|---|---|
| `manufacturing_processes[]` | `RoutingRow[]` | **BoM** machine/cycle/proc-cost · **Cost Breakdown** per-op table |
| `planner` (alias `agentic`) | `PlannerData` | **Manufacturing Plan** (machine ranking, op sequence, rationale) |
| `raw_manufacturing_processes[]` | `RoutingRow[]` | **Manufacturing Plan** feeds & speeds table (live runs only — see §4) |
| `chosen_machine_id`, `machine_class` | `str?` | persisted columns; planner header |

**`RoutingRow`** — flat row, mirrors `core/schemas/plan.RoutingRow` **1:1**.
Emit this shape and the FE + cost engine + persistence all "just work":

| Field | Type | Consumer |
|---|---|---|
| `sequence` | `int` | order (10,20,30…) |
| `op_code` | `str` | Cost Breakdown PROCESS sub-label; Mfg Plan SEQ |
| `description` | `str` | row title |
| `process_type` | `ProcessType\|str` | bucket label (cnc_milling, deburring, inspection…) |
| `category` | `ProcessCategory\|str` | Cost Breakdown bucket routing (`deburring`/`inspection`→ own bucket) |
| `operation_type` | `Roughing\|Finishing\|null` | — |
| `setup_min_per_lot` | `float` | cost setup |
| `run_min_per_part` | `float` | **cycle time** (BoM CYCLE, per-op minutes) |
| `cycle_time_min` | `float` | same as run for CNC ops; cost engine reads this |
| `machine_id` | `str?` (uuid) | cost machine rate; persisted (uuid-validated) |
| `machine_name` | `str?` | **BoM MACHINE column** |
| `tool_ids[]` | `str[]` | tool amortisation (first id) |
| `tool_type`, `tool_dimensions{}` | `str?`, `dict?` | Mfg Plan TOOL / Ø |
| `feature_ids[]` | `str[]` | feature coverage |
| `labor_cost_usd` | `float` | Cost Breakdown **LABOR** (set by cost engine) |
| `machine_cost_usd` | `float` | Cost Breakdown **BURDEN** (set by cost engine) |
| `tool_cost_usd` | `float` | Cost Breakdown **TOOL** (set by cost engine) |
| `total_cost_usd` | `float` | Cost Breakdown **TOTAL** (set by cost engine) |
| `complexity` | `str?` | Cost Breakdown (Cycle view) complexity column |

> `labor_cost_usd` / `machine_cost_usd` / `tool_cost_usd` / `total_cost_usd` are
> filled by the **cost engine**, not the planner. The planner supplies the
> physical row (op, machine, tool, minutes); cost fills the money.

**`PlannerData`** (`component.planner`) — engine-agnostic planner block:
`{ machine_class, chosen_machine_id, ranked_machines[] (or top_machines[]),
operations[], tools_per_operation[], parameters_per_operation[],
total_run_min_per_part, setup_min_per_lot, rationale, evidence[],
confidence_band_pct, suppressed_by_consolidation_gate, error? }`.
- `ranked_machines[]`: `{ rank, machine_id, machine_name, score, burden_rate_usd_per_hr|hourly_rate_usd, reason }` → Mfg Plan machine table.
- `rationale: str` → Mfg Plan "Planner rationale".
- `suppressed_by_consolidation_gate: true` → component's cycle/cost rolled into the assembly owner; FE shows "—" / consolidated (avoids double-count).

**Two ways to plug in a planner:**
1. **Emit `RoutingRow` directly** on `component.manufacturing_processes` (+ a
   `planner` block for the Mfg Plan card). Simplest; bypasses the agentic
   projection entirely.
2. **Emit the agentic `OUTPUT_SCHEMA`** (`machine_class`, `top_machines[]`,
   `operations[]`, `tools_per_operation[]`, `parameters_per_operation[]` — see
   `engines/agentic/prompts/agent.py::OUTPUT_SCHEMA`) and reuse
   `coordinator._build_routing_rows()` to project it into `RoutingRow` +
   `ManufacturingProcess`. This is what the current engine does.

**Failure:** return `ProcessPlan.empty(components=..., error="…")` (or just
leave `manufacturing_processes = []`). Cost then runs in **legacy mode**
(material + deburr + inspection only, no machining) — the run still completes.

`ProcessPlan` (the full Engine-3 return, if you build the whole plan object):
`{ components[], processes_per_component[][] (RoutingRow lists in index order),
cost: CostBreakdown, category_decisions[], catalog{} }`.

### 2.5 Cost engine (rarely replaced, but part of the contract)

- **Input:** `components` (each with `manufacturing_processes[]`) + catalog.
- **Output:** mutates each component →
  - `component.cost` = `{ raw_material_usd, setup_usd, setup_min_per_lot,
    fixed_hrs_per_lot, machining_usd_by_process{}, machining_total_usd,
    deburr_usd, inspection_usd, total_usd, cycle_time_min, cost_source }`
  - `component.cycle_time_min` = Σ per-op run minutes (rolls up to `total_minutes`)
  - per-op rows get `labor_cost_usd / machine_cost_usd / tool_cost_usd / total_cost_usd`.
  - returns `CostBreakdown` `{ total_usd, breakdown_by_component[] }`.
- **`cost_source`**: `"routing"` (planner produced routing → real machining),
  `"legacy"` (no routing → material+deburr+inspection only),
  `"hardware_purchase"` / `"outside_vendor_passthrough"` (bought parts).

---

## 3. The `final_answer.results` envelope (server → UI)

This is the whole object the FE renders (`frontend/.../types.ts::FinalAnswer`).
Streamed live over SSE and rebuilt identically from Supabase for saved runs.

```jsonc
{
  "analysis_id": "uuid",
  "approach": "modular_monolith",
  "engine": "agentic",
  "batch_size": 1,
  "assembly_name": "…", "file_name": "…",
  "sources": { "bucket", "step_path", "drawing_path", "file_name" },   // re-sign viewer URLs

  "total_minutes": 137.0,            // Σ component.cycle_time_min
  "total_usd": 285.25,               // cost.total_usd
  "elapsed_seconds": 92.3,

  "vlm_extraction": { …DrawingExtraction… },                  // §2.1  → Part Info, Extraction, BoM
  "assembly_data": { "component_count", "total_volume_mm3",   // §2.2
                     "pmi_available", "welding_contacts": [] },

  "components": [ { …Component decorated by E2+mapping+E3+cost… } ],   // THE main array
  "processes_per_component": [ [ …RoutingRow… ], … ],         // mirror of component.manufacturing_processes
  "category_decisions": [ … ],

  "cost": { "total_usd", "breakdown_by_component": [ {component_index,total_usd,cost} ] },
  "cost_summary": { "total_usd_per_piece", "total_usd_per_lot",
                    "batch_size", "confidence_band_pct", "evidence": [] },
  "cycle_time": { "total_minutes", "breakdown_by_component": [ {component_index,total_minutes} ] },
  "cam": { "ok", "by_component": [], "total_files" },          // FreeCAD G-code (optional)
  "messages": [ …SSE activity… ]                              // pipeline-activity card (saved runs)
}
```

Each `components[i]` carries (Engine 2 base) + (mapping) + (Engine 3) + (cost):
`component_index, name, description, instance_count, part_type,
part_type_confidence, volume_mm3, surface_area_mm2, bbox, features[],
pmi_annotations[], mapped_to_bom_item, material, mapping_method,
manufacturing_processes[], raw_manufacturing_processes[], planner, agentic,
chosen_machine_id, machine_class, stock, cost, cycle_time_min, ui_overrides`.

---

## 4. Persistence round-trip (Supabase)

Saved runs are **DB-only history**. `persistence.persist_analysis_complete`
writes the envelope across tables; `analyses_repo.get_analysis_envelope`
**reassembles the identical envelope** so a reopened run renders like a live one.

| Envelope piece | Table | Notes |
|---|---|---|
| top-level totals + `sources` + `messages` | `a4_analyses` | `total_minutes`, `total_usd`, `component_count`, `step_url`, `drawing_url`, `messages_json` |
| `vlm_extraction` | `a4_2d_extraction` | one row; `bom_items` etc. as JSON |
| each `component` (scalar cols) | `a4_components` | `component_index, name, part_type, material, mapped_to_bom_item, cycle_time_min, chosen_machine_id, machine_class, …` |
| `component.cost` | `a4_components.cost_breakdown` (jsonb) | whole dict |
| `component.planner` / `agentic` | `a4_components.agentic_plan` (jsonb) | **whole planner block, verbatim** — engine-agnostic |
| `component.stock` | `a4_components.stock_json` (jsonb) | whole dict |
| user inline edits | `a4_components.ui_overrides` (jsonb) | applied on top of computed values |
| `component.features[]` | `a4_features` | |
| `component.manufacturing_processes[]` | `a4_processes` | flat RoutingRow columns |

**What survives a reload — contract caveats for a replacement engine:**
- ✅ Anything inside `planner` survives (stored whole as the `agentic_plan`
  jsonb blob). Put rich planner data there freely.
- ✅ `component.cost`, `component.stock` survive (jsonb blobs).
- ✅ Per-op routing survives via `a4_processes` (flat columns).
- ⚠️ **`machine_id` / `tool_ids[0]` must be a valid UUID** (FK to `a4_machines`
  / `a4_tooling`) or they're coerced to NULL on persist. Emit a real catalog
  UUID, or put the human name in `machine_name` / `tool_type` (those persist as
  text). `chosen_machine_id` is likewise uuid-validated.
- ⚠️ **`raw_manufacturing_processes` is NOT persisted** separately — the
  Manufacturing-Plan *feeds & speeds* table is **live-run only**. (The
  per-op `spindle_rpm`/`feed_mm_per_min` *do* persist on `a4_processes`, so the
  op sequence + costs reload fine; only the dedicated feeds table is empty on a
  reopened run.)
- ⚠️ A new top-level **scalar** you want shown after reload needs a column on
  `a4_components` (+ a migration). New **nested** data is free — nest it under
  `planner` / `cost` / `stock`.

---

## 5. FE display map — which field drives which pixel

The single source: `results` (§3). Per screen (component file in parens):

### Part Information (`extraction/part-information.tsx`, `domain/part-info-model.ts`)
| Label | Source |
|---|---|
| PART DESCRIPTION | `vlm_extraction.description` ?? `title_block.description/title` |
| PART NUMBER | `vlm_extraction.part_number` ?? `title_block.part_number` |
| REVISION | `vlm_extraction.revision` |
| MATERIAL | `vlm_extraction.material` |
| DIMENSION UNIT | `vlm_extraction.dimension_unit` |
| NOTES | `vlm_extraction.drawing_notes[]` |
| TOTAL COST | `total_usd` |
| COMPONENTS | count of `components[]` **excluding** the synthetic `TOP_ASSEMBLY` |

### 3D viewer (`viewport/step-viewer.tsx`, `hooks/viewer/useStepViewer.ts`)
- Model: `sources.step_path` (re-signed) / `step_url`.
- Bounding-box overlay: `component.bbox.{length_mm,width_mm,height_mm}` of the selected component.
- Selection / isolation key: `component_index`.

### Bill of Material (`results/bill-of-material.tsx`, `domain/bom-model.ts` + `selectors.ts`)
- **Level-0 (assembly) row:** PART NUMBER = `vlm_extraction.part_number`;
  DESCRIPTION = `vlm_extraction.description`; QTY/Material/Machine = "—";
  CYCLE = `total_minutes`; costs = sums.
- **Component rows:**

| Column | Source |
|---|---|
| PART NUMBER | `bom_items[item_no==mapped_to_bom_item].part_number` — **blank if none; never the `TC…` name** |
| DESCRIPTION | `bomItem.description` ?? `component.description` ?? (sole machined part) `vlm.description` |
| QTY | `component.instance_count` |
| TYPE | `component.part_type` |
| MATERIAL | `component.material` |
| MACHINE | first `manufacturing_processes[].machine_name`, else `planner.ranked_machines[0].machine_name` |
| CYCLE | `component.cycle_time_min` ?? Σ rows `cycle_time_min` ?? `planner.total_run_min_per_part` |
| MAT COST | `component.cost.raw_material_usd` |
| PROC / TOTAL | `component.cost.total_usd` (− material) |

`ui_overrides` (user inline edits) are layered on top of every cell.

### Cost & Cycle Breakdown (`results/cost-breakdown.tsx`, `domain/cost-model.ts`)
- **Per-op rows** ← `component.manufacturing_processes[]`: PROCESS=`process_type`/`op_code`,
  LABOR=`labor_cost_usd`, BURDEN=`machine_cost_usd`, TOOL=`tool_cost_usd`, TOTAL=sum.
  Cycle-Time view shows `cycle_time_min` + `complexity`.
- **Summary buckets** ← `component.cost`: Material(`raw_material_usd`),
  Setup(`setup_usd`/`setup_min_per_lot`), Deburr(`deburr_usd`),
  Inspection(`inspection_usd`), Machining(derived). Toggling **Cycle Time**
  swaps every bucket to minutes.
- Header total/cycle ← `componentTotalUsd` / `componentCycleMin`.

### Manufacturing Plan (`results/manufacturing-plan.tsx`)
| Section | Source |
|---|---|
| machine class + ranked table | `planner.machine_class`, `planner.ranked_machines[]` (rank, machine_name, score, $/hr, reason) |
| operation sequence | `manufacturing_processes[]` (sequence, op_code, tool_type, `tool_dimensions.diameter_mm`, run_min_per_part) |
| feeds & speeds | `raw_manufacturing_processes[]` (spindle_rpm/`spindle_speed_rpm`, feed, stepdown, stepover) — **live only** |
| rationale | `planner.rationale` |
| complexity badge + counts | **derived from `component.features[]`** (no backend field) |

### Extraction tabs (`extraction/extraction-panel.tsx`)
- **Tolerances** ← `features[]` with `tolerance_plus/minus` + drawing `dimensions[]`.
- **GD&T** ← `features[].gdt_callouts` + component `pmi_annotations` + drawing `gdt_callouts[]`.
- **Threads** ← `features[].is_threaded/thread_spec` + drawing `threads[]`.

---

## 6. Replacement checklists (copy-paste when swapping an engine)

**Replacing Engine 3 (planner) — the common case.** For each component, set:
- [ ] `component.manufacturing_processes = RoutingRow[]` (§2.4 table). At minimum
      per row: `sequence, op_code, process_type, category, run_min_per_part,
      cycle_time_min, machine_name` (+ `machine_id` UUID if you want the cost
      engine to use that machine's rate). Leave the four `*_cost_usd` to the
      cost engine.
- [ ] `component.planner = { machine_class, ranked_machines[], rationale,
      total_run_min_per_part }` for the Manufacturing-Plan card (optional but
      that card goes mostly blank without it).
- [ ] (optional) `component.raw_manufacturing_processes` for the feeds&speeds table.
- [ ] On failure: leave `manufacturing_processes = []` (→ legacy cost, run still completes).
- [ ] Do **not** set `labor/machine/tool/total_cost_usd` — the cost engine owns money.
- [ ] Hardware / outside-vendor parts: you may skip planning; the cost engine
      short-circuits on `part_type=="hardware"` / `component_role=="outside_vendor"`.

**Replacing Engine 1 (2D).** Emit `DrawingExtraction` (§2.1). Required for the UI:
`part_number, revision, description, material, dimension_unit, drawing_notes[]`,
and **`bom_items[]` with `item_no` + `part_number` + `description`** (the BoM
join). `dimensions[]/gdt_callouts[]/threads[]` feed the Extraction tabs.

**Replacing Engine 2 (3D).** Emit `AssemblyData` (§2.2). Per component the UI
needs: `component_index, name, part_type, instance_count, bbox` (with
`length/width/height`), and `features[]` (for Extraction + complexity). Set
`assembly_name`, `component_count`, `welding_contacts[]` at the top.

**Replacing the mapping engine.** Set on each component: `mapped_to_bom_item`
(→ `bom_items[].item_no`), `material`, `mapping_method`; enrich each `feature`
with `tolerance_plus/minus`, `tolerance_class`, `gdt_callouts[]`, `is_threaded`,
`thread_spec`. Without this the BoM part-number/description columns and the
Extraction tags go blank.

**Universal rules.**
- Match the **enum string values** in `core/schemas/enums.py` exactly
  (lowercase snake_case) — the catalog, DB, and FE all key off them.
- Never raise into the orchestrator — return the engine's `empty()` sentinel.
- Extra fields are free (`extra="allow"`); nest rich data under
  `planner`/`cost`/`stock` so it survives the DB reload without a migration.
- New top-level **scalars** that must survive reload need an `a4_components`
  column + a migration in `server/infra/migrations/`.

---

## 7. Quick contract index

| Object | File | Used as |
|---|---|---|
| `DrawingExtraction` | `schemas/drawing.py` | Engine 1 out → `results.vlm_extraction` |
| `AssemblyData` / `Component` | `schemas/assembly.py` | Engine 2 out → `results.components[]` |
| `SimpleFeature` / `FeatureDetail` | `schemas/features.py` | per-component features |
| `PMIAnnotation` | `schemas/pmi.py` | component PMI |
| `BoundingBox` / `Point3D` | `schemas/geometry.py` | 3D viewer |
| `RoutingRow` | `schemas/plan.py` | Engine 3 out → BoM + Cost Breakdown |
| `ManufacturingProcess` | `schemas/plan.py` | per-tool detail (feeds/speeds) |
| `ComponentCost` / `CostBreakdown` | `schemas/plan.py` | cost engine out |
| `PlannerData` (FE) | `frontend/.../types.ts` | engine-agnostic planner block |
| `FinalAnswer` (FE) | `frontend/.../types.ts` | the envelope the UI renders |
| Enums | `schemas/enums.py` | controlled vocabularies |
