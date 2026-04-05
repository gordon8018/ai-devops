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


if __name__ == "__main__":
    unittest.main()
