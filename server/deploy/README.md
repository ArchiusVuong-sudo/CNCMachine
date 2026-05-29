# Pod deploy & migration runbook

Scripts to provision a RunPod pod that hosts **two side-by-side workloads**
sharing one GPU and one network volume:

- **OCR mode** — the customer's `drawing-extraction-api` (Engineering
  Drawing Data Extraction). Default state after the OCR-template image
  finishes booting; supervisord-managed on port `:8000`.
- **CNC mode** — our CoFab stack: vLLM Qwen3-VL on `:11434`, FastAPI on
  `:8002`, Next.js on `:8888`. tmux-managed.

The two modes are **mutually exclusive** because they both want the GPU
and they collide on port `:8888` (Jupyter Lab vs. Next.js). The switch
scripts flip between them.

---

## Files

| File | Purpose |
|---|---|
| [bootstrap_pod.sh](bootstrap_pod.sh) | One-shot setup on a fresh pod — Node, venvs, npm build, scripts into place. |
| [switch_to_cnc.sh](switch_to_cnc.sh) | Stop OCR, free GPU + `:8888`, bring up our three tmux sessions. |
| [switch_to_ocr.sh](switch_to_ocr.sh) | Tear down our tmux sessions, restore the OCR app + Jupyter + nginx. |
| [status.sh](status.sh) | Which mode is active, who owns each port, GPU load. |
| [serve_qwen.sh](serve_qwen.sh) | Launch vLLM Qwen3-VL-32B-Instruct-FP8 on `:11434`. |
| [start_fastapi.sh](start_fastapi.sh) | Launch our FastAPI server on `:8002`. |
| [start_frontend.sh](start_frontend.sh) | Launch the Next.js frontend on `:8888`. |
| [start_kimi_vl.sh](start_kimi_vl.sh) | Legacy — Kimi-VL planner serving (separate-pod era). Not used by `switch_to_cnc.sh`. |

`bootstrap_pod.sh` installs the switch / launch scripts at `/workspace/`
so they're invoked as e.g. `bash /workspace/switch_to_cnc.sh`. The
canonical copies live under `server/deploy/` in this repo.

---

## Architecture on the pod

```
/workspace/                      ← persistent network volume (survives pod restart)
├── CNCMachining/                ← our repo (server, frontend, KNOWLEDGE_BASE)
├── DwgDataExtract/              ← customer's OCR app (supervisord-managed)
├── hf-cache/                    ← HuggingFace model cache (Qwen3-VL lives here)
├── node/                        ← Node 22 binary distribution
├── venvs/
│   ├── server/                  ← Python venv for our FastAPI / engines
│   └── vllm011/                 ← Python venv for vLLM 0.11.x (Qwen3-VL)
├── .venv/                       ← OCR template's own Python venv
├── logs/                        ← stdout/stderr of all services
├── switch_to_cnc.sh             ← installed by bootstrap
├── switch_to_ocr.sh
├── status.sh
├── serve_qwen.sh
├── start_fastapi.sh
└── start_frontend.sh
```

```
                                 ┌─── :8000  drawing-extraction-api  (OCR mode)
                                 │           supervisord ↻
GPU (1×)  ────────────────────┐  ├─── :8888  jupyter-lab               (OCR mode)
                              │  ├─── :3001/:7270/...  nginx defaults  (OCR mode)
                              │  │
                              │  └────────────────────────────────────
                              │
                              │  ┌─── :11434 vLLM Qwen3-VL-32B-FP8     (CNC mode)
                              │  ├─── :8002  FastAPI (our backend)     (CNC mode)
                              │  └─── :8888  Next.js (our frontend)    (CNC mode)
                              ▼
                          (held by whichever mode is active)
```

Public URLs (via RunPod's Cloudflare proxy — only ports the pod has
exposed as HTTP are reachable):

- OCR mode: `https://<pod-id>-8000.proxy.runpod.net`
- CNC mode: `https://<pod-id>-8888.proxy.runpod.net`

---

## Provisioning a new pod (first time)

### 1. Create the pod on RunPod

- **Template**: the customer's OCR template (so `DwgDataExtract`,
  `supervisord`, `jupyter-lab`, `nginx` all come pre-installed).
- **GPU**: RTX PRO 6000 Blackwell (~97 GiB) — Qwen3-VL-32B-FP8 needs ~83 GiB
  at steady state.
- **Network volume**: attach the existing CoFab volume if you have one
  (then `/workspace` keeps the model cache + saved runs); otherwise a
  fresh volume.
- **Exposed HTTP ports**: include both **8000** (OCR) and **8888** (us).
  Optional: 3001, 7270, 7861, 8001, 8081, 9091 for nginx defaults.
- **Exposed TCP port**: include **22** so SSH works.

### 2. Get our repo onto the pod

```bash
# from your laptop
scp -P <pod-ssh-port> -i ~/.ssh/id_ed25519 -r e:/data/CNCMachining root@<pod-ip>:/workspace/

# or — if the pod has git access — clone instead:
ssh -p <pod-ssh-port> -i ~/.ssh/id_ed25519 root@<pod-ip> \
  'git clone https://github.com/ArchiusVuong-sudo/CNCMachine.git /workspace/CNCMachining'
```

Adjust paths as needed if your local checkout isn't at `e:/data/CNCMachining`.

### 3. Run bootstrap

```bash
ssh -p <pod-ssh-port> -i ~/.ssh/id_ed25519 root@<pod-ip>
bash /workspace/CNCMachining/server/deploy/bootstrap_pod.sh
```

