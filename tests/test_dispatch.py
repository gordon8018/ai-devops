#!/usr/bin/env python3
"""
Tests for dispatch.py - Fixed Version
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.bin.dispatch import (
    default_base_dir, queue_dir, tasks_dir, plan_dir,
    subtask_archive_path, dispatch_state_path, execution_task_id,
    load_dispatch_state, save_dispatch_state,
    ready_subtask_ids, topologically_sorted_subtask_ids,
    build_execution_task, archive_subtasks, update_subtask_archive,
    dispatch_ready_subtasks,
)
from orchestrator.bin.plan_schema import Plan, Subtask


def make_plan(**overrides) -> Plan:
    """Helper to create valid Plan"""
    payload = {
        "planId": "test-plan",
        "repo": "test/repo",
        "title": "Test",
        "requestedBy": "user",
        "requestedAt": 1234567890,
        "objective": "Test objective",
        "routing": {"agent": "codex", "model": "gpt-5", "effort": "medium"},
        "version": "1.0",
        "subtasks": [
            {
                "id": "S1",
                "title": "Subtask 1",
                "description": "Test description",
                "worktreeStrategy": "isolated",
                "dependsOn": [],
                "filesHint": [],
                "prompt": "Test prompt",
            },
        ],
    }
    if "subtasks" in overrides:
        for st in overrides["subtasks"]:
            if "worktreeStrategy" not in st:
                st["worktreeStrategy"] = "isolated"
            if "filesHint" not in st:
                st["filesHint"] = []
            if "prompt" not in st:
                st["prompt"] = "Test"
            if "description" not in st:
                st["description"] = "Test description"
    payload.update(overrides)
    return Plan.from_dict(payload)


class TestPathHelpers(unittest.TestCase):
    def test_default_base_dir(self):
        with patch.dict(os.environ, {"AI_DEVOPS_HOME": "/custom/path"}):
            result = default_base_dir()
        self.assertEqual(result, Path("/custom/path"))

    def test_queue_dir(self):
        base = Path("/test/base")
        result = queue_dir(base)
        self.assertEqual(result, base / "orchestrator" / "queue")

    def test_plan_dir(self):
        base = Path("/test/base")
        plan = make_plan(planId="test-plan-123")
        result = plan_dir(plan, base)
        self.assertEqual(result, base / "tasks" / "test-plan-123")


class TestExecutionTaskId(unittest.TestCase):
    def test_execution_task_id_format(self):
        plan = make_plan(planId="plan-123", subtasks=[{"id": "S1", "title": "Test"}])
        subtask = plan.subtasks[0]
        result = execution_task_id(plan, subtask)
        self.assertEqual(result, "plan-123-S1")


class TestDispatchState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.plan = make_plan()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_dispatch_state_not_exists(self):
        result = load_dispatch_state(self.plan, self.base)
        self.assertEqual(result["planId"], "test-plan")

    def test_save_and_load_dispatch_state(self):
        state = {"planId": "test-plan", "dispatched": {"S1": "queued"}}
        save_dispatch_state(self.plan, state, self.base)
        result = load_dispatch_state(self.plan, self.base)
        self.assertEqual(result["dispatched"], {"S1": "queued"})


class TestReadySubtasks(unittest.TestCase):
    def test_ready_subtask_ids_empty_registry(self):
        plan = make_plan()
        result = ready_subtask_ids(plan, [])
        self.assertEqual(result, set())

    def test_ready_subtask_ids_filters_by_plan(self):
        plan = make_plan()
        registry = [
            {"status": "ready", "metadata": {"planId": "other-plan", "subtaskId": "S1"}},
            {"status": "ready", "metadata": {"planId": "test-plan", "subtaskId": "S1"}},
        ]
        result = ready_subtask_ids(plan, registry)
        self.assertEqual(result, {"S1"})

    def test_ready_subtask_ids_filters_by_status(self):
        plan = make_plan()
        registry = [
            {"status": "running", "metadata": {"planId": "test-plan", "subtaskId": "S1"}},
            {"status": "ready", "metadata": {"planId": "test-plan", "subtaskId": "S1"}},
        ]
        result = ready_subtask_ids(plan, registry)
        self.assertEqual(result, {"S1"})


class TestTopologicalSort(unittest.TestCase):
    def test_topologically_sorted_subtask_ids(self):
        plan = make_plan(subtasks=[
            {"id": "S1", "title": "First", "description": "Test", "dependsOn": []},
            {"id": "S2", "title": "Second", "description": "Test", "dependsOn": ["S1"]},
            {"id": "S3", "title": "Third", "description": "Test", "dependsOn": ["S2"]},
        ])
        result = topologically_sorted_subtask_ids(plan)
        self.assertEqual(result, ["S1", "S2", "S3"])


class TestBuildExecutionTask(unittest.TestCase):
    def test_build_execution_task(self):
        plan = make_plan(
            planId="test-plan",
            repo="test/repo",
            title="Test Plan",
            requestedBy="alice#1234",
            objective="Test objective",
            routing={"agent": "codex", "model": "gpt-5", "effort": "high"},
            subtasks=[{
                "id": "S1",
                "title": "Implement feature",
                "description": "Test",
                "worktreeStrategy": "isolated",
                "dependsOn": [],
                "filesHint": ["src/main.py"],
                "prompt": "Test prompt",
            }],
        )
        subtask = plan.subtasks[0]
        result = build_execution_task(plan, subtask, planned_by="zoe")
        
        self.assertEqual(result["id"], "test-plan-S1")
        self.assertEqual(result["repo"], "test/repo")
        self.assertEqual(result["metadata"]["planId"], "test-plan")
        self.assertEqual(result["metadata"]["plannedBy"], "zoe")


class TestArchiveSubtasks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.plan = make_plan()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_archive_subtasks_creates_files(self):
        archive_subtasks(self.plan, self.base)
        archive_path = subtask_archive_path(self.plan, self.plan.subtasks[0], self.base)
        self.assertTrue(archive_path.exists())
        content = json.loads(archive_path.read_text())
        self.assertEqual(content["id"], "S1")


class TestUpdateSubtaskArchive(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.plan = make_plan()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_update_subtask_archive(self):
        archive_subtasks(self.plan, self.base)
        subtask = self.plan.subtasks[0]
        update_subtask_archive(
            self.plan, subtask,
            state="queued", queued_task_id="task-123", queued_at=1234567890,
            base_dir=self.base,
        )
        archive_path = subtask_archive_path(self.plan, subtask, self.base)
        content = json.loads(archive_path.read_text())
        self.assertEqual(content["dispatch"]["state"], "queued")
        self.assertEqual(content["dispatch"]["queuedTaskId"], "task-123")


class TestDispatchReadySubtasks(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.plan = make_plan(subtasks=[
            {"id": "S1", "title": "Subtask 1", "description": "Test", "dependsOn": []},
            {"id": "S2", "title": "Subtask 2", "description": "Test", "dependsOn": ["S1"]},
        ])

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dispatch_ready_subtasks_first_batch(self):
        archive_subtasks(self.plan, self.base)
        queued = dispatch_ready_subtasks(self.plan, base_dir=self.base, registry_items=[])
        self.assertEqual(len(queued), 1)
        self.assertIn("test-plan-S1", str(queued[0]))

    def test_dispatch_ready_subtasks_respects_dependencies(self):
        archive_subtasks(self.plan, self.base)
        queued1 = dispatch_ready_subtasks(self.plan, base_dir=self.base, registry_items=[])
        self.assertEqual(len(queued1), 1)
        
        # S1 is now queued, need to simulate it being completed
        # For S2 to be ready, S1 needs to be in the "completed" set
        # The ready_subtask_ids function looks for status=="ready" in registry
        registry = [{"id": "test-plan-S1", "status": "ready", "metadata": {"planId": "test-plan", "subtaskId": "S1"}}]
        queued2 = dispatch_ready_subtasks(self.plan, base_dir=self.base, registry_items=registry)
        self.assertEqual(len(queued2), 1)
        self.assertIn("test-plan-S2", str(queued2[0]))


if __name__ == "__main__":
    unittest.main()
