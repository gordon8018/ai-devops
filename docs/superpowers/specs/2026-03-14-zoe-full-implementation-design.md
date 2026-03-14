# Zoe Full Implementation Design

**Date:** 2026-03-14
**Status:** Approved
**Scope:** Full alignment of current codebase with the Zoe system design architecture

---

## Background

The Zoe system is an AI agent orchestration platform where Zoe (OpenClaw) acts as the AI product manager and engineering director, dispatching coding tasks to agent workers (Codex, Claude Code) running in isolated git worktrees under tmux sessions.

A gap analysis was performed against the [elvissun reference architecture (Feb 2026)]. The analysis identified the following critical problems in the current codebase:

1. **Split Brain**: `zoe-daemon.py` and `monitor.py` read/write JSON registry (`active-tasks.json`), while `db.py` and `webhook_server.py` use SQLite (`agent_tasks.db`). These are completely independent — webhook-triggered PR status updates never reach the monitor.
2. **`monitor.py --once` missing**: `webhook_server.py` calls `monitor.py --once` but monitor has no such flag; it only runs as an infinite loop. Webhook triggers are silently ignored.
3. **`retry_task` not exposed to OpenClaw**: The architecture diagram includes `Z → retry_task` as a core tool, but it is absent from `zoe_tool_contract.py` and `SKILL.md`.
4. **Ralph Loop v2 incomplete**: Retries only append CI failure logs; no Obsidian business context, no failure history, no success pattern learning.
5. **No PR review pipeline**: No automated multi-model PR review.
6. **No maintenance automation**: No stale worktree cleanup, no structured failure logs, no prompt-template memory.

---

## Design Decisions

| Topic | Decision |
|-------|----------|
| Data store | SQLite only — JSON registry completely removed, no migration layer |
| Notification | Telegram Bot API — Discord webhook removed |
| Obsidian integration | Obsidian Local REST API (port 27123); silently skipped if unreachable |
| PR Review | Local only (no GitHub Actions) — Codex + Claude, Gemini interface reserved |
| Cleanup trigger | Python `schedule` daemon (`cleanup_daemon.py`), started alongside zoe-daemon |

---

## Phase 1: Data Layer Unification

**Goal:** SQLite becomes the single source of truth. All JSON registry references are deleted.

### `db.py` changes

Add missing columns to `agent_tasks` table:

```sql
ALTER TABLE agent_tasks ADD COLUMN execution_mode TEXT DEFAULT 'tmux';
ALTER TABLE agent_tasks ADD COLUMN prompt_file TEXT;
ALTER TABLE agent_tasks ADD COLUMN notify_on_complete INTEGER DEFAULT 1;
ALTER TABLE agent_tasks ADD COLUMN worktree_strategy TEXT DEFAULT 'isolated';
ALTER TABLE agent_tasks ADD COLUMN cleaned_up INTEGER DEFAULT 0;
```

Add new query methods:
- `get_task_by_tmux_session(session: str) -> Optional[dict]`
- `get_task_by_process_id(pid: int) -> Optional[dict]`
- `mark_cleaned_up(task_id: str) -> None`

Remove legacy compatibility functions:
- `migrate_from_json()`
- `load_registry()` (legacy alias)
- `save_registry()` (legacy alias)

### `zoe-daemon.py` changes

- Call `init_db()` at startup
- Replace `load_registry()` / `save_registry()` with `db.get_task()` / `db.insert_task()`
- After `spawn_agent()`, write result directly to SQLite via `db.insert_task()`
- Remove all `REGISTRY` / `active-tasks.json` path references

### `monitor.py` changes

- Add `argparse` with `--once` flag: when set, run one scan loop then exit
- Replace `load_registry()` / `save_registry()` with `db.get_running_tasks()` / `db.update_task()`
- Remove all JSON file references

### Files/references to delete

- All code reading/writing `.clawdbot/active-tasks.json`
- `REGISTRY` path constant in `zoe-daemon.py` and `monitor.py`
- `migrate_from_json`, `load_registry`, `save_registry` in `db.py`

### Verification

- `daemon spawn` → `db.get_task(task_id)` returns record
- Webhook receives PR event → `monitor --once` correctly reads and updates task status
- No code anywhere references `active-tasks.json`

---

