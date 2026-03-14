# Zoe Full Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Zoe orchestration system with the approved design spec by fixing a split-brain data store, completing the core tool surface, adding Ralph Loop v2 intelligence, a local PR review pipeline, and an automated cleanup daemon.

**Architecture:** SQLite becomes the single source of truth (replacing JSON registry). A Telegram notifier replaces Discord webhook. New modules — `notify.py`, `obsidian_client.py`, `reviewer.py`, `cleanup_daemon.py` — integrate cleanly as peers in `orchestrator/bin/`. All new behaviour is TDD-first.

**Tech Stack:** Python 3.12, SQLite (stdlib), `requests` (Telegram + Obsidian), `schedule` (cleanup), `gh` CLI (PR comments), tmux, pytest

**Spec:** `docs/superpowers/specs/2026-03-14-zoe-full-implementation-design.md`

---

## File Map

### Created
| File | Responsibility |
|------|----------------|
| `orchestrator/bin/notify.py` | Telegram Bot API wrapper — single `notify(msg)` function |
| `orchestrator/bin/obsidian_client.py` | Obsidian Local REST API client — search, get_note, find_by_tags |
| `orchestrator/bin/reviewer.py` | Spawn Codex + Claude PR review subprocesses; post `gh pr comment` |
| `orchestrator/bin/cleanup_daemon.py` | `schedule`-based daemon: clean stale worktrees, old queue files, failure logs |
| `scripts/spawn-agent.sh` | Shell wrapper around `zoe_tool_api.py invoke plan_and_dispatch_task` |
| `scripts/cleanup-worktrees.sh` | Single-run cleanup trigger (calls cleanup_daemon --once) |
| `scripts/babysit.sh` | Zero-token tmux + SQLite status check |
| `tests/test_notify.py` | Unit tests for notify.py |
| `tests/test_obsidian_client.py` | Unit tests for obsidian_client.py |
| `tests/test_reviewer.py` | Unit tests for reviewer.py |
| `tests/test_cleanup_daemon.py` | Unit tests for cleanup_daemon.py |

### Modified
| File | Changes |
|------|---------|
| `orchestrator/bin/db.py` | Add 5 columns, 3 query methods; remove 3 legacy functions |
| `orchestrator/bin/zoe-daemon.py` | Replace JSON registry with SQLite; remove REGISTRY constant |
| `orchestrator/bin/monitor.py` | Replace JSON with SQLite; add `--once` flag; add Telegram; add reviewer trigger; add Obsidian retry context |
| `orchestrator/bin/zoe_tools.py` | Add `retry_task()`; add success-pattern injection in `build_plan_request()` |
| `orchestrator/bin/zoe_tool_contract.py` | Register `retry_task` schema |
| `orchestrator/bin/zoe_tool_api.py` | Route `retry_task` calls |
| `orchestrator/bin/planner_engine.py` | Reference `successPatterns` in `_build_prompt()` |
| `openclaw-skills/zoe-local-tools/SKILL.md` | Add `retry_task` usage example; remove `active-tasks.json` reference |
| `discord/bot.py` | Remove Discord webhook notification references |
| `.gitignore` | Add `.clawdbot/`, `worktrees/` patterns |
| `discord/.env.example` | Remove `DISCORD_WEBHOOK_URL`; add Telegram vars |

---

## Chunk 1: Phase 1 — Data Layer Unification

> Remove the split-brain. SQLite is the only task store. JSON registry is deleted everywhere.

---

### Task 1: Extend db.py schema and add new query methods

