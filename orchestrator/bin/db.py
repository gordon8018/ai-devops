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


_INITIAL_BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))


def _resolve_base_dir() -> Path:
    env_base = os.getenv("AI_DEVOPS_HOME")
    if env_base:
        return Path(env_base)
    return _INITIAL_BASE


def _resolve_db_path() -> Path:
    base = _resolve_base_dir()
    return base / ".clawdbot" / "agent_tasks.db"


class _DynamicDBPath(os.PathLike[str]):
    """Path-like proxy that always resolves against current AI_DEVOPS_HOME."""

    def _path(self) -> Path:
        return _resolve_db_path()

    def __fspath__(self) -> str:
        return str(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return f"DynamicDBPath({self._path()!s})"

    @property
    def parent(self) -> Path:
        return self._path().parent

    def exists(self) -> bool:
        return self._path().exists()


# Module-level alias for external code that reads DB_PATH directly (e.g. tests, scripts)
DB_PATH = _DynamicDBPath()


@contextmanager
def get_db():
    """Get database connection with row factory"""
    conn = sqlite3.connect(os.fspath(DB_PATH))
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
            if key == "metadata" and not isinstance(value, str):
                value = json.dumps(value)
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


