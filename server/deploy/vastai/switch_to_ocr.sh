#!/usr/bin/env bash
# Stop the CNC stack on a vast.ai instance.
#
# NOTE: OCR mode is NOT currently deployed on vast.ai. On RunPod, the
# OCR template (DwgDataExtract + supervisord + jupyter-lab + nginx) ships
# pre-installed and switch_to_ocr.sh restores it. Vast.ai has no such
# template, so this script just shuts down the CNC services. To add real
# OCR mode here, install the OCR source under /workspace/DwgDataExtract/
# and extend this script with the start logic.
#
# This kills all three CNC tmux sessions including vLLM (which on vast.ai
# runs in a tmux session, not as container PID 1 — because --ssh disables
# the container entrypoint).
#
# Idempotent — safe to re-run.

set +e

echo "=== stopping CNC tmux sessions + freeing GPU ==="
for s in vllm-qwen fastapi nextjs; do tmux kill-session -t "$s" 2>/dev/null; done

# Belt-and-braces: kill orphan processes.
pkill -9 -f "VLLM::EngineCore"                  2>/dev/null
pkill -9 -f "multiprocessing.resource_tracker"  2>/dev/null
pkill -9 -f "next-server"                       2>/dev/null
pkill -9 -f "server.main"                       2>/dev/null
pkill -9 -f "vllm serve"                        2>/dev/null

sleep 3
echo "GPU memory: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null)"
echo
echo "All CNC services stopped (vLLM, FastAPI, Next.js)."
echo
echo "OCR mode is not configured on this vast.ai deployment."
echo "  To add OCR: install DwgDataExtract source under /workspace/DwgDataExtract/"
echo "  and extend this script to start it (mirror switch_to_ocr.sh from"
echo "  server/deploy/switch_to_ocr.sh, replacing supervisord with tmux)."
echo

bash /workspace/status.sh
