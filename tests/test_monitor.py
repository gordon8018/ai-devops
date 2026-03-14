#!/usr/bin/env python3
"""
Tests for monitor.py - Fixed Version
"""

import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock, mock_open

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from monitor import (
    sh, notify, tmux_available, tmux_alive, process_alive,
    exit_status_path, load_exit_status, log_file_stale, task_elapsed_minutes,
    pr_info, merge_clean, analyze_checks, latest_run_failure,
    restart_codex_agent, check_all_tasks,
)
from db import init_db, insert_task, update_task_status, get_task


def make_task(**overrides) -> dict:
    """Helper to create valid task dict"""
    task = {
        "id": "test-task",
        "repo": "test/repo",
        "title": "Test Task",
        "status": "running",
        "tmuxSession": "test-session",
        "worktree": "/tmp/test",
        "branch": "feat/test",
        "startedAt": int(time.time() * 1000) - 60000,
    }
    task.update(overrides)
    return task


class TestHelperFunctions(unittest.TestCase):
    def test_sh_success(self):
        result = sh(["echo", "hello"])
        self.assertEqual(result, "hello")

    def test_sh_failure_check_false(self):
        result = sh(["false"])
        self.assertEqual(result, "")

    def test_sh_failure_check_true(self):
        with self.assertRaises(RuntimeError):
            sh(["false"], check=True)

    def test_notify_no_webhook(self):
        # notify() is now the fallback (prints to stdout) — must not raise
        notify("test message")

    def test_notify_success(self):
        # notify() is now the fallback (prints to stdout) — must not raise
        notify("test message")

    @patch("monitor.shutil.which")
    def test_tmux_available_true(self, mock_which):
        mock_which.return_value = "/usr/bin/tmux"
        self.assertTrue(tmux_available())

    @patch("monitor.shutil.which")
    def test_tmux_available_false(self, mock_which):
        mock_which.return_value = None
        self.assertFalse(tmux_available())

    def test_process_alive_valid(self):
        self.assertTrue(process_alive(os.getpid()))

    def test_process_alive_invalid(self):
        self.assertFalse(process_alive(None))
        self.assertFalse(process_alive(-1))

    def test_exit_status_path(self):
        path = exit_status_path("test-task-123")
        self.assertIn("test-task-123.exit.json", str(path))

    def test_load_exit_status_not_exists(self):
        result = load_exit_status("nonexistent-task")
        self.assertIsNone(result)

    def test_task_elapsed_minutes(self):
        now = int(time.time() * 1000)
        five_min_ago = now - (5 * 60 * 1000)
        task = {"startedAt": five_min_ago}
        elapsed = task_elapsed_minutes(task)
        self.assertAlmostEqual(elapsed, 5.0, delta=1.0)

    def test_task_elapsed_minutes_no_start(self):
        task = {}
        elapsed = task_elapsed_minutes(task)
        self.assertEqual(elapsed, 0)


class TestPRAnalysis(unittest.TestCase):
    def test_merge_clean_true(self):
        pr = {"mergeable": True, "mergeStateStatus": "clean"}
        self.assertTrue(merge_clean(pr))

    def test_merge_clean_false_not_mergeable(self):
        pr = {"mergeable": False, "mergeStateStatus": "dirty"}
        self.assertFalse(merge_clean(pr))

    def test_analyze_checks_no_rollup(self):
        pr = {}
        passed, summary, pending = analyze_checks(pr)
        self.assertFalse(passed)
        self.assertTrue(pending)

    def test_analyze_checks_all_passed(self):
        pr = {"statusCheckRollup": [
            {"name": "test", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]}
        passed, summary, pending = analyze_checks(pr)
        self.assertTrue(passed)
        self.assertFalse(pending)

    def test_analyze_checks_pending(self):
        pr = {"statusCheckRollup": [
            {"name": "test", "status": "IN_PROGRESS", "conclusion": ""},
        ]}
        passed, summary, pending = analyze_checks(pr)
        self.assertFalse(passed)
        self.assertTrue(pending)

    def test_analyze_checks_failure(self):
        pr = {"statusCheckRollup": [
            {"name": "test", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]}
        passed, summary, pending = analyze_checks(pr)
        self.assertFalse(passed)
        self.assertFalse(pending)


class TestMonitorTaskChecking(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.log_dir = self.base / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.worktree = self.base / "worktrees" / "test-task"
        self.worktree.mkdir(parents=True)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    @patch("monitor.tmux_alive", return_value=True)
    @patch("monitor.log_file_stale", return_value=False)
    @patch("monitor.pr_info", return_value=None)
    @patch("monitor.load_exit_status", return_value=None)
    def test_task_running_alive(self, mock_exit, mock_pr, mock_stale, mock_tmux):
        task = make_task(id="test-task-running", worktree=str(self.worktree))
        insert_task(task)
        changed, notified = check_all_tasks(set())
        updated_task = get_task("test-task-running")
        self.assertEqual(updated_task["status"], "running")

    @patch("monitor.tmux_alive", return_value=False)
    @patch("monitor.pr_info", return_value=None)
    def test_task_running_dead_session(self, mock_pr, mock_tmux):
        task = make_task(id="test-task-dead", worktree=str(self.worktree))
        insert_task(task)
        changed, notified = check_all_tasks(set())
        updated_task = get_task("test-task-dead")
        self.assertEqual(updated_task["status"], "agent_dead")


def test_monitor_once_exits_after_one_cycle(tmp_path, monkeypatch):
    """monitor main() with --once must call run_once exactly once and return."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import sys, importlib

    # Pre-create DB
    if "orchestrator.bin.db" in sys.modules:
        del sys.modules["orchestrator.bin.db"]
    import orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    # Load monitor fresh
    if "orchestrator.bin.monitor" in sys.modules:
        del sys.modules["orchestrator.bin.monitor"]

    old_argv = sys.argv[:]
    sys.argv = ["monitor.py", "--once"]
    try:
        import orchestrator.bin.monitor as mon
        importlib.reload(mon)
        calls = []
        monkeypatch.setattr(mon, "run_once", lambda nr: calls.append(1))
        mon.main()
        assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"
    finally:
        sys.argv = old_argv


def test_monitor_run_once_reads_sqlite(tmp_path, monkeypatch):
    """run_once() must use get_running_tasks() from db, not read any JSON."""
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    import sys, importlib

    if "orchestrator.bin.db" in sys.modules:
        del sys.modules["orchestrator.bin.db"]
    import orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    if "orchestrator.bin.monitor" in sys.modules:
        del sys.modules["orchestrator.bin.monitor"]
    import orchestrator.bin.monitor as mon
    importlib.reload(mon)

    # Patch get_running_tasks to return empty list
    called = []
    monkeypatch.setattr(mon, "get_running_tasks", lambda: called.append(1) or [])
    mon.run_once(set())
    assert len(called) == 1, "get_running_tasks must be called by run_once"


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


if __name__ == "__main__":
    unittest.main()
