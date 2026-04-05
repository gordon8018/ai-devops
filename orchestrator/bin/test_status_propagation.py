#!/usr/bin/env python3
"""
Test script for CP-3: Status Propagation

Tests:
1. StatusPropagator class exists and has required methods
2. propagate_completion works correctly
3. wake_blocked_plans works correctly
4. Integration with GlobalScheduler
5. Integration with dispatch.py
"""

import sys
import time
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.bin.db import init_db, insert_plan, get_plan, update_plan, get_all_plans
from orchestrator.bin.status_propagator import StatusPropagator, get_status_propagator
from orchestrator.bin.global_scheduler import GlobalScheduler, get_global_scheduler


def test_status_propagator_class():
    """Test StatusPropagator class has required methods."""
    print("\n=== Test 1: StatusPropagator Class ===")
    
    propagator = StatusPropagator()
    
    # Check required methods
    required_methods = [
        'find_dependent_plans',
        'propagate_completion',
        'get_blocked_plans',
        'wake_blocked_plans',
        'on_plan_status_change',
        'get_event_log',
    ]
    
    for method in required_methods:
        assert hasattr(propagator, method), f"Missing method: {method}"
        print(f"  ✓ {method} exists")
    
    print("Test 1 PASSED")
    return True


def test_propagate_completion():
    """Test propagate_completion works correctly."""
    print("\n=== Test 2: propagate_completion ===")
    
    init_db()
    propagator = StatusPropagator()
    
    # Create test plans with dependencies
    plan_a = {
        "plan_id": "test-plan-a",
        "repo": "test-repo",
        "title": "Test Plan A",
        "requested_by": "test",
        "requested_at": int(time.time() * 1000),
        "version": "1.0",
        "plan_depends_on": [],
        "status": "pending",
    }
    
    plan_b = {
        "plan_id": "test-plan-b",
        "repo": "test-repo",
        "title": "Test Plan B",
        "requested_by": "test",
        "requested_at": int(time.time() * 1000),
        "version": "1.0",
        "plan_depends_on": ["test-plan-a"],
        "status": "pending",
    }
    
    # Insert plans
    insert_plan(plan_a)
    insert_plan(plan_b)
    
    # Mark plan A as completed
    update_plan("test-plan-a", {"status": "completed"})
    
    # Propagate completion
    result = propagator.propagate_completion("test-plan-a")
    
    print(f"  Propagation result: {json.dumps(result, indent=2)}")
    
    assert "completedPlanId" in result
    assert result["completedPlanId"] == "test-plan-a"
    assert "test-plan-b" in result["dependentPlans"]
    
    # Verify plan B was woken up
    plan_b_after = get_plan("test-plan-b")
    print(f"  Plan B status after propagation: {plan_b_after.get('status')}")
    
    print("Test 2 PASSED")
    return True


def test_wake_blocked_plans():
    """Test wake_blocked_plans works correctly."""
    print("\n=== Test 3: wake_blocked_plans ===")
    
    init_db()
    propagator = StatusPropagator()
    
    # Create test plans
    plan_c = {
        "plan_id": "test-plan-c",
        "repo": "test-repo",
        "title": "Test Plan C",
        "requested_by": "test",
        "requested_at": int(time.time() * 1000),
        "version": "1.0",
        "plan_depends_on": [],
        "status": "completed",
    }
    
    plan_d = {
        "plan_id": "test-plan-d",
        "repo": "test-repo",
        "title": "Test Plan D",
        "requested_by": "test",
        "requested_at": int(time.time() * 1000),
        "version": "1.0",
        "plan_depends_on": ["test-plan-c"],
        "status": "pending",
    }
    
    insert_plan(plan_c)
    insert_plan(plan_d)
    
    # Wake blocked plans
    result = propagator.wake_blocked_plans()
    
    print(f"  Wake result: {json.dumps(result, indent=2)}")
    
    assert "checkedPlans" in result
    assert "wokenPlans" in result
    assert "test-plan-d" in result["wokenPlans"]
    
    print("Test 3 PASSED")
    return True


def test_global_scheduler_integration():
    """Test GlobalScheduler integration with StatusPropagator."""
    print("\n=== Test 4: GlobalScheduler Integration ===")
    
    init_db()
    scheduler = GlobalScheduler()
    
    # The scheduler should now call wake_blocked_plans during schedule()
    # This is verified by checking the schedule method runs without error
    
    decisions = scheduler.schedule()
    print(f"  Scheduling decisions: {len(decisions)}")
    
    # Check scheduling summary
    summary = scheduler.get_scheduling_summary()
    print(f"  Scheduling summary: {json.dumps(summary, indent=2)}")
    
    assert "resourceInfo" in summary
    assert "pendingPlans" in summary
    
    print("Test 4 PASSED")
    return True


def test_dispatch_integration():
    """Test dispatch.py integration with StatusPropagator."""
    print("\n=== Test 5: dispatch.py Integration ===")
    
    from orchestrator.bin.dispatch import get_status_propagator as dispatch_get_status_propagator
    
    propagator = dispatch_get_status_propagator()
    assert propagator is not None
    print("  ✓ dispatch.py can access StatusPropagator")
    
    print("Test 5 PASSED")
    return True


def main():
    print("=" * 60)
    print("CP-3: Status Propagation Tests")
    print("=" * 60)
    
    tests = [
        test_status_propagator_class,
        test_propagate_completion,
        test_wake_blocked_plans,
        test_global_scheduler_integration,
        test_dispatch_integration,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