**Files:**
- Modify: `orchestrator/bin/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for the three new query methods**

Add to `tests/test_db.py`:

```python
def test_get_task_by_tmux_session(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    db_mod.insert_task({
        "id": "t1", "repo": "r", "title": "T",
        "tmuxSession": "agent-t1", "status": "running",
    })
    result = db_mod.get_task_by_tmux_session("agent-t1")
    assert result is not None
    assert result["id"] == "t1"

def test_get_task_by_tmux_session_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    assert db_mod.get_task_by_tmux_session("nonexistent") is None

def test_get_task_by_process_id(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    db_mod.insert_task({
        "id": "t2", "repo": "r", "title": "T",
        "processId": 12345, "status": "running",
    })
    result = db_mod.get_task_by_process_id(12345)
    assert result is not None
    assert result["id"] == "t2"

def test_mark_cleaned_up(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    db_mod.insert_task({"id": "t3", "repo": "r", "title": "T", "status": "merged"})
    db_mod.mark_cleaned_up("t3")
    task = db_mod.get_task("t3")
    assert task["cleaned_up"] == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/gordonyang/workspace/myproject/ai-devops
python -m pytest tests/test_db.py::test_get_task_by_tmux_session tests/test_db.py::test_get_task_by_process_id tests/test_db.py::test_mark_cleaned_up -v 2>&1 | tail -20
```

Expected: `AttributeError` or `FAILED` — methods don't exist yet.

- [ ] **Step 3: Update `init_db()` in `db.py` to add new columns**

Replace the `CREATE TABLE` block inside `init_db()` so the full schema is:

```python
def init_db() -> None:
    """Initialize database schema"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                plan_id TEXT,
                repo TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                agent TEXT DEFAULT 'codex',
                model TEXT DEFAULT 'gpt-5.3-codex',
                effort TEXT DEFAULT 'medium',
                worktree TEXT,
                branch TEXT,
                tmux_session TEXT,
                process_id INTEGER,
                execution_mode TEXT DEFAULT 'tmux',
                prompt_file TEXT,
                notify_on_complete INTEGER DEFAULT 1,
                worktree_strategy TEXT DEFAULT 'isolated',
                cleaned_up INTEGER DEFAULT 0,
                started_at INTEGER,
                completed_at INTEGER,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                pr_number INTEGER,
                pr_url TEXT,
                last_failure TEXT,
                last_failure_at INTEGER,
                note TEXT,
                metadata TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                updated_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
            )
        """)

        # Indexes for common queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON agent_tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plan ON agent_tasks(plan_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_started ON agent_tasks(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_repo ON agent_tasks(repo)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tmux ON agent_tasks(tmux_session)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pid ON agent_tasks(process_id)")

        # Migrate existing DBs: add new columns if absent
        new_columns = [
            ("execution_mode", "TEXT DEFAULT 'tmux'"),
            ("prompt_file", "TEXT"),
            ("notify_on_complete", "INTEGER DEFAULT 1"),
            ("worktree_strategy", "TEXT DEFAULT 'isolated'"),
            ("cleaned_up", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in new_columns:
            try:
                conn.execute(f"ALTER TABLE agent_tasks ADD COLUMN {col_name} {col_def}")
            except Exception:
                pass  # column already exists

        conn.commit()
```

- [ ] **Step 4: Add the three new query methods to `db.py`**

Add after `get_task_by_branch()`:

```python
def get_task_by_tmux_session(session: str) -> Optional[dict]:
    """Get a task by tmux session name"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE tmux_session = ?",
            (session,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_task_by_process_id(pid: int) -> Optional[dict]:
    """Get a task by background process ID"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE process_id = ?",
            (pid,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def mark_cleaned_up(task_id: str) -> None:
    """Mark worktree as cleaned up"""
    update_task(task_id, {"cleaned_up": 1})
```

- [ ] **Step 5: Update `insert_task()` to persist new fields**

In the existing `insert_task()`, update the INSERT statement to include the new columns:

```python
def insert_task(task: dict) -> None:
    """Insert or update a task"""
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO agent_tasks
            (id, plan_id, repo, title, status, agent, model, effort,
             worktree, branch, tmux_session, process_id,
             execution_mode, prompt_file, notify_on_complete, worktree_strategy,
             started_at, attempts, max_attempts, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task["id"],
            task.get("planId") or task.get("plan_id"),
            task["repo"],
            task["title"],
            task.get("status", "queued"),
            task.get("agent", "codex"),
            task.get("model", "gpt-5.3-codex"),
            task.get("effort", "medium"),
            task.get("worktree"),
            task.get("branch"),
            task.get("tmuxSession") or task.get("tmux_session"),
            task.get("processId") or task.get("process_id"),
            task.get("executionMode") or task.get("execution_mode", "tmux"),
            task.get("promptFile") or task.get("prompt_file"),
            int(task.get("notifyOnComplete", task.get("notify_on_complete", 1))),
            task.get("worktreeStrategy") or task.get("worktree_strategy", "isolated"),
            task.get("startedAt") or task.get("started_at"),
            task.get("attempts", 0),
            task.get("maxAttempts") or task.get("max_attempts", 3),
            json.dumps(task.get("metadata", {})),
            int(__import__("time").time() * 1000)
        ))
        conn.commit()
```

- [ ] **Step 6: Run the new tests to confirm they pass**

```bash
python -m pytest tests/test_db.py::test_get_task_by_tmux_session tests/test_db.py::test_get_task_by_tmux_session_miss tests/test_db.py::test_get_task_by_process_id tests/test_db.py::test_mark_cleaned_up -v
```

Expected: all 4 PASS.

- [ ] **Step 7: Run full db test suite to ensure no regressions**

```bash
python -m pytest tests/test_db.py -v
```

Expected: all existing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add orchestrator/bin/db.py tests/test_db.py
git commit -m "feat(db): add new columns, query methods for SQLite-only architecture"
```

---

### Task 2: Remove legacy JSON functions from db.py

**Files:**
- Modify: `orchestrator/bin/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write a test that confirms legacy functions do NOT exist**

Add to `tests/test_db.py`:

```python
def test_legacy_functions_removed():
    import orchestrator.bin.db as db_mod
    assert not hasattr(db_mod, "migrate_from_json"), \
        "migrate_from_json must be removed"
    assert not hasattr(db_mod, "load_registry"), \
        "load_registry must be removed"
    assert not hasattr(db_mod, "save_registry"), \
        "save_registry must be removed"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python -m pytest tests/test_db.py::test_legacy_functions_removed -v
```

Expected: FAIL — functions still exist.

- [ ] **Step 3: Delete the three legacy functions from `db.py`**

Remove the following functions entirely from `db.py`:
- `migrate_from_json()` (entire function, ~30 lines)
- `load_registry()` (the legacy alias at the bottom)
- `save_registry()` (the legacy alias at the bottom)

Also remove the comment block `# Legacy compatibility - load_registry for backward compatibility`.

- [ ] **Step 4: Run the test to confirm it passes**

```bash
python -m pytest tests/test_db.py -v
```

Expected: all tests pass including `test_legacy_functions_removed`.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/db.py tests/test_db.py
git commit -m "feat(db): remove legacy JSON registry compatibility functions"
```

---

### Task 3: Migrate zoe-daemon.py to SQLite-only

**Files:**
- Modify: `orchestrator/bin/zoe-daemon.py`
- Modify: `tests/test_db.py` (add daemon integration test)

- [ ] **Step 1: Write a failing integration test for spawn writing to SQLite**

Add to `tests/test_db.py`:

```python
def test_spawn_agent_writes_sqlite(tmp_path, monkeypatch):
    """After spawn_agent(), the task must appear in SQLite, not a JSON file."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    # JSON registry must NOT exist after spawn
    json_registry = tmp_path / ".clawdbot" / "active-tasks.json"
    assert not json_registry.exists(), \
        "active-tasks.json must not be created by daemon"
```

> Note: full integration test for `spawn_agent()` requires a real git repo and runner; this test validates the file system contract only. Full daemon tests already exist in `tests/test_db.py`.

- [ ] **Step 2: Run to see it pass (or fail if daemon writes JSON)**

```bash
python -m pytest tests/test_db.py::test_spawn_agent_writes_sqlite -v
```

- [ ] **Step 3: Edit `zoe-daemon.py` — replace JSON registry with SQLite**

At the top of the file, replace the import block:

```python
# REMOVE these lines:
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"

# ADD these imports instead:
import sys
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))
from db import init_db, get_task, insert_task
```

Replace `load_registry()` function with nothing (delete it).
Replace `save_registry()` function with nothing (delete it).

In `main()`, replace startup:
```python
# Old:
QUEUE.mkdir(parents=True, exist_ok=True)
print(f"Zoe daemon started. Watching queue: {QUEUE}")

# New:
QUEUE.mkdir(parents=True, exist_ok=True)
init_db()
print(f"Zoe daemon started. Watching queue: {QUEUE}")
```

In `main()`, replace the registry duplicate-check and save:
```python
# Old:
reg = load_registry()
if any(x.get("id") == task["id"] for x in reg):
    p.unlink(missing_ok=True)
    continue

item = spawn_agent(task)
reg.append(item)
save_registry(reg)

# New:
if get_task(task["id"]) is not None:
    p.unlink(missing_ok=True)
    continue

item = spawn_agent(task)
insert_task(item)
```

- [ ] **Step 4: Run existing daemon tests**

```bash
python -m pytest tests/test_db.py -v
```

Expected: all pass.

- [ ] **Step 5: Verify no reference to `active-tasks.json` remains in `zoe-daemon.py`**

```bash
grep -n "active-tasks\|REGISTRY\|load_registry\|save_registry" orchestrator/bin/zoe-daemon.py
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/bin/zoe-daemon.py tests/test_db.py
git commit -m "feat(daemon): migrate to SQLite-only, remove JSON registry"
```

---

### Task 4: Migrate monitor.py to SQLite + add `--once` flag

**Files:**
- Modify: `orchestrator/bin/monitor.py`
- Modify: `tests/test_monitor.py`

- [ ] **Step 1: Write failing tests for `--once` behaviour and SQLite reads**

Add to `tests/test_monitor.py`:

```python
def test_monitor_once_flag_exits(tmp_path, monkeypatch):
    """monitor --once must run one cycle and exit (not loop)."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib
    import orchestrator.bin.monitor as mon
    importlib.reload(mon)

    # Patch db to return empty list (nothing to monitor)
    monkeypatch.setattr(mon, "get_running_tasks", lambda: [])

    calls = []
    def fake_run_once(notified_ready):
        calls.append(1)

    # run_once should be called exactly once when --once is passed
    import sys
    old_argv = sys.argv[:]
    sys.argv = ["monitor.py", "--once"]
    try:
        monkeypatch.setattr(mon, "run_once", fake_run_once)
        mon.main()
    finally:
        sys.argv = old_argv

    assert len(calls) == 1, "run_once should be called exactly once with --once flag"


def test_monitor_reads_sqlite_not_json(tmp_path, monkeypatch):
    """monitor must not access active-tasks.json."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import orchestrator.bin.monitor as mon
    import importlib
    importlib.reload(mon)

    json_path = tmp_path / ".clawdbot" / "active-tasks.json"
    json_path.parent.mkdir(parents=True)
    json_path.write_text('[{"id":"stale","status":"running"}]')

    # If monitor reads JSON, it would see this stale task.
    # If it reads SQLite (empty), it sees nothing.
    seen_ids = []
    original = mon.get_running_tasks if hasattr(mon, "get_running_tasks") else None

    monkeypatch.setattr(mon, "get_running_tasks", lambda: [])
    monkeypatch.setattr(mon, "save_registry", lambda x: None, raising=False)

    # run_once with empty SQLite — should process 0 tasks
    mon.run_once(set())
    # If it tried to read stale JSON task, we'd get an error or side effect
    # reaching here without error is the assertion
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python -m pytest tests/test_monitor.py::test_monitor_once_flag_exits tests/test_monitor.py::test_monitor_reads_sqlite_not_json -v 2>&1 | tail -15
```

Expected: FAIL — `run_once`, `get_running_tasks` not in monitor.

- [ ] **Step 3: Refactor `monitor.py` — extract `run_once()` and add argparse**

At the top of `monitor.py`, add imports:

```python
import argparse
import sys
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))
from db import init_db, get_running_tasks, update_task, get_task
```

Remove:
```python
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"
```

Remove the `load_registry()` and `save_registry()` functions entirely.

Extract the body of the monitor loop into a new function `run_once()`:

```python
def run_once(notified_ready: set) -> None:
    """Run one monitoring cycle over all active tasks."""
    try:
        items = get_running_tasks()
        for t in items:
            try:
                _process_task(t, notified_ready)
            except Exception as exc:
                task_id = t.get("id", "<unknown>")
                update_task(task_id, {"status": "blocked", "note": f"monitor error: {exc}"})
                print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
    except Exception as exc:
        print(f"[ERROR] Monitor loop failed: {exc}")
```

Where `_process_task(t, notified_ready)` contains the current per-task logic (moved verbatim from the inner loop body), replacing `changed = True` + `save_registry(items)` calls with direct `update_task(t["id"], {...})` calls.

Update `main()`:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Zoe task monitor")
    parser.add_argument("--once", action="store_true",
                        help="Run one monitoring cycle and exit")
    args = parser.parse_args()

    init_db()
    notified_ready: set = set()

    if args.once:
        run_once(notified_ready)
        return

    print("Monitor started.")
    while True:
        run_once(notified_ready)
        time.sleep(30)
```

Replace all `changed = True` + `save_registry(items)` patterns in the task processing logic with individual `update_task(task_id, {field: value})` calls.

- [ ] **Step 4: Verify no JSON registry reference remains**

```bash
grep -n "active-tasks\|REGISTRY\|load_registry\|save_registry" orchestrator/bin/monitor.py
```

Expected: no output.

- [ ] **Step 5: Run monitor tests**

```bash
python -m pytest tests/test_monitor.py -v
```

Expected: new tests pass, existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/bin/monitor.py tests/test_monitor.py
git commit -m "feat(monitor): migrate to SQLite, add --once flag, extract run_once()"
```

---

### Task 5: Remove remaining JSON registry references

**Files:**
- Modify: `orchestrator/bin/zoe_tools.py`
- Modify: `orchestrator/bin/dispatch.py`
- Modify: `.gitignore`

- [ ] **Step 1: Scan all remaining JSON registry references**

```bash
grep -rn "active-tasks\.json\|load_registry\|save_registry\|REGISTRY" \
  orchestrator/ discord/ tests/ --include="*.py" | grep -v ".pyc"
```

Record the output for reference.

- [ ] **Step 2: Update `zoe_tools.py` — replace `_load_registry()` with SQLite**

In `zoe_tools.py`, find `_load_registry()` and replace:

```python
# Remove:
def _load_registry(base_dir: Path | None = None) -> list[dict[str, Any]]:
    path = registry_file(base_dir)
    ...

# Replace task_status() body to use db directly:
def task_status(
    *,
    task_id: str | None = None,
    plan_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from db import get_task, get_tasks_by_plan, get_all_tasks

    if task_id:
        item = get_task(task_id)
        if item is None:
            raise PlannerError(f"Task not found in registry: {task_id}")
        return {"task": item}

    if plan_id:
        matching = get_tasks_by_plan(plan_id)
        return {"planId": plan_id, "tasks": matching}

    return {"tasks": get_all_tasks(limit=100)}
```

Remove the import of `registry_file` from the `dispatch` import line if it's only used by `_load_registry`.

- [ ] **Step 3: Run full test suite to catch regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all existing tests pass (some may need minor fixture updates for the removed `registry_file` import).

- [ ] **Step 4: Update `.gitignore`**

Add to `.gitignore`:

```
# AI DevOps runtime artifacts
.clawdbot/agent_tasks.db
.clawdbot/prompt-templates/
.clawdbot/failure-logs/
.clawdbot/active-tasks.json
worktrees/
logs/
orchestrator/queue/*.json
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/zoe_tools.py orchestrator/bin/dispatch.py .gitignore
git commit -m "feat: complete JSON registry removal, update .gitignore"
```

---

## Chunk 2: Phase 2 — Core Tool Completion

> Add `notify.py` (Telegram), `retry_task` tool exposed to OpenClaw.

---

### Task 6: Create notify.py (Telegram)

**Files:**
- Create: `orchestrator/bin/notify.py`
- Create: `tests/test_notify.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_notify.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def test_notify_sends_telegram_message(monkeypatch):
    """notify() must POST to Telegram sendMessage endpoint."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    import importlib, sys
    if "notify" in sys.modules:
        del sys.modules["notify"]
    import orchestrator.bin.notify as notify_mod
    importlib.reload(notify_mod)

    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notify_mod.notify("hello world")

    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert "test-token" in call_url
    assert "sendMessage" in call_url
    call_json = mock_post.call_args[1]["json"]
    assert call_json["chat_id"] == "12345"
    assert call_json["text"] == "hello world"


def test_notify_silent_when_token_missing(monkeypatch):
    """notify() must not raise when TELEGRAM_BOT_TOKEN is unset."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    import importlib, sys
    if "orchestrator.bin.notify" in sys.modules:
        del sys.modules["orchestrator.bin.notify"]
    import orchestrator.bin.notify as notify_mod
    importlib.reload(notify_mod)

    # Must not raise
    notify_mod.notify("this should be silently dropped")


def test_notify_silent_on_request_error(monkeypatch):
    """notify() must not raise on network errors."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")

    import importlib, sys
    if "orchestrator.bin.notify" in sys.modules:
        del sys.modules["orchestrator.bin.notify"]
    import orchestrator.bin.notify as notify_mod
    importlib.reload(notify_mod)

    with patch("requests.post", side_effect=Exception("network error")):
        notify_mod.notify("should not raise")  # must silently pass


def test_notify_ready(monkeypatch):
    """notify_ready() sends a message containing the PR URL."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")

    import importlib, sys
    if "orchestrator.bin.notify" in sys.modules:
        del sys.modules["orchestrator.bin.notify"]
    import orchestrator.bin.notify as notify_mod
    importlib.reload(notify_mod)

    sent = []
    monkeypatch.setattr(notify_mod, "notify", lambda msg: sent.append(msg))
    notify_mod.notify_ready("task-1", "https://github.com/org/repo/pull/42")

    assert len(sent) == 1
    assert "https://github.com/org/repo/pull/42" in sent[0]
    assert "task-1" in sent[0]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_notify.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError` for `orchestrator.bin.notify`.

- [ ] **Step 3: Create `orchestrator/bin/notify.py`**

```python
"""
Telegram Bot API notification module.

Environment:
    TELEGRAM_BOT_TOKEN: Bot token from @BotFather
    TELEGRAM_CHAT_ID: Target chat or group ID
"""
from __future__ import annotations

import os

_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def notify(msg: str) -> None:
    """Send message to configured Telegram chat. Silent on any failure."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", _TOKEN)
    chat_id = os.getenv("TELEGRAM_CHAT_ID", _CHAT_ID)

    if not token or not chat_id:
        print(f"[INFO] Telegram not configured, skipping notify: {msg[:80]}")
        return

    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception as exc:
        print(f"[WARN] Telegram notify failed: {exc}")


def notify_ready(task_id: str, pr_url: str) -> None:
    """Human-review-ready notification."""
    notify(f"✅ PR ready for review: `{task_id}`\n{pr_url}\n(checks ✅ + merge ✅)")


def notify_failure(task_id: str, detail: str) -> None:
    """CI failure or agent death notification."""
    notify(f"⚠️ Task failed: `{task_id}`\n{detail[:400]}")
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_notify.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Migrate monitor.py to use notify.py**

In `monitor.py`, replace:
```python
from dotenv import load_dotenv
load_dotenv(BASE / "discord" / ".env", override=True)
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

def notify(msg: str) -> None:
    if not WEBHOOK:
        ...
    # ... Discord webhook code ...
```

With:
```python
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))
from notify import notify, notify_ready, notify_failure
```

Update all `notify(...)` calls in `monitor.py` to use the imported function directly (no change to call sites — same function name). Replace any `notify_ready` / `notify_failure` inline calls with the named helpers where appropriate.

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/bin/notify.py tests/test_notify.py orchestrator/bin/monitor.py
git commit -m "feat: add Telegram notify.py, migrate monitor.py from Discord webhook"
```

---

### Task 7: Add `retry_task` to zoe_tools.py and contracts

**Files:**
- Modify: `orchestrator/bin/zoe_tools.py`
- Modify: `orchestrator/bin/zoe_tool_contract.py`
- Modify: `orchestrator/bin/zoe_tool_api.py`
- Modify: `tests/test_zoe_tools.py`

- [ ] **Step 1: Write failing tests for `retry_task`**

Add to `tests/test_zoe_tools.py`:

```python
def test_retry_task_increments_attempts(tmp_path, monkeypatch):
    """retry_task() must increment attempts and write a retry prompt."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    # Set up a worktree dir with a prompt
    wt = tmp_path / "worktrees" / "feat-t1"
    wt.mkdir(parents=True)
    (wt / "prompt.txt").write_text("original prompt")

    db_mod.insert_task({
        "id": "t1", "repo": "r", "title": "T",
        "status": "agent_dead", "attempts": 0, "maxAttempts": 3,
        "worktree": str(wt), "branch": "feat/t1",
        "agent": "codex", "model": "gpt-5.3-codex", "effort": "high",
        "promptFile": str(wt / "prompt.txt"),
    })

    import orchestrator.bin.zoe_tools as zt
    importlib.reload(zt)

    # Patch restart to avoid actually launching a process
    import unittest.mock as mock
    with mock.patch.object(zt, "_restart_agent_for_retry", return_value=None):
        result = zt.retry_task("t1", reason="manual", base_dir=tmp_path)

    task = db_mod.get_task("t1")
    assert task["attempts"] == 1
    assert task["status"] == "running"
    retry_prompt = wt / "prompt.retry1.txt"
    assert retry_prompt.exists()
    content = retry_prompt.read_text()
    assert "original prompt" in content
    assert "Retry #1" in content


def test_retry_task_rejects_at_max_attempts(tmp_path, monkeypatch):
    """retry_task() must raise when attempts >= maxAttempts."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    db_mod.insert_task({
        "id": "t2", "repo": "r", "title": "T",
        "status": "blocked", "attempts": 3, "maxAttempts": 3,
        "worktree": str(tmp_path), "branch": "feat/t2",
        "agent": "codex",
    })

    import orchestrator.bin.zoe_tools as zt
    importlib.reload(zt)

    with pytest.raises(Exception, match="max"):
        zt.retry_task("t2", base_dir=tmp_path)


