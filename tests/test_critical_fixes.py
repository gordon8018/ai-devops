#!/usr/bin/env python3
"""
Tests for critical bugs C1-C6 identified in code review.

RED phase: these tests should fail before fixes are applied.
"""
import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))


# ---------------------------------------------------------------------------
# C1: cmd_dispatch uses wrong attribute names on DispatchPlanResult
# ---------------------------------------------------------------------------
class TestCmdDispatchAttributes(unittest.TestCase):
    """C1: cmd_dispatch must use queued_paths, not .queued / .queued_count."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        from db import init_db
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("AI_DEVOPS_HOME", None)

    def test_cmd_dispatch_does_not_raise_attribute_error(self):
        """cmd_dispatch must not raise AttributeError when dispatch_plan returns."""
        from orchestrator.bin.zoe_tools import DispatchPlanResult

        plan_file = self.base / "plan.json"
        plan_file.write_text(json.dumps({"planId": "p1"}), encoding="utf-8")

        queued_path = self.base / "orchestrator" / "queue" / "task.json"
        queued_path.parent.mkdir(parents=True, exist_ok=True)
        fake_result = DispatchPlanResult(
            plan_file=plan_file,
            queued_paths=(queued_path,),
        )

        import agent as agent_mod
        args = MagicMock(plan_file=str(plan_file))

        output = io.StringIO()
        with patch.object(agent_mod, "get_zoe_tools") as mock_get:
            mock_zoe = MagicMock()
            mock_zoe.dispatch_plan.return_value = fake_result
            mock_get.return_value = mock_zoe

            # Must NOT raise AttributeError
            with redirect_stdout(output):
                agent_mod.cmd_dispatch(args)

        result = output.getvalue()
        self.assertIn("1", result)           # queued count
        self.assertIn(str(queued_path), result)  # path listed

    def test_cmd_dispatch_shows_count_and_paths(self):
        """cmd_dispatch output contains the number of queued tasks."""
        from orchestrator.bin.zoe_tools import DispatchPlanResult

        plan_file = self.base / "plan.json"
        plan_file.write_text("{}", encoding="utf-8")

        p1 = Path("/tmp/a.json")
        p2 = Path("/tmp/b.json")
        fake_result = DispatchPlanResult(plan_file=plan_file, queued_paths=(p1, p2))

        import agent as agent_mod
        args = MagicMock(plan_file=str(plan_file))

        output = io.StringIO()
        with patch.object(agent_mod, "get_zoe_tools") as mock_get:
            mock_zoe = MagicMock()
            mock_zoe.dispatch_plan.return_value = fake_result
            mock_get.return_value = mock_zoe

            with redirect_stdout(output):
                agent_mod.cmd_dispatch(args)

        result = output.getvalue()
        self.assertIn("2", result)
        self.assertIn("/tmp/a.json", result)
        self.assertIn("/tmp/b.json", result)


# ---------------------------------------------------------------------------
# C2: Shell injection via unquoted values in tmux command
# ---------------------------------------------------------------------------
class TestTmuxShellQuoting(unittest.TestCase):
    """C2: restart_agent and launch_agent_process must quote values inserted
    into the tmux shell command to prevent shell injection."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.wt = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_restart_agent_quotes_task_id_with_special_chars(self):
        """Special characters in task_id must be shell-quoted (via shlex.quote)
        in the tmux shell command string."""
        import shlex
        runner_path = self.wt / "run-codex-agent.sh"
        runner_path.touch(mode=0o755)

        task = {
            "id": 'task"$(evil)',  # would cause injection if not quoted
            "agent": "codex",
            "model": "gpt-5.3-codex",
            "effort": "high",
            "tmuxSession": "agent-test",
            "execution_mode": "tmux",
            "executionMode": "tmux",
        }

        captured_cmds = []

        def fake_sh(cmd, **kwargs):
            captured_cmds.append(cmd)
            return ""

        with patch("monitor_helpers.subprocess.run") as mock_run, \
             patch("monitor_helpers.sh", side_effect=fake_sh), \
             patch.dict(os.environ, {"CODEX_RUNNER_PATH": str(runner_path)}):
            mock_run.return_value = MagicMock(returncode=0)
            from monitor_helpers import restart_agent
            restart_agent(task, self.wt, "prompt.txt")

        # Find the tmux new-session call
        tmux_calls = [c for c in captured_cmds if "new-session" in c]
        self.assertTrue(tmux_calls, "tmux new-session not called")
        shell_cmd = tmux_calls[0][-1]  # last arg is the shell command string
        # shlex.quote wraps the task_id in single quotes so the shell cannot
        # interpret the metacharacters.  Verify the quoted form is present.
        expected_quoted = shlex.quote('task"$(evil)')
        self.assertIn(expected_quoted, shell_cmd,
                      "task_id must appear as a shlex-quoted token in the tmux command")

    def test_launch_agent_process_quotes_task_id_with_special_chars(self):
        """launch_agent_process in zoe-daemon must also shell-quote the task_id."""
        import importlib.util
        import shlex

        daemon_file = BASE / "orchestrator" / "bin" / "zoe-daemon.py"
        spec = importlib.util.spec_from_file_location("zoe_daemon", daemon_file)
        daemon_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(daemon_mod)

        runner_path = self.wt / "run-codex-agent.sh"
        runner_path.touch(mode=0o755)

        task = {
            "id": 'task"$(evil)',
            "model": "gpt-5.3-codex",
            "effort": "high",
        }

        captured_cmds = []

        def fake_sh(cmd, **kwargs):
            captured_cmds.append(cmd)
            return ""

        with patch.object(daemon_mod, "sh", side_effect=fake_sh), \
             patch.object(daemon_mod, "tmux_available", return_value=True), \
             patch.object(daemon_mod, "tmux_has", return_value=False):
            daemon_mod.launch_agent_process(runner_path, task, self.wt, self.wt / "prompt.txt")

        tmux_calls = [c for c in captured_cmds if "new-session" in c]
        self.assertTrue(tmux_calls, "tmux new-session not called")
        shell_cmd = tmux_calls[0][-1]
        expected_quoted = shlex.quote('task"$(evil)')
        self.assertIn(expected_quoted, shell_cmd,
                      "task_id must appear as a shlex-quoted token in the daemon tmux command")


