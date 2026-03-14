from __future__ import annotations

import json
import re
import time
from pathlib import Path

try:
    from .config import ai_devops_home, queue_dir
except ImportError:
    from config import ai_devops_home, queue_dir


def base_dir() -> Path:
    return ai_devops_home()


def queue_root() -> Path:
    return queue_dir()


def generate_task_id(repo: str, title: str) -> str:
    timestamp = str(int(time.time() * 1000))
    repo_part = re.sub(r"[^A-Za-z0-9_-]", "-", repo.replace("/", "-"))
    slug = re.sub(r"[^A-Za-z0-9_-]", "-", title.lower())[:48]
    return f"{timestamp}-{repo_part}-{slug}"


def format_timestamp(ts_ms: int) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_ms / 1000))
    except (ValueError, OSError):
        return str(ts_ms)


def print_table(tasks: list[dict], columns: list[str] | None = None) -> None:
    if not tasks:
        print("No tasks found.")
        return

    if columns is None:
        columns = ["id", "status", "repo", "title", "agent", "started_at"]

    widths = {}
    for col in columns:
        widths[col] = len(col)
        for task in tasks:
            val = str(task.get(col, "") or "")
            if col == "started_at" and val:
                val = format_timestamp(int(val))[:19]
            elif col == "id" and len(val) > 20:
                val = val[:17] + "..."
            widths[col] = max(widths[col], len(val))

    header = "  ".join(col.upper().ljust(widths[col]) for col in columns)
    print(header)
    print("-" * len(header))
    for task in tasks:
        row = []
        for col in columns:
            val = str(task.get(col, "") or "")
            if col == "started_at" and val:
                val = format_timestamp(int(val))[:19]
            elif col == "id" and len(val) > 20:
                val = val[:17] + "..."
            row.append(val.ljust(widths[col]))
        print("  ".join(row))


def print_task_detail(task: dict) -> None:
    print(f"\n{'='*60}")
    print(f"Task: {task['id']}")
    print(f"{'='*60}")

    fields = [
        ("ID", "id"),
        ("Plan", "plan_id"),
        ("Repo", "repo"),
        ("Title", "title"),
        ("Status", "status"),
        ("Agent", "agent"),
        ("Model", "model"),
        ("Effort", "effort"),
        ("Branch", "branch"),
        ("Worktree", "worktree"),
        ("tmux Session", "tmux_session"),
        ("PR", "pr_url"),
        ("Attempts", "attempts"),
        ("Started", "started_at"),
        ("Completed", "completed_at"),
        ("Note", "note"),
        ("Last Failure", "last_failure"),
        ("Last Failure At", "last_failure_at"),
    ]

    for label, key in fields:
        val = task.get(key)
        if val:
            if key in ("started_at", "completed_at", "last_failure_at"):
                val = format_timestamp(int(val))
            elif isinstance(val, dict):
                val = json.dumps(val, indent=2)
            print(f"{label:15} {val}")

    print(f"{'='*60}\n")
