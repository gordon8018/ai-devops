#!/usr/bin/env python3
"""
Global Scheduler for AI DevOps

Provides multi-plan priority scheduling with dependency-aware and resource-aware dispatch.

Features:
- Priority-based plan scheduling (global_priority)
- Cross-plan dependency checking (plan_depends_on)
- Resource-aware scheduling (concurrency limits)
- Scheduling decision logging
"""

from __future__ import annotations

import json
import time
import threading
import logging
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional
from collections import defaultdict

try:
    from .config import ai_devops_home, queue_dir
except ImportError:
    from config import ai_devops_home, queue_dir

try:
    from .db import (
        init_db,
        get_all_plans,
        get_plan_status,
        are_plan_dependencies_completed,
        count_running_tasks,
        get_running_tasks,
        get_queued_tasks,
    )
except ImportError:
    from db import (
        init_db,
        get_all_plans,
        get_plan_status,
        are_plan_dependencies_completed,
        count_running_tasks,
        get_running_tasks,
        get_queued_tasks,
    )

try:
    from .status_propagator import StatusPropagator, get_status_propagator
except ImportError:
    from status_propagator import StatusPropagator, get_status_propagator

try:
    from orchestrator.api.events import get_event_manager
except ImportError:
    def get_event_manager():  # type: ignore[no-redef]
        return None


@dataclass
class SchedulingDecision:
    """Represents a scheduling decision for a plan."""
    plan_id: str
    decision: str  # 'dispatched', 'blocked', 'deferred', 'skipped'
    reason: str
    timestamp: int
    priority: int = 0
    dependencies_met: bool = True
    resource_available: bool = True
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "decision": self.decision,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "priority": self.priority,
            "dependenciesMet": self.dependencies_met,
            "resourceAvailable": self.resource_available,
            "details": self.details,
        }


@dataclass
class SchedulerConfig:
    """Configuration for GlobalScheduler."""
    max_concurrent_tasks: int = 5
    max_concurrent_plans: int = 3
    scheduling_interval_sec: float = 5.0
    log_decisions: bool = True
    log_file: Optional[Path] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchedulerConfig":
        return cls(
            max_concurrent_tasks=data.get("maxConcurrentTasks", 5),
            max_concurrent_plans=data.get("maxConcurrentPlans", 3),
            scheduling_interval_sec=data.get("schedulingIntervalSec", 5.0),
            log_decisions=data.get("logDecisions", True),
            log_file=Path(data["logFile"]) if data.get("logFile") else None,
        )