# ---------------------------------------------------------------------------
# C3: cmd_kill sends SIGTERM before SIGKILL
# ---------------------------------------------------------------------------
class TestCmdKillSignalOrder(unittest.TestCase):
    """C3: cmd_kill must send SIGTERM first, only escalating to SIGKILL if
    the process does not exit within the grace period."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AI_DEVOPS_HOME"] = str(Path(self.temp_dir.name))
        from db import init_db
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("AI_DEVOPS_HOME", None)

    def _insert_running_task(self, pid: int) -> str:
        from db import insert_task, init_db
        init_db()
        task = {
            "id": "kill-test-task",
            "repo": "repo",
            "title": "kill test",
            "status": "running",
            "process_id": pid,
            "tmux_session": None,
            "agent": "codex",
            "model": "m",
            "effort": "h",
        }
        insert_task(task)
        return task["id"]

    def test_sigterm_sent_before_sigkill(self):
        """SIGTERM must be sent; if process dies, SIGKILL must NOT be sent."""
        import agent as agent_mod

        task_id = self._insert_running_task(pid=99999)
        args = MagicMock(task_id=task_id)

        kill_calls = []

        def fake_kill(pid, sig):
            kill_calls.append(sig)
            if sig == signal.SIGTERM:
                return  # simulate clean exit
            if sig == 0:
                raise OSError("no such process")

        with patch("agent.os.kill", side_effect=fake_kill), \
             patch("agent.shutil.which", return_value=None), \
             patch("agent.subprocess.run"), \
             patch("agent.time.sleep"):
            output = io.StringIO()
            with redirect_stdout(output):
                agent_mod.cmd_kill(args)

        # SIGTERM must appear in the calls
        self.assertIn(signal.SIGTERM, kill_calls,
                      "SIGTERM must be sent before escalating")

    def test_sigkill_not_sent_if_process_exits_after_sigterm(self):
        """If the process exits after SIGTERM, SIGKILL must not be sent."""
        import agent as agent_mod

        task_id = self._insert_running_task(pid=99998)
        args = MagicMock(task_id=task_id)

        kill_calls = []

        def fake_kill(pid, sig):
            kill_calls.append(sig)
            if sig == signal.SIGTERM:
                return
            if sig == 0:
                # simulate process already dead after SIGTERM
                raise OSError("no such process")

        with patch("agent.os.kill", side_effect=fake_kill), \
             patch("agent.shutil.which", return_value=None), \
             patch("agent.subprocess.run"), \
             patch("agent.time.sleep"):
            output = io.StringIO()
            with redirect_stdout(output):
                agent_mod.cmd_kill(args)

        self.assertNotIn(signal.SIGKILL, kill_calls,
                         "SIGKILL must not be sent if process exited after SIGTERM")


# ---------------------------------------------------------------------------
# C4: _restart_agent in zoe_tools must use correct runner per agent type
# ---------------------------------------------------------------------------
class TestRetryTaskUsesCorrectRunner(unittest.TestCase):
    """C4: retry_task (via _restart_agent) must use the claude runner
    for tasks with agent='claude', not always the codex runner."""

    def test_retry_task_claude_uses_claude_runner(self, tmp_path=None):
        """When retrying a claude task, the claude runner must be invoked."""
        import tempfile as _tmp
        with _tmp.TemporaryDirectory() as d:
            wt = Path(d) / "worktree"
            wt.mkdir()
            (wt / "prompt.txt").write_text("original prompt", encoding="utf-8")

            claude_runner = Path(d) / "run-claude-agent.sh"
            claude_runner.touch(mode=0o755)

            task = {
                "id": "task-claude",
                "status": "blocked",
                "attempts": 0,
                "max_attempts": 3,
                "worktree": str(wt),
                "agent": "claude",
                "model": "claude-sonnet-4",
                "effort": "high",
                "execution_mode": "process",
                "tmux_session": None,
                "tmuxSession": None,
            }

            popen_calls = []

            def fake_popen(cmd, **kwargs):
                popen_calls.append(cmd)
                m = MagicMock()
                m.pid = 42
                return m

            with patch("orchestrator.bin.zoe_tools.get_task", return_value=task), \
                 patch("orchestrator.bin.zoe_tools.update_task"), \
                 patch("orchestrator.bin.zoe_tools.merge_task_metadata"), \
                 patch.dict(os.environ, {"CLAUDE_RUNNER_PATH": str(claude_runner)}), \
                 patch("monitor_helpers.subprocess.Popen", side_effect=fake_popen), \
                 patch("monitor_helpers.subprocess.run"):
                from orchestrator.bin.zoe_tools import retry_task
                retry_task("task-claude", reason="test")

            self.assertTrue(popen_calls, "subprocess.Popen was not called")
            runner_used = str(popen_calls[0][0])
            self.assertIn(
                str(claude_runner), runner_used,
                f"Expected claude runner, got: {runner_used}",
            )

    def test_zoe_tools_restart_agent_is_monitor_helpers_restart_agent(self):
        """After fix, _restart_agent in zoe_tools must delegate to
        monitor_helpers.restart_agent (same function object)."""
        from orchestrator.bin import zoe_tools
        from orchestrator.bin.monitor_helpers import restart_agent as mh_restart
        # After fix: zoe_tools._restart_agent IS monitor_helpers.restart_agent
        self.assertIs(
            zoe_tools._restart_agent,
            mh_restart,
            "_restart_agent in zoe_tools must be the same function as "
            "monitor_helpers.restart_agent",
        )


# ---------------------------------------------------------------------------
# C5: webhook_server.py log_event must rotate the log file
# ---------------------------------------------------------------------------
class TestWebhookLogRotation(unittest.TestCase):
    """C5: log_event must rotate webhook.log when it exceeds the size limit."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name) / "logs"
        self.log_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_log_event_rotates_when_file_exceeds_limit(self):
        """webhook.log must be rotated (renamed to .1) when it exceeds MAX_LOG_BYTES."""
        import webhook_server as ws

        log_file = self.log_dir / "webhook.log"
        # Pre-fill the log beyond the rotation threshold
        log_file.write_bytes(b"x" * (ws.MAX_LOG_BYTES + 1))

        original_size = log_file.stat().st_size

        with patch.object(ws, "log_dir", return_value=self.log_dir):
            ws.log_event("check_run", "completed", {"branch": "main"})

        # After rotation, the new log file should be much smaller
        self.assertTrue(log_file.exists(), "webhook.log must still exist after rotation")
        new_size = log_file.stat().st_size
        self.assertLess(
            new_size, original_size,
            "webhook.log should be smaller after rotation (old content moved to .1)",
        )
        rotated = self.log_dir / "webhook.log.1"
        self.assertTrue(rotated.exists(), "webhook.log.1 must exist after rotation")

    def test_log_event_does_not_rotate_small_file(self):
        """No rotation occurs when the log file is within the size limit."""
        import webhook_server as ws

        log_file = self.log_dir / "webhook.log"
        log_file.write_text('{"existing": true}\n', encoding="utf-8")

        with patch.object(ws, "log_dir", return_value=self.log_dir):
            ws.log_event("pull_request", "opened", {"branch": "feat/x"})

        rotated = self.log_dir / "webhook.log.1"
        self.assertFalse(rotated.exists(), "No rotation expected for small log file")


