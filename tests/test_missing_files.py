#!/usr/bin/env python3
"""
Unit tests for the 4 missing orchestrator files:
- health_check.py
- resource_config.py
- status_propagator.py
- shared_workspace.py

Run with: pytest tests/test_missing_files.py -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add orchestrator/bin to path
SCRIPT_DIR = Path(__file__).parent
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))


# ============================================================================
# health_check.py Tests
# ============================================================================

class TestHealthCheckImports(unittest.TestCase):
    def test_imports(self):
        from health_check import (
            HealthChecker,
            ServiceStatus,
            HealthCheckResult,
            SystemHealthReport,
            check_system_health,
            get_health_checker,
        )
        self.assertIsNotNone(HealthChecker)
        self.assertIsNotNone(ServiceStatus)
        self.assertIsNotNone(HealthCheckResult)
        self.assertIsNotNone(SystemHealthReport)


class TestServiceStatus(unittest.TestCase):
    def test_status_enum(self):
        from health_check import ServiceStatus
        self.assertEqual(ServiceStatus.HEALTHY.value, "healthy")
        self.assertEqual(ServiceStatus.UNHEALTHY.value, "unhealthy")
        self.assertEqual(ServiceStatus.UNKNOWN.value, "unknown")


class TestHealthCheckResult(unittest.TestCase):
    def test_result_creation(self):
        from health_check import HealthCheckResult, ServiceStatus
        result = HealthCheckResult(
            service_name="test",
            status=ServiceStatus.HEALTHY,
            message="OK",
        )
        self.assertEqual(result.service_name, "test")
        self.assertTrue(result.is_healthy)


class TestHealthChecker(unittest.TestCase):
    def test_init(self):
        from health_check import HealthChecker
        checker = HealthChecker()
        self.assertIsNotNone(checker._checkers)
    
    def test_check_all(self):
        from health_check import HealthChecker, SystemHealthReport
        checker = HealthChecker()
        report = checker.check_all()
        self.assertIsInstance(report, SystemHealthReport)
    
    def test_check_critical(self):
        from health_check import HealthChecker, SystemHealthReport
        checker = HealthChecker()
        report = checker.check_critical()
        self.assertIsInstance(report, SystemHealthReport)


class TestGlobalHealthChecker(unittest.TestCase):
    def test_get_health_checker(self):
        from health_check import get_health_checker, HealthChecker
        checker = get_health_checker()
        self.assertIsInstance(checker, HealthChecker)


# ============================================================================
# resource_config.py Tests
# ============================================================================

class TestResourceConfigImports(unittest.TestCase):
    def test_imports(self):
        from resource_config import (
            ResourceConfig,
            ConcurrencyLimits,
            ResourceThresholds,
            LoadBalancerConfig,
            get_resource_config,
            can_spawn_task,
        )
        self.assertIsNotNone(ResourceConfig)
        self.assertIsNotNone(ConcurrencyLimits)
        self.assertIsNotNone(ResourceThresholds)
        self.assertIsNotNone(LoadBalancerConfig)


class TestConcurrencyLimits(unittest.TestCase):
    def test_defaults(self):
        from resource_config import ConcurrencyLimits
        limits = ConcurrencyLimits()
        self.assertEqual(limits.max_concurrent_tasks, 5)
    
    def test_to_dict(self):
        from resource_config import ConcurrencyLimits
        limits = ConcurrencyLimits(max_concurrent_tasks=10)
        data = limits.to_dict()
        self.assertIn("maxConcurrentTasks", data)


class TestResourceThresholds(unittest.TestCase):
    def test_defaults(self):
        from resource_config import ResourceThresholds
        thresholds = ResourceThresholds()
        self.assertEqual(thresholds.cpu_high_percent, 80.0)


class TestResourceConfig(unittest.TestCase):
    def test_defaults(self):
        from resource_config import ResourceConfig
        config = ResourceConfig()
        self.assertIsNotNone(config.concurrency)
        self.assertIsNotNone(config.thresholds)
    
    def test_can_spawn_task(self):
        from resource_config import ResourceConfig
        config = ResourceConfig()
        can, reason = config.can_spawn_task(current_running=3)
        self.assertTrue(can)
        self.assertEqual(reason, "OK")


class TestGlobalResourceConfig(unittest.TestCase):
    def test_get_resource_config(self):
        from resource_config import get_resource_config, ResourceConfig
        config = get_resource_config()
        self.assertIsInstance(config, ResourceConfig)


# ============================================================================
# status_propagator.py Tests
# ============================================================================

class TestStatusPropagatorImports(unittest.TestCase):
    def test_imports(self):
        from status_propagator import (
            StatusPropagator,
            PropagationEvent,
            PropagationResult,
            get_status_propagator,
        )
        self.assertIsNotNone(StatusPropagator)
        self.assertIsNotNone(PropagationEvent)
        self.assertIsNotNone(PropagationResult)


class TestPropagationEvent(unittest.TestCase):
    def test_event_creation(self):
        from status_propagator import PropagationEvent
        event = PropagationEvent(
            event_type="plan_completed",
            plan_id="plan-123",
        )
        self.assertEqual(event.event_type, "plan_completed")
        self.assertEqual(event.plan_id, "plan-123")


class TestPropagationResult(unittest.TestCase):
    def test_empty_result(self):
        from status_propagator import PropagationResult
        result = PropagationResult()
        self.assertEqual(len(result.triggered_plans), 0)
        self.assertEqual(len(result.errors), 0)


class TestStatusPropagator(unittest.TestCase):
    def test_init(self):
        from status_propagator import StatusPropagator
        propagator = StatusPropagator()
        self.assertIsNotNone(propagator._listeners)
    
    def test_add_listener(self):
        from status_propagator import StatusPropagator
        propagator = StatusPropagator()
        listener = MagicMock()
        propagator.add_listener(listener)
        self.assertIn(listener, propagator._listeners)
    
    def test_get_event_log(self):
        from status_propagator import StatusPropagator
        propagator = StatusPropagator()
        events = propagator.get_event_log()
        self.assertIsInstance(events, list)


class TestGlobalStatusPropagator(unittest.TestCase):
    def test_get_status_propagator(self):
        from status_propagator import get_status_propagator, StatusPropagator
        propagator = get_status_propagator()
        self.assertIsInstance(propagator, StatusPropagator)


# ============================================================================
# shared_workspace.py Tests
# ============================================================================

class TestSharedWorkspaceImports(unittest.TestCase):
    def test_imports(self):
        from shared_workspace import (
            SharedWorkspace,
            WorkspaceFile,
            get_workspace,
            clear_workspace,
        )
        self.assertIsNotNone(SharedWorkspace)
        self.assertIsNotNone(WorkspaceFile)


class TestWorkspaceFile(unittest.TestCase):
    def test_file_creation(self):
        from shared_workspace import WorkspaceFile
        wf = WorkspaceFile(
            path="test.txt",
            agent_id="agent-1",
            created_at=12345,
            updated_at=12345,
        )
        self.assertEqual(wf.path, "test.txt")
        self.assertEqual(wf.agent_id, "agent-1")
    
    def test_file_to_dict(self):
        from shared_workspace import WorkspaceFile
        wf = WorkspaceFile(
            path="file.py",
            agent_id="agent-2",
            created_at=100,
            updated_at=200,
        )
        data = wf.to_dict()
        self.assertIn("path", data)
        self.assertIn("agentId", data)


class TestSharedWorkspace(unittest.TestCase):
    def setUp(self):
        from shared_workspace import SharedWorkspace
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = SharedWorkspace("test-plan", base_dir=Path(self.temp_dir))
    
    def test_init(self):
        self.assertEqual(self.workspace.plan_id, "test-plan")
        self.assertFalse(self.workspace._initialized)
    
    def test_initialize(self):
        self.workspace.initialize()
        self.assertTrue(self.workspace._initialized)
    
    def test_write_and_read_file(self):
        self.workspace.write_file("test.txt", "Hello", "agent-1")
        content = self.workspace.read_file("test.txt")
        self.assertEqual(content, "Hello")
    
    def test_list_files(self):
        self.workspace.write_file("file1.txt", "content1", "agent-1")
        files = self.workspace.list_files()
        self.assertGreaterEqual(len(files), 1)


class TestGlobalWorkspaceFunctions(unittest.TestCase):
    def test_get_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("shared_workspace.ai_devops_home", return_value=Path(tmpdir)):
                from shared_workspace import get_workspace, clear_workspace, SharedWorkspace
                ws = get_workspace("test-plan")
                self.assertIsInstance(ws, SharedWorkspace)
                clear_workspace("test-plan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
