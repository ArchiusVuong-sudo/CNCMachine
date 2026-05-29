# CoFab CNC Costing Studio

LLM-powered manufacturing cost estimator for CNC-machined parts. Upload a
2D engineering drawing (PDF) and a 3D model (STEP) and the pipeline
extracts features, plans the machining process, and returns a
per-component cost estimate in USD.

```
client ──► POST /v1/analyze-stream (SSE)
              │
              ▼
   ┌──────────┬─────────────────────────────────────┐
   ▼          ▼                                     ▼
Engine 1   Engine 2                            Catalog fetch
(2D VLM)   (3D OCC)                            (Supabase)
   │          │                                     │
   └──────────┴───────────┬─────────────────────────┘
                          ▼
                  Engine 3 — agentic LLM planner
                  (machine → routing → tooling → params)
                          │
                          ▼
                  ProcessPlan + cost
```

- **Engine 1** — drawing OCR via `Qwen3-VL-32B-Instruct-FP8` (vLLM).
- **Engine 2** — STEP feature recognition via `cadquery-ocp` (PythonOCC).
- **Engine 3** — ReAct LLM planner with KB analogue retrieval + per-user
  shop catalog (Supabase).

The repository is structured around three top-level folders:

```
.
├── KNOWLEDGE_BASE/   # markdown + CSV the agent reads at runtime
├── server/           # FastAPI backend (Python 3.11)
└── frontend/         # Next.js UI (Node 18+)
```

## Quick start — local dev against the shared backend

The CoFab team hosts a Qwen3-VL endpoint on vast.ai. New contributors
should point at it instead of standing up their own GPU. This is the
fastest path to running the pipeline end-to-end on a laptop.

### 1. Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11 (exact — `cadquery-ocp` does not yet publish 3.12 wheels) |
| Node.js | 18 or 20 |
| Git | any modern version |

On Windows, install Python via the official installer (not the Windows
Store version — it lacks the C++ runtime the OCC wheel needs).

### 2. Clone

```bash
git clone git@github.com:ArchiusVuong-sudo/CNCMachine.git
cd CNCMachine
```

### 3. Backend

```bash
cd server
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `server/.env` and fill in the **CoFab-hosted Qwen3-VL** block — ask
the team for the current trycloudflare URL and bearer token (the URL
rotates whenever the pod restarts):

```
VISION_MODEL_URL=https://<current-vllm-tunnel>.trycloudflare.com
VISION_MODEL_NAME=Qwen/Qwen3-VL-32B-Instruct-FP8
VISION_MODEL_API_KEY=<bearer token from team>

AGENT_LLM_URL=https://<same-tunnel>.trycloudflare.com
AGENT_LLM_MODEL=Qwen/Qwen3-VL-32B-Instruct-FP8
AGENT_LLM_API_KEY=<same bearer token>

NEXT_PUBLIC_SUPABASE_URL=https://sarcsdmbcjuxribibxqs.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<from team>
SUPABASE_SERVICE_ROLE_KEY=<from team — server-only, never expose client-side>
```

Launch:

```bash
python -m server.main
# → http://localhost:8001
```

Health check (each engine reports its own status, missing deps degrade
gracefully):

```bash
curl http://localhost:8001/v1/health
```

### 4. Frontend

```bash
cd ../frontend
npm install
cp .env.example .env.local   # optional — defaults work for local dev
npm run dev
# → http://localhost:3000
```

Open the browser, click **New Project**, drop in a STEP + drawing pair,
and watch the SSE pipeline.

## Alternative LLM providers

The pipeline's LLM calls are OpenAI-compatible, so any compatible
backend works. Edit `VISION_MODEL_URL` / `AGENT_LLM_URL` in `server/.env`:

- **Google Gemini** (no GPU needed, generous free tier) — see the
  drop-in block at the top of [`server/.env.example`](server/.env.example).
  Roughly `$0.05–0.15` per estimate on the paid tier.
- **Your own GPU pod** — host `Qwen3-VL-32B-Instruct-FP8` (24 GB VRAM
  minimum) with `vllm serve … --api-key <token>`, then point the env
  vars at it.
- **OpenAI / OpenRouter** — point at `https://api.openai.com/v1` or
  `https://openrouter.ai/api/v1` and use any vision-capable model. The
  provider auto-detects hosted endpoints and strips vLLM-only fields
  from the request payload.

## Project layout

```
server/
├── api/                     # FastAPI app + routes
├── core/                    # shared kernel (schemas, settings, SSE)
├── engines/
│   ├── extraction_2d/       # Engine 1 — drawing VLM
│   ├── extraction_3d/       # Engine 2 — OCC feature recognition
│   ├── process_mapping/     # cost engine, BOM mapper, dim tagger
│   └── agentic/             # Engine 3 — LLM coordinator
├── infra/                   # LLM client, Supabase factory, materials
├── pipeline/orchestrator.py # the only place that calls all 3 engines
└── main.py

frontend/
├── src/
│   ├── app/                 # Next.js App Router pages
│   ├── components/          # workspace, viewport, results, extraction
│   ├── lib/                 # API client, domain adapters, hooks
│   └── ...
└── public/

KNOWLEDGE_BASE/
├── AGENT.md                 # operating manual loaded into the prompt
├── MEMORY.md                # agent's own learned heuristics
├── patterns/                # cycle-time model, cutting params, etc.
├── parts/                   # per-analogue part pages
├── reference/               # machines, operations, sequencing
└── extracted/               # CSVs the agent queries
```

## Common gotchas

- **`cadquery-ocp` wheel install fails on Python 3.12+.** Use 3.11. The
  vendored OCC bindings have no 3.12 wheels yet.
- **Windows `pip install` complains about `pdftoppm`/`poppler`.** The
  rasterizer falls back to `pypdfium2` automatically. If you also want
  poppler, install via `choco install poppler` or just live with the
  fallback — it works for every test we run.
- **The trycloudflare URL rotates on pod restart.** The README's
  endpoint will be stale; SSH to the pod and grep the current value:
  ```bash
  ssh -p <port> -i ~/.ssh/id_ed25519 root@ssh6.vast.ai \
    "grep -E 'https://.*trycloudflare' /workspace/logs/cloudflared-vllm.log | tail -1"
  ```
- **Network error during analysis.** Cloudflare's free tunnel kills
  long HTTP/2 streams. The orchestrator detaches the pipeline from the
  SSE response, so the run completes server-side regardless — refresh
  the project list and the new run will appear.
- **`a4_*` Supabase rows return empty.** The catalog is keyed by
  `user_id` with a public-row fallback. If you sign in as a new user,
  expect the cost engine to fall back to default rates in
  [`server/engines/process_mapping/cost_engine.py`](server/engines/process_mapping/cost_engine.py)
  (`_DEFAULT_RATES`).

## Running a regression benchmark

The repo ships ground-truth production data in
`KNOWLEDGE_BASE/extracted/parts.csv` + `operations.csv`. To score the
current cost-engine formula against it:

```bash
cd server
python -m server.tests.benchmark_cost
```

Prints per-part predicted vs actual, MAPE, and pass rates at ±5/10/20%
tiers. Use it to confirm a change hasn't regressed accuracy before
merging.

## Contributing

- Branch off `main`, commit early and often, open a PR.
- Don't add `Co-Authored-By: Claude …` footers — house rule.
- Match the existing code style (`pylint`/`pyright` happy, `eslint`
  clean). No new top-level abstractions for a one-off fix.
- Schemas under `server/core/schemas/` are the wire contracts between
  Python and TypeScript — flag any change there in the PR description.

## License

Proprietary. Contact the CoFab team for usage outside the organization.