# ---------------------------------------------------------------------------
# C6: ready_subtask_ids must treat 'merged' as a completed status
# ---------------------------------------------------------------------------
class TestReadySubtaskIdsIncludesMerged(unittest.TestCase):
    """C6: ready_subtask_ids must count tasks with status='merged' as
    completed so dependent subtasks can be dispatched."""

    def _make_plan(self):
        from orchestrator.bin.plan_schema import Plan
        return Plan.from_dict({
            "planId": "p1",
            "repo": "repo",
            "title": "T",
            "requestedBy": "u",
            "requestedAt": 1,
            "objective": "obj",
            "routing": {"agent": "codex", "model": "m", "effort": "medium"},
            "version": "1.0",
            "subtasks": [
                {
                    "id": "S1", "title": "S1", "description": "d",
                    "dependsOn": [], "worktreeStrategy": "isolated",
                    "filesHint": [], "prompt": "p",
                },
                {
                    "id": "S2", "title": "S2", "description": "d",
                    "dependsOn": ["S1"], "worktreeStrategy": "isolated",
                    "filesHint": [], "prompt": "p",
                },
            ],
        })

    def test_merged_task_counts_as_completed(self):
        """A subtask whose execution task is 'merged' must be in ready set."""
        from orchestrator.bin.dispatch import ready_subtask_ids
        plan = self._make_plan()

        # S1's execution task has status 'merged'
        registry_items = [
            {
                "id": "p1-S1",
                "status": "merged",
                "metadata": {"planId": "p1", "subtaskId": "S1"},
            }
        ]
        result = ready_subtask_ids(plan, registry_items)
        self.assertIn("S1", result,
                      "S1 with status 'merged' must be counted as completed")

    def test_ready_task_still_counts_as_completed(self):
        """Existing 'ready' status must still work (regression guard)."""
        from orchestrator.bin.dispatch import ready_subtask_ids
        plan = self._make_plan()

        registry_items = [
            {
                "id": "p1-S1",
                "status": "ready",
                "metadata": {"planId": "p1", "subtaskId": "S1"},
            }
        ]
        result = ready_subtask_ids(plan, registry_items)
        self.assertIn("S1", result)

    def test_downstream_subtask_dispatched_after_upstream_merged(self):
        """dispatch_ready_subtasks must queue S2 once S1 is 'merged'."""
        import tempfile as _tmp
        from orchestrator.bin.dispatch import dispatch_ready_subtasks

        with _tmp.TemporaryDirectory() as d:
            root = Path(d)
            plan = self._make_plan()

            # S1 is already queued (in dispatch state)
            state_dir = root / "tasks" / "p1"
            state_dir.mkdir(parents=True)
            (state_dir / "dispatch-state.json").write_text(
                json.dumps({
                    "planId": "p1",
                    "dispatched": {
                        "S1": {"state": "queued", "queuedTaskId": "p1-S1", "queuedAt": 1}
                    },
                }),
                encoding="utf-8",
            )
            # Archive dirs
            (state_dir / "subtasks").mkdir()

            # S1's task in registry has status 'merged'
            registry_items = [
                {
                    "id": "p1-S1",
                    "status": "merged",
                    "metadata": {"planId": "p1", "subtaskId": "S1"},
                }
            ]

            queued = dispatch_ready_subtasks(plan, base_dir=root, registry_items=registry_items)
            self.assertTrue(queued, "S2 must be dispatched once S1 is merged")


if __name__ == "__main__":
    unittest.main()
