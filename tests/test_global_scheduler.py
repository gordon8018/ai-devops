#!/usr/bin/env python3
"""
Tests for global_scheduler.py
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from orchestrator.bin.global_scheduler import (
    GlobalScheduler,
    SchedulerConfig,
    SchedulingDecision,
    create_default_scheduler,
    get_global_scheduler,
    reset_global_scheduler,
)


class TestSchedulingDecision(unittest.TestCase):
    """Test SchedulingDecision dataclass"""
    
    def test_to_dict(self):
        decision = SchedulingDecision(
            plan_id="test-plan",
            decision="dispatched",
            reason="Dependencies met",
            timestamp=1234567890,
            priority=10,
        )
        result = decision.to_dict()
        
        self.assertEqual(result["planId"], "test-plan")
        self.assertEqual(result["decision"], "dispatched")
        self.assertEqual(result["priority"], 10)
        self.assertTrue(result["dependenciesMet"])
        self.assertTrue(result["resourceAvailable"])


class TestSchedulerConfig(unittest.TestCase):
    """Test SchedulerConfig"""
    
    def test_default_config(self):
        config = SchedulerConfig()
        self.assertEqual(config.max_concurrent_tasks, 5)
        self.assertEqual(config.max_concurrent_plans, 3)
        self.assertTrue(config.log_decisions)
    
    def test_custom_config(self):
        config = SchedulerConfig(
            max_concurrent_tasks=10,
            max_concurrent_plans=5,
            log_decisions=False,
        )
        self.assertEqual(config.max_concurrent_tasks, 10)
        self.assertEqual(config.max_concurrent_plans, 5)
        self.assertFalse(config.log_decisions)
    
    def test_from_dict(self):
        data = {
            "maxConcurrentTasks": 8,
            "maxConcurrentPlans": 4,
        }
        config = SchedulerConfig.from_dict(data)
        self.assertEqual(config.max_concurrent_tasks, 8)
        self.assertEqual(config.max_concurrent_plans, 4)


class TestGlobalScheduler(unittest.TestCase):
    """Test GlobalScheduler class"""
    
    def setUp(self):
        reset_global_scheduler()
    
    def test_init(self):
        scheduler = GlobalScheduler()
        self.assertIsNotNone(scheduler.config)
        self.assertEqual(len(scheduler._decision_log), 0)
    
    def test_get_pending_plans_empty(self):
        scheduler = GlobalScheduler()
        
        with patch('orchestrator.bin.global_scheduler.get_all_plans') as mock:
            mock.return_value = []
            plans = scheduler.get_pending_plans()
            self.assertEqual(len(plans), 0)
    
    def test_get_pending_plans_sorted_by_priority(self):
        scheduler = GlobalScheduler()
        
        mock_plans = [
            {"plan_id": "plan1", "status": "pending", "global_priority": 5, "requested_at": 100},
            {"plan_id": "plan2", "status": "pending", "global_priority": 10, "requested_at": 200},
            {"plan_id": "plan3", "status": "pending", "global_priority": 5, "requested_at": 50},
        ]
        
        with patch('orchestrator.bin.global_scheduler.get_all_plans') as mock:
            mock.return_value = mock_plans
            plans = scheduler.get_pending_plans()
            
            # Should be sorted by priority (descending), then requested_at (ascending)
            self.assertEqual(plans[0]["plan_id"], "plan2")  # priority 10
            self.assertEqual(plans[1]["plan_id"], "plan3")  # priority 5, requested_at 50
            self.assertEqual(plans[2]["plan_id"], "plan1")  # priority 5, requested_at 100
    
    def test_check_resource_availability(self):
        scheduler = GlobalScheduler()
        
        with patch('orchestrator.bin.global_scheduler.count_running_tasks') as mock_count, \
             patch('orchestrator.bin.global_scheduler.get_queued_tasks') as mock_queued, \
             patch('orchestrator.bin.global_scheduler.get_running_tasks') as mock_running:
            
            mock_count.return_value = 2
            mock_queued.return_value = []
            mock_running.return_value = []
            
            available, info = scheduler.check_resource_availability()
            
            self.assertTrue(available)
            self.assertEqual(info["runningTasks"], 2)
            self.assertEqual(info["activePlans"], 0)
    
    def test_check_resource_availability_limit_reached(self):
        config = SchedulerConfig(max_concurrent_tasks=2)
        scheduler = GlobalScheduler(config)
        
        with patch('orchestrator.bin.global_scheduler.count_running_tasks') as mock_count, \
             patch('orchestrator.bin.global_scheduler.get_queued_tasks') as mock_queued, \
             patch('orchestrator.bin.global_scheduler.get_running_tasks') as mock_running:
            
            mock_count.return_value = 3
            mock_queued.return_value = []
            mock_running.return_value = []
            
            available, info = scheduler.check_resource_availability()
            
            self.assertFalse(available)
            self.assertFalse(info["taskSlotsAvailable"])
    
    def test_check_plan_dependencies(self):
        scheduler = GlobalScheduler()
        
        with patch('orchestrator.bin.global_scheduler.are_plan_dependencies_completed') as mock:
            mock.return_value = (True, [])
            
            met, unmet = scheduler.check_plan_dependencies("plan1")
            self.assertTrue(met)
            self.assertEqual(len(unmet), 0)
    
    def test_should_dispatch_plan_blocked_by_dependencies(self):
        scheduler = GlobalScheduler()
        plan = {"plan_id": "plan1", "global_priority": 5}
        resource_info = {"taskSlotsAvailable": True, "planSlotsAvailable": True}
        
        with patch('orchestrator.bin.global_scheduler.are_plan_dependencies_completed') as mock:
            mock.return_value = (False, ["dep1"])
            
            decision = scheduler.should_dispatch_plan(plan, resource_info)
            
            self.assertEqual(decision.decision, "blocked")
            self.assertFalse(decision.dependencies_met)
            self.assertIn("dep1", decision.reason)
    
    def test_should_dispatch_plan_dispatched(self):
        scheduler = GlobalScheduler()
        plan = {"plan_id": "plan1", "global_priority": 5}
        resource_info = {
            "taskSlotsAvailable": True,
            "planSlotsAvailable": True,
            "runningTasks": 1,
            "maxConcurrentTasks": 5,
        }
        
        with patch('orchestrator.bin.global_scheduler.are_plan_dependencies_completed') as mock:
            mock.return_value = (True, [])
            
            decision = scheduler.should_dispatch_plan(plan, resource_info)
            
            self.assertEqual(decision.decision, "dispatched")
            self.assertTrue(decision.dependencies_met)
            self.assertTrue(decision.resource_available)
    
    def test_schedule_empty(self):
        scheduler = GlobalScheduler()
        
        with patch('orchestrator.bin.global_scheduler.get_all_plans') as mock:
            mock.return_value = []
            
            decisions = scheduler.schedule()
            self.assertEqual(len(decisions), 0)
    
    def test_get_decision_log(self):
        scheduler = GlobalScheduler()
        
        # Add some decisions
        for i in range(5):
            decision = SchedulingDecision(
                plan_id=f"plan{i}",
                decision="dispatched",
                reason="Test",
                timestamp=1000 + i,
            )
            scheduler._decision_log.append(decision)
        
        log = scheduler.get_decision_log(limit=3)
        self.assertEqual(len(log), 3)
        # Should be most recent first
        self.assertEqual(log[0]["planId"], "plan4")


class TestModuleFunctions(unittest.TestCase):
    """Test module-level functions"""
    
    def setUp(self):
        reset_global_scheduler()
    
    def test_create_default_scheduler(self):
        scheduler = create_default_scheduler(
            max_concurrent_tasks=10,
            max_concurrent_plans=5,
        )
        self.assertEqual(scheduler.config.max_concurrent_tasks, 10)
        self.assertEqual(scheduler.config.max_concurrent_plans, 5)
    
    def test_get_global_scheduler_singleton(self):
        scheduler1 = get_global_scheduler()
        scheduler2 = get_global_scheduler()
        self.assertIs(scheduler1, scheduler2)
    
    def test_reset_global_scheduler(self):
        scheduler1 = get_global_scheduler()
        reset_global_scheduler()
        scheduler2 = get_global_scheduler()
        self.assertIsNot(scheduler1, scheduler2)


if __name__ == "__main__":
    unittest.main()
