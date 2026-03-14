#!/usr/bin/env python3
"""
Agent CLI - Unified command interface for AI DevOps

Usage:
    agent spawn --repo <repo> --title <title> [--agent codex] [--model gpt-5.3-codex]
    agent list [--status running] [--limit 10]
    agent status <task-id>
    agent send <task-id> <message>
    agent kill <task-id>
    agent plan --repo <repo> --title <title> --description <desc>
    agent dispatch --plan <plan-file>
    agent retry <task-id>
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Resolve paths
SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))

# Add orchestrator to path
sys.path.insert(0, str(SCRIPT_DIR))

# Import tool layer - use absolute imports
sys.path.insert(0, str(SCRIPT_DIR))

from db import (
    init_db,
    insert_task,
    get_task,
    get_running_tasks,
    get_all_tasks,
    update_task,
    update_task_status,
    delete_task,
    count_running_tasks,
)

# Lazy import zoe_tools (only needed for plan/dispatch commands)
def get_zoe_tools():
    import zoe_tools
    return zoe_tools


# ============================================================================
# Helper Functions
# ============================================================================

def generate_task_id(repo: str, title: str) -> str:
    """Generate a unique task ID"""
    import re
    timestamp = str(int(time.time() * 1000))
    repo_part = re.sub(r'[^A-Za-z0-9_-]', '-', repo.replace('/', '-'))
    slug = re.sub(r'[^A-Za-z0-9_-]', '-', title.lower())[:48]
    return f"{timestamp}-{repo_part}-{slug}"


def print_table(tasks: list[dict], columns: list[str] = None) -> None:
    """Print tasks as a formatted table"""
    if not tasks:
        print("No tasks found.")
        return
    
    if columns is None:
        columns = ["id", "status", "repo", "title", "agent", "started_at"]
    
    # Calculate column widths
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
    
    # Print header
    header = "  ".join(col.upper().ljust(widths[col]) for col in columns)
    print(header)
    print("-" * len(header))
    
    # Print rows
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


def format_timestamp(ts_ms: int) -> str:
    """Format millisecond timestamp"""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_ms / 1000))
    except (ValueError, OSError):
        return str(ts_ms)


def print_task_detail(task: dict) -> None:
    """Print detailed task information"""
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


# ============================================================================
# CLI Commands
# ============================================================================

def cmd_init(args):
    """Initialize the database"""
    init_db()
    print("✓ Database initialized")
    print(f"  Location: {BASE / '.clawdbot' / 'agent_tasks.db'}")


def cmd_spawn(args):
    """Spawn a new task"""
    init_db()
    
    task_id = generate_task_id(args.repo, args.title)
    task = {
        "id": task_id,
        "repo": args.repo,
        "title": args.title,
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
        "status": "queued",
        "metadata": {
            "description": args.description or "",
            "files_hint": args.files.split(",") if args.files else [],
        }
    }
    
    insert_task(task)
    
    # Write to queue
    queue_dir = BASE / "orchestrator" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_path = queue_dir / f"{task_id}.json"
    queue_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    
    print(f"✓ Task spawned: {task_id}")
    print(f"  Repo: {args.repo}")
    print(f"  Title: {args.title}")
    print(f"  Agent: {task['agent']} ({task['model']})")
    print(f"  Queue: {queue_path}")


def cmd_list(args):
    """List tasks"""
    init_db()
    
    if args.status == "running":
        tasks = get_running_tasks()
    elif args.status == "queued":
        # Queued tasks are in queue/*.json
        queue_dir = BASE / "orchestrator" / "queue"
        tasks = []
        if queue_dir.exists():
            for p in queue_dir.glob("*.json"):
                try:
                    task = json.loads(p.read_text())
                    tasks.append(task)
                except:
                    pass
    elif args.status == "all":
        tasks = get_all_tasks(limit=args.limit)
    else:
        tasks = get_all_tasks(limit=args.limit)
    
    print(f"\n{'='*60}")
    print(f"Tasks ({len(tasks)} found)")
    print(f"{'='*60}\n")
    
    if args.json:
        print(json.dumps(tasks, indent=2))
    else:
        print_table(tasks, columns=["id", "status", "repo", "title", "agent", "started_at"])


def cmd_status(args):
    """Show task status"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if args.json:
        print(json.dumps(task, indent=2))
    else:
        print_task_detail(task)


