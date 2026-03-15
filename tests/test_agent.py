#!/usr/bin/env python3
"""
Tests for agent.py - Fixed Version
"""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from agent import cmd_init, cmd_spawn, cmd_list, cmd_status, cmd_retry
from agent_utils import generate_task_id, print_table, format_timestamp, print_task_detail
from db import init_db, get_task, get_all_tasks, update_task


class TestTaskIdGeneration(unittest.TestCase):
    def test_generate_task_id_format(self):
        task_id = generate_task_id("test/repo", "Fix login bug")
        self.assertTrue(task_id[0].isdigit())
        self.assertIn("test-repo", task_id)
        self.assertIn("fix-login-bug", task_id)

    def test_generate_task_id_with_slash(self):
        task_id = generate_task_id("org/repo", "Task")
        self.assertIn("org-repo", task_id)

    def test_generate_task_id_special_chars(self):
        task_id = generate_task_id("test/repo", "Fix bug: <timeout>")
        self.assertNotIn("<", task_id)
        self.assertNotIn(">", task_id)


class TestFormatting(unittest.TestCase):
    def test_format_timestamp(self):
        now = int(time.time() * 1000)
        formatted = format_timestamp(now)
        self.assertIn("-", formatted)
        self.assertIn(":", formatted)

    def test_print_table_empty(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_table([])
        result = output.getvalue()
        self.assertIn("No tasks found", result)

    def test_print_table_with_data(self):
        tasks = [
            {"id": "task-1", "status": "running", "repo": "test", "title": "Task 1"},
        ]
        output = io.StringIO()
        with redirect_stdout(output):
            print_table(tasks, columns=["id", "status", "title"])
        result = output.getvalue()
        self.assertIn("ID", result)
        self.assertIn("task-1", result)

    def test_print_task_detail(self):
        task = {"id": "test-task", "repo": "test/repo", "title": "Test Task", "status": "running"}
        output = io.StringIO()
        with redirect_stdout(output):
            print_task_detail(task)
        result = output.getvalue()
        self.assertIn("test-task", result)
        self.assertIn("Test Task", result)


class TestAgentCommands(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()
        # 清理已有任务
        from db import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM agent_tasks")
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    def test_cmd_init(self):
        args = MagicMock()
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_init(args)
        result = output.getvalue()
        self.assertIn("Database initialized", result)

    def test_cmd_spawn(self):
        args = MagicMock(
            repo="test/repo", title="Test Task",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="Test description", files=None,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_spawn(args)
        result = output.getvalue()
        self.assertIn("Task spawned", result)
        
        all_tasks = get_all_tasks()
        self.assertEqual(len(all_tasks), 1)

    def test_cmd_list(self):
        spawn_args = MagicMock(
            repo="test/repo", title="Test Task",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="", files=None,
        )
        cmd_spawn(spawn_args)
        
        list_args = MagicMock(status=None, limit=10)
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_list(list_args)
        result = output.getvalue()
        self.assertIn("test/repo", result)

    def test_cmd_status(self):
        spawn_args = MagicMock(
            repo="test/repo", title="Test Task",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="", files=None,
        )
        cmd_spawn(spawn_args)
        
        all_tasks = get_all_tasks()
        task_id = all_tasks[0]["id"]
        
        status_args = MagicMock(task_id=task_id)
        output = io.StringIO()
        with redirect_stdout(output):
            cmd_status(status_args)
        result = output.getvalue()
        self.assertIn(task_id, result)


class TestAgentSpawnEdgeCases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()
        from db import get_db
        with get_db() as conn:
            conn.execute("DELETE FROM agent_tasks")
            conn.commit()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    def test_cmd_spawn_default_values(self):
        args = MagicMock(
            repo="test/repo", title="Test",
            agent=None, model=None, effort=None,
            description="", files=None,
        )
        cmd_spawn(args)
        all_tasks = get_all_tasks()
        task = all_tasks[0]
        self.assertEqual(task["agent"], "codex")
        self.assertEqual(task["model"], "gpt-5.3-codex")

    def test_cmd_spawn_creates_queue_file(self):
        args = MagicMock(
            repo="test/repo", title="Test",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="", files=None,
        )
        cmd_spawn(args)
        queue_dir = self.base / "orchestrator" / "queue"
        queue_files = list(queue_dir.glob("*.json"))
        self.assertGreater(len(queue_files), 0)

    def test_cmd_retry_requires_force_for_non_retry_status(self):
        args = MagicMock(
            repo="test/repo", title="Retry Me",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="", files=None,
        )
        cmd_spawn(args)
        task = get_all_tasks()[0]
        retry_args = MagicMock(task_id=task["id"], force=False)
        with self.assertRaises(SystemExit):
            cmd_retry(retry_args)

    def test_cmd_retry_force_requeues_task(self):
        args = MagicMock(
            repo="test/repo", title="Retry Force",
            agent="codex", model="gpt-5.3-codex", effort="medium",
            description="", files=None,
        )
        cmd_spawn(args)
        task = get_all_tasks()[0]
        update_task(task["id"], {"status": "running", "attempts": 2})

        retry_args = MagicMock(task_id=task["id"], force=True)
        cmd_retry(retry_args)

        updated = get_task(task["id"])
        self.assertEqual(updated["status"], "queued")
        self.assertEqual(updated["attempts"], 0)
        queue_files = list((self.base / "orchestrator" / "queue").glob("*.json"))
        self.assertGreaterEqual(len(queue_files), 1)


if __name__ == "__main__":
    unittest.main()


def test_plan_status_command_help():
    """Smoke test: plan-status subcommand is registered."""
    import subprocess, sys, pathlib
    repo_root = str(pathlib.Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "orchestrator/bin/agent.py", "plan-status", "--help"],
        capture_output=True, text=True,
        cwd=repo_root
    )
    assert result.returncode == 0
    assert "plan_id" in result.stdout or "plan-status" in result.stdout

def test_plans_command_help():
    """Smoke test: plans subcommand is registered."""
    import subprocess, sys, pathlib
    repo_root = str(pathlib.Path(__file__).parent.parent)
    result = subprocess.run(
        [sys.executable, "orchestrator/bin/agent.py", "plans", "--help"],
        capture_output=True, text=True,
        cwd=repo_root
    )
    assert result.returncode == 0
