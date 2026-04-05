#!/usr/bin/env python3
"""
Status Propagator - 状态传播器

负责跨 Plan 状态传播，当 Plan 完成时触发依赖 Plan 的派发。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home

try:
    from .db import (
        get_plan, get_plan_status, get_all_plans,
        update_plan, are_plan_dependencies_completed,
    )
except ImportError:
    from db import (
        get_plan, get_plan_status, get_all_plans,
        update_plan, are_plan_dependencies_completed,
    )

logger = logging.getLogger(__name__)


@dataclass
class PropagationEvent:
    """状态传播事件"""
    event_type: str
    plan_id: str
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "eventType": self.event_type,
            "planId": self.plan_id,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass 
class PropagationResult:
    """传播结果"""
    triggered_plans: list[str] = field(default_factory=list)
    blocked_plans: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "triggeredPlans": self.triggered_plans,
            "blockedPlans": self.blocked_plans,
            "errors": self.errors,
        }


class StatusPropagator:
    """状态传播器 - 负责跨 Plan 状态传播"""
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or ai_devops_home()
        self._listeners: list[Callable[[PropagationEvent], None]] = []
        self._event_log: list[PropagationEvent] = []
        self._lock = threading.Lock()
        self._max_event_log = 1000
    
    def add_listener(self, listener: Callable[[PropagationEvent], None]) -> None:
        """添加事件监听器"""
        self._listeners.append(listener)
    
    def remove_listener(self, listener: Callable[[PropagationEvent], None]) -> None:
        """移除事件监听器"""
        if listener in self._listeners:
            self._listeners.remove(listener)
    
    def _emit_event(self, event: PropagationEvent) -> None:
        """发射事件到所有监听器"""
        with self._lock:
            self._event_log.append(event)
            if len(self._event_log) > self._max_event_log:
                self._event_log = self._event_log[-self._max_event_log:]
        
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as e:
                logger.error(f"Listener error: {e}")
    def on_plan_completed(self, plan_id: str) -> PropagationResult:
        """Plan 完成时的处理"""
        result = PropagationResult()
        
        try:
            update_plan(plan_id, {"status": "completed"})
        except Exception as e:
            result.errors.append(f"Failed to update plan status: {e}")
            logger.error(f"Failed to update plan status for {plan_id}: {e}")
            return result
        
        event = PropagationEvent(
            event_type="plan_completed",
            plan_id=plan_id,
            details={"status": "completed"},
        )
        self._emit_event(event)
        logger.info(f"Plan {plan_id} completed, checking dependents...")
        
        dependent_plans = self._find_dependent_plans(plan_id)
        
        for dep_plan_id in dependent_plans:
            try:
                deps_met, _ = are_plan_dependencies_completed(dep_plan_id)
                if deps_met:
                    self._trigger_plan_dispatch(dep_plan_id)
                    result.triggered_plans.append(dep_plan_id)
                    logger.info(f"Triggered dependent plan: {dep_plan_id}")
                else:
                    result.blocked_plans.append(dep_plan_id)
            except Exception as e:
                result.errors.append(f"Error processing {dep_plan_id}: {e}")
                logger.error(f"Error processing dependent plan {dep_plan_id}: {e}")
        
        return result
    
    def on_plan_failed(self, plan_id: str, error: str) -> PropagationResult:
        """Plan 失败时的处理"""
        result = PropagationResult()
        
        try:
            update_plan(plan_id, {"status": "failed", "error": error})
        except Exception as e:
            result.errors.append(f"Failed to update plan status: {e}")
            return result
        
        event = PropagationEvent(
            event_type="plan_failed",
            plan_id=plan_id,
            details={"error": error, "status": "failed"},
        )
        self._emit_event(event)
        logger.warning(f"Plan {plan_id} failed: {error}")
        
        dependent_plans = self._find_dependent_plans(plan_id)
        for dep_plan_id in dependent_plans:
            result.blocked_plans.append(dep_plan_id)
            logger.warning(f"Plan {dep_plan_id} blocked due to dependency failure")
        
        return result
    def _find_dependent_plans(self, plan_id: str) -> list[str]:
        """查找依赖于指定 Plan 的所有 Plan"""
        try:
            all_plans = get_all_plans(limit=1000)
        except Exception as e:
            logger.error(f"Failed to get all plans: {e}")
            return []
        
        dependent = []
        for plan in all_plans:
            current_id = plan.get("plan_id") or plan.get("planId")
            if current_id == plan_id:
                continue
            
            deps_raw = plan.get("plan_depends_on") or plan.get("planDependsOn") or "[]"
            if isinstance(deps_raw, str):
                try:
                    deps = json.loads(deps_raw)
                except json.JSONDecodeError:
                    deps = []
            else:
                deps = list(deps_raw) if deps_raw else []
            
            if plan_id in deps:
                dependent.append(current_id)
        
        return dependent
    
    def _trigger_plan_dispatch(self, plan_id: str) -> bool:
        """触发 Plan 派发"""
        try:
            update_plan(plan_id, {"status": "ready"})
            event = PropagationEvent(
                event_type="dependency_met",
                plan_id=plan_id,
                details={"action": "dispatch_triggered"},
            )
            self._emit_event(event)
            return True
        except Exception as e:
            logger.error(f"Failed to trigger dispatch for {plan_id}: {e}")
            return False
    

    def on_plan_status_change(self, plan_id: str, old_status: str, new_status: str) -> None:
        """处理 Plan 状态变更
        
        Args:
            plan_id: Plan ID
            old_status: 旧状态
            new_status: 新状态
        """
        logger.info(f"Plan {plan_id} status changed: {old_status} -> {new_status}")
        
        event = PropagationEvent(
            event_type="status_changed",
            plan_id=plan_id,
            details={
                "oldStatus": old_status,
                "newStatus": new_status,
            },
        )
        self._emit_event(event)
        
        # 如果状态变为 completed，触发依赖检查
        if new_status == "completed":
            self.on_plan_completed(plan_id)
        elif new_status == "failed":
            # 失败状态需要错误信息，这里使用默认值
            self.on_plan_failed(plan_id, "Status changed to failed")

    def get_event_log(self, limit: int = 100) -> list[PropagationEvent]:
        """获取事件日志"""
        with self._lock:
            return list(self._event_log[-limit:])
    
    def clear_event_log(self) -> None:
        """清空事件日志"""
        with self._lock:
            self._event_log.clear()

# === 单例模式 ===

_instance: Optional[StatusPropagator] = None
_lock = threading.Lock()


def get_status_propagator() -> StatusPropagator:
    """获取全局 StatusPropagator 实例"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = StatusPropagator()
    return _instance


def set_status_propagator(propagator: StatusPropagator) -> None:
    """设置全局 StatusPropagator 实例"""
    global _instance
    with _lock:
        _instance = propagator


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Status Propagator")
    parser.add_argument("--log", action="store_true", help="Show event log")
    args = parser.parse_args()
    
    prop = get_status_propagator()
    if args.log:
        for e in prop.get_event_log():
            print(f"[{e.event_type}] {e.plan_id}: {e.details}")
    else:
        print("Status Propagator - use --log to show events")
