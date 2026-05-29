#!/usr/bin/env bash
# Launch vLLM serving Qwen3-VL-32B-Instruct-FP8 on :11434.
# This is our Engine 1 (drawing VLM) AND Engine 3 (agentic planner) backend.
# Designed to be exec'd inside a tmux session by switch_to_cnc.sh.
#
# Boot: cold ~4-6 min (model load + CUDA graph compile), warm ~60-90s.

export HF_HOME=/workspace/hf-cache
exec /workspace/venvs/vllm011/bin/vllm serve Qwen/Qwen3-VL-32B-Instruct-FP8 \
    --host 0.0.0.0 \
    --port 11434 \
    --served-model-name Qwen/Qwen3-VL-32B-Instruct-FP8 \
    --trust-remote-code \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.9 \
    --limit-mm-per-prompt '{"image": 10}'
