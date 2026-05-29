#!/usr/bin/env bash
# Launch our Next.js UI on :8888 — the vast.ai-exposed HTTP port for the
# public-facing app. Public URL (if Instance Portal is enabled for this
# host) is shown in the vast.ai dashboard, typically:
#   https://<instance-id>.proxy.vast.ai
# Fallback (no Portal): http://<host-public-ip>:<external-port-mapped-to-8888>
#
# Designed to be exec'd inside a tmux session by switch_to_cnc.sh.
export PATH=/workspace/node/bin:$PATH
cd /workspace/CNCMachining/frontend
exec npm run start -- -H 0.0.0.0 -p 8888