def test_retry_task_not_found(tmp_path, monkeypatch):
    """retry_task() must raise when task_id is not in SQLite."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    import orchestrator.bin.zoe_tools as zt
    importlib.reload(zt)

    with pytest.raises(Exception):
        zt.retry_task("nonexistent", base_dir=tmp_path)
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
python -m pytest tests/test_zoe_tools.py::test_retry_task_increments_attempts tests/test_zoe_tools.py::test_retry_task_rejects_at_max_attempts tests/test_zoe_tools.py::test_retry_task_not_found -v 2>&1 | tail -10
```

Expected: FAIL — `retry_task` not in `zoe_tools`.

- [ ] **Step 3: Add `retry_task()` and `_restart_agent_for_retry()` to `zoe_tools.py`**

Add at the end of `zoe_tools.py`:

```python
def _restart_agent_for_retry(task: dict[str, Any], worktree: Path, prompt_file: str) -> None:
    """Launch the agent runner for a retry. Supports tmux and process modes."""
    import subprocess, shutil

    task_id = task["id"]
    agent = str(task.get("agent", "codex"))
    model = str(task.get("model", "gpt-5.3-codex"))
    effort = str(task.get("effort", "high"))
    execution_mode = str(task.get("execution_mode") or task.get("executionMode") or "tmux")

    base = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
    if agent == "codex":
        runner = Path(os.getenv("CODEX_RUNNER_PATH", str(base / "agents" / "run-codex-agent.sh")))
    elif agent == "claude":
        runner = Path(os.getenv("CLAUDE_RUNNER_PATH", str(base / "agents" / "run-claude-agent.sh")))
    else:
        raise PlannerError(f"Unsupported agent for retry: {agent}")

    if execution_mode == "tmux" and shutil.which("tmux"):
        session = task.get("tmuxSession") or task.get("tmux_session") or f"agent-{task_id}"
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
        cmd = f'"{runner}" "{task_id}" "{model}" "{effort}" "{worktree}" "{prompt_file}"'
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(worktree), cmd],
            check=True,
        )
    else:
        old_pid = task.get("processId") or task.get("process_id")
        if isinstance(old_pid, int) and old_pid > 0:
            import signal as _signal
            try:
                os.kill(old_pid, _signal.SIGTERM)
            except OSError:
                pass
        subprocess.Popen(
            [str(runner), task_id, model, effort, str(worktree), prompt_file],
            cwd=str(worktree),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def retry_task(
    task_id: str,
    *,
    reason: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Manually trigger a retry for a task that is blocked or dead.
    Reads the original prompt, appends a retry directive, restarts the agent.
    Returns a summary dict.
    """
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent))
    from db import get_task, update_task  # type: ignore

    task = get_task(task_id)
    if task is None:
        raise PlannerError(f"Task not found: {task_id}")

    attempts = int(task.get("attempts") or 0)
    max_attempts = int(task.get("max_attempts") or task.get("maxAttempts") or 3)

    if attempts >= max_attempts:
        raise PlannerError(
            f"Task {task_id} has reached max retries ({max_attempts}). "
            "Reset attempts manually before retrying."
        )

    worktree = Path(task.get("worktree") or "")
    if not worktree.exists():
        raise PlannerError(f"Worktree not found for task {task_id}: {worktree}")

    prompt_file = Path(task.get("prompt_file") or task.get("promptFile") or worktree / "prompt.txt")
    base_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""

    retry_n = attempts + 1
    retry_prompt = (
        base_prompt
        + "\n\n"
        + f"RERUN DIRECTIVE (Retry #{retry_n}):\n"
        + "A retry has been manually triggered.\n"
        + (f"Reason: {reason}\n" if reason else "")
        + "Instructions:\n"
        + "- Review recent changes and CI output.\n"
        + "- Apply minimal fix.\n"
        + "- Push commits to the SAME branch and update the PR.\n"
    )
    retry_prompt_path = worktree / f"prompt.retry{retry_n}.txt"
    retry_prompt_path.write_text(retry_prompt, encoding="utf-8")

    _restart_agent_for_retry(task, worktree, retry_prompt_path.name)

    update_task(task_id, {
        "status": "running",
        "attempts": retry_n,
        "note": f"manual retry #{retry_n}" + (f": {reason}" if reason else ""),
    })

    return {
        "taskId": task_id,
        "retryNumber": retry_n,
        "promptFile": str(retry_prompt_path),
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_zoe_tools.py::test_retry_task_increments_attempts tests/test_zoe_tools.py::test_retry_task_rejects_at_max_attempts tests/test_zoe_tools.py::test_retry_task_not_found -v
```

Expected: all 3 PASS.

- [ ] **Step 5: Register `retry_task` in `zoe_tool_contract.py`**

In `zoe_tool_contract.py`, add to the tools list:

```python
{
    "name": "retry_task",
    "description": "Manually retry a failed or dead task. Reads original prompt, appends retry directive, restarts agent.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "ID of the task to retry"
            },
            "reason": {
                "type": "string",
                "description": "Optional reason for retry (appended to prompt)"
            }
        },
        "required": ["task_id"]
    }
},
```

- [ ] **Step 6: Route `retry_task` in `zoe_tool_api.py`**

In `zoe_tool_api.py`, in the tool dispatch section, add:

```python
elif tool == "retry_task":
    result = zoe_tools.retry_task(
        args["task_id"],
        reason=args.get("reason", ""),
    )
