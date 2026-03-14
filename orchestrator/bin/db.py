#!/usr/bin/env python3
"""
SQLite Tracker for AI DevOps

Replaces JSON registry with SQLite for atomic operations, concurrent safety,
and efficient queries.

Usage:
    from orchestrator.bin.db import init_db, insert_task, get_task, update_task, get_running_tasks
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
DB_PATH = BASE / ".clawdbot" / "agent_tasks.db"


@contextmanager
def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


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
            except sqlite3.OperationalError:
                pass  # column already exists

        conn.commit()


def insert_task(task: dict) -> None:
    """Insert or update a task

    Note: cleaned_up is normally set via mark_cleaned_up() after worktree removal.
    """
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO agent_tasks
            (id, plan_id, repo, title, status, agent, model, effort,
             worktree, branch, tmux_session, process_id,
             execution_mode, prompt_file, notify_on_complete, worktree_strategy,
             cleaned_up, started_at, attempts, max_attempts, metadata, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            task.get("cleaned_up", 0),
            task.get("startedAt") or task.get("started_at"),
            task.get("attempts", 0),
            task.get("maxAttempts") or task.get("max_attempts", 3),
            json.dumps(task.get("metadata", {})),
            int(__import__("time").time() * 1000)
        ))
        conn.commit()


def get_task(task_id: str) -> Optional[dict]:
    """Get a single task by ID"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE id = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_task_by_branch(branch: str) -> Optional[dict]:
    """Get a task by branch name"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE branch = ?",
            (branch,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


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


def get_tasks_by_plan(plan_id: str) -> list[dict]:
    """Get all tasks for a plan"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE plan_id = ? ORDER BY id",
            (plan_id,)
        )
        return [dict(row) for row in cursor.fetchall()]


def get_running_tasks() -> list[dict]:
    """Get all running or pr_created tasks"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE status IN ('running', 'pr_created', 'retrying') ORDER BY started_at"
        )
        return [dict(row) for row in cursor.fetchall()]


def get_queued_tasks() -> list[dict]:
    """Get all queued tasks"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE status = 'queued' ORDER BY created_at"
        )
        return [dict(row) for row in cursor.fetchall()]


def get_all_tasks(limit: int = 50) -> list[dict]:
    """Get recent tasks"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]


def update_task(task_id: str, updates: dict) -> None:
    """Update task fields"""
    allowed_fields = {
        "status", "agent", "model", "effort", "worktree", "branch",
        "tmux_session", "process_id", "started_at", "completed_at",
        "attempts", "max_attempts", "pr_number", "pr_url",
        "last_failure", "last_failure_at", "note", "metadata",
        "execution_mode", "prompt_file", "notify_on_complete",
        "worktree_strategy", "cleaned_up",
    }
    
    fields = []
    values = []
    for key, value in updates.items():
        if key in allowed_fields:
            fields.append(f"{key} = ?")
            values.append(value)
    
    if not fields:
        return
    
    fields.append("updated_at = ?")
    values.append(int(__import__("time").time() * 1000))
    values.append(task_id)
    
    with get_db() as conn:
        conn.execute(
            f"UPDATE agent_tasks SET {', '.join(fields)} WHERE id = ?",
            values
        )
        conn.commit()


def update_task_status(task_id: str, status: str, note: Optional[str] = None) -> None:
    """Update task status with optional note"""
    updates = {"status": status}
    if note:
        updates["note"] = note
    update_task(task_id, updates)


def delete_task(task_id: str) -> None:
    """Delete a task"""
    with get_db() as conn:
        conn.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))
        conn.commit()


def count_running_tasks() -> int:
    """Count currently running tasks"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM agent_tasks WHERE status IN ('running', 'pr_created', 'retrying')"
        )
        return cursor.fetchone()[0]


def migrate_from_json() -> dict:
    """
    Migrate existing JSON registry to SQLite.
    Returns migration summary.
    """
    json_path = BASE / ".clawdbot" / "active-tasks.json"
    
    if not json_path.exists():
        return {"migrated": 0, "error": "JSON registry not found"}
    
    try:
        items = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"migrated": 0, "error": str(e)}
    
    if not isinstance(items, list):
        return {"migrated": 0, "error": "Invalid JSON format"}
    
    init_db()
    migrated = 0
    
    for item in items:
        if isinstance(item, dict) and "id" in item:
            insert_task(item)
            migrated += 1
    
    return {
        "migrated": migrated,
        "total": len(items),
        "backup": str(json_path)
    }


# Legacy compatibility - load_registry for backward compatibility
def load_registry() -> list[dict]:
    """Load all tasks (legacy compatibility)"""
    return get_all_tasks(limit=1000)


def save_registry(items: list[dict]) -> None:
    """Save tasks (legacy compatibility - updates all)"""
    for item in items:
        insert_task(item)
