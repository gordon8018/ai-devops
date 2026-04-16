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
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from packages.kernel.storage.postgres import ControlPlanePostgresStore
from packages.shared.domain.control_plane import clear_control_plane_store, get_control_plane_store, set_control_plane_store
from packages.shared.domain.models import (
    AuditEvent,
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
)


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


def enable_control_plane_dual_write(store: Any) -> None:
    """Enable mirrored writes into the control-plane store."""
    set_control_plane_store(store)


def disable_control_plane_dual_write() -> None:
    """Disable mirrored writes into the control-plane store."""
    clear_control_plane_store()


def _build_control_plane_store_from_dsn(dsn: str) -> Any:
    try:
        import psycopg  # type: ignore

        return ControlPlanePostgresStore(lambda: psycopg.connect(dsn))
    except ImportError:
        try:
            import psycopg2  # type: ignore

            return ControlPlanePostgresStore(lambda: psycopg2.connect(dsn))
        except ImportError as exc:
            raise RuntimeError("PostgreSQL dual-write requested but neither psycopg nor psycopg2 is installed") from exc


def configure_control_plane_dual_write(
    *,
    store: Any | None = None,
    dsn: str | None = None,
) -> Any | None:
    """Configure control-plane mirroring using an explicit store or env/DSN."""
    if store is not None:
        enable_control_plane_dual_write(store)
        return store

    resolved_dsn = dsn or os.getenv("AI_DEVOPS_CONTROL_PLANE_DSN", "").strip()
    if not resolved_dsn:
        return None

    control_plane_store = _build_control_plane_store_from_dsn(resolved_dsn)
    enable_control_plane_dual_write(control_plane_store)
    return control_plane_store


def _map_work_item_status(task_status: str) -> WorkItemStatus:
    normalized = str(task_status or "queued").strip().lower()
    if normalized == "planning":
        return WorkItemStatus.PLANNING
    if normalized in {"running", "retrying", "pr_created"}:
        return WorkItemStatus.RUNNING
    if normalized in {"ready", "merged"}:
        return WorkItemStatus.READY
    if normalized == "released":
        return WorkItemStatus.RELEASED
    if normalized in {"closed", "completed", "done"}:
        return WorkItemStatus.CLOSED
    if normalized in {
        "blocked",
        "failed",
        "agent_dead",
        "agent_failed",
        "needs_rebase",
        "pr_closed",
        "killed",
    }:
        return WorkItemStatus.BLOCKED
    return WorkItemStatus.QUEUED


def _map_work_item_priority(value: Any) -> WorkItemPriority:
    normalized = str(value or "medium").strip().lower()
    if normalized == "low":
        return WorkItemPriority.LOW
    if normalized == "high":
        return WorkItemPriority.HIGH
    if normalized == "critical":
        return WorkItemPriority.CRITICAL
    return WorkItemPriority.MEDIUM


def _build_work_item_from_task(task: dict[str, Any]) -> WorkItem:
    metadata = _parse_metadata(task.get("metadata"))
    constraints = metadata.get("constraints")
    if not isinstance(constraints, dict):
        constraints = {}

    acceptance = metadata.get("acceptanceCriteria")
    if not isinstance(acceptance, (list, tuple)):
        acceptance = ()

    explicit_type = str(task.get("type") or metadata.get("type") or "feature").strip().lower()
    work_item_type = {
        "feature": WorkItemType.FEATURE,
        "bugfix": WorkItemType.BUGFIX,
        "incident": WorkItemType.INCIDENT,
        "release_note": WorkItemType.RELEASE_NOTE,
        "experiment": WorkItemType.EXPERIMENT,
        "ops": WorkItemType.OPS,
    }.get(explicit_type, WorkItemType.FEATURE)

    return WorkItem(
        work_item_id=str(task["id"]),
        type=work_item_type,
        title=str(task.get("title") or ""),
        goal=str(task.get("note") or task.get("title") or ""),
        priority=_map_work_item_priority(task.get("priority") or metadata.get("priority")),
        status=_map_work_item_status(task.get("status", "queued")),
        repo=str(task.get("repo") or ""),
        constraints=constraints,
        acceptance_criteria=tuple(str(item) for item in acceptance if str(item).strip()),
        requested_by=str(metadata.get("requestedBy") or metadata.get("requested_by") or "sqlite"),
        requested_at=int(task.get("created_at") or int(time.time() * 1000)),
        source="sqlite_dual_write",
        metadata={
            "legacyTaskId": task.get("id"),
            "planId": task.get("plan_id"),
            "attempts": task.get("attempts"),
            "maxAttempts": task.get("max_attempts"),
            "sqlite": {
                "status": task.get("status"),
                "branch": task.get("branch"),
                "tmuxSession": task.get("tmux_session"),
            },
            "metadata": metadata,
        },
    )


