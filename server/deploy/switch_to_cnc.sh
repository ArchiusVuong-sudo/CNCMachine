#!/usr/bin/env bash
# Switch the pod from the OCR template to our CNC stack.
#
# Layout:
#   - OCR side (template default): port 8000 (drawing-extraction-api,
#     supervisord-managed), :8888 jupyter-lab, nginx on :3001/:7270/etc.
#   - CNC side (ours): :11434 vLLM Qwen3-VL, :8002 FastAPI, :8888 Next.js.
#
# Port 8888 is shared (jupyter vs Next.js) and the GPU is shared between
# OCR's vLLM-backed engine and our vLLM. This script stops the OCR side,
# frees the GPU + 8888, and brings our three tmux sessions up.
#
# Idempotent — safe to re-run; existing tmux sessions are killed first.

set +e
SUPCTL=""
if command -v supervisorctl >/dev/null 2>&1; then
    SUPCTL="supervisorctl -c /etc/supervisor/supervisord.conf"
elif [ -x /workspace/.venv/bin/supervisorctl ]; then
    SUPCTL="/workspace/.venv/bin/supervisorctl -c /etc/supervisor/supervisord.conf"
fi

echo "=== stopping OCR + freeing GPU/port 8888 ==="

# 1. Ask supervisord to stop the OCR app (it would auto-respawn otherwise).
if [ -n "$SUPCTL" ]; then
    $SUPCTL stop drawing-extraction-api 2>&1 | head -2
fi

# 2. Kill any orphan vLLM EngineCore left over from the OCR side.
pkill -9 -f "VLLM::EngineCore" 2>/dev/null
pkill -9 -f "multiprocessing.resource_tracker" 2>/dev/null

# 3. Kill Jupyter Lab so Next.js can bind port 8888.
pkill -9 -f "jupyter-lab" 2>/dev/null

sleep 3
echo "GPU memory: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null)"
echo

echo "=== launching CNC tmux sessions ==="
for s in vllm-qwen fastapi nextjs; do tmux kill-session -t "$s" 2>/dev/null; done

tmux new-session -d -s vllm-qwen "bash /workspace/serve_qwen.sh > /workspace/logs/vllm-qwen.log 2>&1"
sleep 1
tmux new-session -d -s fastapi   "bash /workspace/start_fastapi.sh > /workspace/logs/fastapi.log 2>&1"
sleep 1
tmux new-session -d -s nextjs    "bash /workspace/start_frontend.sh > /workspace/logs/nextjs.log 2>&1"
sleep 3

echo "=== readiness polling ==="
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/v1/health 2>/dev/null)
    [ "$code" = "200" ] && { echo "FastAPI :8002 ready in ${i}s"; break; }
    sleep 1
done
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/ 2>/dev/null)
    [ "$code" = "200" ] && { echo "Next.js :8888 ready in ${i}s"; break; }
    sleep 1
done

echo
echo "vLLM Qwen3-VL is loading the 32B FP8 model — first start ~4-6 min,"
echo "warm restart ~60-90s. Watch with: tail -f /workspace/logs/vllm-qwen.log"
echo

bash /workspace/status.sh
