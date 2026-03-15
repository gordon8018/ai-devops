# orchestrator/bin/plan_status.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Statuses considered "completed" for progress tracking
_COMPLETED_STATUSES = frozenset({"ready", "merged"})


@dataclass
class SubtaskView:
    id: str
    title: str
    status: str                         # from DB or dispatch archive
    agent: str | None = None
    model: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    attempts: int = 0
    note: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass
class PlanView:
    plan_id: str
    repo: str
    subtasks: list[SubtaskView]
    objective: str = ""
    requested_by: str = ""
    requested_at: int | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status in _COMPLETED_STATUSES)

    @property
    def total_count(self) -> int:
        return len(self.subtasks)
