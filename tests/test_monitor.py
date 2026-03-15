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

from monitor import notify, check_all_tasks
from monitor_helpers import (
    sh, tmux_available, tmux_alive, process_alive,
    exit_status_path, load_exit_status, log_file_stale, task_elapsed_minutes,
    pr_info, merge_clean, analyze_checks, latest_run_failure,
    restart_agent,
)
from db import init_db, insert_task, update_task_status, get_task


def make_task(**overrides) -> dict:
    """创建有效任务字典的辅助函数"""
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
        # 当前通知函数为回退实现（打印到标准输出），不应抛异常
        notify("test message")

    def test_notify_success(self):
        # 当前通知函数为回退实现（打印到标准输出），不应抛异常
        notify("test message")

    @patch("monitor_helpers.shutil.which")
    def test_tmux_available_true(self, mock_which):
        mock_which.return_value = "/usr/bin/tmux"
        self.assertTrue(tmux_available())

    @patch("monitor_helpers.shutil.which")
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

    @patch("monitor_helpers.subprocess.Popen")
    def test_restart_agent_uses_claude_runner_in_process_mode(self, mock_popen):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            runner = base / "run-claude-agent.sh"
            runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            os.chmod(runner, 0o755)
            wt = base / "wt"
            wt.mkdir()

            with patch.dict(os.environ, {"CLAUDE_RUNNER_PATH": str(runner)}):
                mock_popen.return_value.pid = 1234
                task = {
                    "id": "t-claude",
                    "agent": "claude",
                    "executionMode": "process",
                    "model": "claude-sonnet-4",
                    "effort": "medium",
                }
                restart_agent(task, wt, "prompt.txt")

            args = mock_popen.call_args[0][0]
            self.assertEqual(args[0], str(runner))

    def test_restart_agent_missing_runner_raises(self):
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td) / "wt"
            wt.mkdir()
            with patch.dict(os.environ, {"CODEX_RUNNER_PATH": str(Path(td) / "missing.sh")}):
                task = {"id": "t1", "agent": "codex", "executionMode": "process"}
                with self.assertRaises(RuntimeError):
                    restart_agent(task, wt, "prompt.txt")


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

    @patch("monitor.tmux_alive", return_value=True)
    @patch("monitor.pr_info", return_value=None)
    @patch("monitor.sh", return_value=" M src/background.js")
    def test_task_blocked_when_touched_file_violates_scope(self, mock_sh, mock_pr, mock_tmux):
        task = make_task(
            id="test-task-scope",
            worktree=str(self.worktree),
            metadata={
                "constraints": {
                    "allowedPaths": [str(self.worktree / "skills" / "sonos-pure-play" / "**")],
                    "forbiddenPaths": ["src/**"],
                }
            },
        )
        insert_task(task)
        changed, notified = check_all_tasks(set())
        updated_task = get_task("test-task-scope")
        self.assertEqual(updated_task["status"], "blocked")
        self.assertIn("forbidden paths touched", updated_task["note"])


