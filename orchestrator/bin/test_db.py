#!/usr/bin/env python3
"""
Test script for SQLite tracker
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db import (
    init_db,
    insert_task,
    get_task,
    get_running_tasks,
    get_all_tasks,
    update_task,
    update_task_status,
    count_running_tasks,
    delete_task,
)


def test_basic_operations():
    print("=" * 50)
    print("Testing SQLite Tracker")
    print("=" * 50)
    
    # Initialize
    init_db()
    print("✓ Database initialized")
    
    # Insert a test task
    test_task = {
        "id": "test-task-001",
        "plan_id": "test-plan-001",
        "repo": "test-repo",
        "title": "Test Task",
        "status": "running",
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "effort": "medium",
        "worktree": "/tmp/test-worktree",
        "branch": "feat/test-001",
        "tmuxSession": "agent-test-001",
        "startedAt": 1234567890000,
    }
    
    insert_task(test_task)
    print("✓ Task inserted")
    
    # Get task
    task = get_task("test-task-001")
    assert task is not None, "Task should exist"
    assert task["title"] == "Test Task"
    print(f"✓ Task retrieved: {task['title']}")
    
    # Update task
    update_task_status("test-task-001", "pr_created", "PR created successfully")
    task = get_task("test-task-001")
    assert task["status"] == "pr_created"
    assert task["note"] == "PR created successfully"
    print(f"✓ Task updated: status={task['status']}, note={task['note']}")
    
    # Get running tasks
    running = get_running_tasks()
    assert len(running) >= 1
    print(f"✓ Running tasks: {len(running)}")
    
    # Count running
    count = count_running_tasks()
    assert count >= 1
    print(f"✓ Running count: {count}")
    
    # Get all tasks
    all_tasks = get_all_tasks(limit=10)
    assert len(all_tasks) >= 1
    print(f"✓ All tasks (limit 10): {len(all_tasks)}")
    
    # Delete test task
    delete_task("test-task-001")
    task = get_task("test-task-001")
    assert task is None, "Task should be deleted"
    print("✓ Task deleted")
    
    print("=" * 50)
    print("All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    test_basic_operations()
