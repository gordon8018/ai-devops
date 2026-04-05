#!/usr/bin/env python3
"""
Process Guardian - Agent 进程守护模块

监控 Agent 进程（通过 tmux 会话），检测崩溃并自动重启。
"""

from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

try:
    from .tmux_manager import TmuxManager
    from .db import get_running_tasks, update_task, get_task
    from .recovery_state_machine import RecoveryStateMachine, RecoveryState, RecoveryConfig
except ImportError:
    from tmux_manager import TmuxManager
    from db import get_running_tasks, update_task, get_task
    from recovery_state_machine import RecoveryStateMachine, RecoveryState, RecoveryConfig


logger = logging.getLogger("process_guardian")


@dataclass
class RestartPolicy:
    """重启策略配置"""
    max_restarts: int = 3  # 最多重启次数
    cooldown_seconds: float = 300.0  # 冷却时间（5分钟）
    
    def can_restart(self, restart_count: int, last_restart_at: Optional[float]) -> bool:
        """检查是否允许重启"""
        if restart_count >= self.max_restarts:
            return False
        
        if last_restart_at is not None:
            elapsed = time.time() - last_restart_at
            if elapsed < self.cooldown_seconds:
                return False
        
        return True


@dataclass
class TaskMonitorState:
    """单个任务的监控状态"""
    task_id: str
    session_name: str
    restart_count: int = 0
    last_restart_at: Optional[float] = None
    last_check_at: Optional[float] = None
    is_alive: bool = True
    consecutive_failures: int = 0