def _mirror_task_to_control_plane(task: dict[str, Any], *, action: str) -> None:
    store = get_control_plane_store()
    if store is None:
        return

    work_item = _build_work_item_from_task(task)
    store.save_work_item(work_item)
    store.save_audit_event(
        AuditEvent(
            audit_event_id=f"ae_{task['id']}_{action}_{int(time.time() * 1000)}",
            entity_type="work_item",
            entity_id=work_item.work_item_id,
            action=action,
            payload={
                "taskId": task["id"],
                "status": task.get("status"),
                "repo": task.get("repo"),
            },
        )
    )


@contextmanager
def get_db():
    """Get database connection with row factory"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
                restart_count INTEGER DEFAULT 0,
                last_restart_at REAL,
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                updated_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                timeout_minutes INTEGER,
                last_activity_at INTEGER,
                last_heartbeat_at INTEGER
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
            ("restart_count", "INTEGER DEFAULT 0"),
            ("last_restart_at", "REAL"),
            ("timeout_minutes", "INTEGER"),
            ("last_activity_at", "INTEGER"),
            ("last_heartbeat_at", "INTEGER"),
            ("recovery_state", "TEXT"),
            ("recovery_started_at", "INTEGER"),
            ("recovery_attempts", "INTEGER DEFAULT 0"),
            ("recovery_metadata", "TEXT"),
        ]
        for col_name, col_def in new_columns:
            try:
                conn.execute(f"ALTER TABLE agent_tasks ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists


        # Plans table for cross-plan dependency tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                title TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                requested_at INTEGER NOT NULL,
                objective TEXT,
                constraints TEXT,
                context TEXT,
                version TEXT NOT NULL,
                plan_depends_on TEXT DEFAULT '[]',
                global_priority INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000),
                updated_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_repo ON plans(repo)")
        
        # Migrate existing plans table: add new columns if absent
        plan_columns = [
            ("plan_depends_on", "TEXT DEFAULT '[]'"),
            ("global_priority", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_def in plan_columns:
            try:
                conn.execute(f"ALTER TABLE plans ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # column already exists
        

        # Messages table for agent inter-communication
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                from_agent TEXT NOT NULL,
                to_agent TEXT NOT NULL,
                content TEXT,
                timestamp INTEGER NOT NULL,
                topic TEXT,
                delivered INTEGER DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now') * 1000)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_to_agent ON messages(to_agent)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_from_agent ON messages(from_agent)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_delivered ON messages(delivered)")
        
        # Migrate existing messages table: add new columns if absent
        message_columns = [
            ("topic", "TEXT"),
            ("delivered", "INTEGER DEFAULT 0"),
            ("created_at", "INTEGER DEFAULT (strftime('%s', 'now') * 1000)"),
        ]
        for col_name, col_def in message_columns:
            try:
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_def}")
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
             cleaned_up, started_at, attempts, max_attempts, metadata,
             timeout_minutes, last_activity_at, last_heartbeat_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            task.get("timeout_minutes"),
            task.get("last_activity_at"),
            task.get("last_heartbeat_at"),
            int(time.time() * 1000),
        ))
        conn.commit()
    _mirror_task_to_control_plane(get_task(task["id"]) or task, action="sqlite_task_inserted")


def get_task(task_id: str) -> Optional[dict]:
    """Get a single task by ID"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE id = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def _parse_metadata(raw_metadata: Any) -> dict[str, Any]:
    """将 metadata 统一解析为 dict，异常时返回空字典。"""
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    if isinstance(raw_metadata, str):
        try:
            parsed = json.loads(raw_metadata)
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def merge_task_metadata(task_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """合并 metadata，并保护 planId/subtaskId 不被意外覆盖。"""
    if not isinstance(patch, dict):
        raise ValueError("metadata patch must be a dict")
    task = get_task(task_id)
    if task is None:
        raise ValueError(f"Task not found: {task_id}")

    existing = _parse_metadata(task.get("metadata"))
    merged = dict(existing)
    merged.update(patch)

    # 关键路由字段一旦存在，后续更新只能保持一致，避免打断 dispatch 依赖链。
    for key in ("planId", "subtaskId"):
        existing_value = existing.get(key)
        if existing_value is None:
            continue
        patch_value = patch.get(key, existing_value)
        if patch_value != existing_value:
            raise ValueError(f"metadata.{key} cannot be overwritten for task {task_id}")
        merged[key] = existing_value

    update_task(task_id, {"metadata": merged})
    return merged


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
        "restart_count", "last_restart_at",
        "last_heartbeat_at",
        "recovery_state", "recovery_started_at", "recovery_attempts", "recovery_metadata",
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
    values.append(int(time.time() * 1000))
    values.append(task_id)
    
    with get_db() as conn:
        conn.execute(
            f"UPDATE agent_tasks SET {', '.join(fields)} WHERE id = ?",
            values
        )
        conn.commit()
    latest = get_task(task_id)
    if latest is not None:
        _mirror_task_to_control_plane(latest, action="sqlite_task_updated")
        status = updates.get("status")
        if status is not None:
            from orchestrator.api.events import get_event_manager

            get_event_manager().publish_task_status(
                task_id,
                str(status),
                {
                    "note": latest.get("note"),
                    "plan_id": latest.get("plan_id"),
                    "repo": latest.get("repo"),
                },
                source="sqlite_db",
            )


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

# ============ Plans Table Operations ============

def insert_plan(plan: dict) -> None:
    """Insert or update a plan"""
    plan_depends_on = plan.get("plan_depends_on", [])
    if isinstance(plan_depends_on, (list, tuple)):
        plan_depends_on = json.dumps(list(plan_depends_on))
    elif not isinstance(plan_depends_on, str):
        plan_depends_on = "[]"
    
    constraints = plan.get("constraints", {})
    if isinstance(constraints, dict):
        constraints = json.dumps(constraints)
    elif not isinstance(constraints, str):
        constraints = "{}"
    
    context = plan.get("context", {})
    if isinstance(context, dict):
        context = json.dumps(context)
    elif not isinstance(context, str):
        context = "{}"
    
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO plans
            (plan_id, repo, title, requested_by, requested_at, objective,
             constraints, context, version, plan_depends_on, global_priority,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plan["plan_id"],
            plan["repo"],
            plan["title"],
            plan["requested_by"],
            plan["requested_at"],
            plan.get("objective", ""),
            constraints,
            context,
            plan["version"],
            plan_depends_on,
            plan.get("global_priority", 0),
            plan.get("status", "pending"),
            plan.get("created_at", int(time.time() * 1000)),
            int(time.time() * 1000),
        ))
        conn.commit()


