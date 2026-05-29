#!/usr/bin/env bash
# One-shot bootstrap for a fresh vast.ai instance using the vLLM template.
# Designed to be idempotent — re-run safely after partial failure.
#
# The vast.ai vLLM template image already has:
#   - vLLM installed (system Python, /usr/local/bin/vllm typically)
#   - CUDA + cuDNN runtime
#   - Python 3.11
#   - vLLM auto-started on container entrypoint with $VLLM_MODEL / $VLLM_ARGS
#
# What this script ADDS on top:
#   - Node 22 at /workspace/node (for the Next.js frontend)
#   - Python venv at /workspace/venvs/server (for our FastAPI + engines)
#   - npm install + first build of the Next.js frontend
#   - Switch / launch scripts at /workspace/
#   - Skeleton .env files
#
# Pre-requisites the operator handles before running this:
#   1. Vast.ai instance created with the vLLM template:
#      - GPU:       RTX PRO 6000 Blackwell (or equivalent, ≥96 GiB VRAM)
#      - Disk:      ≥150 GB (IMMUTABLE — set at creation time, cannot resize)
#      - vCPU:      ≥16 (ideally AMD EPYC 9xxx)
#      - RAM:       ≥64 GB
#      - Open ports (in template config — comma-separated):
#          8000   → vLLM (template default; Instance Portal HTTPS candidate)
#          8002   → FastAPI
#          8888   → Next.js (public-facing; mark as primary HTTPS port)
#          22     → SSH
#      - Env vars (in template config):
#          VLLM_MODEL=Qwen/Qwen3-VL-32B-Instruct-FP8
#          VLLM_ARGS=--max-model-len 32768 --gpu-memory-utilization 0.85 --limit-mm-per-prompt '{"image": 10}' --trust-remote-code
#          HF_HOME=/workspace/hf-cache
#          HF_TOKEN=<optional; only if model is gated>
#
#   2. The CNCMachining repo is at /workspace/CNCMachining/. Either:
#        (a) scp -r e:/data/CNCMachining root@<host>:<port>:/workspace/
#        (b) git clone https://github.com/ArchiusVuong-sudo/CNCMachine.git /workspace/CNCMachining
#
# IMPORTANT — vast.ai vLLM image with --ssh:
#   Vast.ai's --ssh instance type DISABLES the container's auto-entrypoint,
#   so vLLM does NOT auto-start despite using vllm/vllm-openai:latest as
#   the image. We start it ourselves in a tmux session (switch_to_cnc.sh →
#   serve_qwen.sh), exactly like the RunPod pattern.
#   The `vllm` binary is on PATH (system Python in the image) — no venv
#   needed for vLLM.
#
# Run from anywhere as root inside the instance:
#   bash /workspace/CNCMachining/server/deploy/vastai/bootstrap_vastai.sh

set -e
set -o pipefail

REPO=/workspace/CNCMachining
SCRIPTS_SRC=$REPO/server/deploy/vastai
NODE_VER=v22.14.0

echo "================================================================"
echo "CNCMachining vast.ai bootstrap"
echo "================================================================"

# ---- sanity ---------------------------------------------------------------
if [ ! -d "$REPO" ]; then
    echo "ERROR: $REPO not found. scp the repo up or git-clone it first." >&2
    exit 1
fi
mkdir -p /workspace/logs /workspace/hf-cache

# ---- vLLM sanity ---------------------------------------------------------
if ! command -v vllm >/dev/null 2>&1; then
    echo "WARNING: 'vllm' command not on PATH. Expected vllm/vllm-openai:latest"
    echo "  to have vllm pre-installed at system Python. If you used a"
    echo "  different image, install vLLM into a venv at /workspace/venvs/vllm011/"
    echo "  and adapt serve_qwen.sh to use that venv path."
else
    echo "vLLM detected at: $(command -v vllm)"
    vllm --version 2>&1 | head -1
fi

