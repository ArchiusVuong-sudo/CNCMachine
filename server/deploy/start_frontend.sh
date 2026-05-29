#!/usr/bin/env bash
# Launch our Next.js UI on :8888 (the only RunPod-exposed HTTP port we own).
# Public URL: https://<pod-id>-8888.proxy.runpod.net
# Designed to be exec'd inside a tmux session by switch_to_cnc.sh.
export PATH=/workspace/node/bin:$PATH
cd /workspace/CNCMachining/frontend
exec npm run start -- -H 0.0.0.0 -p 8888
