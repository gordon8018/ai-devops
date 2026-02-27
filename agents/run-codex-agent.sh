#!/usr/bin/env bash
set -euo pipefail

TASK_NAME=$1
MODEL=$2
EFFORT=$3
WORKTREE=$4
PROMPT_FILE=${5:-prompt.txt}

LOG_DIR=~/ai-devops/logs
mkdir -p "$LOG_DIR"
STATUS_FILE="$LOG_DIR/$TASK_NAME.exit.json"

cd "$WORKTREE"

resolve_codex_bin() {
  if [[ -n "${CODEX_BIN:-}" ]]; then
    printf '%s\n' "$CODEX_BIN"
    return 0
  fi

  if command -v codex >/dev/null 2>&1; then
    command -v codex
    return 0
  fi

  if [[ -s "$HOME/.nvm/nvm.sh" ]]; then
    # shellcheck disable=SC1090
    . "$HOME/.nvm/nvm.sh"
    if command -v codex >/dev/null 2>&1; then
      command -v codex
      return 0
    fi
  fi

  return 1
}

CODEX_BIN=$(resolve_codex_bin || true)
if [[ -z "$CODEX_BIN" ]]; then
  echo "ERROR: codex CLI not found. Set CODEX_BIN or install codex into PATH." >&2
  exit 127
fi
export PATH="$(dirname "$CODEX_BIN"):$PATH"

PROMPT_CONTENT=$(cat "$PROMPT_FILE")
export CODEX_BIN MODEL EFFORT PROMPT_CONTENT
rm -f "$STATUS_FILE"

# Codex requires a terminal on stdin/stdout. Run it under `script` so it keeps
# a PTY whether the caller uses tmux or a detached background process.
set +e
script -qefc '$CODEX_BIN \
  --model "$MODEL" \
  -c "model_reasoning_effort=$EFFORT" \
  --dangerously-bypass-approvals-and-sandbox \
  "$PROMPT_CONTENT"' "$LOG_DIR/$TASK_NAME.log"
EXIT_CODE=$?
set -e

printf '{\n  "taskId": "%s",\n  "exitCode": %s,\n  "finishedAt": %s\n}\n' \
  "$TASK_NAME" \
  "$EXIT_CODE" \
  "$(date +%s%3N)" > "$STATUS_FILE"

exit "$EXIT_CODE"
