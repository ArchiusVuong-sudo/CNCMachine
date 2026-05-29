#!/usr/bin/env bash
# Launch our FastAPI backend on :8002.
# Designed to be exec'd inside a tmux session by switch_to_cnc.sh.
cd /workspace/CNCMachining
exec /workspace/venvs/server/bin/python -m server.main