This is idempotent — re-run safely after partial failures. It will:

- Install Node 22 if missing.
- Create the two venvs (server + vllm011).
- `npm install && npm run build` in the frontend.
- Copy switch/launch scripts to `/workspace/`.
- Seed `.env` files with placeholders (you'll need to fill these in).

### 4. Fill in secrets

```bash
nano /workspace/CNCMachining/server/.env          # Supabase URL + service key
nano /workspace/CNCMachining/frontend/.env.local  # Supabase URL + PUBLISHABLE key
```

`server/.env` is the source of truth — `server/.env.example` documents
every variable.

### 5. Pre-warm the Qwen3-VL model (optional but recommended)

If `/workspace/hf-cache` doesn't already contain the model (e.g.
fresh volume), the first `switch_to_cnc.sh` will lazy-download it on
boot (slow, ~17 GB). Pre-warming avoids that:

```bash
export HF_HOME=/workspace/hf-cache
/workspace/venvs/vllm011/bin/python -c \
  "from huggingface_hub import snapshot_download; \
   snapshot_download('Qwen/Qwen3-VL-32B-Instruct-FP8', local_dir_use_symlinks=False)"
```

### 6. Switch to CNC mode

```bash
bash /workspace/switch_to_cnc.sh
```

Then watch the boot:

```bash
tail -f /workspace/logs/vllm-qwen.log    # ~60-90s warm, ~4-6 min cold
tail -f /workspace/logs/fastapi.log
tail -f /workspace/logs/nextjs.log
bash /workspace/status.sh
```

Public URL: `https://<pod-id>-8888.proxy.runpod.net`

---

## Daily use

### Flipping modes

```bash
# Customer wants the OCR app online
bash /workspace/switch_to_ocr.sh

# We want our CNC stack online
bash /workspace/switch_to_cnc.sh

# Quick check
bash /workspace/status.sh
```

Either switch is idempotent and takes ~5–10s for the orchestration step,
plus ~60–90s for vLLM to warm up on CNC mode.

### Tailing logs

```bash
tail -f /workspace/logs/{vllm-qwen,fastapi,nextjs,jupyter}.log
```

The OCR app's logs depend on its template — usually under
`/workspace/DwgDataExtract/` or the supervisord log dir.

### Deploying a code change to CNC

After scp'ing updated source up:

```bash
cd /workspace/CNCMachining/frontend
export PATH=/workspace/node/bin:$PATH
rm -rf .next .turbo                       # avoid Turbopack cache reuse
npm run build
tmux kill-session -t nextjs; tmux new-session -d -s nextjs \
  "bash /workspace/start_frontend.sh > /workspace/logs/nextjs.log 2>&1"
```

For server-only changes (Python):

```bash
tmux kill-session -t fastapi; tmux new-session -d -s fastapi \
  "bash /workspace/start_fastapi.sh > /workspace/logs/fastapi.log 2>&1"
```

For LLM-only changes (model swap, vLLM flags): edit `serve_qwen.sh`,
then `tmux kill-session -t vllm-qwen; tmux new-session …`.

---

## Migration from the old pod (network volume re-attach)

If you provision a new pod with the **same** network volume that the
old one used, almost everything is preserved:

- `CNCMachining/` source + uncommitted edits
- `KNOWLEDGE_BASE/_research/notes/*` (saved-run history that drives the
  Previous Projects panel)
- `hf-cache/` (model weights)
- `venvs/server`, `venvs/vllm011` (no need to reinstall — they may need
  a `pip install -r` refresh if you've bumped requirements)
- `.env` files

What you still need to re-do:

1. Run `bootstrap_pod.sh` once — it'll be near-instant (everything
   above is already there) but it ensures the latest copy of the
   switch/launch scripts is in `/workspace/`.
2. Reconfigure SSH if you've rotated keys.

If the new pod gets a **fresh** volume:

- Re-scp the source, re-run bootstrap, re-fill `.env`, lazy-download the
  model. Saved-run history is lost unless you tar `_research/notes` from
  the old volume first.

---

## Troubleshooting

| Symptom | Most likely cause | Fix |
|---|---|---|
| `switch_to_cnc.sh` exits with GPU still pinned | OCR's vLLM EngineCore is orphan-parented to init | The script kills it; if it returns, run `pkill -9 -f VLLM::EngineCore` then re-switch |
| Next.js can't bind `:8888` (`EADDRINUSE`) | Jupyter Lab respawned | `pkill -9 -f jupyter-lab` then retry |
| Public URL serves stale HTML | Cloudflare's edge cached an old `s-maxage=31536000` response | Stop & start the pod to refresh proxy state, or wait, or hit via SSH tunnel: `ssh -L 8888:localhost:8888 …` |
| `/api/v1/analyses` returns 404 via proxy | RunPod edge hasn't re-primed the route after a mode flip | Same fix as above — Stop/Start the pod |
| OCR auto-respawns after `switch_to_cnc.sh` | supervisord is asked to *stop* the program, not killed | If you want it dead longer, also `supervisorctl shutdown` but that disables ALL supervisord-managed services |
| FastAPI 500s on `analyze-stream` | vLLM still loading | `tail -f /workspace/logs/vllm-qwen.log` — wait for `Application startup complete`, then `/v1/models` should be 200 |
| `bootstrap_pod.sh` fails on vLLM install | torch/CUDA mismatch with the pod's base image | Force a specific vLLM version: `pip install vllm==0.11.0` (or whichever is current); check `nvidia-smi` driver matches |
