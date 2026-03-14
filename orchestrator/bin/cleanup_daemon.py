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
    from orchestrator.bin.db import init_db, get_all_tasks, mark_cleaned_up
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
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", worktree],
                cwd=str(repo_root) if repo_root.exists() else worktree,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                print(f"[WARN] git worktree remove failed for {task_id} (rc={result.returncode}): {result.stderr[:200]}")
            else:
                print(f"[INFO] Removed worktree for {task_id}: {worktree}")
                mark_cleaned_up(task_id)
        except Exception as exc:
            print(f"[WARN] Failed to remove worktree for {task_id}: {exc}")


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
