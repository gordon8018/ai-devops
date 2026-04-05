#!/usr/bin/env python3
"""
Health Check Module - 系统健康检查

提供 zoe-daemon、monitor 和其他关键服务的健康状态检测。

Usage:
    from orchestrator.bin.health_check import HealthChecker, check_system_health
    
    checker = HealthChecker()
    status = checker.check_all()
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home


class ServiceStatus(Enum):
    """服务状态枚举"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    STARTING = "starting"
    STOPPED = "stopped"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    service_name: str
    status: ServiceStatus
    message: str = ""
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    details: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "serviceName": self.service_name,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "details": self.details,
        }
    
    @property
    def is_healthy(self) -> bool:
        return self.status == ServiceStatus.HEALTHY


@dataclass
class SystemHealthReport:
    """系统健康报告"""
    overall_status: ServiceStatus
    checks: list[HealthCheckResult] = field(default_factory=list)
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "overallStatus": self.overall_status.value,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp,
            "healthyCount": sum(1 for c in self.checks if c.is_healthy),
            "unhealthyCount": sum(1 for c in self.checks if not c.is_healthy),
        }

class HealthChecker:
    """系统健康检查器
    
    检查各个服务的健康状态：
    - zoe-daemon 进程
    - monitor 进程
    - 数据库连接
    - 磁盘空间
    - tmux 可用性
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or ai_devops_home()
        self._checkers: dict[str, Callable[[], HealthCheckResult]] = {
            "zoe-daemon": self._check_zoe_daemon,
            "monitor": self._check_monitor,
            "database": self._check_database,
            "disk_space": self._check_disk_space,
            "tmux": self._check_tmux,
        }
    
    def register_checker(self, name: str, checker: Callable[[], HealthCheckResult]) -> None:
        """注册自定义健康检查器"""
        self._checkers[name] = checker
    
    def unregister_checker(self, name: str) -> None:
        """注销健康检查器"""
        self._checkers.pop(name, None)
    
    def check(self, service_name: str) -> HealthCheckResult:
        """检查单个服务"""
        checker = self._checkers.get(service_name)
        if not checker:
            return HealthCheckResult(
                service_name=service_name,
                status=ServiceStatus.UNKNOWN,
                message=f"No checker registered for: {service_name}",
            )
        try:
            return checker()
        except Exception as e:
            return HealthCheckResult(
                service_name=service_name,
                status=ServiceStatus.UNHEALTHY,
                message=f"Check failed: {e}",
            )
    
    def check_all(self) -> SystemHealthReport:
        """检查所有服务"""
        results = []
        for name in self._checkers:
            results.append(self.check(name))
        
        if all(r.is_healthy for r in results):
            overall = ServiceStatus.HEALTHY
        elif any(r.status == ServiceStatus.UNHEALTHY for r in results):
            overall = ServiceStatus.UNHEALTHY
        else:
            overall = ServiceStatus.UNKNOWN
        
        return SystemHealthReport(overall_status=overall, checks=results)
    
    def check_critical(self) -> SystemHealthReport:
        """只检查关键服务（zoe-daemon 和数据库）"""
        critical_services = ["zoe-daemon", "database"]
        results = [self.check(name) for name in critical_services if name in self._checkers]
        overall = ServiceStatus.HEALTHY if all(r.is_healthy for r in results) else ServiceStatus.UNHEALTHY
        return SystemHealthReport(overall_status=overall, checks=results)
    
    # === 内置检查器 ===
    
    def _check_zoe_daemon(self) -> HealthCheckResult:
        """检查 zoe-daemon 进程"""
        try:
            proc = subprocess.run(
                ["pgrep", "-f", "zoe-daemon.py"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                pids = proc.stdout.strip().split("\n")
                return HealthCheckResult(
                    service_name="zoe-daemon",
                    status=ServiceStatus.HEALTHY,
                    message=f"Running (PIDs: {', '.join(pids)})",
                    details={"pids": pids, "count": len(pids)},
                )
            return HealthCheckResult(
                service_name="zoe-daemon",
                status=ServiceStatus.STOPPED,
                message="Not running",
            )
        except Exception as e:
            return HealthCheckResult(
                service_name="zoe-daemon",
                status=ServiceStatus.UNKNOWN,
                message=f"Check error: {e}",
            )
    def _check_monitor(self) -> HealthCheckResult:
        """检查 monitor 进程"""
        try:
            proc = subprocess.run(
                ["pgrep", "-f", "monitor.py"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                pids = proc.stdout.strip().split("\n")
                return HealthCheckResult(
                    service_name="monitor",
                    status=ServiceStatus.HEALTHY,
                    message=f"Running (PIDs: {', '.join(pids)})",
                    details={"pids": pids, "count": len(pids)},
                )
            return HealthCheckResult(
                service_name="monitor",
                status=ServiceStatus.STOPPED,
                message="Not running (may be scheduled)",
            )
        except Exception as e:
            return HealthCheckResult(
                service_name="monitor",
                status=ServiceStatus.UNKNOWN,
                message=f"Check error: {e}",
            )
    
    def _check_database(self) -> HealthCheckResult:
        """检查数据库连接"""
        try:
            from db import get_db, DB_PATH
            with get_db() as conn:
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()
            return HealthCheckResult(
                service_name="database",
                status=ServiceStatus.HEALTHY,
                message=f"Connected ({DB_PATH})",
                details={"path": str(DB_PATH)},
            )
        except ImportError:
            return HealthCheckResult(
                service_name="database",
                status=ServiceStatus.UNHEALTHY,
                message="db module not available",
            )
        except Exception as e:
            return HealthCheckResult(
                service_name="database",
                status=ServiceStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
            )
    def _check_disk_space(self) -> HealthCheckResult:
        """检查磁盘空间"""
        try:
            import shutil
            total, used, free = shutil.disk_usage(self.base_dir)
            free_gb = free / (1024 ** 3)
            used_percent = (used / total) * 100
            
            if free_gb < 1:
                status = ServiceStatus.UNHEALTHY
                message = f"Critical: only {free_gb:.2f}GB free"
            elif free_gb < 5:
                status = ServiceStatus.UNHEALTHY
                message = f"Warning: only {free_gb:.2f}GB free"
            else:
                status = ServiceStatus.HEALTHY
                message = f"{free_gb:.2f}GB free ({used_percent:.1f}% used)"
            
            return HealthCheckResult(
                service_name="disk_space",
                status=status,
                message=message,
                details={
                    "free_gb": round(free_gb, 2),
                    "used_percent": round(used_percent, 1),
                    "total_gb": round(total / (1024 ** 3), 2),
                },
            )
        except Exception as e:
            return HealthCheckResult(
                service_name="disk_space",
                status=ServiceStatus.UNKNOWN,
                message=f"Check error: {e}",
            )
    
    def _check_tmux(self) -> HealthCheckResult:
        """检查 tmux 可用性"""
        try:
            proc = subprocess.run(
                ["which", "tmux"],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                return HealthCheckResult(
                    service_name="tmux",
                    status=ServiceStatus.UNHEALTHY,
                    message="tmux not found in PATH",
                )
            
            version_proc = subprocess.run(
                ["tmux", "-V"],
                capture_output=True,
                text=True,
            )
            version = version_proc.stdout.strip() if version_proc.returncode == 0 else "unknown"
            
            return HealthCheckResult(
                service_name="tmux",
                status=ServiceStatus.HEALTHY,
                message=f"Available ({version})",
                details={"version": version},
            )
        except Exception as e:
            return HealthCheckResult(
                service_name="tmux",
                status=ServiceStatus.UNKNOWN,
                message=f"Check error: {e}",
            )

def check_system_health(full: bool = True) -> SystemHealthReport:
    """快捷函数：检查系统健康状态
    
    Args:
        full: True 检查所有服务，False 只检查关键服务
    
    Returns:
        SystemHealthReport
    """
    checker = HealthChecker()
    return checker.check_all() if full else checker.check_critical()


# === 单例模式 ===

_checker_instance: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """获取全局 HealthChecker 实例"""
    global _checker_instance
    if _checker_instance is None:
        _checker_instance = HealthChecker()
    return _checker_instance


if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description="System health check")
    parser.add_argument("--critical", action="store_true", help="Only check critical services")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    checker = HealthChecker()
    report = checker.check_critical() if args.critical else checker.check_all()
    
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"System Health: {report.overall_status.value.upper()}")
        print("-" * 50)
        for check in report.checks:
            status_icon = "OK" if check.is_healthy else "FAIL"
            print(f"[{status_icon}] {check.service_name}: {check.message}")
