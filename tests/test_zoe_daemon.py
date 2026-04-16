#!/usr/bin/env python3
"""Tests for zoe-daemon.py - ZoeDaemon 测试 (10+ test cases)"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import importlib.util

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent

# Load zoe-daemon.py module (hyphen in filename requires special handling)
ZOE_DAEMON_PATH = BASE / "orchestrator" / "bin" / "zoe-daemon.py"


def load_zoe_daemon_module():
    """Load zoe-daemon.py as a module"""
    # Add orchestrator/bin to sys.path for imports
    bin_dir = str(BASE / "orchestrator" / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)
    
    spec = importlib.util.spec_from_file_location("zoe_daemon", ZOE_DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["zoe_daemon"] = module
    spec.loader.exec_module(module)
    return module


class TestSanitizeBranchComponent(unittest.TestCase):
    """分支名清理测试 (6 cases)"""
    
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_sanitize_simple(self):
        result = self.zoe_daemon.sanitize_branch_component("my-branch")
        self.assertEqual(result, "my-branch")

    def test_sanitize_removes_special_chars(self):
        result = self.zoe_daemon.sanitize_branch_component("my@branch#name")
        self.assertNotIn("@", result)
        self.assertNotIn("#", result)

    def test_sanitize_preserves_alnum_dash_underscore(self):
        result = self.zoe_daemon.sanitize_branch_component("my-branch_123")
        self.assertEqual(result, "my-branch_123")

    def test_sanitize_collapses_multiple_dashes(self):
        result = self.zoe_daemon.sanitize_branch_component("my--branch")
        self.assertNotIn("--", result)

    def test_sanitize_empty_returns_task(self):
        result = self.zoe_daemon.sanitize_branch_component("")
        self.assertEqual(result, "task")

    def test_sanitize_all_special_returns_task(self):
        result = self.zoe_daemon.sanitize_branch_component("@#$%")
        self.assertEqual(result, "task")


class TestTmuxAvailability(unittest.TestCase):
    """Tmux 可用性检查测试 (3 cases)"""
    
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_tmux_available_true(self):
        with patch("zoe_daemon.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/tmux"
            result = self.zoe_daemon.tmux_available()
            self.assertTrue(result)

    def test_tmux_available_false(self):
        with patch("zoe_daemon.shutil.which") as mock_which:
            mock_which.return_value = None
            result = self.zoe_daemon.tmux_available()
            self.assertFalse(result)

    def test_tmux_has_session_true(self):
        with patch("zoe_daemon.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = self.zoe_daemon.tmux_has("test-session")
            self.assertTrue(result)


class TestRunnerForAgent(unittest.TestCase):
    """Agent runner 路径解析测试 (3 cases)"""
    
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_runner_for_codex(self):
        result = self.zoe_daemon.runner_for_agent("codex")
        self.assertIn("codex", str(result).lower())

    def test_runner_for_claude(self):
        result = self.zoe_daemon.runner_for_agent("claude")
        self.assertIn("claude", str(result).lower())

    def test_runner_for_invalid_agent(self):
        with self.assertRaises(RuntimeError):
            self.zoe_daemon.runner_for_agent("invalid_agent")


class TestResolveBranch(unittest.TestCase):
    """分支名解析测试 (3 cases)"""
    
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_resolve_branch_default(self):
        task = {"id": "task-123", "repo": "test-repo"}
        result = self.zoe_daemon.resolve_branch(task)
        self.assertIn("feat/", result)

    def test_resolve_branch_with_plan_id(self):
        task = {
            "id": "task-456",
            "repo": "test-repo",
            "metadata": {
                "planId": "plan-abc",
                "worktreeStrategy": "shared"
            }
        }
        result = self.zoe_daemon.resolve_branch(task)
        self.assertIn("plan/", result)

    def test_resolve_branch_sanitizes_id(self):
        task = {"id": "task@123#test", "repo": "test-repo"}
        result = self.zoe_daemon.resolve_branch(task)
        self.assertNotIn("@", result)
        self.assertNotIn("#", result)


class TestShCommand(unittest.TestCase):
    """Shell 命令执行测试 (3 cases)"""
    
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_sh_success(self):
        with patch("zoe_daemon.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
            result = self.zoe_daemon.sh(["echo", "hello"])
            self.assertEqual(result, "output")

    def test_sh_failure_raises(self):
        with patch("zoe_daemon.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            with self.assertRaises(RuntimeError):
                self.zoe_daemon.sh(["false"], check=True)

    def test_sh_failure_no_check(self):
        with patch("zoe_daemon.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
            result = self.zoe_daemon.sh(["false"], check=False)
            self.assertEqual(result, "")


class TestMainBootstrap(unittest.TestCase):
    def setUp(self):
        self.zoe_daemon = load_zoe_daemon_module()

    def test_main_configures_control_plane_dual_write(self):
        consumer = MagicMock()
        consumer.list_queue_files.return_value = []
        control_plane_store = MagicMock()

        with patch.object(self.zoe_daemon, "init_db") as mock_init_db, \
             patch.object(self.zoe_daemon, "configure_control_plane_dual_write", return_value=control_plane_store) as mock_configure, \
             patch.object(self.zoe_daemon, "configure_runtime_persistence") as mock_configure_runtime_persistence, \
             patch.object(self.zoe_daemon, "start_api_server"), \
             patch.object(self.zoe_daemon, "ProcessGuardian") as mock_guardian_cls, \
             patch.object(self.zoe_daemon, "ReleaseWorker") as mock_release_worker_cls, \
             patch.object(self.zoe_daemon, "IncidentWorker") as mock_incident_worker_cls, \
             patch.object(self.zoe_daemon, "get_event_manager") as mock_get_event_manager, \
             patch.object(self.zoe_daemon, "QueueConsumer", return_value=consumer), \
             patch.object(self.zoe_daemon, "queue_dir", return_value=Path(tempfile.mkdtemp())), \
             patch.object(self.zoe_daemon, "get_global_scheduler") as mock_get_scheduler, \
             patch.object(self.zoe_daemon, "get_running_tasks", return_value=[]), \
             patch.object(self.zoe_daemon, "time") as mock_time:
            mock_guardian_cls.return_value = MagicMock(check_all=MagicMock(return_value={}))
            release_worker = MagicMock()
            mock_release_worker_cls.return_value = release_worker
            incident_worker = MagicMock()
            mock_incident_worker_cls.return_value = incident_worker
            mock_get_event_manager.return_value = MagicMock()
            mock_get_scheduler.return_value = MagicMock(schedule=MagicMock(return_value=[]))
            mock_time.time.return_value = 999999999
            mock_time.sleep.side_effect = KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                self.zoe_daemon.main()

        mock_init_db.assert_called_once()
        mock_configure.assert_called_once_with()
        mock_configure_runtime_persistence.assert_called_once_with(store=control_plane_store)
        release_worker.start.assert_called_once_with()
        incident_worker.start.assert_called_once_with()

    def test_main_moves_invalid_prepare_failures_to_dead_letter(self):
        consumer = MagicMock()
        control_plane_store = MagicMock()
        queue_root = Path(tempfile.mkdtemp())
        queue_file = queue_root / "task-bad.json"
        queue_file.write_text("{}", encoding="utf-8")
        consumer.list_queue_files.return_value = [queue_file]
        consumer.load_task.return_value = {
            "id": "task-bad",
            "repo": "acme/platform",
            "title": "Bad task",
            "description": "Will fail during prepare",
        }

        with patch.object(self.zoe_daemon, "init_db"), \
             patch.object(self.zoe_daemon, "configure_control_plane_dual_write", return_value=control_plane_store), \
             patch.object(self.zoe_daemon, "configure_runtime_persistence"), \
             patch.object(self.zoe_daemon, "start_api_server"), \
             patch.object(self.zoe_daemon, "ProcessGuardian") as mock_guardian_cls, \
             patch.object(self.zoe_daemon, "ReleaseWorker") as mock_release_worker_cls, \
             patch.object(self.zoe_daemon, "IncidentWorker") as mock_incident_worker_cls, \
             patch.object(self.zoe_daemon, "get_event_manager") as mock_get_event_manager, \
             patch.object(self.zoe_daemon, "QueueConsumer", return_value=consumer), \
             patch.object(self.zoe_daemon, "queue_dir", return_value=queue_root), \
             patch.object(self.zoe_daemon, "get_global_scheduler") as mock_get_scheduler, \
             patch.object(self.zoe_daemon, "get_running_tasks", return_value=[]), \
             patch.object(self.zoe_daemon, "get_task", return_value=None), \
             patch.object(self.zoe_daemon, "spawn_agent", side_effect=ValueError("prepare failed")), \
             patch.object(self.zoe_daemon, "time") as mock_time:
            mock_guardian_cls.return_value = MagicMock(check_all=MagicMock(return_value={}))
            mock_release_worker_cls.return_value = MagicMock()
            mock_incident_worker_cls.return_value = MagicMock()
            mock_get_event_manager.return_value = MagicMock()
            mock_get_scheduler.return_value = MagicMock(schedule=MagicMock(return_value=[]))
            mock_time.time.return_value = 999999999
            mock_time.sleep.side_effect = KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                self.zoe_daemon.main()

        dead_file = queue_root / "dead" / "task-bad.json"
        err_file = queue_root / "dead" / "task-bad.err"
        self.assertTrue(dead_file.exists(), "invalid queue task should be moved to dead-letter")
        self.assertTrue(err_file.exists(), "dead-letter must include an .err sidecar")
        self.assertFalse(queue_file.exists(), "original queue file should be removed after dead-lettering")


if __name__ == "__main__":
    unittest.main()