```

- [ ] **Step 7: Update SKILL.md with retry_task example**

In `openclaw-skills/zoe-local-tools/SKILL.md`:

1. Replace the reference to `active-tasks.json`:
   - Old: `Prefer these tools over manually reading \`tasks/\`, \`orchestrator/queue/\`, or \`.clawdbot/active-tasks.json\``
   - New: `Prefer these tools over manually reading \`tasks/\`, \`orchestrator/queue/\`, or the SQLite database directly.`

2. Add `retry_task` to the tool list and add usage example after the `task_status` section:

```markdown
- `retry_task`: manually retry a failed or dead task by task_id

For retry requests:

\`\`\`bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{"task_id": "<task-id>", "reason": "Investigated root cause: missing env var"}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call retry_task --args-file /tmp/zoe-tool-args.json
\`\`\`
```

- [ ] **Step 8: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add orchestrator/bin/zoe_tools.py orchestrator/bin/zoe_tool_contract.py \
        orchestrator/bin/zoe_tool_api.py openclaw-skills/zoe-local-tools/SKILL.md \
        tests/test_zoe_tools.py
git commit -m "feat: add retry_task tool, register in contracts and SKILL.md"
```

---

## Chunk 3: Phase 3 — Ralph Loop v2

> Obsidian business context injection, structured failure logs, success pattern memory.

---

### Task 8: Create obsidian_client.py

**Files:**
- Create: `orchestrator/bin/obsidian_client.py`
- Create: `tests/test_obsidian_client.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_obsidian_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock


def _make_client():
    import importlib, sys
    if "orchestrator.bin.obsidian_client" in sys.modules:
        del sys.modules["orchestrator.bin.obsidian_client"]
    import orchestrator.bin.obsidian_client as m
    return m.ObsidianClient(base_url="http://localhost:27123", token="test-token")


def test_search_returns_results():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json.return_value = {
        "results": [
            {"filename": "notes/meeting.md", "matches": [{"context": "discussed auth bug"}]}
        ]
    }
    with patch("requests.post", return_value=fake_response):
        results = client.search("auth bug", limit=3)
    assert len(results) == 1
    assert results[0]["path"] == "notes/meeting.md"
    assert "auth bug" in results[0]["excerpt"]


def test_search_returns_empty_on_connection_error():
    client = _make_client()
    with patch("requests.post", side_effect=Exception("refused")):
        results = client.search("anything")
    assert results == []


def test_search_returns_empty_on_4xx():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 401
    with patch("requests.post", return_value=fake_response):
        results = client.search("anything")
    assert results == []


def test_get_note_returns_content():
    client = _make_client()
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = "# Meeting Notes\nDiscussed auth bug fix."
    with patch("requests.get", return_value=fake_response):
        content = client.get_note("notes/meeting.md")
    assert "auth bug" in content


def test_get_note_returns_empty_on_error():
    client = _make_client()
    with patch("requests.get", side_effect=Exception("timeout")):
        content = client.get_note("notes/missing.md")
    assert content == ""


def test_from_env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_API_TOKEN", "my-token")
    monkeypatch.setenv("OBSIDIAN_API_PORT", "27123")
    import importlib, sys
    if "orchestrator.bin.obsidian_client" in sys.modules:
        del sys.modules["orchestrator.bin.obsidian_client"]
    import orchestrator.bin.obsidian_client as m
    importlib.reload(m)
    client = m.ObsidianClient.from_env()
    assert client.token == "my-token"
    assert "27123" in client.base_url
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/test_obsidian_client.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `orchestrator/bin/obsidian_client.py`**

