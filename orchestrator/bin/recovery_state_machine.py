#!/usr/bin/env python3
"""
Recovery State Machine - 崩溃恢复状态机

管理任务崩溃后的恢复流程：
- detecting：检测崩溃
- recovering：正在恢复
- recovered：恢复成功
- failed：恢复失败

状态转换：
  detecting → recovering (开始恢复)
  recovering → recovered (恢复成功)
  recovering → failed (恢复失败/超过重试次数)
  failed → detecting (手动重试)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any

try:
    from .db import update_task, get_task
except ImportError:
    from db import update_task, get_task


class RecoveryState(Enum):
    """恢复状态枚举"""
    DETECTING = "detecting"
    RECOVERING = "recovering"
    RECOVERED = "recovered"
    FAILED = "failed"


# 状态转换表：定义允许的转换
VALID_TRANSITIONS: dict[RecoveryState, set[RecoveryState]] = {
    RecoveryState.DETECTING: {RecoveryState.RECOVERING},
    RecoveryState.RECOVERING: {RecoveryState.RECOVERED, RecoveryState.FAILED},
    RecoveryState.RECOVERED: set(),  # 终态
    RecoveryState.FAILED: {RecoveryState.DETECTING},  # 允许手动重试
}


@dataclass
class RecoveryConfig:
    """恢复策略配置"""
    max_recovery_attempts: int = 3  # 最大恢复尝试次数
    recovery_cooldown_seconds: float = 300.0  # 恢复冷却时间（秒）
    detection_timeout_seconds: float = 60.0  # 检测超时时间
    recovery_timeout_seconds: float = 600.0  # 单次恢复超时时间（10分钟）
    backoff_multiplier: float = 1.5  # 退避乘数
    max_backoff_seconds: float = 1800.0  # 最大退避时间（30分钟）


@dataclass
class RecoveryContext:
    """恢复上下文信息"""
    task_id: str
    state: RecoveryState = RecoveryState.DETECTING
    attempts: int = 0
    started_at: Optional[float] = None
    last_attempt_at: Optional[float] = None
    last_error: Optional[str] = None
    recovery_metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "attempts": self.attempts,
            "started_at": self.started_at,
            "last_attempt_at": self.last_attempt_at,
            "last_error": self.last_error,
            "recovery_metadata": self.recovery_metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "RecoveryContext":
        """从字典创建"""
        return cls(
            task_id=data.get("task_id", ""),
            state=RecoveryState(data.get("state", "detecting")),
            attempts=data.get("attempts", 0),
            started_at=data.get("started_at"),
            last_attempt_at=data.get("last_attempt_at"),
            last_error=data.get("last_error"),
            recovery_metadata=data.get("recovery_metadata", {}),
        )


class RecoveryStateMachine:
    """
    崩溃恢复状态机
    
    负责管理任务崩溃后的恢复流程，包括：
    - 状态转换验证
    - 恢复尝试计数
    - 冷却时间和退避策略
    - 恢复日志记录
    """
    
    def __init__(
        self,
        config: Optional[RecoveryConfig] = None,
        on_state_change: Optional[Callable[[str, RecoveryState, RecoveryState], None]] = None,
        on_recovery_attempt: Optional[Callable[[str, int], None]] = None,
        on_recovery_success: Optional[Callable[[str], None]] = None,
        on_recovery_failed: Optional[Callable[[str, str], None]] = None,
    ):
        self.config = config or RecoveryConfig()
        self.on_state_change = on_state_change  # 回调: (task_id, old_state, new_state)
        self.on_recovery_attempt = on_recovery_attempt  # 回调: (task_id, attempt_number)
        self.on_recovery_success = on_recovery_success  # 回调: (task_id)
        self.on_recovery_failed = on_recovery_failed  # 回调: (task_id, error_message)
        
        # 任务恢复上下文缓存
        self._contexts: dict[str, RecoveryContext] = {}
    
    def get_context(self, task_id: str) -> RecoveryContext:
        """获取或创建任务的恢复上下文"""
        if task_id not in self._contexts:
            # 尝试从数据库加载
            task = get_task(task_id)
            if task and task.get("recovery_metadata"):
                try:
                    import json
                    metadata = json.loads(task["recovery_metadata"])
                    if isinstance(metadata, dict):
                        self._contexts[task_id] = RecoveryContext.from_dict(metadata)
                except (json.JSONDecodeError, ValueError):
                    pass
            
            if task_id not in self._contexts:
                self._contexts[task_id] = RecoveryContext(task_id=task_id)
        
        return self._contexts[task_id]
    
    def can_transition(self, task_id: str, new_state: RecoveryState) -> tuple[bool, str]:
        """
        检查是否可以进行状态转换
        
        Returns:
            (can_transition, reason)
        """
        ctx = self.get_context(task_id)
        current_state = ctx.state
        
        if new_state not in VALID_TRANSITIONS.get(current_state, set()):
            return False, f"Invalid transition: {current_state.value} -> {new_state.value}"
        
        # 检查恢复次数限制
        if new_state == RecoveryState.RECOVERING:
            if ctx.attempts >= self.config.max_recovery_attempts:
                return False, f"Max recovery attempts ({self.config.max_recovery_attempts}) exceeded"
            
            # 检查冷却时间
            if ctx.last_attempt_at is not None:
                elapsed = time.time() - ctx.last_attempt_at
                cooldown = self._calculate_backoff(ctx.attempts)
                if elapsed < cooldown:
                    return False, f"In cooldown period ({cooldown - elapsed:.1f}s remaining)"
        
        return True, "OK"
    
    def transition(self, task_id: str, new_state: RecoveryState, error: Optional[str] = None) -> bool:
        """
        执行状态转换
        
        Args:
            task_id: 任务ID
            new_state: 新状态
            error: 可选的错误信息（用于 failed 状态）
        
        Returns:
            转换是否成功
        """
        can_trans, reason = self.can_transition(task_id, new_state)
        if not can_trans:
            return False
        
        ctx = self.get_context(task_id)
        old_state = ctx.state
        
        # 更新上下文
        ctx.state = new_state
        ctx.last_error = error
        
        if new_state == RecoveryState.RECOVERING:
            if ctx.started_at is None:
                ctx.started_at = time.time()
            ctx.attempts += 1
            ctx.last_attempt_at = time.time()
            
            if self.on_recovery_attempt:
                self.on_recovery_attempt(task_id, ctx.attempts)
        
        elif new_state == RecoveryState.RECOVERED:
            if self.on_recovery_success:
                self.on_recovery_success(task_id)
        
        elif new_state == RecoveryState.FAILED:
            if self.on_recovery_failed:
                self.on_recovery_failed(task_id, error or "Recovery failed")
        
        # 持久化到数据库
        self._persist_context(ctx)
        
        # 触发状态变更回调
        if self.on_state_change:
            self.on_state_change(task_id, old_state, new_state)
        
        return True
    
    def start_detection(self, task_id: str) -> bool:
        """
        开始检测崩溃
        
        如果任务不在恢复流程中，初始化为 detecting 状态
        """
        ctx = self.get_context(task_id)
        
        # 如果已经处于恢复流程，不做操作
        if ctx.state != RecoveryState.DETECTING:
            return False
        
        ctx.started_at = time.time()
        self._persist_context(ctx)
        return True
    
    def start_recovery(self, task_id: str) -> tuple[bool, str]:
        """
        开始恢复流程
        
        Returns:
            (success, message)
        """
        can_trans, reason = self.can_transition(task_id, RecoveryState.RECOVERING)
        if not can_trans:
            return False, reason
        
        success = self.transition(task_id, RecoveryState.RECOVERING)
        if success:
            return True, f"Recovery started (attempt {self.get_context(task_id).attempts})"
        return False, "Failed to transition to recovering state"
    
    def complete_recovery(self, task_id: str) -> bool:
        """
        标记恢复成功
        """
        return self.transition(task_id, RecoveryState.RECOVERED)
    
    def fail_recovery(self, task_id: str, error: str) -> bool:
        """
        标记恢复失败
        """
        return self.transition(task_id, RecoveryState.FAILED, error=error)
    
    def reset(self, task_id: str) -> None:
        """
        重置恢复状态（用于手动重试）
        """
        if task_id in self._contexts:
            ctx = self._contexts[task_id]
            ctx.state = RecoveryState.DETECTING
            ctx.attempts = 0
            ctx.started_at = None
            ctx.last_attempt_at = None
            ctx.last_error = None
            ctx.recovery_metadata = {}
            self._persist_context(ctx)
    
    def get_state(self, task_id: str) -> RecoveryState:
        """获取任务当前的恢复状态"""
        return self.get_context(task_id).state
    
    def get_attempts(self, task_id: str) -> int:
        """获取任务的恢复尝试次数"""
        return self.get_context(task_id).attempts
    
    def get_next_attempt_after(self, task_id: str) -> Optional[float]:
        """
        获取下次可尝试恢复的时间戳
        
        Returns:
            下次可尝试的时间戳，如果当前可尝试则返回 None
        """
        ctx = self.get_context(task_id)
        
        if ctx.state != RecoveryState.RECOVERING:
            return None
        
        if ctx.last_attempt_at is None:
            return None
        
        cooldown = self._calculate_backoff(ctx.attempts)
        next_attempt_at = ctx.last_attempt_at + cooldown
        
        if time.time() >= next_attempt_at:
            return None
        
        return next_attempt_at
    
    def _calculate_backoff(self, attempt: int) -> float:
        """
        计算退避时间
        
        使用指数退避策略
        """
        if attempt <= 0:
            return self.config.recovery_cooldown_seconds
        
        backoff = self.config.recovery_cooldown_seconds * (
            self.config.backoff_multiplier ** (attempt - 1)
        )
        return min(backoff, self.config.max_backoff_seconds)
    
    def _persist_context(self, ctx: RecoveryContext) -> None:
        """将恢复上下文持久化到数据库"""
        import json
        
        update_data = {
            "recovery_state": ctx.state.value,
            "recovery_attempts": ctx.attempts,
            "recovery_started_at": int(ctx.started_at * 1000) if ctx.started_at else None,
            "recovery_metadata": json.dumps(ctx.to_dict()),
        }
        
        # 移除 None 值
        update_data = {k: v for k, v in update_data.items() if v is not None}
        
        update_task(ctx.task_id, update_data)
    
    @property
    def active_recoveries(self) -> int:
        """当前正在恢复的任务数量"""
        return sum(
            1 for ctx in self._contexts.values()
            if ctx.state == RecoveryState.RECOVERING
        )
    
    def get_all_contexts(self) -> dict[str, RecoveryContext]:
        """获取所有恢复上下文（只读）"""
        return dict(self._contexts)


# 便捷函数
def create_default_state_machine() -> RecoveryStateMachine:
    """创建默认配置的状态机"""
    return RecoveryStateMachine(
        config=RecoveryConfig(),
        on_state_change=_default_state_change_logger,
    )


def _default_state_change_logger(task_id: str, old_state: RecoveryState, new_state: RecoveryState) -> None:
    """默认的状态变更日志记录器"""
    import logging
    logger = logging.getLogger("recovery_state_machine")
    logger.info(f"Task {task_id}: {old_state.value} -> {new_state.value}")


if __name__ == "__main__":
    # 简单测试
    sm = RecoveryStateMachine()
    
    # 测试状态转换
    print("Testing state machine...")
    
    task_id = "test-task-001"
    
    # detecting -> recovering
    success, msg = sm.start_recovery(task_id)
    print(f"Start recovery: {success}, {msg}")
    print(f"State: {sm.get_state(task_id).value}")
    print(f"Attempts: {sm.get_attempts(task_id)}")
    
    # recovering -> recovered
    success = sm.complete_recovery(task_id)
    print(f"Complete recovery: {success}")
    print(f"State: {sm.get_state(task_id).value}")
    
    # Reset
    sm.reset(task_id)
    print(f"After reset: {sm.get_state(task_id).value}")
    print(f"Attempts after reset: {sm.get_attempts(task_id)}")
    
    print("\nState machine test completed.")
