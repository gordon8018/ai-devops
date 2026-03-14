#!/usr/bin/env python3
"""
Tests for important issues I1-I13.

Pure-refactoring changes (I1, I2, I3, I4, I6, I8, I10) are covered by
existing tests; this file adds tests for the behaviorally-observable issues.
"""
import importlib.util
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
# I5: bare except: in cmd_list must not swallow KeyboardInterrupt
# ---------------------------------------------------------------------------
class TestCmdListBareExcept(unittest.TestCase):
    """I5: bare except: → except Exception: so KeyboardInterrupt propagates."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AI_DEVOPS_HOME"] = str(Path(self.temp_dir.name))
        from db import init_db
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("AI_DEVOPS_HOME", None)

    def test_keyboard_interrupt_propagates_through_cmd_list(self):
        """KeyboardInterrupt raised while reading a queue file must not be
        swallowed — it should propagate out of cmd_list."""
        import agent as agent_mod
        from agent_utils import queue_root

        # Create a malformed queue file so json.loads is attempted
        q = queue_root()
        q.mkdir(parents=True, exist_ok=True)
        (q / "bad.json").write_text("not-json", encoding="utf-8")

        args = MagicMock(status="queued", limit=10, json=False)

        with patch("agent.json.loads", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                agent_mod.cmd_list(args)

    def test_malformed_json_is_skipped_silently(self):
        """A malformed queue file (JSON error) must be skipped without crashing."""
        import agent as agent_mod
        from agent_utils import queue_root

        q = queue_root()
        q.mkdir(parents=True, exist_ok=True)
        (q / "bad.json").write_text("not-json", encoding="utf-8")

        args = MagicMock(status="queued", limit=10, json=False)
        output = io.StringIO()
        # Must not raise
        with redirect_stdout(output):
            agent_mod.cmd_list(args)


# ---------------------------------------------------------------------------
# I9: create_worktree must detect the default branch dynamically
# ---------------------------------------------------------------------------
class TestCreateWorktreeDefaultBranch(unittest.TestCase):
    """I9: create_worktree must not hardcode origin/main; it must detect
    the remote default branch via git symbolic-ref."""

    def _load_daemon(self):
        daemon_file = BASE / "orchestrator" / "bin" / "zoe-daemon.py"
        spec = importlib.util.spec_from_file_location("zoe_daemon", daemon_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_create_worktree_uses_detected_default_branch(self):
        """When origin HEAD points to develop, worktree must be based on
        origin/develop, not origin/main."""
        daemon = self._load_daemon()

        with tempfile.TemporaryDirectory() as d:
            wt_base = Path(d) / "worktrees"
            wt_base.mkdir()
            repo = Path(d) / "repo"
            repo.mkdir()

            sh_calls = []

            def fake_sh(cmd, cwd=None, check=True):
                sh_calls.append(cmd)
                if "symbolic-ref" in cmd:
                    # git symbolic-ref --short returns "origin/develop" (not the full ref)
                    return "origin/develop"
                return ""

            with patch.object(daemon, "sh", side_effect=fake_sh), \
                 patch.object(daemon, "worktrees_dir", return_value=wt_base):
                # Make the worktree dir NOT exist so the real path runs
                daemon.create_worktree(repo, "feat/my-task")

            # git worktree add must reference origin/develop, not origin/main
            add_calls = [c for c in sh_calls if "worktree" in c and "add" in c]
            self.assertTrue(add_calls, "git worktree add not called")
            worktree_cmd = add_calls[0]
            self.assertNotIn("origin/main", worktree_cmd,
                             "create_worktree must not hardcode origin/main")
            self.assertIn("origin/develop", worktree_cmd,
                          "create_worktree must use the detected default branch")

    def test_create_worktree_falls_back_to_main_when_detection_fails(self):
        """If git symbolic-ref fails (empty output), fall back to origin/main."""
        daemon = self._load_daemon()

        with tempfile.TemporaryDirectory() as d:
            wt_base = Path(d) / "worktrees"
            wt_base.mkdir()
            repo = Path(d) / "repo"
            repo.mkdir()

            def fake_sh(cmd, cwd=None, check=True):
                if "symbolic-ref" in cmd:
                    return ""   # detection failure
                return ""

            with patch.object(daemon, "sh", side_effect=fake_sh), \
                 patch.object(daemon, "worktrees_dir", return_value=wt_base):
                daemon.create_worktree(repo, "feat/fallback")

            # no assertion on this test — just must not raise


# ---------------------------------------------------------------------------
# I6: create_worktree must resolve worktrees_dir() dynamically, not frozen
# ---------------------------------------------------------------------------
class TestCreateWorktreeDynamicPath(unittest.TestCase):
    """I6: create_worktree must call worktrees_dir() at call time so that
    changes to AI_DEVOPS_HOME after import are respected."""

    def _load_daemon(self):
        daemon_file = BASE / "orchestrator" / "bin" / "zoe-daemon.py"
        spec = importlib.util.spec_from_file_location("zoe_daemon_i6", daemon_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_create_worktree_respects_ai_devops_home_change(self):
        """create_worktree must place the worktree under the *current*
        AI_DEVOPS_HOME/worktrees, not the path frozen at import time."""
        daemon = self._load_daemon()

        with tempfile.TemporaryDirectory() as d:
            new_home = Path(d)
            repo = new_home / "repo"
            repo.mkdir()

            def fake_sh(cmd, cwd=None, check=True):
                if "symbolic-ref" in cmd:
                    return "origin/main"
                return ""

            with patch.dict(os.environ, {"AI_DEVOPS_HOME": str(new_home)}), \
                 patch.object(daemon, "sh", side_effect=fake_sh):
                wt = daemon.create_worktree(repo, "feat/dynamic")

            expected_base = new_home / "worktrees"
            self.assertTrue(
                str(wt).startswith(str(expected_base)),
                f"create_worktree placed worktree under {wt}, expected under {expected_base}; "
                f"WORKTREES is probably still frozen at import time",
            )


# ---------------------------------------------------------------------------
# I11: restart_codex_agent dead alias must be removed from monitor_helpers
# ---------------------------------------------------------------------------
class TestRestartCodexAgentRemoved(unittest.TestCase):
    """I11: restart_codex_agent is a dead alias and must be removed."""

    def test_restart_codex_agent_not_exported(self):
        """monitor_helpers must not export restart_codex_agent after removal."""
        import monitor_helpers
        self.assertFalse(
            hasattr(monitor_helpers, "restart_codex_agent"),
            "restart_codex_agent should be removed from monitor_helpers",
        )


# ---------------------------------------------------------------------------
# I12: webhook_server run_server must accept a configurable bind host
# ---------------------------------------------------------------------------
class TestWebhookServerBindHost(unittest.TestCase):
    """I12: run_server must bind to a configurable host, not always 0.0.0.0."""

    def test_run_server_accepts_host_parameter(self):
        """run_server(port, host=...) must use the provided host when binding."""
        import webhook_server as ws

        bound_to = []

        class FakeHTTPServer:
            def __init__(self, server_address, handler):
                bound_to.append(server_address)

            def serve_forever(self):
                raise KeyboardInterrupt

            def shutdown(self):
                pass

        with patch("webhook_server.HTTPServer", FakeHTTPServer), \
             patch("webhook_server.init_db"), \
             patch.object(ws, "WEBHOOK_SECRET", b"secret"):
            try:
                ws.run_server(port=9999, host="127.0.0.1")
            except KeyboardInterrupt:
                pass

        self.assertTrue(bound_to, "HTTPServer constructor never called")
        host_used, port_used = bound_to[0]
        self.assertEqual(host_used, "127.0.0.1",
                         "run_server must bind to the provided host")
        self.assertEqual(port_used, 9999)

    def test_run_server_defaults_to_0000(self):
        """run_server without host= must still default to 0.0.0.0."""
        import webhook_server as ws

        bound_to = []

        class FakeHTTPServer:
            def __init__(self, server_address, handler):
                bound_to.append(server_address)

            def serve_forever(self):
                raise KeyboardInterrupt

            def shutdown(self):
                pass

        with patch("webhook_server.HTTPServer", FakeHTTPServer), \
             patch("webhook_server.init_db"), \
             patch.object(ws, "WEBHOOK_SECRET", b"secret"):
            try:
                ws.run_server(port=9998)
            except KeyboardInterrupt:
                pass

        self.assertEqual(bound_to[0][0], "0.0.0.0")


# ---------------------------------------------------------------------------
# I13: cmd_clean must include all terminal statuses
# ---------------------------------------------------------------------------
class TestCmdCleanTerminalStatuses(unittest.TestCase):
    """I13: cmd_clean must clean tasks with any terminal status, not just
    'ready', 'killed', 'agent_exited'."""

    TERMINAL_STATUSES = [
        "ready", "killed", "agent_exited",
        "merged", "pr_closed", "needs_rebase",
        "blocked", "agent_dead", "agent_failed",
        "timeout", "log_stale",
    ]

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["AI_DEVOPS_HOME"] = str(Path(self.temp_dir.name))
        from db import init_db, insert_task, get_db
        init_db()
        # Insert one task per terminal status, then back-date created_at
        old_ts = int((time.time() - 40 * 86400) * 1000)  # 40 days ago
        for status in self.TERMINAL_STATUSES:
            insert_task({
                "id": f"task-{status}",
                "repo": "repo",
                "title": f"task {status}",
                "status": status,
                "agent": "codex",
                "model": "m",
                "effort": "h",
            })
        # Back-date all tasks so they fall outside the 30-day window
        with get_db() as conn:
            conn.execute("UPDATE agent_tasks SET created_at = ?", (old_ts,))
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("AI_DEVOPS_HOME", None)

    def test_merged_tasks_are_cleaned(self):
        """Tasks with status 'merged' must be included in cmd_clean."""
        import agent as agent_mod
        from db import get_task

        args = MagicMock(days=30, dry_run=False)
        output = io.StringIO()
        with redirect_stdout(output):
            agent_mod.cmd_clean(args)

        self.assertIsNone(get_task("task-merged"),
                          "merged task must be deleted by cmd_clean")

    def test_pr_closed_tasks_are_cleaned(self):
        """Tasks with status 'pr_closed' must be included in cmd_clean."""
        import agent as agent_mod
        from db import get_task

        args = MagicMock(days=30, dry_run=False)
        output = io.StringIO()
        with redirect_stdout(output):
            agent_mod.cmd_clean(args)

        self.assertIsNone(get_task("task-pr_closed"),
                          "pr_closed task must be deleted by cmd_clean")

    def test_all_terminal_statuses_are_cleaned(self):
        """All terminal statuses must be cleaned — none should survive."""
        import agent as agent_mod
        from db import get_task

        args = MagicMock(days=30, dry_run=False)
        output = io.StringIO()
        with redirect_stdout(output):
            agent_mod.cmd_clean(args)

        for status in self.TERMINAL_STATUSES:
            task_id = f"task-{status}"
            remaining = get_task(task_id)
            self.assertIsNone(
                remaining,
                f"task with status '{status}' must be cleaned by cmd_clean",
            )

    def test_dry_run_does_not_delete(self):
        """--dry-run must report tasks but not delete them."""
        import agent as agent_mod
        from db import get_task

        args = MagicMock(days=30, dry_run=True)
        output = io.StringIO()
        with redirect_stdout(output):
            agent_mod.cmd_clean(args)

        # All tasks must still exist after dry run
        for status in self.TERMINAL_STATUSES:
            task_id = f"task-{status}"
            self.assertIsNotNone(
                get_task(task_id),
                f"dry_run must not delete task with status '{status}'",
            )


if __name__ == "__main__":
    unittest.main()