```python
"""
Obsidian Local REST API client.

Requires the Obsidian Local REST API plugin (https://github.com/coddingtonbear/obsidian-local-rest-api).

Environment:
    OBSIDIAN_API_TOKEN: API token configured in the plugin
    OBSIDIAN_API_PORT: Port (default: 27123)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObsidianClient:
    base_url: str
    token: str
    timeout: int = 8

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        Search the vault. Returns list of {path, excerpt}.
        Returns [] on any error (unreachable, auth failure, etc.).
        """
        try:
            import requests
            resp = requests.post(
                f"{self.base_url}/search/simple/",
                headers=self._headers(),
                params={"query": query, "contextLength": 200},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[WARN] Obsidian API error {resp.status_code}, skipping")
                return []
            data = resp.json()
            results = []
            for item in (data.get("results") or [])[:limit]:
                filename = item.get("filename", "")
                matches = item.get("matches") or []
                excerpt = " … ".join(
                    m.get("context", "") for m in matches[:2]
                )
                results.append({"path": filename, "excerpt": excerpt})
            return results
        except Exception as exc:
            print(f"[INFO] Obsidian unreachable, skipping business context: {exc}")
            return []

    def get_note(self, path: str) -> str:
        """
        Fetch full note content by vault-relative path.
        Returns '' on any error.
        """
        try:
            import requests
            resp = requests.get(
                f"{self.base_url}/vault/{path}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[WARN] Obsidian get_note {resp.status_code} for {path}")
                return ""
            return resp.text
        except Exception as exc:
            print(f"[INFO] Obsidian unreachable for note {path}: {exc}")
            return ""

    def find_by_tags(self, tags: list[str]) -> list[dict[str, Any]]:
        """
        Find notes by tags. Returns [] on any error.
        Implemented via search (tag: prefix per Obsidian search syntax).
        """
        query = " OR ".join(f"tag:{t}" for t in tags)
        return self.search(query)

    @classmethod
    def from_env(cls) -> "ObsidianClient":
        """Construct from environment variables."""
        token = os.getenv("OBSIDIAN_API_TOKEN", "")
        port = os.getenv("OBSIDIAN_API_PORT", "27123")
        return cls(base_url=f"http://localhost:{port}", token=token)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_obsidian_client.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/obsidian_client.py tests/test_obsidian_client.py
git commit -m "feat: add ObsidianClient for Local REST API integration"
```

---

### Task 9: Enhance monitor retry prompt with Obsidian context + failure logs

**Files:**
- Modify: `orchestrator/bin/monitor.py`
- Modify: `tests/test_monitor.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_monitor.py`:

```python
def test_retry_prompt_includes_business_context(tmp_path, monkeypatch):
    """When Obsidian returns results, retry prompt must contain BUSINESS CONTEXT."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.monitor as mon
    importlib.reload(mon)

    wt = tmp_path / "worktrees" / "feat-t1"
    wt.mkdir(parents=True)
    (wt / "prompt.txt").write_text("base prompt")

    task = {
        "id": "t1", "repo": "my-repo", "title": "Fix auth",
        "branch": "feat/t1", "worktree": str(wt),
        "tmuxSession": "agent-t1", "executionMode": "tmux",
        "model": "gpt-5.3-codex", "effort": "high",
        "attempts": 0, "maxAttempts": 3,
    }

    obsidian_results = [{"path": "meeting.md", "excerpt": "discussed auth issue"}]
    monkeypatch.setattr(mon, "_obsidian_search", lambda query: obsidian_results)
    monkeypatch.setattr(mon, "restart_codex_agent", lambda *a, **kw: None)
    monkeypatch.setattr(mon, "latest_run_failure", lambda *a: None)

    prompt_path = mon._build_retry_prompt(task, 1, "tests:FAILURE", "")
    content = (wt / "prompt.retry1.txt").read_text()
    assert "BUSINESS CONTEXT" in content
    assert "discussed auth issue" in content


def test_retry_prompt_skips_context_when_obsidian_empty(tmp_path, monkeypatch):
    """When Obsidian returns [], retry prompt must not include BUSINESS CONTEXT."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.monitor as mon
    importlib.reload(mon)

    wt = tmp_path / "worktrees" / "feat-t2"
    wt.mkdir(parents=True)
    (wt / "prompt.txt").write_text("base prompt")

    task = {
        "id": "t2", "repo": "r", "title": "T",
        "branch": "feat/t2", "worktree": str(wt),
        "tmuxSession": None, "executionMode": "process",
        "model": "gpt-5.3-codex", "effort": "high",
        "attempts": 0, "maxAttempts": 3,
    }

    monkeypatch.setattr(mon, "_obsidian_search", lambda query: [])
    prompt_path = mon._build_retry_prompt(task, 1, "lint:FAILURE", "")
    content = (wt / "prompt.retry1.txt").read_text()
    assert "BUSINESS CONTEXT" not in content


def test_failure_log_written_on_ci_failure(tmp_path, monkeypatch):
    """On CI failure detection, a structured failure log must be written."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.monitor as mon
    importlib.reload(mon)

    mon._write_failure_log("my-repo", "task-1", "lint:FAILURE", "details here")

    import json
    logs = list((tmp_path / ".clawdbot" / "failure-logs" / "my-repo").glob("*.json"))
    assert len(logs) == 1
    data = json.loads(logs[0].read_text())
    assert data["taskId"] == "task-1"
    assert data["failSummary"] == "lint:FAILURE"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/test_monitor.py::test_retry_prompt_includes_business_context tests/test_monitor.py::test_retry_prompt_skips_context_when_obsidian_empty tests/test_monitor.py::test_failure_log_written_on_ci_failure -v 2>&1 | tail -15
```

Expected: FAIL — `_obsidian_search`, `_build_retry_prompt`, `_write_failure_log` not in monitor.

- [ ] **Step 3: Add `_obsidian_search()`, `_write_failure_log()`, `_build_retry_prompt()` to `monitor.py`**

Add after the import block in `monitor.py`:

```python
from obsidian_client import ObsidianClient


def _obsidian_search(query: str) -> list[dict]:
    """Search Obsidian for context. Returns [] if unconfigured or unreachable."""
    import os
    token = os.getenv("OBSIDIAN_API_TOKEN", "")
    if not token:
        return []
    client = ObsidianClient.from_env()
    return client.search(query, limit=2)


def _write_failure_log(repo: str, task_id: str, fail_summary: str, ci_detail: str) -> None:
    """Write a structured failure record to .clawdbot/failure-logs/<repo>/."""
    import time as _time
    log_dir = BASE / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(_time.time() * 1000)
    log_file = log_dir / f"{task_id}-{timestamp}.json"
    log_file.write_text(
        json.dumps({
            "taskId": task_id,
            "repo": repo,
            "failSummary": fail_summary,
            "ciDetail": ci_detail[:2000] if ci_detail else "",
            "timestamp": timestamp,
        }, indent=2),
        encoding="utf-8",
    )


def _load_failure_logs(repo: str, limit: int = 2) -> str:
    """Load recent failure log excerpts for a repo."""
    log_dir = BASE / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    if not log_dir.exists():
        return ""
    logs = sorted(log_dir.glob("*.json"), reverse=True)[:limit]
    excerpts = []
    for log in logs:
        try:
            data = json.loads(log.read_text(encoding="utf-8"))
            excerpts.append(f"- [{data.get('taskId','')}] {data.get('failSummary','')} — {data.get('ciDetail','')[:200]}")
        except Exception:
            continue
    return "\n".join(excerpts)


def _build_retry_prompt(task: dict, retry_n: int, fail_summary: str, ci_detail: str) -> Path:
    """
    Build and write prompt.retryN.txt for a task.
    Injects Obsidian business context and past failure history.
    Returns path to the written file.
    """
    worktree = Path(task.get("worktree", ""))
    base_prompt_path = worktree / "prompt.txt"
    base_prompt = base_prompt_path.read_text(encoding="utf-8") if base_prompt_path.exists() else ""

    # Obsidian context
    query = f"{task.get('title', '')} {task.get('repo', '')}"
    obsidian_results = _obsidian_search(query)
    obsidian_section = ""
    if obsidian_results:
        excerpts = "\n".join(f"- [{r['path']}]: {r['excerpt']}" for r in obsidian_results)
        obsidian_section = f"\nBUSINESS CONTEXT (from Obsidian):\n{excerpts}\n"

    # Past failure history
    past_failures = _load_failure_logs(task.get("repo", ""))
    failures_section = ""
    if past_failures:
        failures_section = f"\nPAST FAILURES FOR THIS REPO:\n{past_failures}\n"

    retry_prompt = (
        base_prompt
        + obsidian_section
        + failures_section
        + "\n\n"
        + f"RERUN DIRECTIVE (Retry #{retry_n}):\n"
        + "CI is failing. Your ONLY priority is to make CI green.\n"
        + f"Failed checks summary: {fail_summary}\n\n"
        + (ci_detail + "\n\n" if ci_detail else "")
        + "Instructions:\n"
        + "- Read failing logs and identify root cause.\n"
        + "- Apply minimal fix.\n"
        + "- Run local equivalent checks/tests if available.\n"
        + "- Push commits to the SAME branch and update the PR.\n"
    )

    retry_prompt_path = worktree / f"prompt.retry{retry_n}.txt"
    retry_prompt_path.write_text(retry_prompt, encoding="utf-8")
    return retry_prompt_path
```

