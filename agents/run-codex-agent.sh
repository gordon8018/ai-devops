#!/usr/bin/env bash
set -euo pipefail

TASK_NAME=$1
MODEL=$2
EFFORT=$3
WORKTREE=$4
PROMPT_FILE=${5:-prompt.txt}

LOG_DIR=~/ai-devops/logs
mkdir -p "$LOG_DIR"

cd "$WORKTREE"

codex \
  --model "$MODEL" \
  -c "model_reasoning_effort=$EFFORT" \
  --dangerously-bypass-approvals-and-sandbox \
  "$(cat "$PROMPT_FILE")" \
  | tee "$LOG_DIR/$TASK_NAME.log"
