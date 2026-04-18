#!/usr/bin/env bash
set -euo pipefail

TASK_NAME=$1
MODEL=$2
EFFORT=$3
WORKTREE=$4
PROMPT_FILE=${5:-prompt.txt}

LOG_ROOT=${AI_DEVOPS_HOME:-$HOME/ai-devops}
LOG_DIR="$LOG_ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$TASK_NAME.log"
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

write_status() {
  local exit_code=$1
  python3 - <<'PY' "$STATUS_FILE" "$TASK_NAME" "$exit_code"
import json, sys, time
from pathlib import Path
status_file = Path(sys.argv[1])
task_name = sys.argv[2]
exit_code = int(sys.argv[3])
status_file.write_text(json.dumps({
    'taskId': task_name,
    'exitCode': exit_code,
    'finishedAt': int(time.time() * 1000),
}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
}

CODEX_BIN=$(resolve_codex_bin || true)
: > "$LOG_FILE"
rm -f "$STATUS_FILE"
if [[ -z "$CODEX_BIN" ]]; then
  echo "ERROR: codex CLI not found. Set CODEX_BIN or install codex into PATH." | tee -a "$LOG_FILE" >&2
  write_status 127
  exit 127
fi
export PATH="$(dirname "$CODEX_BIN"):$PATH"

TASK_SPEC_FILE=${TASK_SPEC_FILE:-}
TASK_SPEC_REQUIRED=${TASK_SPEC_REQUIRED:-0}
SCOPE_MANIFEST_FILE=${SCOPE_MANIFEST_FILE:-}
if [[ "$TASK_SPEC_REQUIRED" == "1" ]]; then
  if [[ -z "$TASK_SPEC_FILE" || ! -f "$TASK_SPEC_FILE" ]]; then
    echo "ERROR: TASK_SPEC_FILE is required for scoped execution but missing." | tee -a "$LOG_FILE" >&2
    write_status 66
    exit 66
  fi
fi
if [[ -n "$SCOPE_MANIFEST_FILE" && ! -f "$SCOPE_MANIFEST_FILE" ]]; then
  echo "ERROR: SCOPE_MANIFEST_FILE was provided but missing: $SCOPE_MANIFEST_FILE" | tee -a "$LOG_FILE" >&2
  write_status 67
  exit 67
fi

PROMPT_CONTENT=$(cat "$PROMPT_FILE")
export CODEX_BIN MODEL EFFORT PROMPT_CONTENT TASK_SPEC_FILE TASK_SPEC_REQUIRED SCOPE_MANIFEST_FILE LOG_FILE

if [[ -n "$SCOPE_MANIFEST_FILE" && -f "$SCOPE_MANIFEST_FILE" ]]; then
  echo "[SCOPE_MANIFEST] using manifest: $SCOPE_MANIFEST_FILE" | tee -a "$LOG_FILE" >&2
fi

if [[ -n "$TASK_SPEC_FILE" && -f "$TASK_SPEC_FILE" ]]; then
  echo "[TASK_SPEC] using contract: $TASK_SPEC_FILE" | tee -a "$LOG_FILE" >&2
  python3 - <<'PY' "$TASK_SPEC_FILE" 2>&1 | tee -a "$LOG_FILE" >&2
import json, sys
from pathlib import Path
p = Path(sys.argv[1])
data = json.loads(p.read_text(encoding='utf-8'))
allowed = data.get('allowedPaths') or []
forbidden = data.get('forbiddenPaths') or []
must_touch = data.get('mustTouch') or []
print('[TASK_SPEC] allowedPaths=', len(allowed))
print('[TASK_SPEC] forbiddenPaths=', len(forbidden))
print('[TASK_SPEC] mustTouch=', len(must_touch))
PY
fi

set +e
python3 - <<'PY' "$LOG_FILE"
import os, pty, sys
log_path = sys.argv[1]
argv = [
    os.environ['CODEX_BIN'],
    '--model', os.environ['MODEL'],
    '-c', f"model_reasoning_effort={os.environ['EFFORT']}",
    '--dangerously-bypass-approvals-and-sandbox',
    os.environ['PROMPT_CONTENT'],
]
pid, fd = pty.fork()
if pid == 0:
    os.execvp(argv[0], argv)
exit_code = 1
with open(log_path, 'ab') as logf:
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            logf.write(chunk)
            logf.flush()
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        exit_code = os.WEXITSTATUS(status)
    elif os.WIFSIGNALED(status):
        exit_code = 128 + os.WTERMSIG(status)
    else:
        exit_code = 1
sys.exit(exit_code)
PY
EXIT_CODE=$?
set -e

write_status "$EXIT_CODE"
exit "$EXIT_CODE"