## Phase 2: Core Tool Completion

**Goal:** Expose `retry_task` to OpenClaw; migrate notifications to Telegram.

### `retry_task` tool

Add to `zoe_tools.py`:

```python
def retry_task(
    task_id: str,
    *,
    reason: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Manually trigger a retry for a task.
    Reads the original prompt, appends retry directive, restarts the agent.
    Returns updated task dict.
    """
```

Logic:
1. Load task from SQLite
2. Validate `status in ('blocked', 'agent_dead', 'agent_failed')` and `attempts < maxAttempts`
3. Read `prompt_file` from task record
4. Write `prompt.retryN.txt` with retry directive appended
5. Call `restart_codex_agent()` (or claude equivalent)
6. Increment `attempts`, set `status = 'running'`, update SQLite

Register in `zoe_tool_contract.py`:
```python
{
    "name": "retry_task",
    "description": "Manually retry a failed or dead task by task_id",
    "parameters": {
        "task_id": {"type": "string", "required": True},
        "reason": {"type": "string", "required": False},
    }
}
```

Add routing in `zoe_tool_api.py`. Add usage example in `openclaw-skills/zoe-local-tools/SKILL.md`:

```bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{"task_id": "<task-id>", "reason": "Manual retry after investigating root cause"}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call retry_task --args-file /tmp/zoe-tool-args.json
```

### `orchestrator/bin/notify.py`

New module encapsulating Telegram Bot API:

```python
def notify(msg: str) -> None:
    """Send message to configured Telegram chat. Silent on failure."""

def notify_ready(task_id: str, pr_url: str) -> None:
    """Human-review-ready notification with PR link."""

def notify_failure(task_id: str, detail: str) -> None:
    """CI failure / agent death notification."""
```

Environment variables:
- `TELEGRAM_BOT_TOKEN` — Bot token from @BotFather
- `TELEGRAM_CHAT_ID` — Target chat/group ID

All `notify()` calls in `monitor.py` replaced with `from notify import notify`. Discord webhook `DISCORD_WEBHOOK_URL` references removed from `monitor.py` and `discord/.env.example`.

### Verification

- Zoe calls `retry_task` → agent restarts, SQLite `attempts` incremented
- CI failure → Telegram message received
- No Discord webhook calls anywhere in monitor code path

---

## Phase 3: Ralph Loop v2

**Goal:** Retry prompts include Obsidian business context and structured failure history. Successful prompts are saved as templates.

### `orchestrator/bin/obsidian_client.py`

```python
class ObsidianClient:
    def __init__(self, base_url: str, token: str): ...

    def search(self, query: str, limit: int = 3) -> list[dict]:
        """Search vault, return list of {path, excerpt}. Returns [] if unreachable."""

    def get_note(self, path: str) -> str:
        """Fetch full note content. Returns '' if unreachable."""

    def find_by_tags(self, tags: list[str]) -> list[dict]:
        """Find notes by tags."""

    @classmethod
    def from_env(cls) -> "ObsidianClient":
        """Construct from OBSIDIAN_API_TOKEN and OBSIDIAN_API_PORT env vars."""
```

All methods catch connection errors and return empty results (never raise). This ensures Obsidian being offline never blocks the retry loop.

Error handling contract:
- Connection refused / timeout → log `[INFO] Obsidian unreachable, skipping business context` and return `[]` / `""`
- HTTP 4xx → log `[WARN] Obsidian API error <status>` and return empty
- No retry on failure within the same monitor cycle; next cycle will try again naturally

### Enhanced retry prompt in `monitor.py`

When CI failure triggers a retry, build the retry prompt as:

```
<original prompt.txt content>

BUSINESS CONTEXT (from Obsidian):
<top 1-2 search results for task title + repo>

PAST FAILURES FOR THIS REPO:
<last 2 failure log excerpts from .clawdbot/failure-logs/<repo>/>

RERUN DIRECTIVE (Retry #N):
CI is failing. Your ONLY priority is to make CI green.
Failed checks summary: <fail_summary>

<ci_detail tail>

Instructions:
- Read failing logs and identify root cause.
- Apply minimal fix.
- Run local equivalent checks/tests if available.
- Push commits to the SAME branch and update the PR.
```

