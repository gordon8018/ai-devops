#!/usr/bin/env python3
"""Timeout configuration management for task execution.

Provides default timeout settings and per-task/per-repo override capabilities.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

try:
    from .context_injector import get_context_injector
except ImportError:
    from context_injector import get_context_injector

from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home


# Default timeout in minutes
DEFAULT_TIMEOUT_MINUTES = 180


@dataclass
class TimeoutConfig:
    """Configuration for task timeouts.
    
    Supports hierarchical timeout resolution:
    1. Task-specific timeout (highest priority)
    2. Repository-specific timeout
    3. Global default timeout
    """
    default_timeout: int = DEFAULT_TIMEOUT_MINUTES
    repo_timeouts: Dict[str, int] = field(default_factory=dict)
    task_timeouts: Dict[str, int] = field(default_factory=dict)
    
    def get_timeout(self, task_id: Optional[str] = None, repo: Optional[str] = None) -> int:
        """Get timeout for a task with hierarchical resolution.
        
        Priority: task_id > repo > default
        """
        # 1. Task-specific timeout (highest priority)
        if task_id and task_id in self.task_timeouts:
            return self.task_timeouts[task_id]
        
        # 2. Repository-specific timeout
        if repo and repo in self.repo_timeouts:
            return self.repo_timeouts[repo]
        
        # 3. Global default
        return self.default_timeout
    
    def set_task_timeout(self, task_id: str, timeout_minutes: int) -> None:
        """Set timeout for a specific task."""
        if timeout_minutes <= 0:
            raise ValueError(f"Timeout must be positive, got: {timeout_minutes}")
        self.task_timeouts[task_id] = timeout_minutes
    
    def set_repo_timeout(self, repo: str, timeout_minutes: int) -> None:
        """Set timeout for all tasks in a repository."""
        if timeout_minutes <= 0:
            raise ValueError(f"Timeout must be positive, got: {timeout_minutes}")
        self.repo_timeouts[repo] = timeout_minutes
    
    def clear_task_timeout(self, task_id: str) -> None:
        """Remove task-specific timeout, falling back to repo/default."""
        self.task_timeouts.pop(task_id, None)
    

    def get_context_aware_timeout(
        self,
        task_id: Optional[str] = None,
        repo: Optional[str] = None,
        task_type: Optional[str] = None,
        files_hint: Optional[List[str]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Get context-aware timeout based on task complexity and history.
        
        Args:
            task_id: Task ID
            repo: Repository name
            task_type: Task type (fix, implement, refactor, etc.)
            files_hint: Files hints for complexity estimation
            constraints: Task constraints
        
        Returns:
            Timeout in minutes
        """
        base_timeout = self.get_timeout(task_id=task_id, repo=repo)
        
        # 1. Get context injector for success patterns
        try:
            injector = get_context_injector()
        except Exception:
            return base_timeout
        
        # 2. Adjust based on task complexity
        complexity_multiplier = self._estimate_complexity_multiplier(
            task_type=task_type,
            files_hint=files_hint,
            constraints=constraints or {},
        )
        
        # 3. Adjust based on historical execution time
        if task_type and files_hint:
            patterns = injector.find_similar_success_patterns(
                task_type=task_type,
                files_hint=files_hint,
                limit=3,
            )
            if patterns:
                # Use average execution time from similar tasks
                avg_time = sum(p.execution_time_minutes for p in patterns) / len(patterns)
                if avg_time > 0:
                    # Use historical average with 20% buffer
                    historical_timeout = int(avg_time * 1.2)
                    # Take max of base and historical
                    base_timeout = max(base_timeout, historical_timeout)
        
        # Apply complexity multiplier
        final_timeout = int(base_timeout * complexity_multiplier)
        
        # Ensure reasonable bounds (min 30 min, max 480 min / 8 hours)
        return max(30, min(final_timeout, 480))
    
    def _estimate_complexity_multiplier(
        self,
        task_type: Optional[str] = None,
        files_hint: Optional[List[str]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Estimate complexity multiplier based on task characteristics.
        
        Returns:
            Multiplier (1.0 = normal, >1.0 = complex, <1.0 = simple)
        """
        multiplier = 1.0
        constraints = constraints or {}
        files_hint = files_hint or []
        
        # Task type complexity
        if task_type in ("refactor", "migrate", "integrate"):
            multiplier *= 1.5
        elif task_type in ("fix", "bugfix"):
            multiplier *= 1.0
        elif task_type in ("implement", "feature"):
            multiplier *= 1.3
        elif task_type in ("docs", "documentation"):
            multiplier *= 0.7
        elif task_type in ("test", "testing"):
            multiplier *= 0.9
        
        # Files complexity
        file_count = len(files_hint)
        if file_count > 10:
            multiplier *= 1.4
        elif file_count > 5:
            multiplier *= 1.2
        elif file_count > 3:
            multiplier *= 1.1
        
        # Constraints complexity
        if constraints.get("requiresTests"):
            multiplier *= 1.2
        if constraints.get("requiresDocs"):
            multiplier *= 1.1
        if constraints.get("hasDependencies"):
            multiplier *= 1.3
        
        return multiplier
    
    def to_dict(self) -> dict:
        """Serialize config to dictionary."""
        return {
            "default_timeout": self.default_timeout,
            "repo_timeouts": dict(self.repo_timeouts),
            "task_timeouts": dict(self.task_timeouts),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TimeoutConfig":
        """Deserialize config from dictionary."""
        return cls(
            default_timeout=data.get("default_timeout", DEFAULT_TIMEOUT_MINUTES),
            repo_timeouts=data.get("repo_timeouts", {}),
            task_timeouts=data.get("task_timeouts", {}),
        )


def _config_path() -> Path:
    """Get path to timeout config file."""
    return ai_devops_home() / ".clawdbot" / "timeout_config.json"


def load_timeout_config() -> TimeoutConfig:
    """Load timeout configuration from file.
    
    Returns default config if file doesn't exist or is invalid.
    """
    path = _config_path()
    if not path.exists():
        return TimeoutConfig()
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TimeoutConfig.from_dict(data)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to load timeout config, using defaults: %s", e
        )
        return TimeoutConfig()


def save_timeout_config(config: TimeoutConfig) -> None:
    """Save timeout configuration to file."""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2),
        encoding="utf-8"
    )


# Module-level config cache
_config: Optional[TimeoutConfig] = None


def get_timeout_config() -> TimeoutConfig:
    """Get or load the timeout configuration (cached)."""
    global _config
    if _config is None:
        _config = load_timeout_config()
    return _config


def reload_timeout_config() -> TimeoutConfig:
    """Force reload timeout configuration from file."""
    global _config
    _config = load_timeout_config()
    return _config


def get_task_timeout(task_id: Optional[str] = None, repo: Optional[str] = None) -> int:
    """Convenience function to get timeout for a task."""
    return get_timeout_config().get_timeout(task_id=task_id, repo=repo)


def get_context_aware_timeout(
    task_id: Optional[str] = None,
    repo: Optional[str] = None,
    task_type: Optional[str] = None,
    files_hint: Optional[List[str]] = None,
    constraints: Optional[Dict[str, Any]] = None,
) -> int:
    """Convenience function to get context-aware timeout for a task."""
    return get_timeout_config().get_context_aware_timeout(
        task_id=task_id,
        repo=repo,
        task_type=task_type,
        files_hint=files_hint,
        constraints=constraints,
    )