class GlobalScheduler:
    """
    Global scheduler for multi-plan priority scheduling.
    
    Features:
    - Priority-based scheduling (higher global_priority first)
    - Dependency-aware (respects plan_depends_on)
    - Resource-aware (checks concurrency limits)
    - Decision logging for observability
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        event_publisher: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ):
        self.config = config or SchedulerConfig()
        self.event_publisher = event_publisher or self._default_event_publisher
        self._decision_log: list[SchedulingDecision] = []
        self._last_scheduling_time = 0
        init_db()

    def _default_event_publisher(self, event_type: str, payload: dict[str, Any]) -> None:
        manager = get_event_manager()
        if manager is None:
            return
        if event_type == "plan_status":
            manager.publish_plan_status(
                str(payload.get("plan_id") or ""),
                str(payload.get("status") or ""),
                {
                    "reason": payload.get("reason"),
                    "priority": payload.get("priority"),
                },
                source="global_scheduler",
            )

    def _log_decision(self, decision: SchedulingDecision) -> None:
        """Log a scheduling decision."""
        self._decision_log.append(decision)
        if self.event_publisher:
            self.event_publisher(
                "plan_status",
                {
                    "plan_id": decision.plan_id,
                    "status": decision.decision,
                    "reason": decision.reason,
                    "priority": decision.priority,
                },
            )
        
        if not self.config.log_decisions:
            return

        # Console logging
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(decision.timestamp / 1000))
        print(f"[SCHEDULER] [{ts}] Plan {decision.plan_id}: {decision.decision} - {decision.reason}")
        
        # File logging with rotation
        if self.config.log_file:
            try:
                self.config.log_file.parent.mkdir(parents=True, exist_ok=True)
                # 使用 RotatingFileHandler: 最大 10MB，保留 5 个备份
                handler = RotatingFileHandler(
                    self.config.log_file,
                    maxBytes=10*1024*1024,  # 10MB
                    backupCount=5,
                    encoding="utf-8"
                )
                logger = logging.getLogger("scheduler")
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
                logger.info(json.dumps(decision.to_dict(), ensure_ascii=False))
                handler.close()
                logger.removeHandler(handler)
            except Exception as e:
                print(f"[SCHEDULER-ERROR] Failed to write log: {e}")

    def get_pending_plans(self) -> list[dict[str, Any]]:
        """
        Get all pending plans sorted by priority (highest first).
        
        Returns:
            List of plan dictionaries sorted by global_priority (descending)
        """
        all_plans = get_all_plans(limit=100)
        pending_plans = [p for p in all_plans if p.get("status") in ("pending", "running")]
        
        # Sort by global_priority (descending), then by requested_at (ascending)
        pending_plans.sort(
            key=lambda p: (-p.get("global_priority", 0), p.get("requested_at", 0))
        )
        
        return pending_plans

    def check_resource_availability(self) -> tuple[bool, dict[str, Any]]:
        """
        Check if resources are available for new task dispatch.
        
        Returns:
            Tuple of (is_available, resource_info)
        """
        running_count = count_running_tasks()
        queued_tasks = get_queued_tasks()
        queued_count = len(queued_tasks)
        
        # Count active plans (plans with running tasks)
        running_tasks = get_running_tasks()
        active_plan_ids = set()
        for task in running_tasks:
            plan_id = task.get("plan_id")
            if plan_id:
                active_plan_ids.add(plan_id)
        active_plan_count = len(active_plan_ids)
        
        resource_info = {
            "runningTasks": running_count,
            "queuedTasks": queued_count,
            "activePlans": active_plan_count,
            "maxConcurrentTasks": self.config.max_concurrent_tasks,
            "maxConcurrentPlans": self.config.max_concurrent_plans,
        }
        
        # Check resource limits
        task_slots_available = running_count < self.config.max_concurrent_tasks
        plan_slots_available = active_plan_count < self.config.max_concurrent_plans
        
        is_available = task_slots_available and plan_slots_available
        resource_info["taskSlotsAvailable"] = task_slots_available
        resource_info["planSlotsAvailable"] = plan_slots_available
        
        return (is_available, resource_info)

    def check_plan_dependencies(self, plan_id: str) -> tuple[bool, list[str]]:
        """
        Check if a plan's cross-plan dependencies are met.
        
        Args:
            plan_id: The plan ID to check
            
        Returns:
            Tuple of (all_met, list_of_unmet_dependency_ids)
        """
        return are_plan_dependencies_completed(plan_id)

    def should_dispatch_plan(
        self,
        plan: dict[str, Any],
        resource_info: dict[str, Any]
    ) -> SchedulingDecision:
        """
        Determine if a plan should be dispatched now.
        
        Args:
            plan: The plan dictionary
            resource_info: Current resource availability info
            
        Returns:
            SchedulingDecision indicating what to do
        """
        plan_id = plan["plan_id"]
        timestamp = int(time.time() * 1000)
        priority = plan.get("global_priority", 0)
        
        # Check cross-plan dependencies
        deps_met, unmet_deps = self.check_plan_dependencies(plan_id)
        if not deps_met:
            return SchedulingDecision(
                plan_id=plan_id,
                decision="blocked",
                reason=f"Waiting for dependencies: {', '.join(unmet_deps)}",
                timestamp=timestamp,
                priority=priority,
                dependencies_met=False,
                details={"unmetDependencies": unmet_deps},
            )
        
        # Check resource availability
        if not resource_info.get("taskSlotsAvailable", True):
            return SchedulingDecision(
                plan_id=plan_id,
                decision="deferred",
                reason=f"Task capacity reached ({resource_info['runningTasks']}/{resource_info['maxConcurrentTasks']})",
                timestamp=timestamp,
                priority=priority,
                resource_available=False,
                details=resource_info,
            )
        
        if not resource_info.get("planSlotsAvailable", True):
            return SchedulingDecision(
                plan_id=plan_id,
                decision="deferred",
                reason=f"Plan capacity reached ({resource_info['activePlans']}/{resource_info['maxConcurrentPlans']})",
                timestamp=timestamp,
                priority=priority,
                resource_available=False,
                details=resource_info,
            )
        
        # All checks passed - dispatch
        return SchedulingDecision(
            plan_id=plan_id,
            decision="dispatched",
            reason="Dependencies met and resources available",
            timestamp=timestamp,
            priority=priority,
            details=resource_info,
        )

    def schedule(self) -> list[SchedulingDecision]:
        """
        Perform a scheduling cycle.
        
        This is the main entry point for the scheduler. It:
        1. Wakes up blocked plans whose dependencies are now satisfied
        2. Gets pending plans sorted by priority
        3. Checks resource availability
        4. For each plan, checks dependencies and resources
        5. Makes scheduling decisions
        6. Logs decisions
        
        Returns:
            List of SchedulingDecision objects
        """
        self._last_scheduling_time = int(time.time() * 1000)
        decisions: list[SchedulingDecision] = []
        
        # First, wake up any blocked plans whose dependencies are now satisfied
        try:
            propagator = get_status_propagator()
            wake_result = propagator.wake_blocked_plans()
            if wake_result.get("wokenPlans"):
                self._log_decision(SchedulingDecision(
                    plan_id="__system__",
                    decision="woken",
                    reason=f"Woke {len(wake_result['wokenPlans'])} plans with satisfied dependencies",
                    timestamp=int(time.time() * 1000),
                    details=wake_result,
                ))
        except Exception as e:
            print(f"[SCHEDULER] Wake blocked plans failed: {e}")
        
        # Get pending plans
        pending_plans = self.get_pending_plans()
        if not pending_plans:
            return decisions
        
        # Check resource availability once
        resource_available, resource_info = self.check_resource_availability()
        
        # Make decisions for each plan
        for plan in pending_plans:
            decision = self.should_dispatch_plan(plan, resource_info)
            decisions.append(decision)
            self._log_decision(decision)
            
            # If we dispatched, update resource info for next plan
            if decision.decision == "dispatched":
                resource_info["runningTasks"] = resource_info.get("runningTasks", 0) + 1
        
        return decisions

    def get_decision_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get recent scheduling decisions.
        
        Args:
            limit: Maximum number of decisions to return
            
        Returns:
            List of decision dictionaries (most recent first)
        """
        recent = self._decision_log[-limit:] if limit else self._decision_log
        return [d.to_dict() for d in reversed(recent)]

    def clear_decision_log(self) -> None:
        """Clear the in-memory decision log."""
        self._decision_log.clear()

    def get_scheduling_summary(self) -> dict[str, Any]:
        """
        Get a summary of current scheduling state.
        
        Returns:
            Dictionary with scheduling statistics
        """
        resource_available, resource_info = self.check_resource_availability()
        pending_plans = self.get_pending_plans()
        
        # Categorize plans
        by_status = defaultdict(int)
        by_priority = defaultdict(int)
        for plan in pending_plans:
            status = plan.get("status", "unknown")
            priority = plan.get("global_priority", 0)
            by_status[status] += 1
            by_priority[priority] += 1
        
        return {
            "timestamp": int(time.time() * 1000),
            "lastSchedulingTime": self._last_scheduling_time,
            "resourceAvailable": resource_available,
            "resourceInfo": resource_info,
            "pendingPlans": len(pending_plans),
            "plansByStatus": dict(by_status),
            "plansByPriority": dict(by_priority),
            "totalDecisions": len(self._decision_log),
        }