def get_plan(plan_id: str) -> Optional[dict]:
    """Get a single plan by ID"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM plans WHERE plan_id = ?",
            (plan_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        # Parse JSON fields
        if result.get("plan_depends_on"):
            try:
                result["plan_depends_on"] = json.loads(result["plan_depends_on"])
            except (json.JSONDecodeError, ValueError):
                result["plan_depends_on"] = []
        else:
            result["plan_depends_on"] = []
        if result.get("constraints"):
            try:
                result["constraints"] = json.loads(result["constraints"])
            except (json.JSONDecodeError, ValueError):
                result["constraints"] = {}
        if result.get("context"):
            try:
                result["context"] = json.loads(result["context"])
            except (json.JSONDecodeError, ValueError):
                result["context"] = {}
        return result


def update_plan(plan_id: str, updates: dict) -> None:
    """Update plan fields"""
    allowed_fields = {
        "repo", "title", "objective", "constraints", "context",
        "version", "plan_depends_on", "global_priority", "status"
    }
    
    fields = []
    values = []
    for key, value in updates.items():
        if key in allowed_fields:
            if key == "plan_depends_on":
                if isinstance(value, (list, tuple)):
                    value = json.dumps(list(value))
                elif not isinstance(value, str):
                    value = "[]"
            elif key in ("constraints", "context"):
                if isinstance(value, dict):
                    value = json.dumps(value)
                elif not isinstance(value, str):
                    value = "{}"
            fields.append(f"{key} = ?")
            values.append(value)
    
    if not fields:
        return
    
    fields.append("updated_at = ?")
    values.append(int(time.time() * 1000))
    values.append(plan_id)
    
    with get_db() as conn:
        conn.execute(
            f"UPDATE plans SET {', '.join(fields)} WHERE plan_id = ?",
            values
        )
        conn.commit()


def get_all_plans(limit: int = 50) -> list[dict]:
    """Get recent plans"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM plans ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        results = []
        for row in cursor.fetchall():
            plan = dict(row)
            if plan.get("plan_depends_on"):
                try:
                    plan["plan_depends_on"] = json.loads(plan["plan_depends_on"])
                except (json.JSONDecodeError, ValueError):
                    plan["plan_depends_on"] = []
            else:
                plan["plan_depends_on"] = []
            results.append(plan)
        return results


