#!/usr/bin/env python3
"""
Heartbeat Management - 心跳管理模块

为任务执行提供心跳机制，用于检测 stale（卡死）任务。

Usage:
    from orchestrator.bin.heartbeat import update_heartbeat, get_last_heartbeat, check_stale
"""

from __future__ import annotations

import time
from typing import Optional

try:
    from .db import get_db
except ImportError:
    from db import get_db


def update_heartbeat(task_id: str) -> None:
    """
    更新任务心跳时间。
    
    Args:
        task_id: 任务ID
    """
    now_ms = int(time.time() * 1000)
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_tasks SET last_heartbeat_at = ?, updated_at = ? WHERE id = ?",
            (now_ms, now_ms, task_id)
        )
        conn.commit()


def get_last_heartbeat(task_id: str) -> Optional[int]:
    """
    获取任务最后心跳时间。
    
    Args:
        task_id: 任务ID
        
    Returns:
        最后心跳时间（毫秒时间戳），如果任务不存在或无心跳记录则返回 None
    """
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT last_heartbeat_at FROM agent_tasks WHERE id = ?",
            (task_id,)
        )
        row = cursor.fetchone()
        if row and row["last_heartbeat_at"]:
            return row["last_heartbeat_at"]
        return None


def check_stale(task_id: str, threshold_minutes: int = 30) -> bool:
    """
    检查任务是否 stale（超过指定时间无心跳）。
    
    Args:
        task_id: 任务ID
        threshold_minutes: 判定为 stale 的阈值（分钟），默认 30 分钟
        
    Returns:
        True 如果任务 stale，False 如果任务活跃或不存在
    """
    last_heartbeat = get_last_heartbeat(task_id)
    if last_heartbeat is None:
        # 无心跳记录，检查 started_at 作为回退
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT started_at, status FROM agent_tasks WHERE id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            # 只对 running/retrying 状态的任务判定 stale
            status = row["status"]
            if status not in ("running", "retrying", "pr_created"):
                return False
            started_at = row["started_at"]
            if not started_at:
                return False
            # 使用 started_at 作为基准时间
            base_time = started_at
    else:
        # 有心跳记录，需要检查任务状态
        with get_db() as conn:
            cursor = conn.execute(
                "SELECT status FROM agent_tasks WHERE id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if not row:
                return False
            status = row["status"]
            # 只对 running/retrying/pr_created 状态的任务判定 stale
            if status not in ("running", "retrying", "pr_created"):
                return False
        base_time = last_heartbeat
    
    now_ms = int(time.time() * 1000)
    elapsed_minutes = (now_ms - base_time) / 60000
    
    return elapsed_minutes > threshold_minutes


def get_stale_tasks(threshold_minutes: int = 30) -> list[dict]:
    """
    获取所有 stale 的任务。
    
    Args:
        threshold_minutes: 判定为 stale 的阈值（分钟）
        
    Returns:
        stale 任务列表
    """
    threshold_ms = int(time.time() * 1000 - threshold_minutes * 60000)
    
    with get_db() as conn:
        # 查找活跃但超时无心跳的任务
        cursor = conn.execute("""
            SELECT * FROM agent_tasks
            WHERE status IN ('running', 'retrying', 'pr_created')
            AND (
                last_heartbeat_at IS NULL AND started_at < ?
                OR last_heartbeat_at IS NOT NULL AND last_heartbeat_at < ?
            )
        """, (threshold_ms, threshold_ms))
        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    # 测试代码
    print("Heartbeat module loaded")
    print("Functions: update_heartbeat, get_last_heartbeat, check_stale, get_stale_tasks")
