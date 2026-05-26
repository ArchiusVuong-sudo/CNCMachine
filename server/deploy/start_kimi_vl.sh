#!/usr/bin/env bash
# Kimi-VL-A3B-Thinking-2506 (bf16) -> OpenAI-compatible API for the CNC
# agentic engine (Engine 3). Single RTX PRO 6000 (97 GiB).
#
# Replaces cyankiwi/Kimi-Linear-48B-A3B-Instruct-AWQ-4bit, whose linear-
# attention KDA hybrid degenerated into a repeated-'!' collapse under chunked
# prefill on the 4-bit quant. This model is a standard Moonlight MoE
# (16B total / ~2.8B active) served in bf16 -> numerically stable.
#
# Notes:
#  * Served name kept as 'kimi-agent' so the client config (AGENT_LLM_MODEL)
#    is unchanged.
#  * --trust-remote-code: KimiVL ships custom HF config/processor modules.
#  * Thinking model: emits a reasoning block before the JSON answer; the
#    client AgentVLLMProvider strips it before parsing (no vLLM reasoning
#    parser is registered for Kimi-VL in this build).
#  * --skip-mm-profiling + --limit-mm-per-prompt '{"image":0}': Engine 3 is
#    TEXT-ONLY (drawing vision is Engine 1/Qwen3-VL on the other pod). Without
#    these, vLLM's memory profiler feeds a max-resolution dummy image through
#    the MoonViT vision tower, whose SDPA attention materializes a full
#    O(patches^2) score matrix -> a single 216 GiB allocation -> CUDA OOM at
#    boot. Skipping MM profiling and disallowing images removes that path.
set -euo pipefail
source /etc/rp_environment 2>/dev/null || true
export PATH="/root/.local/bin:$PATH"
export HF_HUB_OFFLINE=1
export PYTORCH_ALLOC_CONF=expandable_segments:True
SNAP=/workspace/hf-cache/models--moonshotai--Kimi-VL-A3B-Thinking-2506/snapshots/aa1730989e7558695b44ee493623e03bd325a994
exec /workspace/kimivenv/bin/vllm serve "$SNAP" \
  --served-model-name kimi-agent \
  --host 0.0.0.0 --port 8000 \
  --trust-remote-code \
  --tensor-parallel-size 1 \
  --max-model-len 65536 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 32 \
  --max-num-batched-tokens 16384 \
  --skip-mm-profiling \
  --limit-mm-per-prompt '{"image":0}'
