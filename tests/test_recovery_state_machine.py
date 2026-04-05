#!/usr/bin/env python3
"""Tests for recovery_state_machine.py - RecoveryStateMachine 测试 (15+ test cases)"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from recovery_state_machine import (
    RecoveryStateMachine,
    RecoveryState,
    RecoveryConfig,
    RecoveryContext,
    VALID_TRANSITIONS,
)


class TestRecoveryState(unittest.TestCase):
    """RecoveryState 枚举测试 (4 cases)"""
    
    def test_state_detecting(self):
        self.assertEqual(RecoveryState.DETECTING.value, "detecting")

    def test_state_recovering(self):
        self.assertEqual(RecoveryState.RECOVERING.value, "recovering")

    def test_state_recovered(self):
        self.assertEqual(RecoveryState.RECOVERED.value, "recovered")

    def test_state_failed(self):
        self.assertEqual(RecoveryState.FAILED.value, "failed")


class TestRecoveryConfig(unittest.TestCase):
    """RecoveryConfig 配置测试 (6 cases)"""
    
    def test_default_config(self):
        config = RecoveryConfig()
        self.assertEqual(config.max_recovery_attempts, 3)
        self.assertEqual(config.recovery_cooldown_seconds, 300.0)

    def test_custom_config(self):
        config = RecoveryConfig(
            max_recovery_attempts=5,
            recovery_cooldown_seconds=600.0,
            backoff_multiplier=2.0,
            max_backoff_seconds=3600.0
        )
        self.assertEqual(config.max_recovery_attempts, 5)
        self.assertEqual(config.recovery_cooldown_seconds, 600.0)

    def test_default_backoff_multiplier(self):
        config = RecoveryConfig()
        self.assertEqual(config.backoff_multiplier, 1.5)

    def test_default_detection_timeout(self):
        config = RecoveryConfig()
        self.assertEqual(config.detection_timeout_seconds, 60.0)

    def test_default_recovery_timeout(self):
        config = RecoveryConfig()
        self.assertEqual(config.recovery_timeout_seconds, 600.0)

    def test_default_max_backoff(self):
        config = RecoveryConfig()
        self.assertEqual(config.max_backoff_seconds, 1800.0)


class TestRecoveryContext(unittest.TestCase):
    """RecoveryContext 上下文测试 (6 cases)"""
    
    def test_initial_context(self):
        ctx = RecoveryContext(task_id="task-123")
        self.assertEqual(ctx.task_id, "task-123")
        self.assertEqual(ctx.state, RecoveryState.DETECTING)
        self.assertEqual(ctx.attempts, 0)

    def test_context_to_dict(self):
        ctx = RecoveryContext(task_id="task-456", attempts=2)
        data = ctx.to_dict()
        self.assertEqual(data["task_id"], "task-456")
        self.assertEqual(data["attempts"], 2)

    def test_context_from_dict(self):
        data = {
            "task_id": "task-789",
            "state": "recovering",
            "attempts": 3,
            "last_error": "Test error"
        }
        ctx = RecoveryContext.from_dict(data)
        self.assertEqual(ctx.task_id, "task-789")
        self.assertEqual(ctx.state, RecoveryState.RECOVERING)
        self.assertEqual(ctx.attempts, 3)

    def test_context_with_metadata(self):
        ctx = RecoveryContext(
            task_id="task-abc",
            recovery_metadata={"key": "value"}
        )
        self.assertEqual(ctx.recovery_metadata["key"], "value")

    def test_context_last_error(self):
        ctx = RecoveryContext(task_id="task-xyz", last_error="Error message")
        self.assertEqual(ctx.last_error, "Error message")

    def test_context_started_at(self):
        timestamp = time.time()
        ctx = RecoveryContext(task_id="task-test", started_at=timestamp)
        self.assertEqual(ctx.started_at, timestamp)


class TestRecoveryStateMachineTransitions(unittest.TestCase):
    """RecoveryStateMachine 状态转换测试 (8 cases)"""
    
    def setUp(self):
        self.sm = RecoveryStateMachine()

    def test_initial_state(self):
        state = self.sm.get_state("task-new")
        self.assertEqual(state, RecoveryState.DETECTING)

    def test_valid_transition_detecting_to_recovering(self):
        success, msg = self.sm.start_recovery("task-1")
        self.assertTrue(success)
        self.assertEqual(self.sm.get_state("task-1"), RecoveryState.RECOVERING)

    def test_valid_transition_recovering_to_recovered(self):
        self.sm.start_recovery("task-2")
        success = self.sm.complete_recovery("task-2")
        self.assertTrue(success)
        self.assertEqual(self.sm.get_state("task-2"), RecoveryState.RECOVERED)

    def test_valid_transition_recovering_to_failed(self):
        self.sm.start_recovery("task-3")
        success = self.sm.fail_recovery("task-3", "Test error")
        self.assertTrue(success)
        self.assertEqual(self.sm.get_state("task-3"), RecoveryState.FAILED)

    def test_valid_transition_failed_to_detecting_via_reset(self):
        self.sm.start_recovery("task-4")
        self.sm.fail_recovery("task-4", "Error")
        self.sm.reset("task-4")
        self.assertEqual(self.sm.get_state("task-4"), RecoveryState.DETECTING)

    def test_invalid_transition_recovered_to_recovering(self):
        self.sm.start_recovery("task-5")
        self.sm.complete_recovery("task-5")
        success, msg = self.sm.start_recovery("task-5")
        self.assertFalse(success)

    def test_transition_increments_attempts(self):
        self.sm.start_recovery("task-6")
        self.assertEqual(self.sm.get_attempts("task-6"), 1)

    def test_max_attempts_blocks_transition(self):
        config = RecoveryConfig(max_recovery_attempts=2)
        sm = RecoveryStateMachine(config=config)
        
        # First attempt
        sm.start_recovery("task-7")
        sm.fail_recovery("task-7", "Error 1")
        
        # Second attempt (should be allowed)
        sm.reset("task-7")
        success1, _ = sm.start_recovery("task-7")
        self.assertTrue(success1)
        sm.fail_recovery("task-7", "Error 2")
        
        # Third attempt (should be blocked after 2 attempts)
        sm.reset("task-7")
        # Manually set attempts to max
        sm.get_context("task-7").attempts = 2
        success2, msg = sm.start_recovery("task-7")
        self.assertFalse(success2)


class TestRecoveryStateMachineBackoff(unittest.TestCase):
    """RecoveryStateMachine 退避策略测试 (4 cases)"""
    
    def setUp(self):
        self.config = RecoveryConfig(
            recovery_cooldown_seconds=100.0,
            backoff_multiplier=2.0,
            max_backoff_seconds=500.0
        )
        self.sm = RecoveryStateMachine(config=self.config)

    def test_initial_backoff(self):
        backoff = self.sm._calculate_backoff(0)
        self.assertEqual(backoff, 100.0)

    def test_backoff_with_multiplier(self):
        backoff = self.sm._calculate_backoff(2)
        # 100 * 2^(2-1) = 200
        self.assertEqual(backoff, 200.0)

    def test_backoff_respects_max(self):
        backoff = self.sm._calculate_backoff(10)
        self.assertLessEqual(backoff, 500.0)

    def test_get_next_attempt_after(self):
        self.sm.start_recovery("task-backoff")
        next_time = self.sm.get_next_attempt_after("task-backoff")
        # Should return a future time or None
        self.assertTrue(next_time is None or next_time > time.time())


class TestRecoveryStateMachineCallbacks(unittest.TestCase):
    """RecoveryStateMachine 回调测试 (4 cases)"""
    
    def test_state_change_callback(self):
        callback = MagicMock()
        sm = RecoveryStateMachine(on_state_change=callback)
        
        sm.start_recovery("task-callback")
        
        callback.assert_called()

    def test_recovery_attempt_callback(self):
        callback = MagicMock()
        sm = RecoveryStateMachine(on_recovery_attempt=callback)
        
        sm.start_recovery("task-attempt")
        
        callback.assert_called_with("task-attempt", 1)

    def test_recovery_success_callback(self):
        callback = MagicMock()
        sm = RecoveryStateMachine(on_recovery_success=callback)
        
        sm.start_recovery("task-success")
        sm.complete_recovery("task-success")
        
        callback.assert_called_with("task-success")

    def test_recovery_failed_callback(self):
        callback = MagicMock()
        sm = RecoveryStateMachine(on_recovery_failed=callback)
        
        sm.start_recovery("task-failed")
        sm.fail_recovery("task-failed", "Test error")
        
        callback.assert_called()


class TestRecoveryStateMachinePersistence(unittest.TestCase):
    """RecoveryStateMachine 持久化测试 (3 cases)"""
    
    def setUp(self):
        self.sm = RecoveryStateMachine()

    def test_context_persistence(self):
        ctx = RecoveryContext(task_id="task-persist", attempts=3)
        self.sm._contexts["task-persist"] = ctx
        
        # Get context should return the same object
        retrieved = self.sm.get_context("task-persist")
        self.assertEqual(retrieved.attempts, 3)

    def test_active_recoveries_count(self):
        self.sm.start_recovery("task-active-1")
        self.sm.start_recovery("task-active-2")
        
        self.assertEqual(self.sm.active_recoveries, 2)

    def test_get_all_contexts(self):
        self.sm.start_recovery("task-all-1")
        self.sm.start_recovery("task-all-2")
        
        all_contexts = self.sm.get_all_contexts()
        self.assertGreaterEqual(len(all_contexts), 2)


if __name__ == "__main__":
    unittest.main()