def create_default_scheduler(
    max_concurrent_tasks: int = 5,
    max_concurrent_plans: int = 3,
    log_file: Optional[Path] = None,
) -> GlobalScheduler:
    """
    Create a GlobalScheduler with default configuration.
    
    Args:
        max_concurrent_tasks: Maximum concurrent tasks
        max_concurrent_plans: Maximum concurrent plans
        log_file: Optional log file path
        
    Returns:
        Configured GlobalScheduler instance
    """
    config = SchedulerConfig(
        max_concurrent_tasks=max_concurrent_tasks,
        max_concurrent_plans=max_concurrent_plans,
        log_file=log_file,
    )
    return GlobalScheduler(config)


# Module-level singleton and lock for thread-safe initialization
_global_scheduler: Optional[GlobalScheduler] = None
_scheduler_lock = threading.Lock()


def get_global_scheduler() -> GlobalScheduler:
    """
    Get the module-level GlobalScheduler singleton.
    
    Thread-safe implementation using double-checked locking pattern.
    
    Returns:
        GlobalScheduler instance
    """
    global _global_scheduler
    if _global_scheduler is None:
        with _scheduler_lock:
            # Double-check after acquiring lock
            if _global_scheduler is None:
                # Default configuration
                log_path = ai_devops_home() / "logs" / "scheduler.log"
                _global_scheduler = create_default_scheduler(log_file=log_path)
    return _global_scheduler


def reset_global_scheduler() -> None:
    """Reset the module-level GlobalScheduler singleton.
    
    Thread-safe implementation.
    """
    global _global_scheduler
    with _scheduler_lock:
        _global_scheduler = None
