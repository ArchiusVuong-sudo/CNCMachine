#!/usr/bin/env bash
# Start the CNC stack on a vast.ai instance.
#
# vast.ai --ssh instance type disables the container entrypoint, so vLLM
# does NOT auto-start. This script brings up all three services in tmux,
# mirroring the RunPod switch_to_cnc.sh pattern:
#   :8000  vLLM Qwen3-VL  (tmux session: vllm-qwen)
#   :8002  FastAPI        (tmux session: fastapi)
#   :8888  Next.js        (tmux session: nextjs)
#
# vllm is the system-installed binary from vllm/vllm-openai:latest image
# (no venv needed). FastAPI uses /workspace/venvs/server/bin/python.
#
# Idempotent — safe to re-run; existing tmux sessions are killed first.

set +e

echo "=== stopping any running CNC sessions + freeing GPU ==="
for s in vllm-qwen fastapi nextjs; do tmux kill-session -t "$s" 2>/dev/null; done

# Belt-and-braces: kill orphan vLLM workers.
pkill -9 -f "VLLM::EngineCore"                  2>/dev/null
pkill -9 -f "multiprocessing.resource_tracker"  2>/dev/null
pkill -9 -f "next-server"                       2>/dev/null
pkill -9 -f "server.main"                       2>/dev/null

sleep 3
echo "GPU memory: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null)"
echo

echo "=== launching CNC tmux sessions ==="
tmux new-session -d -s vllm-qwen "bash /workspace/serve_qwen.sh > /workspace/logs/vllm-qwen.log 2>&1"
sleep 1
tmux new-session -d -s fastapi   "bash /workspace/start_fastapi.sh > /workspace/logs/fastapi.log 2>&1"
sleep 1
tmux new-session -d -s nextjs    "bash /workspace/start_frontend.sh > /workspace/logs/nextjs.log 2>&1"
sleep 3

echo "=== readiness polling ==="
# FastAPI usually ready in seconds (vLLM client connects lazily).
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/v1/health 2>/dev/null)
    [ "$code" = "200" ] && { echo "FastAPI :8002 ready in ${i}s"; break; }
    sleep 1
done
# Next.js ready in ~5-10s.
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
