#!/usr/bin/env bash
# Zero-token status check: tmux sessions + SQLite active tasks.
# No Python LLM calls. Safe to run at any time.
set -uo pipefail

BASE_DIR="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
DB="$BASE_DIR/.clawdbot/agent_tasks.db"

echo "=== Active tmux agent sessions ==="
if command -v tmux &>/dev/null; then
  tmux ls 2>/dev/null | grep '^agent-' || echo "(none)"
else
  echo "(tmux not available)"
fi

echo ""
echo "=== Active tasks (SQLite) ==="
if [[ -f "$DB" ]]; then
  sqlite3 "$DB" "SELECT id, status, attempts, branch FROM agent_tasks WHERE status IN ('running','pr_created') ORDER BY started_at;"
else
  echo "(database not found: $DB)"
fi
