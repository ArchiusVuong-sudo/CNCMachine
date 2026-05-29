#!/usr/bin/env bash
# Quick status: which mode is active, who owns which port, GPU load.

echo "=== tmux sessions ==="
tmux ls 2>/dev/null || echo "(no tmux server)"
echo

echo "=== port listeners ==="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) \
    | grep -E ":(3000|3001|7270|7861|8000|8001|8002|8081|8888|9091|11434) " \
    | sort -k4,4 -t: -n -k2 | head -20
echo

echo "=== local HTTP health ==="
for port in 8000 8002 8888 11434; do
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 http://localhost:$port/ 2>/dev/null)
    case "$port" in
        8000)  label="OCR app"       ;;
        8002)  label="CNC FastAPI"   ;;
        8888)  label="CNC Next.js / OCR Jupyter" ;;
        11434) label="CNC vLLM Qwen3-VL" ;;
    esac
    printf "  :%-6s %-32s  %s\n" "$port" "$label" "$code"
done
echo

echo "=== supervisord ==="
if command -v supervisorctl >/dev/null 2>&1; then
    supervisorctl -c /etc/supervisor/supervisord.conf status 2>/dev/null
elif [ -x /workspace/.venv/bin/supervisorctl ]; then
    /workspace/.venv/bin/supervisorctl -c /etc/supervisor/supervisord.conf status 2>/dev/null
else
    echo "(supervisorctl not found)"
fi
echo

echo "=== GPU ==="
nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "(nvidia-smi unavailable)"

echo
# Mode inference: presence of tmux sessions for our stack indicates CNC.
if tmux has-session -t fastapi 2>/dev/null && tmux has-session -t nextjs 2>/dev/null; then
    echo "Mode: CNC"
elif pgrep -f "DwgDataExtract/app.py" >/dev/null 2>&1; then
    echo "Mode: OCR"
else
    echo "Mode: idle / mixed"
fi
