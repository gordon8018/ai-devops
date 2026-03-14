#!/usr/bin/env bash
# Usage: ./scripts/spawn-agent.sh <repo> <title> <description> [agent] [model]
# Wraps zoe_tool_api.py plan_and_dispatch_task for quick CLI access.
set -euo pipefail

REPO="${1:?Usage: spawn-agent.sh <repo> <title> <description>}"
TITLE="${2:?}"
DESCRIPTION="${3:?}"
AGENT="${4:-codex}"
MODEL="${5:-gpt-5.3-codex}"

BASE_DIR="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
VENV="$BASE_DIR/.venv/bin/python"
API="$BASE_DIR/orchestrator/bin/zoe_tool_api.py"

[[ -x "$VENV" ]] || { echo "[ERROR] Python venv not found at $VENV. Set AI_DEVOPS_HOME or run 'python -m venv .venv'." >&2; exit 1; }
[[ -f "$API" ]] || { echo "[ERROR] API script not found: $API" >&2; exit 1; }

ARGS_FILE=$(mktemp /tmp/zoe-spawn-XXXXXX.json)
trap 'rm -f "$ARGS_FILE"' EXIT

# Use Python single-quoted -c to build JSON safely — avoids shell injection
# via title/description. Arguments are passed as sys.argv, not shell-expanded.
python3 -c \
  'import json,sys,time; print(json.dumps({"repo":sys.argv[1],"title":sys.argv[2],"description":sys.argv[3],"agent":sys.argv[4],"model":sys.argv[5],"requested_by":"cli","requested_at":int(time.time()*1000)}))' \
  "$REPO" "$TITLE" "$DESCRIPTION" "$AGENT" "$MODEL" > "$ARGS_FILE"

printf '%s\n' "{\"tool\":\"plan_and_dispatch_task\",\"args\":$(cat "$ARGS_FILE")}" |
  "$VENV" "$API" invoke
