#!/usr/bin/env bash
# One-shot bootstrap for a fresh OCR-template pod that needs our CNC stack
# layered on top. Designed to be idempotent — re-run after partial failure.
#
# Pre-requisites the operator handles before running this:
#   1. Pod provisioned on RunPod with an OCR-template image.
#      Exposed HTTP ports must include 8000 (OCR) AND 8888 (us).
#   2. Network volume attached at /workspace if you want to preserve old
#      runs / KB / model cache; otherwise we set up from scratch.
#   3. The CNCMachining repo is available at /workspace/CNCMachining/.
#      Either:
#        (a) scp -r from local:   scp -r CNCMachining/ root@pod:/workspace/
#        (b) git clone (HTTPS):   git clone https://github.com/ArchiusVuong-sudo/CNCMachine.git /workspace/CNCMachining
#        (c) re-attached volume from a previous pod.
#
# What this script does:
#   - Installs Node 22 to /workspace/node if missing.
#   - Creates two Python venvs:
#       /workspace/venvs/server   (FastAPI + engines)
#       /workspace/venvs/vllm011  (vLLM 0.11.x for Qwen3-VL serving)
#   - npm install + first build of the Next.js frontend.
#   - Copies the deploy scripts (switch_to_*, status, start_*, serve_qwen)
#     to /workspace/ where the switch flow expects them.
#   - Creates /workspace/logs.
#   - DOES NOT download the Qwen3-VL model — see step 7 of the printout
#     at the end if HF cache is empty.
#
# Run from anywhere as root:
#   bash /workspace/CNCMachining/server/deploy/bootstrap_pod.sh

set -e
set -o pipefail

REPO=/workspace/CNCMachining
SCRIPTS_SRC=$REPO/server/deploy
NODE_VER=v22.14.0

echo "================================================================"
echo "CNCMachining pod bootstrap"
echo "================================================================"

# ---- sanity ---------------------------------------------------------------
if [ ! -d "$REPO" ]; then
    echo "ERROR: $REPO not found. scp the repo up or git-clone it first." >&2
    exit 1
fi
mkdir -p /workspace/logs

# ---- Node ----------------------------------------------------------------
if [ ! -x /workspace/node/bin/node ]; then
    echo "=== installing Node $NODE_VER ==="
    cd /tmp
    tarball=node-${NODE_VER}-linux-x64.tar.xz
    [ -f "$tarball" ] || curl -fsSL "https://nodejs.org/dist/${NODE_VER}/${tarball}" -o "$tarball"
    mkdir -p /workspace/node
    # --no-same-owner avoids "Cannot change ownership" on the network volume.
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

# ---- Python: vllm venv (Qwen3-VL serving) --------------------------------
# Kept separate from the server venv to avoid torch/vllm version drift.
if [ ! -x /workspace/venvs/vllm011/bin/vllm ]; then
    echo "=== creating /workspace/venvs/vllm011 (will install vLLM 0.11.x) ==="
    python3 -m venv /workspace/venvs/vllm011
    /workspace/venvs/vllm011/bin/pip install --upgrade pip --quiet
    # vLLM 0.11.x pins compatible torch; let it resolve its own deps.
    /workspace/venvs/vllm011/bin/pip install "vllm>=0.11,<0.12"
fi

# ---- Frontend ------------------------------------------------------------
echo "=== installing frontend deps + first build ==="
cd "$REPO/frontend"
# Skip if node_modules + .next already present and fresh.
[ -d node_modules ] || npm install
npm run build

# ---- .env files (skeleton) -----------------------------------------------
SERVER_ENV=$REPO/server/.env
FRONT_ENV=$REPO/frontend/.env.local
if [ ! -f "$SERVER_ENV" ]; then
    echo "=== seeding server/.env (placeholder — fill in Supabase keys!) ==="
    cp "$REPO/server/.env.example" "$SERVER_ENV"
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
         start_fastapi.sh start_frontend.sh serve_qwen.sh; do
    install -m 0755 "$SCRIPTS_SRC/$s" "/workspace/$s"
done

# ---- Done ----------------------------------------------------------------
cat <<'EOF'

================================================================
Bootstrap done.

Next steps (operator):

1. Fill in /workspace/CNCMachining/server/.env with Supabase URLs/keys.
2. Fill in /workspace/CNCMachining/frontend/.env.local (SUPABASE_URL +
   PUBLISHABLE_KEY) — the publishable key is the only one that ships to
   the browser.
3. If /workspace/hf-cache is empty (no Qwen3-VL model on disk), pre-download:

       export HF_HOME=/workspace/hf-cache
       /workspace/venvs/vllm011/bin/python -c \
         "from huggingface_hub import snapshot_download; \
          snapshot_download('Qwen/Qwen3-VL-32B-Instruct-FP8', \
                            local_dir_use_symlinks=False)"

   The first `switch_to_cnc.sh` run will also download it lazily, but
   it'll be slow (~4-6 min just to fetch).

4. Switch to CNC mode for the first time:

       bash /workspace/switch_to_cnc.sh

5. Verify with:

       bash /workspace/status.sh
       curl -s http://localhost:8002/v1/health
       curl -s http://localhost:11434/v1/models

6. Browse: https://<pod-id>-8888.proxy.runpod.net

To go back to the customer's OCR app:

       bash /workspace/switch_to_ocr.sh

================================================================
EOF
