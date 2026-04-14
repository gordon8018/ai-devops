#!/usr/bin/env python3
"""
Unit tests for ralph integration modules.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from task_to_prd import (
    task_spec_to_prd_json,
    save_prd_json,
    load_task_spec_from_file,
    validate_prd_json,
    TaskSpecError
)
from ralph_state import RalphState, RalphStateError
from ralph_runner import RalphRunner, RalphRunnerError


def test_task_to_prd_conversion():
    """Test TaskSpec → prd.json conversion."""
    print("\n=== Testing TaskSpec → prd.json Conversion ===")
    
    # Create sample TaskSpec
    task_spec = {
        "taskId": "task-20260414-001",
        "task": "Add priority field to database",
        "acceptanceCriteria": [
            "Add priority column to tasks table",
            "Typecheck passes"
        ],
        "repo": "user01/ai-devops",
        "userStories": [
            "Create migration for priority column",
            "Update API to support priority field"
        ]
    }
    
    # Convert to PRD
    prd = task_spec_to_prd_json(task_spec)
    
    # Verify basic structure
    assert "project" in prd
    assert "branchName" in prd
    assert "description" in prd
    assert "userStories" in prd
    assert "qualityChecks" in prd
    
    # Verify content
    assert prd["project"] == "ai-devops"
    assert prd["description"] == "Add priority field to database"
    assert len(prd["userStories"]) == 2
    assert prd["userStories"][0]["priority"] == 1
    assert prd["userStories"][1]["priority"] == 2
    assert prd["userStories"][0]["passes"] == False
    
    # Validate PRD
    validate_prd_json(prd)
    
    print("✓ TaskSpec → prd.json conversion test passed")
    return True


def test_ralph_state_crud():
    """Test RalphState CRUD operations."""
    print("\n=== Testing RalphState CRUD Operations ===")
    
    # Use temporary database
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_ralph.db"
        state = RalphState(db_path)
        
        # Test create
        task_id = "test-task-001"
        row_id = state.create(
            task_id=task_id,
            status="queued",
            progress=0,
            logs="Initial state"
        )
        assert row_id > 0
        print(f"✓ Created state entry (ID: {row_id})")
        
        # Test get
        entry = state.get(task_id)
        assert entry is not None
        assert entry["task_id"] == task_id
        assert entry["status"] == "queued"
        assert entry["progress"] == 0
        print(f"✓ Retrieved state entry")
        
        # Test update
        state.update(task_id, status="running", progress=25)
        entry = state.get(task_id)
        assert entry["status"] == "running"
        assert entry["progress"] == 25
        print(f"✓ Updated state entry")
        
        # Test append log
        state.append_log(task_id, "Started iteration 1")
        entry = state.get(task_id)
        assert "Started iteration 1" in entry["logs"]
        print(f"✓ Appended log entry")
        
        # Test list
        state.create("test-task-002", status="completed", progress=100)
        entries = state.list()
        assert len(entries) == 2
        print(f"✓ Listed {len(entries)} entries")
        
        # Test filter by status
        queued_entries = state.list(status="queued")
        assert len(queued_entries) == 0
        print(f"✓ Filtered entries by status")
        
        # Test delete
        deleted = state.delete(task_id)
        assert deleted is True
        entry = state.get(task_id)
        assert entry is None
        print(f"✓ Deleted state entry")
    
    print("✓ RalphState CRUD test passed")
    return True


def test_ralph_runner_basic():
    """Test RalphRunner basic operations."""
    print("\n=== Testing RalphRunner Basic Operations ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        ralph_dir = Path(tmpdir)
        
        # Note: We skip actual ralph.sh execution in unit tests
        # Test file operations only
        
        # Create sample prd.json
        prd = {
            "project": "test-project",
            "branchName": "ralph/test-branch",
            "description": "Test PRD",
            "userStories": [
                {"id": "US-001", "title": "Story 1", "passes": False, "priority": 1},
                {"id": "US-002", "title": "Story 2", "passes": True, "priority": 2}
            ]
        }
        
        # Create runner (will fail if ralph.sh not found, but that's ok for unit tests)
        try:
            runner = RalphRunner(ralph_dir)
        except RalphRunnerError:
            # ralph.sh not found, but we can still test file operations
            runner = RalphRunner.__new__(RalphRunner)
            runner.ralph_dir = ralph_dir
            runner.tool = "claude"
        
        # Save PRD
        runner.save_prd_json(prd)
        assert (ralph_dir / "prd.json").exists()
        print(f"✓ Saved prd.json")
        
        # Parse PRD
        prd_info = runner.parse_prd_json()
        assert prd_info["exists"] is True
        assert prd_info["total_stories"] == 2
        assert prd_info["completed_stories"] == 1
        assert prd_info["progress_percent"] == 50
        print(f"✓ Parsed prd.json: {prd_info['total_stories']} stories, {prd_info['progress_percent']}% complete")
        
        # Create progress.txt
        progress_file = ralph_dir / "progress.txt"
        progress_file.write_text("# Progress Log\n## 2026-04-14 - US-001\nImplemented story 1\n")
        
        # Parse progress
        progress_info = runner.parse_progress()
        assert progress_info["exists"] is True
        assert progress_info["iterations"] == 1
        print(f"✓ Parsed progress.txt: {progress_info['iterations']} iterations")
        
        # Get status
        status = runner.get_status()
        assert status["status"] == "running"
        assert status["prd"]["exists"] is True
        assert status["progress"]["exists"] is True
        print(f"✓ Got status: {status['status']}")
    
    print("✓ RalphRunner basic test passed")
    return True


def test_end_to_end_workflow():
    """Test end-to-end workflow: TaskSpec → prd.json → state tracking."""
    print("\n=== Testing End-to-End Workflow ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        db_path = tmpdir / "test_workflow.db"
        ralph_dir = tmpdir / "ralph"
        ralph_dir.mkdir()
        
        # 1. Create TaskSpec
        task_spec = {
            "taskId": "workflow-test-001",
            "task": "Implement workflow test feature",
            "acceptanceCriteria": [
                "Feature implemented",
                "Tests pass"
            ],
            "repo": "user01/test-repo",
            "userStories": [
                "Implement core logic",
                "Add unit tests"
            ]
        }
        
        # 2. Convert to PRD
        prd = task_spec_to_prd_json(task_spec)
        print(f"✓ Converted TaskSpec to PRD")
        
        # 3. Save PRD
        save_prd_json(prd, ralph_dir / "prd.json")
        assert (ralph_dir / "prd.json").exists()
        print(f"✓ Saved prd.json")
        
        # 4. Create state entry
        state = RalphState(db_path)
        row_id = state.create(
            task_id=task_spec["taskId"],
            status="queued",
            progress=0
        )
        print(f"✓ Created state entry (ID: {row_id})")
        
        # 5. Update state to running
        state.update(task_spec["taskId"], status="running", progress=0)
        print(f"✓ Updated state to running")
        
        # 6. Simulate progress
        for i in range(1, 4):
            progress = i * 33
            state.update(task_spec["taskId"], progress=progress)
            state.append_log(task_spec["taskId"], f"Completed iteration {i}")
        print(f"✓ Simulated progress updates")
        
        # 7. Verify final state
        entry = state.get(task_spec["taskId"])
        assert entry["status"] == "running"
        assert entry["progress"] == 99
        assert "Completed iteration 1" in entry["logs"]
        print(f"✓ Final state verified: status={entry['status']}, progress={entry['progress']}%")
        
        # 8. Update to completed
        state.update(task_spec["taskId"], status="completed", progress=100)
        entry = state.get(task_spec["taskId"])
        assert entry["status"] == "completed"
        print(f"✓ Updated to completed")
    
    print("✓ End-to-end workflow test passed")
    return True


def run_all_tests():
    """Run all unit tests."""
    print("=" * 60)
    print("Running Ralph Integration Unit Tests")
    print("=" * 60)
    
    tests = [
        ("TaskSpec → prd.json Conversion", test_task_to_prd_conversion),
        ("RalphState CRUD Operations", test_ralph_state_crud),
        ("RalphRunner Basic Operations", test_ralph_runner_basic),
        ("End-to-End Workflow", test_end_to_end_workflow)
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✓ {name} passed\n")
            else:
                failed += 1
                print(f"✗ {name} failed\n")
        except Exception as e:
            failed += 1
            print(f"✗ {name} failed with error: {e}\n")
            import traceback
            traceback.print_exc()
    
    print("=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
