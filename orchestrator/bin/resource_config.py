#!/usr/bin/env python3
"""
Resource Configuration - 资源配置管理模块

管理 Agent 并发限制、资源监控配置和负载均衡策略。

Usage:
    from orchestrator.bin.resource_config import ResourceConfig, get_resource_config
    
    config = get_resource_config()
    if config.can_spawn_task(repo="owner/repo", agent_type="codex"):
        spawn_task(...)
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home


@dataclass
class ConcurrencyLimits:
    """并发限制配置"""
    max_concurrent_tasks: int = 5
    max_concurrent_per_repo: int = 2
    max_concurrent_per_agent_type: dict[str, int] = field(default_factory=lambda: {
        "codex": 3,
        "claude": 2,
        "pi": 2,
        "opencode": 2,
    })
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "maxConcurrentTasks": self.max_concurrent_tasks,
            "maxConcurrentPerRepo": self.max_concurrent_per_repo,
            "maxConcurrentPerAgentType": self.max_concurrent_per_agent_type,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConcurrencyLimits":
        return cls(
            max_concurrent_tasks=data.get("maxConcurrentTasks", 5),
            max_concurrent_per_repo=data.get("maxConcurrentPerRepo", 2),
            max_concurrent_per_agent_type=data.get("maxConcurrentPerAgentType", {
                "codex": 3, "claude": 2, "pi": 2, "opencode": 2,
            }),
        )


@dataclass
class ResourceThresholds:
    """资源阈值配置"""
    cpu_high_percent: float = 80.0
    cpu_critical_percent: float = 95.0
    memory_high_percent: float = 80.0
    memory_critical_percent: float = 95.0
    disk_low_gb: float = 5.0
    disk_critical_gb: float = 1.0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "cpuHighPercent": self.cpu_high_percent,
            "cpuCriticalPercent": self.cpu_critical_percent,
            "memoryHighPercent": self.memory_high_percent,
            "memoryCriticalPercent": self.memory_critical_percent,
            "diskLowGb": self.disk_low_gb,
            "diskCriticalGb": self.disk_critical_gb,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResourceThresholds":
        return cls(
            cpu_high_percent=data.get("cpuHighPercent", 80.0),
            cpu_critical_percent=data.get("cpuCriticalPercent", 95.0),
            memory_high_percent=data.get("memoryHighPercent", 80.0),
            memory_critical_percent=data.get("memoryCriticalPercent", 95.0),
            disk_low_gb=data.get("diskLowGb", 5.0),
            disk_critical_gb=data.get("diskCriticalGb", 1.0),
        )

@dataclass
class LoadBalancerConfig:
    """负载均衡配置"""
    strategy: str = "round_robin"  # round_robin, least_loaded, priority
    priority_agents: list[str] = field(default_factory=list)
    weight_by_agent: dict[str, float] = field(default_factory=lambda: {
        "codex": 1.0,
        "claude": 0.8,
        "pi": 0.7,
        "opencode": 0.6,
    })
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "priorityAgents": self.priority_agents,
            "weightByAgent": self.weight_by_agent,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LoadBalancerConfig":
        return cls(
            strategy=data.get("strategy", "round_robin"),
            priority_agents=data.get("priorityAgents", []),
            weight_by_agent=data.get("weightByAgent", {
                "codex": 1.0, "claude": 0.8, "pi": 0.7, "opencode": 0.6,
            }),
        )


@dataclass
class ResourceConfig:
    """资源配置主类"""
    concurrency: ConcurrencyLimits = field(default_factory=ConcurrencyLimits)
    thresholds: ResourceThresholds = field(default_factory=ResourceThresholds)
    load_balancer: LoadBalancerConfig = field(default_factory=LoadBalancerConfig)
    config_path: Optional[Path] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "concurrency": self.concurrency.to_dict(),
            "thresholds": self.thresholds.to_dict(),
            "loadBalancer": self.load_balancer.to_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any], config_path: Optional[Path] = None) -> "ResourceConfig":
        return cls(
            concurrency=ConcurrencyLimits.from_dict(data.get("concurrency", {})),
            thresholds=ResourceThresholds.from_dict(data.get("thresholds", {})),
            load_balancer=LoadBalancerConfig.from_dict(data.get("loadBalancer", {})),
            config_path=config_path,
        )
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "ResourceConfig":
        """从文件加载配置"""
        if path is None:
            base = ai_devops_home()
            path = base / "config" / "resource_config.json"
        
        if path.exists():
            with open(path, "r") as f:
                data = json.load(f)
            return cls.from_dict(data, config_path=path)
        return cls(config_path=path)
    
    def save(self, path: Optional[Path] = None) -> None:
        """保存配置到文件"""
        save_path = path or self.config_path
        if save_path is None:
            base = ai_devops_home()
            save_path = base / "config" / "resource_config.json"
        
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def can_spawn_task(
        self,
        repo: Optional[str] = None,
        agent_type: Optional[str] = None,
        current_running: int = 0,
        current_per_repo: Optional[dict[str, int]] = None,
        current_per_agent: Optional[dict[str, int]] = None,
    ) -> tuple[bool, str]:
        """检查是否可以启动新任务
        
        Args:
            repo: 目标仓库
            agent_type: Agent 类型
            current_running: 当前运行任务总数
            current_per_repo: 每个仓库的运行任务数
            current_per_agent: 每种 Agent 类型的运行任务数
            
        Returns:
            (can_spawn, reason) - 是否可以启动，以及原因
        """
        # 检查总并发限制
        if current_running >= self.concurrency.max_concurrent_tasks:
            return False, f"Max concurrent tasks reached ({self.concurrency.max_concurrent_tasks})"
        
        # 检查仓库限制
        if repo and current_per_repo:
            repo_count = current_per_repo.get(repo, 0)
            if repo_count >= self.concurrency.max_concurrent_per_repo:
                return False, f"Max concurrent tasks per repo reached for {repo}"
        
        # 检查 Agent 类型限制
        if agent_type and current_per_agent:
            agent_count = current_per_agent.get(agent_type, 0)
            max_agent = self.concurrency.max_concurrent_per_agent_type.get(agent_type, 2)
            if agent_count >= max_agent:
                return False, f"Max concurrent tasks for agent type {agent_type} reached"
        
        return True, "OK"
    
    def get_load_balancer_weight(self, agent_type: str) -> float:
        """获取 Agent 的负载均衡权重"""
        return self.load_balancer.weight_by_agent.get(agent_type, 1.0)
    
    def get_resource_status(
        self,
        cpu_percent: Optional[float] = None,
        memory_percent: Optional[float] = None,
        disk_free_gb: Optional[float] = None,
    ) -> dict[str, Any]:
        """评估资源状态"""
        status = {
            "overall": "healthy",
            "warnings": [],
            "criticals": [],
        }
        
        if cpu_percent is not None:
            if cpu_percent >= self.thresholds.cpu_critical_percent:
                status["overall"] = "critical"
                status["criticals"].append(f"CPU at {cpu_percent:.1f}%")
            elif cpu_percent >= self.thresholds.cpu_high_percent:
                if status["overall"] == "healthy":
                    status["overall"] = "warning"
                status["warnings"].append(f"CPU at {cpu_percent:.1f}%")
        
        if memory_percent is not None:
            if memory_percent >= self.thresholds.memory_critical_percent:
                status["overall"] = "critical"
                status["criticals"].append(f"Memory at {memory_percent:.1f}%")
            elif memory_percent >= self.thresholds.memory_high_percent:
                if status["overall"] == "healthy":
                    status["overall"] = "warning"
                status["warnings"].append(f"Memory at {memory_percent:.1f}%")
        
        if disk_free_gb is not None:
            if disk_free_gb <= self.thresholds.disk_critical_gb:
                status["overall"] = "critical"
                status["criticals"].append(f"Disk only {disk_free_gb:.2f}GB free")
            elif disk_free_gb <= self.thresholds.disk_low_gb:
                if status["overall"] == "healthy":
                    status["overall"] = "warning"
                status["warnings"].append(f"Disk only {disk_free_gb:.2f}GB free")
        
        return status


# === 单例模式 ===

_config_instance: Optional[ResourceConfig] = None


def get_resource_config(reload: bool = False) -> ResourceConfig:
    """获取全局资源配置实例
    
    Args:
        reload: 是否重新加载配置文件
    """
    global _config_instance
    if _config_instance is None or reload:
        _config_instance = ResourceConfig.load()
    return _config_instance


def set_resource_config(config: ResourceConfig) -> None:
    """设置全局资源配置实例"""
    global _config_instance
    _config_instance = config


def can_spawn_task(
    repo: Optional[str] = None,
    agent_type: Optional[str] = None,
    current_running: int = 0,
    current_per_repo: Optional[dict[str, int]] = None,
    current_per_agent: Optional[dict[str, int]] = None,
) -> tuple[bool, str]:
    """快捷函数：检查是否可以启动新任务"""
    return get_resource_config().can_spawn_task(
        repo=repo,
        agent_type=agent_type,
        current_running=current_running,
        current_per_repo=current_per_repo,
        current_per_agent=current_per_agent,
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Resource configuration")
    parser.add_argument("--show", action="store_true", help="Show current config")
    parser.add_argument("--save", action="store_true", help="Save default config")
    args = parser.parse_args()
    
    config = get_resource_config()
    
    if args.show:
        print(json.dumps(config.to_dict(), indent=2))
    elif args.save:
        config.save()
        print(f"Config saved to: {config.config_path}")
    else:
        print("Resource Configuration Module")
        print("Use --show to display config, --save to save default config")