class ProcessGuardian:
    """进程守护类 - 监控并自动恢复崩溃的 Agent 进程"""
    
    DEFAULT_CHECK_INTERVAL = 30.0  # 默认检查间隔（秒）
    
    def __init__(
        self,
        policy: Optional[RestartPolicy] = None,
        check_interval: float = DEFAULT_CHECK_INTERVAL,
        on_restart: Optional[Callable[[str, str], None]] = None,
        on_max_restarts: Optional[Callable[[str, int], None]] = None,
    ):
        self.policy = policy or RestartPolicy()
        self.check_interval = check_interval
        self.on_restart = on_restart  # 回调: (task_id, session_name)
        self.on_max_restarts = on_max_restarts  # 回调: (task_id, restart_count)
        
        self._monitors: dict[str, TaskMonitorState] = {}
        self._last_global_check: float = 0
        
        # 崩溃恢复状态机
        recovery_config = RecoveryConfig(
            max_recovery_attempts=policy.max_restarts if policy else 3,
            recovery_cooldown_seconds=policy.cooldown_seconds if policy else 300.0,
        )
        self._recovery_sm = RecoveryStateMachine(
            config=recovery_config,
            on_state_change=self._on_recovery_state_change,
            on_recovery_attempt=self._on_recovery_attempt,
            on_recovery_success=self._on_recovery_success,
            on_recovery_failed=self._on_recovery_failed,
        )
        
        # 配置日志轮转: 最大 10MB，保留 5 个备份
        self._setup_logging()
    
    def _setup_logging(self) -> None:
        """配置日志处理器，使用 RotatingFileHandler"""
        log_dir = Path(__file__).parent.parent.parent / ".clawdbot" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "process_guardian.log"
        
        # 清除现有处理器
        logger = logging.getLogger("process_guardian")
        logger.handlers.clear()
        
        # 添加 RotatingFileHandler
        handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        # 同时输出到控制台
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            "[%(levelname)s] %(message)s"
        ))
        logger.addHandler(console_handler)
    
    def _get_session_name(self, task: dict) -> Optional[str]:
        """从任务记录中提取 tmux 会话名"""
        session = task.get("tmux_session") or task.get("tmuxSession")
        return session
    
    def _get_worktree(self, task: dict) -> Optional[Path]:
        """从任务记录中提取 worktree 路径"""
        wt = task.get("worktree")
        return Path(wt) if wt else None
    
    def _get_agent(self, task: dict) -> str:
        """获取 agent 类型"""
        return task.get("agent", "codex")
    
    def _get_model(self, task: dict) -> str:
        """获取 model"""
        return task.get("model", "gpt-5.3-codex")
    
    def _get_effort(self, task: dict) -> str:
        """获取 effort"""
        return task.get("effort", "high")
    
    def _get_prompt_file(self, task: dict) -> str:
        """获取 prompt 文件名"""
        pf = task.get("prompt_file") or task.get("promptFile")
        if pf:
            return Path(pf).name
        return "prompt.txt"
    
    # === 恢复状态机回调 ===
    
    def _on_recovery_state_change(self, task_id: str, old_state: 'RecoveryState', new_state: 'RecoveryState') -> None:
        """状态变更回调"""
        logger.info(f"[Recovery] Task {task_id}: {old_state.value} -> {new_state.value}")
    
    def _on_recovery_attempt(self, task_id: str, attempt: int) -> None:
        """恢复尝试回调"""
        logger.warning(f"[Recovery] Task {task_id}: starting recovery attempt #{attempt}")
    
    def _on_recovery_success(self, task_id: str) -> None:
        """恢复成功回调"""
        logger.info(f"[Recovery] Task {task_id}: recovery successful")
    
    def _on_recovery_failed(self, task_id: str, error: str) -> None:
        """恢复失败回调"""
        logger.error(f"[Recovery] Task {task_id}: recovery failed - {error}")

    
    def _build_tmux_manager(self, task: dict) -> Optional[TmuxManager]:
        """为任务构建 TmuxManager 实例"""
        session_name = self._get_session_name(task)
        worktree = self._get_worktree(task)
        
        if not session_name or not worktree:
            return None
        
        agent = self._get_agent(task)
        runner_script = "run-claude-agent.sh" if agent == "claude" else "run-codex-agent.sh"
        
        return TmuxManager(
            session_name=session_name,
            worktree=worktree,
            runner_script=runner_script
        )
    
    def sync_from_db(self) -> None:
        """从数据库同步当前运行中的任务"""
        running_tasks = get_running_tasks()
        
        for task in running_tasks:
            task_id = task["id"]
            if task_id not in self._monitors:
                session_name = self._get_session_name(task)
                if session_name:
                    self._monitors[task_id] = TaskMonitorState(
                        task_id=task_id,
                        session_name=session_name,
                        restart_count=task.get("restart_count", 0) or 0,
                        last_restart_at=task.get("last_restart_at"),
                    )
    
    def check_all(self) -> dict[str, dict]:
        """
        检查所有监控的会话，返回状态变更报告。
        
        Returns:
            dict: {task_id: {"status": "alive|dead|restarted|max_restarts", "detail": ...}}
        """
        now = time.time()
        if now - self._last_global_check < self.check_interval:
            return {}
        
        self._last_global_check = now
        self.sync_from_db()
        
        report: dict[str, dict] = {}
        
        for task_id, monitor in list(self._monitors.items()):
            task = get_task(task_id)
            if task is None:
                # 任务已被删除，移除监控
                del self._monitors[task_id]
                continue
            
            status_code = task.get("status", "")
            if status_code not in ("running", "retrying", "pr_created"):
                # 非活跃任务，跳过检查
                continue
            
            monitor.last_check_at = now
            tm = self._build_tmux_manager(task)
            
            if tm is None:
                # 非 tmux 模式，无法监控
                continue
            
            is_alive = tm.is_healthy
            monitor.is_alive = is_alive
            
            if not is_alive:
                # 会话已消失，记录崩溃检测并尝试恢复
                logger.warning(f"[Guardian] Task {task_id}: crash detected (session {monitor.session_name} dead)")
                
                # 通知状态机开始恢复
                can_start, msg = self._recovery_sm.start_recovery(task_id)
                if not can_start:
                    logger.warning(f"[Guardian] Task {task_id}: cannot start recovery - {msg}")
                
                restart_result = self._attempt_restart(task, monitor)
                report[task_id] = restart_result
            else:
                monitor.consecutive_failures = 0
        
        return report
    
    def _attempt_restart(self, task: dict, monitor: TaskMonitorState) -> dict:
        """尝试重启崩溃的会话"""
        task_id = task["id"]
        restart_count = monitor.restart_count
        last_restart_at = monitor.last_restart_at
        
        if not self.policy.can_restart(restart_count, last_restart_at):
            # 达到重启上限或冷却中
            monitor.consecutive_failures += 1
            
            if restart_count >= self.policy.max_restarts:
                # 达到最大重启次数，通知状态机并标记任务失败
                self._recovery_sm.fail_recovery(task_id, f"Exceeded max restarts ({restart_count})")
                logger.error(f"[Guardian] Task {task_id}: exceeded max restarts ({restart_count})")
                
                update_task(task_id, {
                    "status": "failed",
                    "note": f"Process crashed after {restart_count} restart attempts",
                })
                
                if self.on_max_restarts:
                    self.on_max_restarts(task_id, restart_count)
                
                return {
                    "status": "max_restarts",
                    "detail": f"Exceeded max restarts ({restart_count})",
                }
            
            return {
                "status": "cooldown",
                "detail": f"In cooldown period, last restart at {last_restart_at}",
            }
        
        # 执行重启
        tm = self._build_tmux_manager(task)
        if tm is None:
            return {"status": "error", "detail": "Cannot build TmuxManager"}
        
        agent = self._get_agent(task)
        model = self._get_model(task)
        effort = self._get_effort(task)
        prompt_filename = self._get_prompt_file(task)
        
        success, message = tm.safe_rebuild(
            agent=agent,
            task_id=task_id,
            model=model,
            effort=effort,
            prompt_filename=prompt_filename,
        )
        
        if success:
            now = time.time()
            monitor.restart_count += 1
            monitor.last_restart_at = now
            monitor.consecutive_failures = 0
            
            # 通知状态机恢复成功
            self._recovery_sm.complete_recovery(task_id)
            logger.info(f"[Guardian] Task {task_id}: recovery completed successfully")
            
            # 更新数据库
            update_task(task_id, {
                "restart_count": monitor.restart_count,
                "last_restart_at": now,
                "status": "running",
            })
            
            if self.on_restart:
                self.on_restart(task_id, monitor.session_name)
            
            return {
                "status": "restarted",
                "detail": f"Session restarted (attempt {monitor.restart_count})",
            }
        else:
            monitor.consecutive_failures += 1
            
            # 通知状态机恢复失败
            self._recovery_sm.fail_recovery(task_id, message)
            logger.error(f"[Guardian] Task {task_id}: recovery failed - {message}")
            
            return {
                "status": "restart_failed",
                "detail": f"Failed to restart: {message}",
            }
    
    def add_task(self, task_id: str, session_name: str) -> None:
        """手动添加任务到监控"""
        task = get_task(task_id)
        if task is None:
            return
        
        self._monitors[task_id] = TaskMonitorState(
            task_id=task_id,
            session_name=session_name,
            restart_count=task.get("restart_count", 0) or 0,
            last_restart_at=task.get("last_restart_at"),
        )
    
    def remove_task(self, task_id: str) -> None:
        """从监控中移除任务"""
        self._monitors.pop(task_id, None)
    
    def get_monitor_state(self, task_id: str) -> Optional[TaskMonitorState]:
        """获取任务的监控状态"""
        return self._monitors.get(task_id)
    
    def reset_restart_count(self, task_id: str) -> None:
        """重置任务的重启计数"""
        monitor = self._monitors.get(task_id)
        if monitor:
            monitor.restart_count = 0
            monitor.last_restart_at = None
        
        update_task(task_id, {
            "restart_count": 0,
            "last_restart_at": None,
        })
    
    @property
    def monitored_count(self) -> int:
        """当前监控的任务数量"""
        return len(self._monitors)
    
    def get_all_monitors(self) -> dict[str, TaskMonitorState]:
        """获取所有监控状态（只读）"""
        return dict(self._monitors)

    
    # === 状态机访问方法 ===
    
    def get_recovery_state(self, task_id: str) -> 'RecoveryState':
        """获取任务的恢复状态"""
        return self._recovery_sm.get_state(task_id)
    
    def get_recovery_attempts(self, task_id: str) -> int:
        """获取任务的恢复尝试次数"""
        return self._recovery_sm.get_attempts(task_id)
    
    def reset_recovery(self, task_id: str) -> None:
        """重置任务的恢复状态（用于手动重试）"""
        self._recovery_sm.reset(task_id)
        monitor = self._monitors.get(task_id)
        if monitor:
            monitor.restart_count = 0
            monitor.last_restart_at = None
            monitor.consecutive_failures = 0
        logger.info(f"[Guardian] Task {task_id}: recovery state reset")
    
    @property
    def active_recoveries(self) -> int:
        """当前正在恢复的任务数量"""
        return self._recovery_sm.active_recoveries
