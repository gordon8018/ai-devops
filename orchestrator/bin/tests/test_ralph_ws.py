#!/usr/bin/env python3
"""Unit tests for ralph_ws_server.py"""

import sys
import os
import tempfile
import asyncio
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from ralph_ws_server import RalphWebSocketServer, RalphEventType, RalphEvent
    from ralph_state import RalphState
except ImportError:
    from orchestrator.bin.ralph_ws_server import RalphWebSocketServer, RalphEventType, RalphEvent
    from orchestrator.bin.ralph_state import RalphState


def test_ralph_event():
    """Test RalphEvent class"""
    event = RalphEvent(
        event_type=RalphEventType.STATUS_CHANGE,
        task_id="test-task",
        data={"old_status": "queued", "new_status": "running"}
    )
    
    assert event.event_type == RalphEventType.STATUS_CHANGE
    assert event.task_id == "test-task"
    assert event.data["old_status"] == "queued"
    
    data = event.to_dict()
    assert data["type"] == "status_change"
    assert data["task_id"] == "test-task"
    assert "timestamp" in data
    
    print("✓ test_ralph_event passed")


def test_ralph_ws_server_init():
    """Test RalphWebSocketServer initialization"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        RalphState(db_path).create("test-task")
        
        server = RalphWebSocketServer(host="127.0.0.1", port=8767)
        assert server.host == "127.0.0.1"
        assert server.port == 8767
        assert server.state is not None
        assert len(server.clients) == 0
        
        print("✓ test_ralph_ws_server_init passed")


def test_ralph_event_types():
    """Test RalphEventType enum values"""
    assert RalphEventType.STATUS_CHANGE.value == "status_change"
    assert RalphEventType.PROGRESS_UPDATE.value == "progress_update"
    assert RalphEventType.LOG_APPEND.value == "log_append"
    assert RalphEventType.TASK_COMPLETE.value == "task_complete"
    assert RalphEventType.TASK_FAILED.value == "task_failed"
    
    print("✓ test_ralph_event_types passed")


def test_event_creation():
    """Test creating different event types"""
    events = [
        RalphEvent(RalphEventType.STATUS_CHANGE, "task-1", {"status": "running"}),
        RalphEvent(RalphEventType.PROGRESS_UPDATE, "task-1", {"progress": 50}),
        RalphEvent(RalphEventType.LOG_APPEND, "task-1", {"log": "Processing..."}),
        RalphEvent(RalphEventType.TASK_COMPLETE, "task-1", {"result": "success"}),
        RalphEvent(RalphEventType.TASK_FAILED, "task-1", {"error": "Failed"}),
    ]
    
    for i, event in enumerate(events):
        data = event.to_dict()
        assert "type" in data
        assert "task_id" in data
        assert "data" in data
        assert "timestamp" in data
    
    print("✓ test_event_creation passed")


def run_all_tests():
    """Run all tests"""
    print("Running ralph_ws_server tests...")
    print()
    
    test_ralph_event()
    test_ralph_ws_server_init()
    test_ralph_event_types()
    test_event_creation()
    
    print()
    print("All ralph_ws_server tests passed!")


if __name__ == "__main__":
    run_all_tests()