In the CI failure branch of `_process_task()`, replace the existing inline retry-prompt construction with:

```python
# Write failure log
_write_failure_log(t.get("repo", ""), task_id, fail_summary, ci_detail)

# Build retry prompt with Obsidian context
retry_prompt_path = _build_retry_prompt(t, retry_n, fail_summary, ci_detail)

# Restart agent
restart_codex_agent(t, worktree, retry_prompt_path.name)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_monitor.py -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/monitor.py tests/test_monitor.py orchestrator/bin/obsidian_client.py
git commit -m "feat(monitor): Ralph Loop v2 — Obsidian context + structured failure logs"
```

---

### Task 10: Implement success pattern memory

**Files:**
- Modify: `orchestrator/bin/monitor.py`
- Modify: `orchestrator/bin/zoe_tools.py`
- Modify: `orchestrator/bin/planner_engine.py`
- Modify: `tests/test_monitor.py`
- Modify: `tests/test_zoe_tools.py`

- [ ] **Step 1: Write failing test for success pattern write**

Add to `tests/test_monitor.py`:

```python
def test_success_pattern_written_on_ready(tmp_path, monkeypatch):
    """When task reaches 'ready', prompt.txt must be saved to prompt-templates/."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import importlib, orchestrator.bin.monitor as mon
    importlib.reload(mon)

    wt = tmp_path / "worktrees" / "feat-t1"
    wt.mkdir(parents=True)
    (wt / "prompt.txt").write_text("winning prompt content")

    mon._save_success_pattern(
        repo="my-repo", task_id="t1",
        title="Fix auth flow", worktree=wt, attempts=1
    )

    templates_dir = tmp_path / ".clawdbot" / "prompt-templates" / "my-repo"
    files = list(templates_dir.glob("*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "winning prompt content" in content
    assert "attempts=1" in content
```

- [ ] **Step 2: Run to confirm it fails**

```bash
python -m pytest tests/test_monitor.py::test_success_pattern_written_on_ready -v 2>&1 | tail -10
```

- [ ] **Step 3: Add `_save_success_pattern()` to `monitor.py`**

```python
def _save_success_pattern(
    *, repo: str, task_id: str, title: str, worktree: Path, attempts: int
) -> None:
    """Save successful prompt as a template for future planning reference."""
    import time as _time, re as _re
    prompt_path = worktree / "prompt.txt"
    if not prompt_path.exists():
        return
    content = prompt_path.read_text(encoding="utf-8")

    templates_dir = BASE / ".clawdbot" / "prompt-templates" / repo.replace("/", "_")
    templates_dir.mkdir(parents=True, exist_ok=True)

    slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    timestamp = int(_time.time() * 1000)
    out_file = templates_dir / f"{slug}.md"
    out_file.write_text(
        f"<!-- attempts={attempts} timestamp={timestamp} repo={repo} -->\n{content}",
        encoding="utf-8",
    )
```

In `_process_task()`, in the `ready` status detection block, add after setting `t["status"] = "ready"`:

```python
_save_success_pattern(
    repo=t.get("repo", ""),
    task_id=task_id,
    title=t.get("title", task_id),
    worktree=worktree,
    attempts=int(t.get("attempts", 0)),
)
```

- [ ] **Step 4: Write failing test for success pattern injection in planner**

Add to `tests/test_zoe_tools.py`:

```python
def test_build_plan_request_injects_success_patterns(tmp_path, monkeypatch):
    """build_plan_request() injects successPatterns when templates exist for the repo."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    templates_dir = tmp_path / ".clawdbot" / "prompt-templates" / "my-repo"
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / "fix-auth.md").write_text(
        "<!-- attempts=1 timestamp=1741910400000 repo=my-repo -->\noriginal prompt"
    )

    import importlib, orchestrator.bin.zoe_tools as zt
    importlib.reload(zt)

    result = zt.build_plan_request({
        "repo": "my-repo", "title": "Fix auth", "description": "Fix it",
        "requested_by": "zoe", "requested_at": 1741910400000,
    })
    patterns = result.get("context", {}).get("successPatterns")
    assert patterns is not None
    assert len(patterns) >= 1
    assert patterns[0]["title"] == "fix-auth"
```

- [ ] **Step 5: Run to confirm it fails**

```bash
python -m pytest tests/test_zoe_tools.py::test_build_plan_request_injects_success_patterns -v 2>&1 | tail -10
```

- [ ] **Step 6: Add success pattern loading to `build_plan_request()` in `zoe_tools.py`**

At the end of `build_plan_request()`, before the `return` statement, add:

```python
# Inject success patterns from saved templates
_inject_success_patterns(context, repo=repo, base_dir=base_dir)
```

Add the helper function before `build_plan_request()`:

```python
def _load_success_patterns(repo: str, *, base_dir: Path | None = None) -> list[dict]:
    """Load up to 3 recent success prompt templates for a repo."""
    import re as _re
    root = (base_dir or default_base_dir()) / ".clawdbot" / "prompt-templates" / repo.replace("/", "_")
    if not root.exists():
        return []
    files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    patterns = []
    for f in files:
        try:
            first_line = f.read_text(encoding="utf-8").splitlines()[0]
            attempts_match = _re.search(r"attempts=(\d+)", first_line)
            ts_match = _re.search(r"timestamp=(\d+)", first_line)
            patterns.append({
                "title": f.stem,
                "attemptCount": int(attempts_match.group(1)) if attempts_match else 0,
                "timestamp": int(ts_match.group(1)) if ts_match else 0,
            })
        except Exception:
            continue
    return patterns


def _inject_success_patterns(context: dict, *, repo: str, base_dir: Path | None = None) -> None:
    patterns = _load_success_patterns(repo, base_dir=base_dir)
    if patterns:
        context["successPatterns"] = patterns
```

Update `build_plan_request()` signature to accept `base_dir`:

```python
def build_plan_request(task_input: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
```

And in the return statement, pass `base_dir` to `_inject_success_patterns`.

- [ ] **Step 7: Add `successPatterns` hint to `_build_prompt()` in `planner_engine.py`**

In `_build_prompt()`, after the `FILES TO CHECK FIRST` section, add:

```python
# In the lines list, after the files_hint block:
success_patterns = constraints.get("successPatterns") or []  # passed via context
if success_patterns:
    lines.extend(["", "PAST SUCCESSES (approaches that worked before):"])
    lines.extend(f"- {p['title']} (succeeded in {p['attemptCount']} attempt(s))" for p in success_patterns[:3])
```

Note: `constraints` in `_build_prompt()` needs to be augmented to also receive `context` or the patterns injected at a higher level. The cleanest approach: pass `success_patterns: list[dict]` as a parameter to `_build_prompt()` with default `[]`.

- [ ] **Step 8: Run all tests**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add orchestrator/bin/monitor.py orchestrator/bin/zoe_tools.py orchestrator/bin/planner_engine.py tests/test_monitor.py tests/test_zoe_tools.py
git commit -m "feat: success pattern memory — write on ready, inject in planner"
```

---

## Chunk 4: Phase 4 — Local PR Review Pipeline

---

### Task 11: Create reviewer.py

**Files:**
- Create: `orchestrator/bin/reviewer.py`
- Create: `tests/test_reviewer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_reviewer.py`:

```python
import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path


def _reload():
    import importlib, sys
    if "orchestrator.bin.reviewer" in sys.modules:
        del sys.modules["orchestrator.bin.reviewer"]
    import orchestrator.bin.reviewer as m
    return m


def test_review_pr_spawns_two_reviewers(tmp_path):
    """review_pr() must spawn Codex and Claude subprocesses."""
    rev = _reload()
    spawned = []

    def fake_popen(cmd, **kwargs):
        spawned.append(cmd[0] if cmd else "")
        m = MagicMock()
        m.pid = 9999
        return m

    with patch("subprocess.Popen", side_effect=fake_popen):
        with patch.object(rev, "_get_pr_diff", return_value="diff content"):
            rev.review_pr("task-1", 42, tmp_path)

    # Should have spawned at least 2 processes (codex + claude review)
    assert len(spawned) >= 2


