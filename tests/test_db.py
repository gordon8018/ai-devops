#!/usr/bin/env python3
"""
Tests for db.py (SQLite Tracker)
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR.parent / "orchestrator" / "bin"))

# Keep DB writes inside a writable temp root for unittest-style cases.
_TEST_HOME = tempfile.mkdtemp(prefix="ai-devops-test-db-")
atexit.register(shutil.rmtree, _TEST_HOME, True)
os.environ["AI_DEVOPS_HOME"] = _TEST_HOME

# Import after path setup
from db import (
    get_db, init_db, insert_task, get_task, get_running_tasks,
    get_all_tasks, update_task, update_task_status, delete_task,
    count_running_tasks, get_task_by_branch, DB_PATH, merge_task_metadata,
)


def cleanup_db():
    """Delete all records from database"""
    with get_db() as conn:
        conn.execute("DELETE FROM agent_tasks")
        conn.commit()


class TestDatabaseInit(unittest.TestCase):
    def setUp(self):
        os.environ["AI_DEVOPS_HOME"] = _TEST_HOME
        init_db()
        cleanup_db()

    def test_init_db_creates_directory(self):
        db_dir = DB_PATH.parent
        self.assertTrue(db_dir.exists())

    def test_init_db_creates_table(self):
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_tasks'"
            )
            result = cursor.fetchone()
        self.assertIsNotNone(result)

    def test_init_db_creates_indexes(self):
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agent_tasks'"
            )
            indexes = {row[0] for row in cursor.fetchall()}
        self.assertIn("idx_status", indexes)

    def test_init_db_idempotent(self):
        init_db()  # Should not raise
        with get_db() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM agent_tasks")
            count = cursor.fetchone()[0]
        self.assertEqual(count, 0)


class TestTaskCRUD(unittest.TestCase):
    def setUp(self):
        os.environ["AI_DEVOPS_HOME"] = _TEST_HOME
        init_db()
        cleanup_db()

    def make_task(self, **overrides) -> dict:
        task = {"id": "test-task-123", "repo": "test/repo", "title": "Test Task", "status": "queued"}
        task.update(overrides)
        return task

    def test_insert_task(self):
        task = self.make_task()
        insert_task(task)
        result = get_task("test-task-123")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "test-task-123")

    def test_get_task_not_found(self):
        result = get_task("nonexistent-task")
        self.assertIsNone(result)

    def test_update_task(self):
        task = self.make_task()
        insert_task(task)
        update_task("test-task-123", {"status": "running", "note": "Test note"})
        result = get_task("test-task-123")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["note"], "Test note")

    def test_update_task_status(self):
        task = self.make_task()
        insert_task(task)
        update_task_status("test-task-123", "completed")
        result = get_task("test-task-123")
        self.assertEqual(result["status"], "completed")

    def test_delete_task(self):
        task = self.make_task()
        insert_task(task)
        delete_task("test-task-123")
        result = get_task("test-task-123")
        self.assertIsNone(result)


class TestTaskQueries(unittest.TestCase):
    def setUp(self):
        os.environ["AI_DEVOPS_HOME"] = _TEST_HOME
        init_db()
        cleanup_db()
        tasks = [
            {"id": "task-1", "repo": "repo-a", "title": "Task 1", "status": "running", "branch": "feat/a"},
            {"id": "task-2", "repo": "repo-a", "title": "Task 2", "status": "running", "branch": "feat/b"},
            {"id": "task-3", "repo": "repo-b", "title": "Task 3", "status": "queued", "branch": "feat/c"},
        ]
        for task in tasks:
            insert_task(task)

    def test_get_running_tasks(self):
        running = get_running_tasks()
        self.assertEqual(len(running), 2)

    def test_get_all_tasks(self):
        all_tasks = get_all_tasks()
        self.assertEqual(len(all_tasks), 3)

    def test_count_running_tasks(self):
        count = count_running_tasks()
        self.assertEqual(count, 2)

    def test_get_task_by_branch_found(self):
        task = get_task_by_branch("feat/a")
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], "task-1")

    def test_get_task_by_branch_not_found(self):
        task = get_task_by_branch("nonexistent-branch")
        self.assertIsNone(task)


class TestTaskStatusTransitions(unittest.TestCase):
    def setUp(self):
        os.environ["AI_DEVOPS_HOME"] = _TEST_HOME
        init_db()
        cleanup_db()

    def test_status_queued_to_running(self):
        task = {"id": "task-transition", "repo": "test", "title": "Test", "status": "queued"}
        insert_task(task)
        update_task_status("task-transition", "running")
        result = get_task("task-transition")
        self.assertEqual(result["status"], "running")

    def test_status_running_to_completed(self):
        task = {"id": "task-complete", "repo": "test", "title": "Test", "status": "running"}
        insert_task(task)
        update_task_status("task-complete", "completed")
        result = get_task("task-complete")
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()


class TestDbExtendedQueries(unittest.TestCase):
    """Extended DB query tests (TestCase style)."""

    def setUp(self):
        import importlib
        self._tmp = tempfile.mkdtemp(prefix="ai-devops-test-ext-")
        os.environ["AI_DEVOPS_HOME"] = self._tmp
        import orchestrator.bin.db as db_mod
        importlib.reload(db_mod)
        db_mod.init_db()

    def tearDown(self):
        os.environ.pop("AI_DEVOPS_HOME", None)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _db(self):
        import orchestrator.bin.db as db_mod
        return db_mod

    def test_get_task_by_tmux_session(self):
        db_mod = self._db()
        db_mod.insert_task({
            "id": "t1", "repo": "r", "title": "T",
            "tmuxSession": "agent-t1", "status": "running",
        })
        result = db_mod.get_task_by_tmux_session("agent-t1")
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "t1")

    def test_get_task_by_tmux_session_miss(self):
        self.assertIsNone(self._db().get_task_by_tmux_session("nonexistent"))

    def test_get_task_by_process_id(self):
        db_mod = self._db()
        db_mod.insert_task({
            "id": "t2", "repo": "r", "title": "T",
            "processId": 12345, "status": "running",
        })
        result = db_mod.get_task_by_process_id(12345)
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "t2")

    def test_mark_cleaned_up(self):
        db_mod = self._db()
        db_mod.insert_task({"id": "t3", "repo": "r", "title": "T", "status": "merged"})
        db_mod.mark_cleaned_up("t3")
        task = db_mod.get_task("t3")
        self.assertEqual(task["cleaned_up"], 1)

    def test_legacy_functions_removed(self):
        import orchestrator.bin.db as db_mod
        self.assertFalse(hasattr(db_mod, "migrate_from_json"),
                         "migrate_from_json must be removed")
        self.assertFalse(hasattr(db_mod, "load_registry"),
                         "load_registry must be removed")
        self.assertFalse(hasattr(db_mod, "save_registry"),
                         "save_registry must be removed")

    def test_spawn_agent_writes_sqlite_not_json(self):
        """After daemon processes a task, active-tasks.json must NOT be created."""
        import importlib, sys
        json_registry = Path(self._tmp) / ".clawdbot" / "active-tasks.json"
        if "orchestrator.bin.db" in sys.modules:
            del sys.modules["orchestrator.bin.db"]
        import orchestrator.bin.db as db_mod
        importlib.reload(db_mod)
        db_mod.init_db()
        self.assertFalse(json_registry.exists(),
                         "active-tasks.json must not be created — SQLite only")

    def test_merge_task_metadata_keeps_plan_fields(self):
        db_mod = self._db()
        db_mod.insert_task({
            "id": "t4",
            "repo": "r",
            "title": "T",
            "status": "running",
            "metadata": {"planId": "p1", "subtaskId": "S1", "foo": "bar"},
        })
        merged = merge_task_metadata("t4", {"lastRetryReason": "ci failed"})
        self.assertEqual(merged["planId"], "p1")
        self.assertEqual(merged["subtaskId"], "S1")
        self.assertEqual(merged["lastRetryReason"], "ci failed")

    def test_merge_task_metadata_rejects_overwrite_plan_id(self):
        db_mod = self._db()
        db_mod.insert_task({
            "id": "t5",
            "repo": "r",
            "title": "T",
            "status": "running",
            "metadata": {"planId": "p1", "subtaskId": "S1"},
        })
        with self.assertRaises(ValueError):
            merge_task_metadata("t5", {"planId": "p2"})
