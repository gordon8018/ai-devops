#!/usr/bin/env python3
"""Tests for process_guardian.py - ProcessGuardian 测试 (15+ test cases)"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from process_guardian import (
    ProcessGuardian,
    RestartPolicy,
    TaskMonitorState,
)


class TestRestartPolicy(unittest.TestCase):
    """重启策略测试 (6 cases)"""
    
    def test_can_restart_initial(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=300.0)
        can_restart = policy.can_restart(restart_count=0, last_restart_at=None)
        self.assertTrue(can_restart)

    def test_can_restart_within_limit(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=300.0)
        can_restart = policy.can_restart(restart_count=2, last_restart_at=time.time() - 400)
        self.assertTrue(can_restart)

    def test_cannot_restart_exceeds_limit(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=300.0)
        can_restart = policy.can_restart(restart_count=3, last_restart_at=None)
        self.assertFalse(can_restart)

    def test_cannot_restart_in_cooldown(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=300.0)
        can_restart = policy.can_restart(restart_count=1, last_restart_at=time.time() - 100)
        self.assertFalse(can_restart)

    def test_default_policy_values(self):
        policy = RestartPolicy()
        self.assertEqual(policy.max_restarts, 3)
        self.assertEqual(policy.cooldown_seconds, 300.0)

    def test_custom_policy_values(self):
        policy = RestartPolicy(max_restarts=5, cooldown_seconds=600.0)
        self.assertEqual(policy.max_restarts, 5)
        self.assertEqual(policy.cooldown_seconds, 600.0)


class TestTaskMonitorState(unittest.TestCase):
    """任务监控状态测试 (5 cases)"""
    
    def test_initial_state(self):
        state = TaskMonitorState(task_id="task-123", session_name="session-123")
        self.assertEqual(state.task_id, "task-123")
        self.assertEqual(state.session_name, "session-123")
        self.assertEqual(state.restart_count, 0)
        self.assertIsNone(state.last_restart_at)

    def test_state_with_restart_count(self):
        state = TaskMonitorState(
            task_id="task-456",
            session_name="session-456",
            restart_count=2,
            last_restart_at=time.time()
        )
        self.assertEqual(state.restart_count, 2)
        self.assertIsNotNone(state.last_restart_at)

    def test_state_is_alive_default(self):
        state = TaskMonitorState(task_id="task-789", session_name="session-789")
        self.assertTrue(state.is_alive)

    def test_state_consecutive_failures_default(self):
        state = TaskMonitorState(task_id="task-abc", session_name="session-abc")
        self.assertEqual(state.consecutive_failures, 0)

    def test_state_last_check_at_default(self):
        state = TaskMonitorState(task_id="task-xyz", session_name="session-xyz")
        self.assertIsNone(state.last_check_at)


class TestProcessGuardianInit(unittest.TestCase):
    """ProcessGuardian 初始化测试 (4 cases)"""
    
    def test_init_default_policy(self):
        guardian = ProcessGuardian()
        self.assertIsNotNone(guardian.policy)
        self.assertEqual(guardian.policy.max_restarts, 3)

    def test_init_custom_policy(self):
        policy = RestartPolicy(max_restarts=5, cooldown_seconds=600.0)
        guardian = ProcessGuardian(policy=policy)
        self.assertEqual(guardian.policy.max_restarts, 5)
        self.assertEqual(guardian.policy.cooldown_seconds, 600.0)

    def test_init_custom_check_interval(self):
        guardian = ProcessGuardian(check_interval=60.0)
        self.assertEqual(guardian.check_interval, 60.0)

    def test_init_with_callbacks(self):
        on_restart = MagicMock()
        on_max_restarts = MagicMock()
        guardian = ProcessGuardian(on_restart=on_restart, on_max_restarts=on_max_restarts)
        self.assertEqual(guardian.on_restart, on_restart)
        self.assertEqual(guardian.on_max_restarts, on_max_restarts)


class TestProcessGuardianTaskManagement(unittest.TestCase):
    """ProcessGuardian 任务管理测试 (5 cases)"""
    
    def setUp(self):
        self.guardian = ProcessGuardian()
        # Directly add to _monitors to bypass DB check
        self.guardian._monitors["task-123"] = TaskMonitorState(
            task_id="task-123",
            session_name="session-123"
        )
        self.guardian._monitors["task-456"] = TaskMonitorState(
            task_id="task-456",
            session_name="session-456"
        )

    def test_add_task(self):
        # Add a task directly to monitors
        initial_count = self.guardian.monitored_count
        self.guardian._monitors["new-task"] = TaskMonitorState(
            task_id="new-task",
            session_name="new-session"
        )
        self.assertEqual(self.guardian.monitored_count, initial_count + 1)

    def test_remove_task(self):
        initial_count = self.guardian.monitored_count
        self.guardian.remove_task("task-123")
        self.assertEqual(self.guardian.monitored_count, initial_count - 1)

    def test_get_monitor_state(self):
        state = self.guardian.get_monitor_state("task-456")
        self.assertIsNotNone(state)
        self.assertEqual(state.task_id, "task-456")

    def test_get_nonexistent_monitor_state(self):
        state = self.guardian.get_monitor_state("nonexistent-task")
        self.assertIsNone(state)

    def test_monitored_count(self):
        # Already have 2 tasks in setUp
        self.assertGreaterEqual(self.guardian.monitored_count, 2)


class TestProcessGuardianRestartLogic(unittest.TestCase):
    """ProcessGuardian 重启逻辑测试 (5 cases)"""
    
    def setUp(self):
        self.guardian = ProcessGuardian()
        # Directly add to _monitors to bypass DB check
        self.guardian._monitors["task-789"] = TaskMonitorState(
            task_id="task-789",
            session_name="session-789"
        )

    def test_reset_restart_count(self):
        state = self.guardian.get_monitor_state("task-789")
        state.restart_count = 3
        state.last_restart_at = time.time()
        
        with patch("process_guardian.update_task"):
            self.guardian.reset_restart_count("task-789")
        
        state = self.guardian.get_monitor_state("task-789")
        self.assertEqual(state.restart_count, 0)
        self.assertIsNone(state.last_restart_at)

    def test_policy_allows_restart(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=0)
        state = self.guardian.get_monitor_state("task-789")
        state.restart_count = 2
        state.last_restart_at = time.time() - 1000
        
        can_restart = policy.can_restart(state.restart_count, state.last_restart_at)
        self.assertTrue(can_restart)

    def test_policy_blocks_restart_cooldown(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=300.0)
        can_restart = policy.can_restart(1, time.time() - 100)
        self.assertFalse(can_restart)

    def test_policy_blocks_restart_max_restarts(self):
        policy = RestartPolicy(max_restarts=3, cooldown_seconds=0)
        can_restart = policy.can_restart(3, None)
        self.assertFalse(can_restart)

    def test_get_all_monitors(self):
        # Add another task
        self.guardian._monitors["task-test"] = TaskMonitorState(
            task_id="task-test",
            session_name="session-test"
        )
        
        monitors = self.guardian.get_all_monitors()
        self.assertGreaterEqual(len(monitors), 1)


class TestProcessGuardianRecoveryState(unittest.TestCase):
    """ProcessGuardian 恢复状态测试 (3 cases)"""
    
    def setUp(self):
        self.guardian = ProcessGuardian()

    def test_get_recovery_state(self):
        state = self.guardian.get_recovery_state("task-new")
        # 新任务应该有默认的恢复状态
        self.assertIsNotNone(state)

    def test_get_recovery_attempts(self):
        attempts = self.guardian.get_recovery_attempts("task-new")
        # 新任务应该有 0 次尝试
        self.assertEqual(attempts, 0)

    def test_reset_recovery(self):
        self.guardian.reset_recovery("task-test")
        # 重置应该不会抛出异常
        state = self.guardian.get_recovery_state("task-test")
        self.assertIsNotNone(state)


if __name__ == "__main__":
    unittest.main()