Obsidian search uses task `title` as query. If Obsidian is unreachable, the `BUSINESS CONTEXT` section is omitted silently.

### Success pattern memory

When a task transitions to `ready` status in `monitor.py`:
1. Copy `prompt.txt` to `.clawdbot/prompt-templates/<repo>/<sanitized-title>.md`
2. Write metadata header with: repo, attempts count, CI duration, timestamp

In `zoe_tools.py` `build_plan_request()`, before returning the plan request:
1. Check `.clawdbot/prompt-templates/<repo>/` for existing templates (max 3, sorted by mtime descending)
2. If found, inject into the plan request payload:
   ```python
   context["successPatterns"] = [
       {"title": "<sanitized-title>", "attemptCount": 1, "timestamp": 1741910400000}
       # one entry per template file, parsed from the markdown header
   ]
   ```
3. `planner_engine.py` references `context.get("successPatterns")` in `_build_prompt()`: if present, appends a `PAST SUCCESSES` section listing the titles as hints to the agent about what approaches worked before
4. Template format (markdown header):
   ```markdown
   <!-- attempts=1 timestamp=1741910400000 repo=my-repo -->
   <original prompt.txt content>
   ```

### Failure log structure

On CI failure detection in `monitor.py`, write:

```
.clawdbot/failure-logs/<repo>/<task-id>-<timestamp>.json
```

```json
{
  "taskId": "...",
  "repo": "...",
  "failSummary": "test:FAILURE; lint:FAILURE",
  "ciDetail": "...",
  "attemptNumber": 1,
  "timestamp": 1741910400000
}
```

### Verification

- Retry prompt contains `BUSINESS CONTEXT` section when Obsidian is running
- Retry proceeds normally (no error) when Obsidian is offline
- After task `ready`: `prompt-templates/<repo>/` contains new file
- After CI failure: `failure-logs/<repo>/` contains structured JSON

---

## Phase 4: Local PR Review Pipeline

**Goal:** Auto-trigger Codex + Claude review comments on PR creation. Gemini reserved.

### `orchestrator/bin/reviewer.py`

```python
def review_pr(task_id: str, pr_number: int, repo_dir: Path) -> None:
    """
    Fetch PR diff, run Codex and Claude reviewers as background subprocesses,
    post gh pr comment for each. Gemini is reserved (no-op).
    Called by monitor.py when task transitions to pr_created.
    """

def _run_codex_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Spawn codex with review prompt, post result as gh pr comment."""

def _run_claude_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Spawn claude with review prompt, post result as gh pr comment."""

def _run_gemini_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Reserved. Logs skip message, does nothing."""
```

Each reviewer runs as an independent `subprocess.Popen` (non-blocking). Review prompt template:

```
You are a senior code reviewer. Review the following PR diff for correctness,
security issues, edge cases, and test coverage gaps.
Be concise. Use GitHub markdown. Start with a one-line summary.

PR DIFF:
<diff content>
```

Comment prefix includes reviewer identity: `🤖 **Codex Review:**` / `🤖 **Claude Review:**`.

### Integration in `monitor.py`

When task status changes from `running` → `pr_created`:

```python
from reviewer import review_pr
# Fire and forget — reviewer runs in background subprocess
threading.Thread(
    target=review_pr,
    args=(task_id, pr.get("number"), worktree),
    daemon=True,
).start()
```

### Verification

- PR created → two review comments appear (Codex + Claude)
- Gemini reviewer logs `[INFO] Gemini reviewer not yet implemented, skipping`
- Monitor main loop not blocked by review subprocess

---

## Phase 5: Cleanup Daemon + Directory Structure

**Goal:** Daily automated maintenance; complete directory and script structure per design spec.

### `orchestrator/bin/cleanup_daemon.py`

Uses `schedule` library. Runs as a standalone process alongside `zoe-daemon.py` and `monitor.py`.

```python
def cleanup_stale_worktrees() -> None:
    """
    For all tasks in terminal states (blocked, merged, agent_failed, agent_dead)
    where cleaned_up=0: run `git worktree remove --force`, mark cleaned_up=1 in SQLite.
    """

def cleanup_old_queue_files() -> None:
    """Delete queue/*.json files older than 7 days."""

def cleanup_failure_logs() -> None:
    """Delete .clawdbot/failure-logs/**/*.json older than 30 days."""

def main() -> None:
    schedule.every().day.at("02:00").do(cleanup_stale_worktrees)
    schedule.every().day.at("02:00").do(cleanup_old_queue_files)
    schedule.every().day.at("02:30").do(cleanup_failure_logs)
    while True:
        schedule.run_pending()
        time.sleep(60)
```

