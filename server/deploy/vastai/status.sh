#!/usr/bin/env bash
# Quick status on a vast.ai instance: tmux sessions, port listeners,
# GPU usage, vLLM readiness.

echo "=== tmux sessions ==="
tmux ls 2>/dev/null || echo "(no tmux server)"
echo

echo "=== port listeners ==="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) \
    | grep -E ":(8000|8002|8888|11434) " \
    | sort -k4,4 -t: -n -k2 | head -20
echo

echo "=== local HTTP health ==="
for port in 8000 8002 8888; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:$port/ 2>/dev/null)
    case "$port" in
        8000) label="vLLM Qwen3-VL (template entrypoint)" ;;
        8002) label="CNC FastAPI" ;;
        8888) label="CNC Next.js" ;;
    esac
    printf "  :%-6s %-40s  %s\n" "$port" "$label" "$code"
done
echo

echo "=== vLLM models ==="
curl -s --max-time 3 http://localhost:8000/v1/models 2>/dev/null \
    | head -c 400
echo
echo

echo "=== GPU ==="
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null \
    || echo "(nvidia-smi unavailable)"
echo

# Mode inference: presence of our tmux sessions = CNC active.
if tmux has-session -t fastapi 2>/dev/null && tmux has-session -t nextjs 2>/dev/null; then
    echo "Mode: CNC"
else
    echo "Mode: idle (vLLM up but FastAPI/Next.js down)"
fi