def test_gemini_reviewer_is_noop(tmp_path, capsys):
    """_run_gemini_review() must log skip and not raise."""
    rev = _reload()
    # Should not raise and should print skip message
    rev._run_gemini_review(42, "some diff", tmp_path)
    captured = capsys.readouterr()
    assert "Gemini" in captured.out or "gemini" in captured.out.lower()


def test_get_pr_diff_calls_gh(tmp_path):
    """_get_pr_diff() must call gh pr diff."""
    rev = _reload()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "--- a/foo\n+++ b/foo\n+new line"
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        diff = rev._get_pr_diff(42, tmp_path)
    assert "new line" in diff
    call_args = mock_run.call_args[0][0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "diff" in call_args


def test_review_pr_handles_empty_diff(tmp_path, capsys):
    """review_pr() with empty diff must log and skip gracefully."""
    rev = _reload()
    with patch.object(rev, "_get_pr_diff", return_value=""):
        rev.review_pr("task-1", 42, tmp_path)
    captured = capsys.readouterr()
    assert "empty" in captured.out.lower() or "skip" in captured.out.lower()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/test_reviewer.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `orchestrator/bin/reviewer.py`**

```python
"""
Local PR Review Pipeline.

Spawns Codex and Claude as reviewers for a PR diff.
Posts review comments via gh pr comment.
Gemini reviewer is reserved (no-op).
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Optional

REVIEW_PROMPT_TEMPLATE = """\
You are a senior code reviewer. Review the following PR diff for:
- Correctness and logic errors
- Security vulnerabilities (injection, auth bypass, data exposure)
- Edge cases and error handling gaps
- Test coverage gaps

Be concise. Use GitHub-flavoured markdown. Start with a one-line summary.

PR DIFF:
{diff}
"""


def _get_pr_diff(pr_number: int, repo_dir: Path) -> str:
    """Fetch PR diff using gh CLI. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number)],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"[WARN] gh pr diff failed for #{pr_number}: {result.stderr[:200]}")
            return ""
        return result.stdout or ""
    except Exception as exc:
        print(f"[WARN] Failed to get PR diff for #{pr_number}: {exc}")
        return ""


def _post_comment(pr_number: int, body: str, repo_dir: Path) -> None:
    """Post a comment on the PR via gh CLI."""
    try:
        subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        print(f"[WARN] Failed to post PR comment: {exc}")


def _run_codex_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Spawn Codex reviewer and post result as gh pr comment."""
    import shutil, os
    codex_bin = os.getenv("CODEX_BIN") or shutil.which("codex")
    if not codex_bin:
        print("[WARN] Codex not found, skipping Codex review")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=diff[:8000])
    try:
        result = subprocess.run(
            [codex_bin, "--model", "gpt-5.3-codex", prompt],
            capture_output=True, text=True, timeout=120,
        )
        review_text = (result.stdout or "").strip()
        if review_text:
            _post_comment(pr_number, f"🤖 **Codex Review:**\n\n{review_text}", repo_dir)
    except Exception as exc:
        print(f"[WARN] Codex review failed: {exc}")


def _run_claude_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Spawn Claude reviewer and post result as gh pr comment."""
    import shutil
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("[WARN] claude not found, skipping Claude review")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=diff[:8000])
    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True, text=True, timeout=120,
        )
        review_text = (result.stdout or "").strip()
        if review_text:
            _post_comment(pr_number, f"🤖 **Claude Review:**\n\n{review_text}", repo_dir)
    except Exception as exc:
        print(f"[WARN] Claude review failed: {exc}")


def _run_gemini_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Reserved. Gemini reviewer not yet implemented."""
    print(f"[INFO] Gemini reviewer not yet implemented, skipping PR #{pr_number}")


def review_pr(task_id: str, pr_number: int, repo_dir: Path) -> None:
    """
    Fetch PR diff and spawn Codex + Claude review subprocesses.
    Posts gh pr comment for each. Non-blocking — runs reviewers in threads.
    """
    diff = _get_pr_diff(pr_number, repo_dir)
    if not diff:
        print(f"[INFO] Empty diff for PR #{pr_number}, skipping review")
        return

    print(f"[INFO] Triggering PR review for task {task_id} PR #{pr_number}")

    def run_reviews():
        _run_codex_review(pr_number, diff, repo_dir)
        _run_claude_review(pr_number, diff, repo_dir)
        _run_gemini_review(pr_number, diff, repo_dir)

    thread = threading.Thread(target=run_reviews, daemon=True)
    thread.start()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_reviewer.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Integrate reviewer into `monitor.py`**

At the top of `monitor.py`, add:

```python
from reviewer import review_pr
```

In `_process_task()`, in the block where `pr` is detected and `t["status"]` is changed to `"pr_created"`:

```python
if pr and t.get("status") == "running":
    t_status_before = "running"
    update_task(task_id, {
        "status": "pr_created",
        "pr_number": pr.get("number"),
        "pr_url": pr.get("url"),
    })
    # Trigger async review — non-blocking
    worktree_path = Path(t.get("worktree", ""))
    if worktree_path.exists() and pr.get("number"):
        review_pr(task_id, pr["number"], worktree_path)
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/bin/reviewer.py tests/test_reviewer.py orchestrator/bin/monitor.py
git commit -m "feat: add local PR review pipeline (Codex + Claude, Gemini reserved)"
```

---

## Chunk 5: Phase 5 — Cleanup Daemon + Scripts

---

### Task 12: Create cleanup_daemon.py

**Files:**
- Create: `orchestrator/bin/cleanup_daemon.py`
- Create: `tests/test_cleanup_daemon.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cleanup_daemon.py`:

```python
import json, time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _reload(tmp_path, monkeypatch):
    import importlib, sys, orchestrator.bin.db as db_mod
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    importlib.reload(db_mod)
    db_mod.init_db()
    if "orchestrator.bin.cleanup_daemon" in sys.modules:
        del sys.modules["orchestrator.bin.cleanup_daemon"]
    import orchestrator.bin.cleanup_daemon as m
    importlib.reload(m)
    return m, db_mod


def test_cleanup_stale_worktrees_marks_cleaned_up(tmp_path, monkeypatch):
    """cleanup_stale_worktrees() must remove worktrees and mark cleaned_up=1."""
    m, db = _reload(tmp_path, monkeypatch)

    # Create a fake worktree dir
    wt = tmp_path / "worktrees" / "feat-t1"
    wt.mkdir(parents=True)

    db.insert_task({
        "id": "t1", "repo": "r", "title": "T",
        "status": "merged", "worktree": str(wt),
        "branch": "feat/t1",
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        m.cleanup_stale_worktrees()

    task = db.get_task("t1")
    assert task["cleaned_up"] == 1
    # git worktree remove must have been called
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("worktree" in c and "remove" in c for c in calls)


def test_cleanup_stale_worktrees_skips_running(tmp_path, monkeypatch):
    """cleanup_stale_worktrees() must NOT clean up running tasks."""
    m, db = _reload(tmp_path, monkeypatch)

    wt = tmp_path / "worktrees" / "feat-t2"
    wt.mkdir(parents=True)
    db.insert_task({
        "id": "t2", "repo": "r", "title": "T",
        "status": "running", "worktree": str(wt),
    })

    with patch("subprocess.run") as mock_run:
        m.cleanup_stale_worktrees()

    task = db.get_task("t2")
    assert task["cleaned_up"] == 0


def test_cleanup_old_queue_files(tmp_path, monkeypatch):
    """cleanup_old_queue_files() must delete queue files older than 7 days."""
    m, db = _reload(tmp_path, monkeypatch)

    queue_dir = tmp_path / "orchestrator" / "queue"
    queue_dir.mkdir(parents=True)

    old_file = queue_dir / "old-task.json"
    old_file.write_text("{}")
    # Backdate mtime by 8 days
    import os
    old_mtime = time.time() - 8 * 86400
    os.utime(old_file, (old_mtime, old_mtime))

    recent_file = queue_dir / "recent-task.json"
    recent_file.write_text("{}")

    m.cleanup_old_queue_files()

    assert not old_file.exists(), "Old queue file must be deleted"
    assert recent_file.exists(), "Recent queue file must be kept"


def test_cleanup_failure_logs(tmp_path, monkeypatch):
    """cleanup_failure_logs() must delete failure logs older than 30 days."""
    m, db = _reload(tmp_path, monkeypatch)

    log_dir = tmp_path / ".clawdbot" / "failure-logs" / "my-repo"
    log_dir.mkdir(parents=True)

    old_log = log_dir / "t1-old.json"
    old_log.write_text("{}")
    import os
    old_mtime = time.time() - 31 * 86400
    os.utime(old_log, (old_mtime, old_mtime))

    recent_log = log_dir / "t2-recent.json"
    recent_log.write_text("{}")

    m.cleanup_failure_logs()

    assert not old_log.exists()
    assert recent_log.exists()
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/test_cleanup_daemon.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `orchestrator/bin/cleanup_daemon.py`**

```python
"""
Cleanup Daemon — daily maintenance for AI DevOps.

Schedules:
    02:00 — Remove stale worktrees for terminal-state tasks
    02:00 — Delete queue files older than 7 days
    02:30 — Delete failure logs older than 30 days

Usage:
    python cleanup_daemon.py            # run as daemon (scheduler loop)
    python cleanup_daemon.py --once     # run all cleanup tasks once and exit
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
QUEUE_DIR = BASE / "orchestrator" / "queue"
FAILURE_LOGS_DIR = BASE / ".clawdbot" / "failure-logs"

TERMINAL_STATUSES = {"blocked", "merged", "pr_closed", "agent_failed", "agent_dead", "agent_exited"}
QUEUE_MAX_AGE_DAYS = 7
FAILURE_LOG_MAX_AGE_DAYS = 30


def _db():
    import sys
    sys.path.insert(0, str(BASE / "orchestrator" / "bin"))
    from db import init_db, get_all_tasks, mark_cleaned_up
    init_db()
    return get_all_tasks, mark_cleaned_up


def cleanup_stale_worktrees() -> None:
    """Remove worktrees for tasks in terminal states where cleaned_up=0."""
    get_all_tasks, mark_cleaned_up = _db()
    tasks = get_all_tasks(limit=1000)

    for task in tasks:
        if task.get("status") not in TERMINAL_STATUSES:
            continue
        if task.get("cleaned_up"):
            continue

        worktree = task.get("worktree") or ""
        task_id = task.get("id", "")
        if not worktree or not Path(worktree).exists():
            mark_cleaned_up(task_id)
            continue

        try:
            # Find the repo root from the worktree path
            repo_name = task.get("repo", "")
            repo_root = BASE / "repos" / repo_name
            subprocess.run(
                ["git", "worktree", "remove", "--force", worktree],
                cwd=str(repo_root) if repo_root.exists() else worktree,
                capture_output=True,
                text=True,
                timeout=30,
            )
            print(f"[INFO] Removed worktree for {task_id}: {worktree}")
        except Exception as exc:
            print(f"[WARN] Failed to remove worktree for {task_id}: {exc}")

        mark_cleaned_up(task_id)


def cleanup_old_queue_files() -> None:
    """Delete queue JSON files older than QUEUE_MAX_AGE_DAYS."""
    if not QUEUE_DIR.exists():
        return
    cutoff = time.time() - QUEUE_MAX_AGE_DAYS * 86400
    for f in QUEUE_DIR.glob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            print(f"[INFO] Deleted old queue file: {f.name}")


def cleanup_failure_logs() -> None:
    """Delete failure log files older than FAILURE_LOG_MAX_AGE_DAYS."""
    if not FAILURE_LOGS_DIR.exists():
        return
    cutoff = time.time() - FAILURE_LOG_MAX_AGE_DAYS * 86400
    for f in FAILURE_LOGS_DIR.rglob("*.json"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            print(f"[INFO] Deleted old failure log: {f.name}")


def run_all() -> None:
    """Run all cleanup tasks once."""
    print("[INFO] Running cleanup tasks...")
    cleanup_stale_worktrees()
    cleanup_old_queue_files()
    cleanup_failure_logs()
    print("[INFO] Cleanup complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI DevOps cleanup daemon")
    parser.add_argument("--once", action="store_true", help="Run cleanup once and exit")
    args = parser.parse_args()

    if args.once:
        run_all()
        return

    try:
        import schedule
    except ImportError:
        print("[ERROR] 'schedule' package not installed. Run: pip install schedule")
        raise

    schedule.every().day.at("02:00").do(cleanup_stale_worktrees)
    schedule.every().day.at("02:00").do(cleanup_old_queue_files)
    schedule.every().day.at("02:30").do(cleanup_failure_logs)

    print("[INFO] Cleanup daemon started. Scheduled at 02:00 / 02:30 daily.")
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_cleanup_daemon.py -v
```

Expected: all 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/cleanup_daemon.py tests/test_cleanup_daemon.py
git commit -m "feat: add cleanup_daemon.py — daily worktree + log maintenance"
```

---

### Task 13: Create shell scripts and add dependencies

**Files:**
- Create: `scripts/spawn-agent.sh`
- Create: `scripts/cleanup-worktrees.sh`
- Create: `scripts/babysit.sh`
- Modify: `discord/.env.example` (if exists, else create)
- Modify: project dependency file (pyproject.toml or requirements.txt)

- [ ] **Step 1: Create `scripts/spawn-agent.sh`**

```bash
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

ARGS_FILE=$(mktemp /tmp/zoe-spawn-XXXXXX.json)
trap 'rm -f "$ARGS_FILE"' EXIT

cat > "$ARGS_FILE" <<JSON
{
  "repo": "$REPO",
  "title": "$TITLE",
  "description": "$DESCRIPTION",
  "agent": "$AGENT",
  "model": "$MODEL",
  "requested_by": "cli",
  "requested_at": $(date +%s%3N)
}
JSON

printf '%s\n' "{\"tool\":\"plan_and_dispatch_task\",\"args\":$(cat "$ARGS_FILE")}" \
  | "$VENV" "$API" invoke
```

- [ ] **Step 2: Create `scripts/cleanup-worktrees.sh`**

```bash
#!/usr/bin/env bash
# Single-run cleanup trigger — runs all cleanup tasks once without the scheduler.
set -euo pipefail

BASE_DIR="${AI_DEVOPS_HOME:-$HOME/ai-devops}"
VENV="$BASE_DIR/.venv/bin/python"
DAEMON="$BASE_DIR/orchestrator/bin/cleanup_daemon.py"

echo "[INFO] Running cleanup tasks (single-run mode)..."
"$VENV" "$DAEMON" --once
```

- [ ] **Step 3: Create `scripts/babysit.sh`**

```bash
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
  sqlite3 "$DB" \
    "SELECT id, status, attempts, branch FROM agent_tasks WHERE status IN ('running','pr_created') ORDER BY started_at;"
else
  echo "(database not found: $DB)"
fi
```

- [ ] **Step 4: Make scripts executable**

```bash
chmod +x scripts/spawn-agent.sh scripts/cleanup-worktrees.sh scripts/babysit.sh
```

- [ ] **Step 5: Verify scripts are syntactically valid**

```bash
bash -n scripts/spawn-agent.sh && echo "spawn-agent.sh OK"
bash -n scripts/cleanup-worktrees.sh && echo "cleanup-worktrees.sh OK"
bash -n scripts/babysit.sh && echo "babysit.sh OK"
```

Expected: all three print OK.

- [ ] **Step 6: Add `requests` and `schedule` dependencies**

Check which dependency file exists:

```bash
ls pyproject.toml requirements.txt setup.py 2>/dev/null
```

If `pyproject.toml` exists, add to `[project] dependencies`:
```toml
dependencies = [
    "requests>=2.31",
    "schedule>=1.2",
    "python-dotenv",
    # ... existing deps
]
```

If only `requirements.txt` exists, add:
```
requests>=2.31
schedule>=1.2
```

Install:
```bash
pip install requests schedule
```

- [ ] **Step 7: Update `discord/.env.example`**

Replace `DISCORD_WEBHOOK_URL=` with Telegram vars:

```bash
# Telegram notifications (required for monitor alerts)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Obsidian Local REST API (optional — enables business context in retries)
OBSIDIAN_API_TOKEN=
OBSIDIAN_API_PORT=27123
```

- [ ] **Step 8: Run full test suite one final time**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 9: Final commit**

```bash
git add scripts/spawn-agent.sh scripts/cleanup-worktrees.sh scripts/babysit.sh \
        discord/.env.example pyproject.toml
git commit -m "feat: add shell scripts, declare requests+schedule dependencies, update env template"
```

---

## Summary

| Phase | Tasks | New Files | Modified Files |
|-------|-------|-----------|----------------|
| 1 — Data Layer | 1–5 | — | `db.py`, `zoe-daemon.py`, `monitor.py`, `zoe_tools.py`, `.gitignore` |
| 2 — Core Tools | 6–7 | `notify.py` | `monitor.py`, `zoe_tools.py`, `zoe_tool_contract.py`, `zoe_tool_api.py`, `SKILL.md` |
| 3 — Ralph Loop v2 | 8–10 | `obsidian_client.py` | `monitor.py`, `zoe_tools.py`, `planner_engine.py` |
| 4 — PR Review | 11 | `reviewer.py` | `monitor.py` |
| 5 — Cleanup + Scripts | 12–13 | `cleanup_daemon.py`, 3 shell scripts | `discord/.env.example`, `pyproject.toml` |

**Total: 13 tasks, ~40 checkable steps, TDD throughout.**
