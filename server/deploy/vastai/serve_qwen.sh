#!/usr/bin/env bash
# Launch vLLM serving Qwen3-VL-32B-Instruct-FP8 on :8000.
# This is our Engine 1 (drawing VLM) AND Engine 3 (agentic planner) backend.
# Designed to be exec'd inside a tmux session by switch_to_cnc.sh.
#
# On vast.ai, the vllm/vllm-openai:latest image has `vllm` pre-installed
# at the system Python level — no venv needed. The `--ssh` instance type
# disables the container entrypoint, so vLLM does NOT auto-start; this
# script is what brings it up.
#
# Boot: cold ~4-6 min (model load + CUDA graph compile), warm ~60-90s.

export HF_HOME=/workspace/hf-cache
exec vllm serve Qwen/Qwen3-VL-32B-Instruct-FP8 \
    --host 0.0.0.0 \
    --port 8000 \
    --served-model-name Qwen/Qwen3-VL-32B-Instruct-FP8 \
    --trust-remote-code \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.9 \
    --limit-mm-per-prompt '{"image": 10}'
