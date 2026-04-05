#!/usr/bin/env python3
"""
Test script for WebSocket event streaming

Tests:
- EventManager functionality
- WebSocket connection
- Event publishing and subscription
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.api.events import (
    EventManager,
    EventType,
    Event,
    get_event_manager
)
from orchestrator.api.websocket import (
    WebSocketHandler,
    get_websocket_handler,
    WEBSOCKETS_AVAILABLE
)


def test_event_manager():
    """Test EventManager basic functionality"""
    print("\n=== Testing EventManager ===")
    
    em = get_event_manager()
    
    # Track received events
    received_events = []
    
    def callback(event: Event):
        received_events.append(event)
        print(f"  ✓ Received event: {event.event_type.value}")
    
    # Subscribe to all events
    unsubscribe = em.subscribe(callback)
    
    # Publish test events
    em.publish_task_status("task_001", "running", {"progress": 50})
    em.publish_plan_status("plan_001", "dispatched", {"subtasks": 3})
    em.publish_alert("warning", "Test alert", {"code": "TEST001"})
    
    # Verify events received
    assert len(received_events) == 3, f"Expected 3 events, got {len(received_events)}"
    print(f"  ✓ All {len(received_events)} events received")
    
    # Test event history
    history = em.get_history()
    assert len(history) >= 3, "Event history should contain events"
    print(f"  ✓ Event history: {len(history)} events")
    
    # Unsubscribe
    unsubscribe()
    
    # Clear for next test
    received_events.clear()
    
    # Publish again - should not receive
    em.publish_task_status("task_002", "completed", {})
    assert len(received_events) == 0, "Should not receive events after unsubscribe"
    print("  ✓ Unsubscribe works correctly")
    
    print("✓ EventManager tests passed\n")
    return True


def test_event_types():
    """Test EventType enum"""
    print("=== Testing EventTypes ===")
    
    expected_types = {"task_status", "plan_status", "alert", "system"}
    actual_types = {e.value for e in EventType}
    
    assert expected_types == actual_types, f"Event types mismatch: {actual_types}"
    print(f"  ✓ Event types: {', '.join(actual_types)}")
    
    print("✓ EventTypes tests passed\n")
    return True


def test_event_serialization():
    """Test Event serialization"""
    print("=== Testing Event Serialization ===")
    
    event = Event(
        event_type=EventType.TASK_STATUS,
        data={"task_id": "test_001", "status": "running"},
        source="test_script"
    )
    
    # Test to_dict
    event_dict = event.to_dict()
    assert event_dict["type"] == "task_status"
    assert event_dict["data"]["task_id"] == "test_001"
    assert event_dict["source"] == "test_script"
    print("  ✓ to_dict() works")
    
    # Test to_json
    json_str = event.to_json()
    assert '"type": "task_status"' in json_str
    print("  ✓ to_json() works")
    
    print("✓ Event serialization tests passed\n")
    return True


async def test_websocket_handler():
    """Test WebSocketHandler initialization"""
    print("=== Testing WebSocketHandler ===")
    
    if not WEBSOCKETS_AVAILABLE:
        print("  ⚠ websockets library not available, skipping")
        return True
    
    ws_handler = get_websocket_handler()
    
    # Test properties
    assert ws_handler.client_count == 0
    print(f"  ✓ Client count: {ws_handler.client_count}")
    
    # Test client info
    client_info = ws_handler.get_client_info()
    assert isinstance(client_info, list)
    print(f"  ✓ get_client_info() returns list")
    
    # Test is_running
    assert not ws_handler.is_running
    print(f"  ✓ is_running: {ws_handler.is_running}")
    
    print("✓ WebSocketHandler tests passed\n")
    return True


def run_tests():
    """Run all tests"""
    print("\n" + "="*50)
    print("WebSocket Event Streaming Tests")
    print("="*50)
    
    results = []
    
    # Sync tests
    results.append(("EventManager", test_event_manager()))
    results.append(("EventTypes", test_event_types()))
    results.append(("Event Serialization", test_event_serialization()))
    
    # Async test
    results.append(("WebSocketHandler", asyncio.run(test_websocket_handler())))
    
    # Summary
    print("="*50)
    print("Test Summary:")
    print("="*50)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return all(r for _, r in results)


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
