# vast.ai deploy & migration runbook

Scripts to provision a [vast.ai](https://vast.ai) instance hosting the
**CNC stack only** (vLLM Qwen3-VL on `:8000`, FastAPI on `:8002`,
Next.js on `:8888`).

This mirrors the RunPod pod #1 layout (see `../README.md`) but adapted
for vast.ai's container model:

| Difference | RunPod | vast.ai |
|---|---|---|
| Network volume | Detachable, persists across pods | Disk fixed at instance creation, dies with instance |
| OCR mode | Pre-installed via customer template | Not deployed (CNC-only) |
| supervisord | Yes — manages OCR app | No — tmux only |
| HTTPS proxy | `https://<pod-id>-<port>.proxy.runpod.net` (auto) | Try Instance Portal; fallback IP:PORT |
| vLLM | We run it in tmux (`serve_qwen.sh`) | Container entrypoint (template auto-starts) |

---

## Files

| File | Purpose |
|---|---|
| [bootstrap_vastai.sh](bootstrap_vastai.sh) | One-shot setup on a fresh instance — Node, server venv, npm build, scripts into place. |
| [switch_to_cnc.sh](switch_to_cnc.sh) | Bring up FastAPI + Next.js tmux sessions. vLLM is already running (entrypoint). |
| [switch_to_ocr.sh](switch_to_ocr.sh) | Stop FastAPI + Next.js. Stub — OCR app not installed; extend if you add it later. |
| [status.sh](status.sh) | Tmux sessions, port listeners, GPU load, vLLM readiness. |
| [start_fastapi.sh](start_fastapi.sh) | Launch our FastAPI server on `:8002`. |
| [start_frontend.sh](start_frontend.sh) | Launch the Next.js frontend on `:8888`. |

`bootstrap_vastai.sh` installs the switch / launch scripts at
`/workspace/` so they're invoked as e.g. `bash /workspace/switch_to_cnc.sh`.
The canonical copies live here in the repo.

---

## Architecture on the instance

```
/workspace/                      ← container disk (IMMUTABLE size — set ≥150 GB at creation)
├── CNCMachining/                ← our repo (server, frontend, KNOWLEDGE_BASE)
├── hf-cache/                    ← HuggingFace model cache (Qwen3-VL FP8 ~17 GB)
├── node/                        ← Node 22 binary distribution
├── venvs/
│   └── server/                  ← Python venv for our FastAPI / engines
├── logs/                        ← stdout/stderr of FastAPI, Next.js
├── switch_to_cnc.sh             ← installed by bootstrap
├── switch_to_ocr.sh
├── status.sh
├── start_fastapi.sh
└── start_frontend.sh

NOTE: vLLM is NOT a venv here. It comes from the vast.ai vLLM template
      base image (`vllm/vllm-openai:latest`) and runs as container PID 1.
```

```
                                 ┌─── :8000  vLLM Qwen3-VL-32B-FP8 (container entrypoint)
GPU (1×)  ────────────────────┐  ├─── :8002  FastAPI (tmux: fastapi)
                              │  └─── :8888  Next.js (tmux: nextjs)
                              ▼
                          (held by vLLM, FastAPI calls vLLM over localhost)
```

Public URLs:

- **If Instance Portal is enabled for the host**:
  `https://<instance-id>.proxy.vast.ai` (HTTPS, free, similar to RunPod)
- **Fallback (raw IP:PORT, HTTP)**:
  `http://<host-public-ip>:<external-port-mapped-to-8888>`
- For production with custom domain: install `cloudflared` and tunnel
  to a Cloudflare zone you control.

---

## Provisioning a new instance (first time)

### 1. Create the instance on vast.ai

In the [vast.ai console](https://cloud.vast.ai/create/):

- **Template**: search for "vLLM" → select the official **vLLM** template
  (base image `vllm/vllm-openai:latest`).
- **GPU filter**:
  - `gpu_name`: `RTX_PRO_6000_S` (Server Edition) or `RTX_PRO_6000_WS` (Workstation)
  - `num_gpus`: 1
  - `gpu_ram` ≥ 96 GB (≥98304 MB)
  - Reliability score ≥ 0.99 (for production); verified host preferred
- **CPU / RAM**:
  - `cpu_cores` ≥ 16 (prefer AMD EPYC 9xxx)
  - `cpu_ram` ≥ 64 GB
- **Disk**: **≥150 GB** ⚠️ IMMUTABLE — cannot resize after creation.
- **Open ports** (template "Edit Template" → Docker Options → comma-separated):
  ```
  8000,8002,8888
  ```
  Port 22 (SSH) is exposed by default.
- **Environment variables** (template "Edit Template" → Env Vars):
  ```
  VLLM_MODEL=Qwen/Qwen3-VL-32B-Instruct-FP8
  VLLM_ARGS=--max-model-len 32768 --gpu-memory-utilization 0.85 --limit-mm-per-prompt {"image":10} --trust-remote-code
  HF_HOME=/workspace/hf-cache
  HF_TOKEN=                   # set if model is gated; Qwen3-VL is public
  ```
  Note: vLLM template's default port is **8000** (not 11434 like RunPod).
  We don't override — we adapt `VISION_MODEL_URL` instead.
- **On-start script** (optional, in template "On-start script"):
  ```bash
  mkdir -p /workspace/hf-cache /workspace/logs
  ```

Click "RENT". Boot time: container ~30s, vLLM model load + CUDA graphs ~4–6 min.

### 2. SSH into the instance

From the vast.ai dashboard, the instance card shows:
```
ssh -p <external-ssh-port> root@<host-ip>
```
Or click "Connect" → "Direct SSH". Use the same `~/.ssh/id_ed25519` key
that's registered on your vast.ai account.

```bash
ssh -p <external-ssh-port> -i ~/.ssh/id_ed25519 root@<host-ip>
```

### 3. Get our repo onto the instance

```bash
# from your laptop
scp -P <external-ssh-port> -i ~/.ssh/id_ed25519 -r e:/data/CNCMachining root@<host-ip>:/workspace/

# or — if the instance has git access — clone instead:
ssh -p <external-ssh-port> -i ~/.ssh/id_ed25519 root@<host-ip> \
  'git clone https://github.com/ArchiusVuong-sudo/CNCMachine.git /workspace/CNCMachining'
```

### 4. Run bootstrap

```bash
ssh -p <external-ssh-port> -i ~/.ssh/id_ed25519 root@<host-ip>
bash /workspace/CNCMachining/server/deploy/vastai/bootstrap_vastai.sh
```

This is idempotent. It will:

- Install Node 22 if missing.
- Create the `server` venv (vLLM venv is NOT created — vLLM lives in the
  container image at system Python).
- `npm install && npm run build` in the frontend.
- Copy switch/launch scripts to `/workspace/`.
- Seed `.env` files with placeholders (you'll need to fill these in).
- Default `VISION_MODEL_URL=http://localhost:8000` (vast.ai vLLM port).

### 5. Fill in secrets

```bash
nano /workspace/CNCMachining/server/.env          # Supabase URL + service key
nano /workspace/CNCMachining/frontend/.env.local  # Supabase URL + PUBLISHABLE key
```

`server/.env.example` documents every variable.

### 6. Wait for vLLM to be ready

vLLM is the container entrypoint — it's already loading the model from
the moment the instance started. Check:

```bash
curl -s http://localhost:8000/v1/models
nvidia-smi   # GPU memory should be ~83 GiB used when model is loaded
```

If you see `{"object":"list","data":[{...}]}` → ready.

Cold boot first-ever model download: ~4–6 min (~17 GB from HF).
Warm restart with cached model: ~60–90s.

### 7. Switch to CNC mode (FastAPI + Next.js)

```bash
bash /workspace/switch_to_cnc.sh
```

Watch boot:

```bash
tail -f /workspace/logs/fastapi.log
tail -f /workspace/logs/nextjs.log
bash /workspace/status.sh
```

### 8. Get the public URL

Two ways depending on whether Instance Portal is available for your host:

**Option A — Instance Portal (try this first)**

In vast.ai dashboard → click on instance → "Open" or "Instance Portal":
- If the host supports it, port 8888 should show an HTTPS URL like:
  `https://<instance-id>.proxy.vast.ai`
- Some hosts only enable Portal for ports 1111/8080 — if 8888 isn't
  routable, switch Next.js to port 8080 (edit `start_frontend.sh`).

**Option B — Direct IP:PORT (fallback)**

In the instance card, "IP & Port Info" shows mapping like:
```
Internal 8888 → External 12345  on host 1.2.3.4
```
Then: `http://1.2.3.4:12345`

⚠️ HTTP only. Supabase Storage requests from `https://*.supabase.co` to
`http://` URLs may be blocked by browser mixed-content policy. If that
becomes an issue, fall through to Option C.

**Option C — Cloudflare Tunnel (if A and B don't work)**

```bash
# Install cloudflared
wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    -O /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# Quick tunnel (no Cloudflare account needed; URL is ephemeral)
cloudflared tunnel --url http://localhost:8888
# Outputs:  https://random-words-xxxx.trycloudflare.com

# For a stable URL: cloudflared tunnel login (requires Cloudflare domain)
```

---

## Daily use

### Start / stop CNC services

```bash
bash /workspace/switch_to_cnc.sh    # start FastAPI + Next.js
bash /workspace/switch_to_ocr.sh    # stop FastAPI + Next.js (vLLM stays up)
bash /workspace/status.sh           # quick check
```

vLLM cannot be stopped without restarting the instance (it's PID 1).
Use the vast.ai dashboard to fully stop the instance.

### Tailing logs

```bash
tail -f /workspace/logs/{fastapi,nextjs}.log
# vLLM logs live in the container's PID-1 stdout — view from vast.ai
# dashboard's "Logs" tab, or:
journalctl -t vllm 2>/dev/null
```

### Deploying a frontend code change

```bash
cd /workspace/CNCMachining/frontend
export PATH=/workspace/node/bin:$PATH
rm -rf .next .turbo
npm run build
tmux kill-session -t nextjs
tmux new-session -d -s nextjs \
  "bash /workspace/start_frontend.sh > /workspace/logs/nextjs.log 2>&1"
```

### Deploying a server (Python) code change

```bash
tmux kill-session -t fastapi
tmux new-session -d -s fastapi \
  "bash /workspace/start_fastapi.sh > /workspace/logs/fastapi.log 2>&1"
```

### Changing the vLLM model

Because vLLM is the container entrypoint, you must:

1. **Stop the instance** in the vast.ai dashboard.
2. **Edit the template's env vars** (VLLM_MODEL, VLLM_ARGS).
3. **Start the instance** again — vLLM picks up the new config.

(There's no in-place restart of just vLLM without taking the container
down.)

---

## Cost note

Vast.ai bills hourly for: GPU + CPU + RAM + disk + network. Estimated
budget for this stack:

| Item | Cost |
|---|---|
| RTX PRO 6000 S (Server Edition, verified, ~16 vCPU, 64 GB RAM) | ~$1.50/hr |
| 150 GB disk | ~$0.03/hr (~$22/mo) |
| Network egress | first ~10 GB free, then ~$0.005/GB |
| **Total** | **~$1.55/hr ≈ $37/day ≈ $1.1k/mo** |

Cheaper than RunPod Secure Cloud (~$2.09/hr) but watch reliability —
host can go offline. Use only `verified` hosts with reliability >0.99
for sustained production.

---

## Troubleshooting

| Symptom | Most likely cause | Fix |
|---|---|---|
| `curl http://localhost:8000/v1/models` returns 503 | vLLM still loading | Wait 4–6 min. Watch `nvidia-smi` — memory should climb to ~83 GiB. |
| `switch_to_cnc.sh` says FastAPI not ready | vLLM not up yet → FastAPI health check fails on first request | Re-run `switch_to_cnc.sh` after vLLM is ready, OR FastAPI may self-recover once vLLM is up. |
| Next.js can't bind `:8888` (`EADDRINUSE`) | Stale `next-server` process | `pkill -9 -f next-server` then re-run `switch_to_cnc.sh`. |
| Instance Portal shows no URL for 8888 | Host doesn't support Portal for that port | Use IP:PORT fallback, or move Next.js to port 8080 in `start_frontend.sh`. |
| Supabase Storage upload blocked from browser | Mixed-content: browser refuses `http://` upload from `https://app` page | Use Cloudflare Tunnel (Option C above) to get HTTPS. |
| Bootstrap fails on `vllm` import | You're not using the vLLM template image | Either re-create instance with the vLLM template, or `pip install vllm==0.11.x` into a new venv at `/workspace/venvs/vllm011/` and adapt scripts. |
| GPU memory full / OOM at vLLM boot | `--gpu-memory-utilization` too high or limit-mm-per-prompt too large | Lower in `VLLM_ARGS` template env (e.g. `--gpu-memory-utilization 0.80`); restart instance. |
| Container restarts unexpectedly | Host disruption / instance preempted (if interruptible tier) | Switch to on-demand tier when re-creating; check reliability score. |
| `scp` works but `ssh` immediately disconnects | Direct SSH port not exposed in template | Edit template → Docker Options → expose `22`. |

---

## Differences callout vs RunPod runbook

If you're familiar with `../README.md` (RunPod), the mental shifts:

1. **vLLM is not yours to start/stop**. It's PID 1; only restart the
   instance to change model.
2. **`/workspace` is not a network volume**. If you destroy the instance,
   `/workspace` is gone. Back up `KNOWLEDGE_BASE/_research/notes/` and
   any other state you care about before stopping/destroying.
3. **No supervisord, no Jupyter, no nginx**. The image is bare-bones;
   only tmux + your own scripts.
4. **OCR mode is not deployed**. To add it back, drop the
   DwgDataExtract source under `/workspace/DwgDataExtract/`, port
   `../switch_to_ocr.sh`'s logic here, and replace supervisord with tmux.
5. **No automatic public HTTPS URL**. Try Instance Portal first; fall
   back to IP:PORT or set up a Cloudflare Tunnel.