def cmd_send(args):
    """Send message to running agent via tmux"""
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    session = task.get("tmux_session") or task.get("tmuxSession")
    if not session:
        print(f"✗ Cannot send: no tmux session for {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if not shutil.which("tmux"):
        print("✗ tmux not found", file=sys.stderr)
        sys.exit(1)
    
    # Send keys to tmux session
    subprocess.run(["tmux", "send-keys", "-t", session, args.message, "Enter"])
    print(f"✓ Message sent to {args.task_id} (tmux: {session})")


def cmd_kill(args):
    """Kill running task"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    status = task.get("status")
    if status not in ("running", "pr_created", "retrying"):
        print(f"⚠ Task is not running (status: {status})")
    
    # Kill tmux session
    session = task.get("tmux_session") or task.get("tmuxSession")
    if session and shutil.which("tmux"):
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
        print(f"✓ tmux session killed: {session}")
    
    # Kill process
    process_id = task.get("process_id") or task.get("processId")
    if isinstance(process_id, int) and process_id > 0:
        try:
            os.kill(process_id, 9)
            print(f"✓ Process killed: {process_id}")
        except OSError as e:
            print(f"⚠ Process already dead: {e}")
    
    # Update status
    update_task_status(args.task_id, "killed", "killed by user")
    print(f"✓ Task killed: {args.task_id}")


def cmd_plan(args):
    """Plan a task without dispatching"""
    init_db()
    
    task_input = {
        "repo": args.repo,
        "title": args.title,
        "description": args.description,
        "requested_by": args.user or "cli",
        "requested_at": int(time.time() * 1000),
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
    }
    
    if args.files:
        task_input["context"] = {"filesHint": args.files.split(",")}
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.plan_task(task_input)
        print(f"✓ Plan created: {result.plan.plan_id}")
        print(f"  Subtasks: {len(result.plan.subtasks)}")
        print(f"  Plan file: {result.plan_path}")
        
        if not args.quiet:
            print("\nSubtasks:")
            for i, subtask in enumerate(result.plan.subtasks):
                print(f"  {subtask.id}: {subtask.title}")
                if subtask.depends_on:
                    print(f"         Depends: {', '.join(subtask.depends_on)}")
    except Exception as e:
        print(f"✗ Plan failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dispatch(args):
    """Dispatch an existing plan"""
    init_db()
    
    plan_path = Path(args.plan_file)
    if not plan_path.exists():
        print(f"✗ Plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.dispatch_plan(plan_path)
        print(f"✓ Dispatched: {result.queued_count} tasks queued")
        for path in result.queued:
            print(f"  - {path}")
    except Exception as e:
        print(f"✗ Dispatch failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plan_and_dispatch(args):
    """Plan and dispatch in one command"""
    init_db()
    
    task_input = {
        "repo": args.repo,
        "title": args.title,
        "description": args.description,
        "requested_by": args.user or "cli",
        "requested_at": int(time.time() * 1000),
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
    }
    
    if args.files:
        task_input["context"] = {"filesHint": args.files.split(",")}
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.plan_and_dispatch_task(task_input)
        print(f"✓ Plan created: {result.plan.plan_id}")
        print(f"  Subtasks: {len(result.plan.subtasks)}")
        print(f"  Queued: {len(result.queued_paths)} tasks")
        for path in result.queued_paths:
            print(f"  - {path}")
    except Exception as e:
        print(f"✗ Failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_retry(args):
    """Retry a failed task"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if task.get("status") not in ("blocked", "agent_failed", "timeout", "log_stale"):
        print(f"⚠ Task status is {task.get('status')}, not a retry candidate")
        if not args.force:
            print("Use --force to retry anyway")
            sys.exit(1)
    
    # Reset status and attempts
    update_task(args.task_id, {
        "status": "queued",
        "attempts": 0,
        "note": "retried by user"
    })
    
    # Re-queue
    queue_dir = BASE / "orchestrator" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    
    task_data = {
        "id": task["id"],
        "repo": task["repo"],
        "title": task["title"],
        "agent": task.get("agent", "codex"),
        "model": task.get("model", "gpt-5.3-codex"),
        "effort": task.get("effort", "medium"),
        "status": "queued",
    }
    
    queue_path = queue_dir / f"{task['id']}.json"
    queue_path.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
    
    print(f"✓ Task queued for retry: {args.task_id}")
    print(f"  Queue: {queue_path}")


def cmd_clean(args):
    """Clean up old tasks"""
    init_db()
    
    from db import get_db
    
    cutoff_days = args.days
    cutoff_ms = int((time.time() - cutoff_days * 86400) * 1000)
    
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT id, status, created_at FROM agent_tasks WHERE created_at < ? AND status IN ('ready', 'killed', 'agent_exited')",
            (cutoff_ms,)
        )
        old_tasks = cursor.fetchall()
    
    if not old_tasks:
        print(f"No tasks older than {cutoff_days} days to clean")
        return
    
    print(f"Found {len(old_tasks)} tasks older than {cutoff_days} days:")
    for task_id, status, created_at in old_tasks:
        print(f"  {task_id} ({status})")
    
    if not args.dry_run:
        for task_id, _, _ in old_tasks:
            delete_task(task_id)
        print(f"✓ Deleted {len(old_tasks)} tasks")
    else:
        print(f"\nDry run - use without --dry-run to delete")


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="AI DevOps Agent CLI - Unified command interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agent spawn --repo my-repo --title "Fix auth bug"
  agent list --status running
  agent status 1234567890-my-repo-fix-auth-bug-S1
  agent send 1234567890-my-repo-fix-auth-bug-S1 "please check line 42"
  agent kill 1234567890-my-repo-fix-auth-bug-S1
  agent plan --repo my-repo --title "Add tests" --description "Add unit tests"
  agent dispatch --plan ~/ai-devops/tasks/xxx/plan.json
  agent retry 1234567890-my-repo-fix-auth-bug-S1
  agent clean --days 30 --dry-run
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")
    
    # init
    p = subparsers.add_parser("init", help="Initialize the database")
    p.set_defaults(func=cmd_init)
    
    # spawn
    p = subparsers.add_parser("spawn", help="Spawn a new task")
    p.add_argument("--repo", required=True, help="Repository name")
    p.add_argument("--title", required=True, help="Task title")
    p.add_argument("--description", help="Task description")
    p.add_argument("--agent", default="codex", choices=["codex", "claude"])
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--files", help="Comma-separated file hints")
    p.set_defaults(func=cmd_spawn)
    
    # list
    p = subparsers.add_parser("list", help="List tasks")
    p.add_argument("--status", default="all", choices=["all", "running", "queued", "ready", "blocked"])
    p.add_argument("--limit", type=int, default=20, help="Max tasks to show")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_list)
    
    # status
    p = subparsers.add_parser("status", help="Show task status")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_status)
    
    # send
    p = subparsers.add_parser("send", help="Send message to running agent")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("message", help="Message to send")
    p.set_defaults(func=cmd_send)
    
    # kill
    p = subparsers.add_parser("kill", help="Kill running task")
    p.add_argument("task_id", help="Task ID")
    p.set_defaults(func=cmd_kill)
    
    # plan
    p = subparsers.add_parser("plan", help="Plan a task without dispatching")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--user", default="cli")
    p.add_argument("--agent", default="codex")
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium")
    p.add_argument("--files", help="Comma-separated file hints")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_plan)
    
    # dispatch
    p = subparsers.add_parser("dispatch", help="Dispatch existing plan")
    p.add_argument("--plan", dest="plan_file", required=True, help="Path to plan.json")
    p.set_defaults(func=cmd_dispatch)
    
    # plan-and-dispatch
    p = subparsers.add_parser("plan-and-dispatch", help="Plan and dispatch in one command")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--user", default="cli")
    p.add_argument("--agent", default="codex")
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium")
    p.add_argument("--files", help="Comma-separated file hints")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_plan_and_dispatch)
    
    # retry
    p = subparsers.add_parser("retry", help="Retry a failed task")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("--force", "-f", action="store_true")
    p.set_defaults(func=cmd_retry)
    
    # clean
    p = subparsers.add_parser("clean", help="Clean up old tasks")
    p.add_argument("--days", type=int, default=30, help="Delete tasks older than N days")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_clean)
    
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