### Directory structure to create

```
.clawdbot/
├── agent_tasks.db                    # SQLite (existing)
├── prompt-templates/                 # NEW: successful prompt templates by repo
│   └── <repo>/
│       └── <sanitized-title>.md
└── failure-logs/                     # NEW: structured failure records by repo
    └── <repo>/
        └── <task-id>-<timestamp>.json
```

Both directories created programmatically at startup (not committed to git; add to `.gitignore`).

### New scripts

**`scripts/spawn-agent.sh`** — Shell wrapper to invoke `plan_and_dispatch_task` via `zoe_tool_api.py`:
```bash
#!/usr/bin/env bash
# Usage: ./scripts/spawn-agent.sh <repo> <title> <description>
```

**`scripts/cleanup-worktrees.sh`** — Manual single-run cleanup trigger:
```bash
#!/usr/bin/env bash
# Runs cleanup_daemon.py cleanup functions once (not the scheduler loop)
python3 orchestrator/bin/cleanup_daemon.py --once
```

**`scripts/babysit.sh`** — Zero-token lightweight status check (no Python/LLM):
```bash
#!/usr/bin/env bash
# Check tmux sessions and print SQLite task status — zero token cost
echo "=== Active tmux agent sessions ==="
tmux ls 2>/dev/null | grep '^agent-' || echo "(none)"

echo ""
echo "=== Active tasks (SQLite) ==="
sqlite3 "${AI_DEVOPS_HOME:-$HOME/ai-devops}/.clawdbot/agent_tasks.db" \
  "SELECT id, status, attempts, branch FROM agent_tasks WHERE status IN ('running','pr_created') ORDER BY started_at;"
```

### `.gitignore` additions

```
.clawdbot/agent_tasks.db
.clawdbot/prompt-templates/
.clawdbot/failure-logs/
.clawdbot/active-tasks.json
```

### Verification

- `cleanup_daemon.py` starts without error, runs scheduled jobs at 02:00
- `.clawdbot/prompt-templates/` and `failure-logs/` created on first run
- `babysit.sh` outputs current active tasks with no Python dependency
- `cleanup-worktrees.sh --once` removes worktrees for terminal-state tasks

---

## New Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram notification bot |
| `TELEGRAM_CHAT_ID` | Yes | — | Telegram target chat/group |
| `OBSIDIAN_API_TOKEN` | No | — | Obsidian Local REST API auth |
| `OBSIDIAN_API_PORT` | No | `27123` | Obsidian Local REST API port |

## Removed Environment Variables

| Variable | Reason |
|----------|--------|
| `DISCORD_WEBHOOK_URL` | Replaced by Telegram |

---

## Delivery Order

| Phase | Key files changed/created | Blocks |
|-------|--------------------------|--------|
| 1 | `db.py`, `zoe-daemon.py`, `monitor.py` | All others |
| 2 | `notify.py`, `zoe_tools.py`, `zoe_tool_contract.py`, `SKILL.md` | Phase 3 retry |
| 3 | `obsidian_client.py`, `monitor.py` (retry enhancement) | — |
| 4 | `reviewer.py`, `monitor.py` (pr_created hook) | — |
| 5 | `cleanup_daemon.py`, `scripts/*.sh` | — |

Phases 3, 4, 5 are independent after Phase 2 and can be parallelized.

---

## New Python Dependencies

The following packages must be added to `pyproject.toml` / `requirements.txt`:

| Package | Version | Phase | Purpose |
|---------|---------|-------|---------|
| `requests` | `>=2.31` | 2, 3 | Telegram API, Obsidian REST API |
| `schedule` | `>=1.2` | 5 | Cleanup daemon scheduling |

## Out of Scope

- GitHub Actions workflows (deliberately excluded)
- Gemini agent runner (interface reserved, implementation deferred)
- Obsidian vault file sync (Obsidian manages its own vault; we only query via API)
- Production DB readonly connector
- Playwright E2E test setup