def get_plan_status(plan_id: str) -> Optional[str]:
    """Get the status of a plan (pending, running, completed, failed)"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT status FROM plans WHERE plan_id = ?",
            (plan_id,)
        )
        row = cursor.fetchone()
        return row["status"] if row else None


def are_plan_dependencies_completed(plan_id: str) -> tuple[bool, list[str]]:
    """
    Check if all dependencies of a plan are completed.
    Returns (all_completed, list_of_incomplete_plan_ids)
    """
    plan = get_plan(plan_id)
    if not plan:
        return (False, [plan_id])
    
    depends_on = plan.get("plan_depends_on", [])
    if not depends_on:
        return (True, [])
    
    incomplete = []
    for dep_plan_id in depends_on:
        dep_status = get_plan_status(dep_plan_id)
        if dep_status != "completed":
            incomplete.append(dep_plan_id)
    
    return (len(incomplete) == 0, incomplete)


# ============ Messages Table Operations ============

def save_message(message: dict) -> None:
    """Save a message to the database"""
    content = message.get("content")
    if not isinstance(content, str):
        content = json.dumps(content) if content else "{}"
    
    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO messages
            (message_id, from_agent, to_agent, content, timestamp, topic, delivered, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            message["message_id"],
            message["from_agent"],
            message["to_agent"],
            content,
            message["timestamp"],
            message.get("topic"),
            message.get("delivered", 0),
            message.get("created_at", int(time.time() * 1000)),
        ))
        conn.commit()


def get_pending_messages(to_agent: str, limit: int = 10) -> list[dict]:
    """Get pending (undelivered) messages for an agent"""
    with get_db() as conn:
        cursor = conn.execute(
            """SELECT * FROM messages 
               WHERE to_agent = ? AND delivered = 0 
               ORDER BY timestamp ASC 
               LIMIT ?""",
            (to_agent, limit)
        )
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            # Parse content if JSON
            if msg.get("content"):
                try:
                    msg["content"] = json.loads(msg["content"])
                except (json.JSONDecodeError, ValueError):
                    pass
            messages.append(msg)
        return messages


def mark_message_delivered(message_id: str) -> None:
    """Mark a message as delivered"""
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET delivered = 1 WHERE message_id = ?",
            (message_id,)
        )
        conn.commit()


def get_all_messages(limit: int = 50) -> list[dict]:
    """Get recent messages"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
        messages = []
        for row in cursor.fetchall():
            msg = dict(row)
            if msg.get("content"):
                try:
                    msg["content"] = json.loads(msg["content"])
                except (json.JSONDecodeError, ValueError):
                    pass
            messages.append(msg)
        return messages


def delete_old_messages(days: int = 30) -> int:
    """Delete messages older than N days"""
    cutoff_ms = int((time.time() - days * 86400) * 1000)
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM messages WHERE timestamp < ?",
            (cutoff_ms,)
        )
        conn.commit()
        return cursor.rowcount
