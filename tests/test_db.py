#!/usr/bin/env python3
"""
Tests for db.py (SQLite Tracker)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR.parent / "orchestrator" / "bin"))

# Import after path setup
from db import (
    get_db, init_db, insert_task, get_task, get_running_tasks,
    get_all_tasks, update_task, update_task_status, delete_task,
    count_running_tasks, get_task_by_branch, DB_PATH,
)


def cleanup_db():
    """Delete all records from database"""
    with get_db() as conn:
        conn.execute("DELETE FROM agent_tasks")
        conn.commit()


class TestDatabaseInit(unittest.TestCase):
    def setUp(self):
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