class TestMonitorIntegration(unittest.TestCase):
    """Integration-style monitor tests (TestCase style)."""

    def setUp(self):
        import shutil
        self._tmp = tempfile.mkdtemp(prefix="ai-devops-test-mon-")
        os.environ["AI_DEVOPS_HOME"] = self._tmp

    def tearDown(self):
        import shutil
        os.environ.pop("AI_DEVOPS_HOME", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_monitor_once_exits_after_one_cycle(self):
        """一次执行模式下应只调用一次监控循环并返回。"""
        import sys, importlib
        from unittest.mock import patch

        if "orchestrator.bin.db" in sys.modules:
            del sys.modules["orchestrator.bin.db"]
        import orchestrator.bin.db as db_mod
        importlib.reload(db_mod)
        db_mod.init_db()

        if "orchestrator.bin.monitor" in sys.modules:
            del sys.modules["orchestrator.bin.monitor"]

        old_argv = sys.argv[:]
        sys.argv = ["monitor.py", "--once"]
        try:
            import orchestrator.bin.monitor as mon
            importlib.reload(mon)
            calls = []
            with patch.object(mon, "run_once", side_effect=lambda nr: calls.append(1)):
                mon.main()
            self.assertEqual(len(calls), 1)
        finally:
            sys.argv = old_argv

    def test_monitor_run_once_reads_sqlite(self):
        """监控循环必须通过数据库读取运行任务，不应读取文本注册文件。"""
        import sys, importlib
        from unittest.mock import patch

        if "orchestrator.bin.db" in sys.modules:
            del sys.modules["orchestrator.bin.db"]
        import orchestrator.bin.db as db_mod
        importlib.reload(db_mod)
        db_mod.init_db()

        if "orchestrator.bin.monitor" in sys.modules:
            del sys.modules["orchestrator.bin.monitor"]
        import orchestrator.bin.monitor as mon
        importlib.reload(mon)

        called = []
        with patch.object(mon, "get_running_tasks", side_effect=lambda: called.append(1) or []):
            mon.run_once(set())
        self.assertEqual(len(called), 1, "get_running_tasks must be called by run_once")

    def test_retry_prompt_includes_business_context(self):
        """当知识库返回结果时，重试提示词应包含业务上下文段落。"""
        import importlib, orchestrator.bin.monitor as mon
        from unittest.mock import patch
        importlib.reload(mon)

        wt = Path(self._tmp) / "worktrees" / "feat-t1"
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
        with patch.object(mon, "_obsidian_search", return_value=obsidian_results), \
             patch.object(mon, "latest_run_failure", return_value=None):
            mon._build_retry_prompt(task, 1, "tests:FAILURE", "")

        content = (wt / "prompt.retry1.txt").read_text()
        self.assertIn("BUSINESS CONTEXT", content)
        self.assertIn("discussed auth issue", content)

    def test_retry_prompt_skips_context_when_obsidian_empty(self):
        """当知识库返回空数组时，重试提示词不应包含业务上下文段落。"""
        import importlib, orchestrator.bin.monitor as mon
        from unittest.mock import patch
        importlib.reload(mon)

        wt = Path(self._tmp) / "worktrees" / "feat-t2"
        wt.mkdir(parents=True)
        (wt / "prompt.txt").write_text("base prompt")

        task = {
            "id": "t2", "repo": "r", "title": "T",
            "branch": "feat/t2", "worktree": str(wt),
            "tmuxSession": None, "executionMode": "process",
            "model": "gpt-5.3-codex", "effort": "high",
            "attempts": 0, "maxAttempts": 3,
        }

        with patch.object(mon, "_obsidian_search", return_value=[]):
            mon._build_retry_prompt(task, 1, "lint:FAILURE", "")
        content = (wt / "prompt.retry1.txt").read_text()
        self.assertNotIn("BUSINESS CONTEXT", content)

    def test_failure_log_written_on_ci_failure(self):
        """检测到流水线失败时，应写入结构化失败日志。"""
        import importlib, orchestrator.bin.monitor as mon
        importlib.reload(mon)

        mon._write_failure_log("my-repo", "task-1", "lint:FAILURE", "details here")

        logs = list((Path(self._tmp) / ".clawdbot" / "failure-logs" / "my-repo").glob("*.json"))
        self.assertEqual(len(logs), 1)
        data = json.loads(logs[0].read_text())
        self.assertEqual(data["taskId"], "task-1")
        self.assertEqual(data["failSummary"], "lint:FAILURE")

    def test_success_pattern_written_on_ready(self):
        """任务进入就绪状态时，应将提示词文件写入模板目录。"""
        import importlib, orchestrator.bin.monitor as mon
        importlib.reload(mon)

        wt = Path(self._tmp) / "worktrees" / "feat-t1"
        wt.mkdir(parents=True)
        (wt / "prompt.txt").write_text("winning prompt content")

        mon._save_success_pattern(
            repo="my-repo", task_id="t1",
            title="Fix auth flow", worktree=wt, attempts=1
        )

        templates_dir = Path(self._tmp) / ".clawdbot" / "prompt-templates" / "my-repo"
        files = list(templates_dir.glob("*.md"))
        self.assertEqual(len(files), 1)
        content = files[0].read_text()
        self.assertIn("winning prompt content", content)
        self.assertIn("attempts=1", content)


if __name__ == "__main__":
    unittest.main()
