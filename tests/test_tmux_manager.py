#!/usr/bin/env python3
"""Tests for tmux_manager.py - TmuxManager 测试 (20+ test cases)"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from tmux_manager import (
    TmuxManager,
    validate_agent,
    validate_task_id,
    validate_effort,
    validate_prompt_filename,
    validate_session_name,
)


class TestValidateAgent(unittest.TestCase):
    """Agent 参数验证测试 (7 cases)"""
    
    def test_valid_agent_claude(self):
        valid, err = validate_agent("claude")
        self.assertTrue(valid)

    def test_valid_agent_codex(self):
        valid, err = validate_agent("codex")
        self.assertTrue(valid)

    def test_empty_agent(self):
        valid, err = validate_agent("")
        self.assertFalse(valid)

    def test_invalid_agent(self):
        valid, err = validate_agent("invalid_agent")
        self.assertFalse(valid)

    def test_malicious_agent_injection(self):
        valid, err = validate_agent("claude; rm -rf /")
        self.assertFalse(valid)

    def test_malicious_agent_subshell(self):
        valid, err = validate_agent("codex$(whoami)")
        self.assertFalse(valid)

    def test_malicious_agent_backtick(self):
        valid, err = validate_agent("claude`id`")
        self.assertFalse(valid)


class TestValidateTaskId(unittest.TestCase):
    """Task ID 参数验证测试 (8 cases)"""
    
    def test_valid_task_id_simple(self):
        valid, err = validate_task_id("task-123")
        self.assertTrue(valid)

    def test_valid_task_id_underscore(self):
        valid, err = validate_task_id("task_456_test")
        self.assertTrue(valid)

    def test_valid_task_id_complex(self):
        valid, err = validate_task_id("my-task-id-789")
        self.assertTrue(valid)

    def test_empty_task_id(self):
        valid, err = validate_task_id("")
        self.assertFalse(valid)

    def test_task_id_with_semicolon(self):
        valid, err = validate_task_id("task; rm -rf /")
        self.assertFalse(valid)

    def test_task_id_with_subshell(self):
        valid, err = validate_task_id("task$(whoami)")
        self.assertFalse(valid)

    def test_task_id_with_backtick(self):
        valid, err = validate_task_id("task`id`")
        self.assertFalse(valid)

    def test_task_id_with_special_chars(self):
        valid, err = validate_task_id("task@#$%")
        self.assertFalse(valid)


class TestValidateEffort(unittest.TestCase):
    """Effort 参数验证测试 (6 cases)"""
    
    def test_valid_effort_low(self):
        valid, err = validate_effort("low")
        self.assertTrue(valid)

    def test_valid_effort_medium(self):
        valid, err = validate_effort("medium")
        self.assertTrue(valid)

    def test_valid_effort_high(self):
        valid, err = validate_effort("high")
        self.assertTrue(valid)

    def test_empty_effort(self):
        valid, err = validate_effort("")
        self.assertFalse(valid)

    def test_invalid_effort(self):
        valid, err = validate_effort("extreme")
        self.assertFalse(valid)

    def test_effort_case_sensitive(self):
        valid, err = validate_effort("HIGH")
        self.assertFalse(valid)


class TestValidatePromptFilename(unittest.TestCase):
    """Prompt filename 参数验证测试 (6 cases)"""
    
    def test_valid_filename_simple(self):
        valid, err = validate_prompt_filename("prompt.txt")
        self.assertTrue(valid)

    def test_valid_filename_with_path(self):
        valid, err = validate_prompt_filename("prompts/task.md")
        self.assertTrue(valid)

    def test_valid_filename_with_dots(self):
        valid, err = validate_prompt_filename("prompt.v1.txt")
        self.assertTrue(valid)

    def test_empty_filename(self):
        valid, err = validate_prompt_filename("")
        self.assertFalse(valid)

    def test_filename_path_traversal(self):
        valid, err = validate_prompt_filename("../../../etc/passwd")
        self.assertFalse(valid)

    def test_filename_relative_path_traversal(self):
        valid, err = validate_prompt_filename("folder/../../../etc/passwd")
        self.assertFalse(valid)


class TestValidateSessionName(unittest.TestCase):
    """Session name 参数验证测试 (6 cases)"""
    
    def test_valid_session_name_simple(self):
        valid, err = validate_session_name("my-session")
        self.assertTrue(valid)

    def test_valid_session_name_with_colon(self):
        valid, err = validate_session_name("session:window")
        self.assertTrue(valid)

    def test_valid_session_name_complex(self):
        valid, err = validate_session_name("agent-123_test:main")
        self.assertTrue(valid)

    def test_empty_session_name(self):
        valid, err = validate_session_name("")
        self.assertFalse(valid)

    def test_session_name_with_semicolon(self):
        valid, err = validate_session_name("session; rm -rf /")
        self.assertFalse(valid)

    def test_session_name_with_subshell(self):
        valid, err = validate_session_name("session$(whoami)")
        self.assertFalse(valid)


class TestTmuxManagerInit(unittest.TestCase):
    """TmuxManager 初始化测试 (3 cases)"""
    
    def test_init_valid_session_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = TmuxManager("valid-session", Path(tmpdir), "runner.sh")
            self.assertEqual(tm.session_name, "valid-session")

    def test_init_invalid_session_name_injection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                TmuxManager("session; rm -rf /", Path(tmpdir), "runner.sh")
            self.assertIn("Invalid session_name", str(ctx.exception))

    def test_init_invalid_session_name_subshell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(ValueError) as ctx:
                TmuxManager("session$(whoami)", Path(tmpdir), "runner.sh")
            self.assertIn("Invalid session_name", str(ctx.exception))


class TestTmuxManagerHealthCheck(unittest.TestCase):
    """TmuxManager 健康检查测试 (4 cases)"""
    
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tmux_manager.subprocess.run")
    def test_tmux_not_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm._tmux_available()
        self.assertFalse(result)

    @patch("tmux_manager.subprocess.run")
    def test_session_exists_true(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.check_session_exists()
        self.assertTrue(result)

    @patch("tmux_manager.subprocess.run")
    def test_session_exists_false(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="/usr/bin/tmux", stderr=""),
            MagicMock(returncode=1, stdout="", stderr=""),
        ]
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.check_session_exists()
        self.assertFalse(result)

    @patch("tmux_manager.subprocess.run")
    def test_check_health_no_windows(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="/usr/bin/tmux", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
            MagicMock(returncode=1, stdout="", stderr=""),
        ]
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.check_health()
        self.assertFalse(result)


class TestTmuxManagerSessionOperations(unittest.TestCase):
    """TmuxManager 会话操作测试 (5 cases)"""
    
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tmux_manager.subprocess.run")
    @patch("tmux_manager.time.sleep")
    def test_create_session_tmux_unavailable(self, mock_sleep, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.create_session()
        self.assertFalse(result)

    @patch("tmux_manager.subprocess.run")
    @patch("tmux_manager.time.sleep")
    def test_destroy_session_tmux_unavailable(self, mock_sleep, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.destroy_session()
        self.assertFalse(result)

    @patch("tmux_manager.subprocess.run")
    def test_list_sessions_tmux_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        sessions = tm.list_sessions()
        self.assertEqual(sessions, [])

    @patch("tmux_manager.subprocess.run")
    def test_run_command_tmux_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        success, stdout, stderr = tm.run_command_in_session("ls -la")
        self.assertFalse(success)

    @patch("tmux_manager.subprocess.run")
    def test_get_session_info_tmux_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        info = tm.get_session_info()
        self.assertIsNone(info)


class TestTmuxManagerRebuild(unittest.TestCase):
    """TmuxManager 会话重建安全测试 (6 cases)"""
    
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_rebuild_invalid_agent(self):
        tm = TmuxManager("test-session", self.base, "runner.sh")
        with self.assertRaises(ValueError) as ctx:
            tm.rebuild_session(
                agent="invalid_agent",
                task_id="task-123",
                model="gpt-5.3-codex",
                effort="high",
                prompt_filename="prompt.txt"
            )
        self.assertIn("Invalid agent", str(ctx.exception))

    def test_rebuild_invalid_task_id(self):
        tm = TmuxManager("test-session", self.base, "runner.sh")
        with self.assertRaises(ValueError) as ctx:
            tm.rebuild_session(
                agent="codex",
                task_id="task; rm -rf /",
                model="gpt-5.3-codex",
                effort="high",
                prompt_filename="prompt.txt"
            )
        self.assertIn("Invalid task_id", str(ctx.exception))

    def test_rebuild_invalid_effort(self):
        tm = TmuxManager("test-session", self.base, "runner.sh")
        with self.assertRaises(ValueError) as ctx:
            tm.rebuild_session(
                agent="codex",
                task_id="task-123",
                model="gpt-5.3-codex",
                effort="extreme",
                prompt_filename="prompt.txt"
            )
        self.assertIn("Invalid effort", str(ctx.exception))

    def test_rebuild_path_traversal_prompt(self):
        tm = TmuxManager("test-session", self.base, "runner.sh")
        with self.assertRaises(ValueError) as ctx:
            tm.rebuild_session(
                agent="codex",
                task_id="task-123",
                model="gpt-5.3-codex",
                effort="high",
                prompt_filename="../../../etc/passwd"
            )
        self.assertIn("Invalid prompt_filename", str(ctx.exception))

    @patch("tmux_manager.subprocess.run")
    def test_safe_rebuild_tmux_not_available(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="tmux not found")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        success, message = tm.safe_rebuild(
            agent="codex",
            task_id="task-123",
            model="gpt-5.3-codex",
            effort="high",
            prompt_filename="prompt.txt"
        )
        self.assertFalse(success)
        self.assertIn("tmux not available", message)

    @patch("tmux_manager.subprocess.run")
    def test_safe_rebuild_invalid_agent(self, mock_run):
        tm = TmuxManager("test-session", self.base, "runner.sh")
        success, message = tm.safe_rebuild(
            agent="invalid_agent",
            task_id="task-123",
            model="gpt-5.3-codex",
            effort="high",
            prompt_filename="prompt.txt"
        )
        self.assertFalse(success)
        self.assertFalse(success)


class TestTmuxManagerProperties(unittest.TestCase):
    """TmuxManager 属性测试 (3 cases)"""
    
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tmux_manager.subprocess.run")
    def test_session_exists_property(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.session_exists
        self.assertFalse(result)

    @patch("tmux_manager.subprocess.run")
    def test_is_healthy_property(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        tm = TmuxManager("test-session", self.base, "runner.sh")
        result = tm.is_healthy
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
