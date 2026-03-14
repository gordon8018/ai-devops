"""
Configuration helpers for AI DevOps.

All path functions are evaluated lazily so that AI_DEVOPS_HOME can be
changed at runtime (e.g. in tests) without importing stale values.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "ai_devops_home",
    "logs_dir",
    "queue_dir",
    "repos_dir",
    "worktrees_dir",
    "agents_dir",
]


def ai_devops_home() -> Path:
    return Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))


def logs_dir() -> Path:
    return ai_devops_home() / "logs"


def queue_dir() -> Path:
    return ai_devops_home() / "orchestrator" / "queue"


def repos_dir() -> Path:
    return ai_devops_home() / "repos"


def worktrees_dir() -> Path:
    return ai_devops_home() / "worktrees"


def agents_dir() -> Path:
    return ai_devops_home() / "agents"
