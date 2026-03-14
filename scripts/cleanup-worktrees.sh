#!/usr/bin/env bash
# Single-run cleanup trigger — runs all cleanup tasks once without the scheduler.
set -euo pipefail

BASE_DIR="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
VENV="$BASE_DIR/.venv/bin/python"
DAEMON="$BASE_DIR/orchestrator/bin/cleanup_daemon.py"

echo "[INFO] Running cleanup tasks (single-run mode)..."
"$VENV" "$DAEMON" --once
