# CNC Analysis Server

Modular monolith rewrite of `E:\CNCMachine\CNCapp\python`. Each engine
lives in its own folder under `server/engines/`; the orchestrator wires
them into a 3-stage SSE pipeline (`POST /v1/analyze-stream`).

## Layout

```
server/
├── core/                       # Shared kernel
│   ├── schemas/                # Pydantic boundary contracts (drawing, assembly, plan, ...)
│   ├── settings.py             # Dataclass settings resolved from env vars
│   ├── logging.py              # Idempotent root-logger setup
│   ├── events.py               # SSE event types + EventBridge queue
│   ├── http.py                 # download_bytes() helper
│   └── tracing.py              # Per-analysis JSON trace writer
│
├── engines/
│   ├── extraction_2d/          # Engine 1 — VLM-driven drawing extraction
│   │   ├── rasterizer.py       #   PDF/image → base64 PNG pages
│   │   ├── prompts.py          #   Qwen3-VL system prompt
│   │   ├── page_analyzer.py    #   per-page VLM call with retries
│   │   ├── merger.py           #   multi-page JSON merge
│   │   └── engine.py           #   public `run(drawing_bytes) -> DrawingExtraction`
│   │
│   ├── extraction_3d/          # Engine 2 — OCC + welding
│   │   ├── occ/                #   vendored cadquery-ocp pipeline
│   │   ├── runner_script.py    #   subprocess heredoc
│   │   ├── subprocess_runner.py#   OCC subprocess wrapper
│   │   ├── welding.py          #   FreeCAD distToShape() contact detection
│   │   └── engine.py           #   public `run(step_bytes) -> AssemblyData`
│   │
│   ├── process_mapping/        # Shared helpers reused by the agentic engine
│   │   ├── bom_mapper.py       #   drawing BOM ↔ 3D components (fuzzy match)
│   │   ├── category_reconciler.py# OCR-declared vs AFR-detected part type
│   │   ├── dim_tagger.py       #   drawing dims/GD&T/threads → AFR features
│   │   └── cost_engine.py      #   labor + machine + tool → USD per component
│   │
│   └── agentic/                # Engine 3 — LLM coordinator (only planner; no fallback)
│       ├── dispatcher.py       #   public `dispatch(...) -> ProcessPlan` + session-note writeback
│       ├── coordinator.py      #   assembly orchestration; per-component asyncio.gather
│       ├── per_component_agent.py# Phase A→B→C→D chain per component
│       ├── tool_loop.py        #   ReAct/JSON-mode driver (8-iter cap, 2 parse retries)
│       ├── writeback.py        #   session-note + /v1/feedback persistence (path-validated)
│       ├── prompts/            #   system prompt + 4 phase user-message builders
│       └── tools/              #   kb_read, kb_find_analogues, kb_query_csv,
│                               #   catalog_lookup, compute_cycle_time
│
├── infra/                      # Network/DB adapters
│   ├── supabase.py             #   lazy client factory
│   ├── materials.py            #   static material database
│   └── llm.py                  #   Qwen3-VL streaming chat client
│
├── pipeline/                   # SSE orchestrator
│   └── orchestrator.py         #   `run_pipeline(...)` async generator
│
├── api/                        # FastAPI surface
│   ├── app.py                  #   `create_app()`
│   ├── sse.py                  #   SSE frame encoding
│   └── routes/
│       ├── analyze.py          #   POST /v1/analyze-stream
│       ├── feedback.py         #   POST /v1/feedback  (KB writeback; 64 KB cap)
│       └── health.py           #   GET  /v1/health
│
├── main.py                     # `python -m server.main`
├── requirements.txt
└── .env.example
```

## Quick start

```bash
# 1. Install deps
pip install -r server/requirements.txt

# 2. Provision external binaries
# - OCC: cadquery-ocp wheel is enough (no extra step)
# - FreeCAD: install separately, set FREECAD_PYTHON in .env
#            (required for milling cycle time + welding detection)

# 3. Configure
cp server/.env.example server/.env
# edit VISION_MODEL_URL, NEXT_PUBLIC_SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

# 4. Run
python -m server.main
# or:
uvicorn server.main:app --host 0.0.0.0 --port 8001
```

## API

### `GET /v1/health`

Liveness probe. Returns 200 with version + best-effort dependency status:

```json
{
  "status":  "ok",
  "version": "1.0.0",
  "services": {
    "supabase":     false,
    "occ_python":   true,
    "freecad":      false,
    "vlm_endpoint": true
  }
}
```

### `POST /v1/analyze-stream`

Run the 3-engine pipeline and stream events as `text/event-stream`.

**JSON body** (Supabase-hosted files):

```json
{
  "analysis_id": "uuid-v4",
  "step_url":    "https://…/part.step",
  "drawing_url": "https://…/drawing.pdf",
  "step_name":   "part.step",
  "user_id":     "auth-uuid",
  "batch_size":  10,
  "forced_assembly_part_type": null
}
```

**multipart/form-data** (local upload): `step` + `drawing` file fields
plus the same form fields as above.

**Event stream**:

| event           | payload                                                          |
|-----------------|------------------------------------------------------------------|
| `status`        | `{ title, message, completed? }` — coarse progress              |
| `tool_call`     | `{ tool, iteration, label }` — engine started a phase           |
| `tool_result`   | `{ tool, result }` — phase finished                             |
| `thinking`      | `{ content }` — VLM chain-of-thought chunk                      |
| `heartbeat`     | `{}` — idle keep-alive                                          |
| `final_answer`  | `{ results, summary }` — assembled pipeline output              |
| `error`         | `{ message }` — pipeline aborted                                |
| `done`          | `{ total_minutes, total_usd, elapsed_seconds }` — always last   |

## Architecture notes

- **Pydantic v2 boundary contracts**: `DrawingExtraction` (Engine 1) →
  `AssemblyData` (Engine 2) → `ProcessPlan` (Engine 3). Engines never
  trade in opaque dicts at their public surface; the orchestrator passes
  models through unchanged.
- **Subprocess isolation**: OCC (cadquery-ocp) and FreeCAD Path run in
  child Python processes so segfaults or memory issues in those native
  bindings can't take the FastAPI server down.
- **EventBridge**: engines emit through an async callback; the
  orchestrator drains a queue and yields heartbeats during idle gaps so
  the SSE connection stays open under slow VLM responses.
- **Per-user shop catalog**: Supabase tables `a4_labor_rates`,
  `a4_machines`, `a4_tooling`, `a4_material_stock` are pre-fetched once
  per analysis and passed to the agent via `catalog_lookup`. Empty
  catalog → the agent flags the gap in its rationale (no vendored
  fallback shop; "Agent only, no fallback").
- **Agentic engine** (`server/engines/agentic/`): the only planner.
  `dispatch(...)` calls the coordinator, which fans out per-component
  agents via `asyncio.gather`. Each agent runs a 4-phase prompt chain
  (Machine → Routing → Tooling → Parameters) through a ReAct/JSON tool
  loop against Qwen3-VL. Top-3 ranked picks are surfaced in the UI; the
  user's chosen option is written back via `POST /v1/feedback` (KB
  writes happen ONLY via that explicit endpoint, never auto-saved).
- **Knowledge base** (`E:/data/KNOWLEDGE_BASE/`): the agent reads
  `AGENT.md`, per-part analogue pages, and pattern docs at runtime via
  `kb_read` / `kb_find_analogues` / `kb_query_csv`. Paths are restricted
  to the KB root (no traversal) and CSV queries are restricted to
  `extracted/`.
