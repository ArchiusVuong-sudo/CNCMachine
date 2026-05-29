#!/usr/bin/env bash
# Switch the pod back to the OCR template (drawing-extraction-api).
#
# Kills our three tmux sessions, frees the GPU, then asks supervisord to
# start the OCR app and re-launches Jupyter Lab + nginx if they're not
# already running (the OCR template expects all three).
#
# Idempotent — safe to re-run.

set +e
SUPCTL=""
if command -v supervisorctl >/dev/null 2>&1; then
    SUPCTL="supervisorctl -c /etc/supervisor/supervisord.conf"
elif [ -x /workspace/.venv/bin/supervisorctl ]; then
    SUPCTL="/workspace/.venv/bin/supervisorctl -c /etc/supervisor/supervisord.conf"
fi

echo "=== stopping CNC tmux sessions + freeing GPU ==="
for s in vllm-qwen fastapi nextjs nextjs-3001; do tmux kill-session -t "$s" 2>/dev/null; done

# Belt-and-braces: kill leftover processes by name.
pkill -9 -f "next-server"            2>/dev/null
pkill -9 -f "server.main"            2>/dev/null
pkill -9 -f "vllm serve"             2>/dev/null
pkill -9 -f "VLLM::EngineCore"       2>/dev/null

sleep 3
echo "GPU memory: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null)"
echo

echo "=== restoring OCR + jupyter + nginx ==="

# 1. Start OCR via supervisord.
if [ -n "$SUPCTL" ]; then
    $SUPCTL start drawing-extraction-api 2>&1 | head -2
fi

# 2. Re-launch Jupyter Lab on :8888 (OCR template default).
if ! pgrep -f "jupyter-lab" >/dev/null && [ -x /usr/local/bin/jupyter-lab ]; then
    nohup /usr/local/bin/jupyter-lab --allow-root --no-browser --port=8888 --ip='*' \
        --FileContentsManager.delete_to_trash=False \
        --ServerApp.allow_origin='*' --ServerApp.preferred_dir=/workspace \
        > /workspace/logs/jupyter.log 2>&1 &
    disown
fi

# 3. Re-launch nginx if killed.
if ! pgrep -x nginx >/dev/null && command -v nginx >/dev/null 2>&1; then
    nginx
fi

echo "=== readiness polling ==="
for i in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
    [ "$code" = "200" ] && { echo "OCR :8000 ready in ${i}s"; break; }
    sleep 1
done

echo
bash /workspace/status.sh