# ---- Node ----------------------------------------------------------------
if [ ! -x /workspace/node/bin/node ]; then
    echo "=== installing Node $NODE_VER ==="
    cd /tmp
    tarball=node-${NODE_VER}-linux-x64.tar.xz
    [ -f "$tarball" ] || curl -fsSL "https://nodejs.org/dist/${NODE_VER}/${tarball}" -o "$tarball"
    mkdir -p /workspace/node
    tar -xf "$tarball" --strip-components=1 -C /workspace/node --no-same-owner
    /workspace/node/bin/node --version
fi
export PATH=/workspace/node/bin:$PATH

# ---- Python: server venv -------------------------------------------------
if [ ! -x /workspace/venvs/server/bin/python ]; then
    echo "=== creating /workspace/venvs/server ==="
    python3 -m venv /workspace/venvs/server
fi
echo "=== installing server requirements ==="
/workspace/venvs/server/bin/pip install --upgrade pip --quiet
/workspace/venvs/server/bin/pip install -r "$REPO/server/requirements.txt" --quiet

# ---- Frontend ------------------------------------------------------------
echo "=== installing frontend deps + first build ==="
cd "$REPO/frontend"
[ -d node_modules ] || npm install
npm run build

# ---- .env files (skeleton) -----------------------------------------------
SERVER_ENV=$REPO/server/.env
FRONT_ENV=$REPO/frontend/.env.local
if [ ! -f "$SERVER_ENV" ]; then
    echo "=== seeding server/.env (placeholder — fill in Supabase keys!) ==="
    cp "$REPO/server/.env.example" "$SERVER_ENV"
    # vast.ai vLLM template defaults to port 8000, not RunPod's 11434.
    sed -i 's|^VISION_MODEL_URL=.*|VISION_MODEL_URL=http://localhost:8000|' "$SERVER_ENV"
fi
if [ ! -f "$FRONT_ENV" ]; then
    cat > "$FRONT_ENV" <<EOF
# Pod-local Next.js → Python proxy target (FastAPI on :8002).
PYTHON_SERVICE_URL=http://localhost:8002

# Supabase (Storage only — publishable key; never the service-role key).
# Fill in or copy from your local frontend/.env.local before switching to CNC.
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
EOF
fi

# ---- Install switch + launch scripts at /workspace ----------------------
echo "=== installing switch/launch scripts at /workspace ==="
for s in switch_to_cnc.sh switch_to_ocr.sh status.sh \
         serve_qwen.sh start_fastapi.sh start_frontend.sh; do
    install -m 0755 "$SCRIPTS_SRC/$s" "/workspace/$s"
done

# ---- Done ----------------------------------------------------------------
cat <<'EOF'

================================================================
Bootstrap done.

Next steps (operator):

1. Fill in /workspace/CNCMachining/server/.env with Supabase URLs/keys.
   (VISION_MODEL_URL is already set to http://localhost:8000 to match
   vast.ai vLLM template's default port.)

2. Fill in /workspace/CNCMachining/frontend/.env.local (SUPABASE_URL +
   PUBLISHABLE_KEY).

3. Pre-warm the Qwen3-VL model (recommended — first switch_to_cnc.sh
   will lazy-download it otherwise, ~17 GB, slow):

       export HF_HOME=/workspace/hf-cache
       python3 -c "from huggingface_hub import snapshot_download; \
           snapshot_download('Qwen/Qwen3-VL-32B-Instruct-FP8', \
                             local_dir_use_symlinks=False)"

4. Start CNC stack (vLLM + FastAPI + Next.js):

       bash /workspace/switch_to_cnc.sh

5. Verify:

       bash /workspace/status.sh
       curl -s http://localhost:8002/v1/health
       curl -s http://localhost:8888/
       tail -f /workspace/logs/vllm-qwen.log    # cold ~4-6 min

6. Get the public URL:
   - Check vast.ai dashboard → Instance → Instance Portal:
     If available, port 8888 will have an HTTPS URL like:
         https://<instance-id>.proxy.vast.ai
   - Fallback: direct IP:PORT
         http://<host-public-ip>:<external-port-mapped-to-8888>
     (Find the external port in dashboard or via `printenv | grep PORT`)

OCR mode is NOT deployed on this vast.ai setup (CNC-only).
   switch_to_ocr.sh just stops the CNC services. If you later want OCR,
   provide DwgDataExtract source and adapt switch_to_ocr.sh.

================================================================
EOF
