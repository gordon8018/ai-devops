#!/usr/bin/env python3
"""
Integration test for global scheduler with dispatch system
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from orchestrator.bin.plan_schema import Plan
from orchestrator.bin.global_scheduler import GlobalScheduler, SchedulerConfig
from orchestrator.bin.dispatch import (
    dispatch_with_global_scheduler,
    get_scheduling_summary,
    get_plan_scheduling_priority,
)


def make_plan(**overrides) -> Plan:
    """Helper to create valid Plan"""
    payload = {
        "planId": "test-plan",
        "repo": "test/repo",
        "title": "Test",
        "requestedBy": "user",
        "requestedAt": 1234567890,
        "objective": "Test objective",
        "routing": {"agent": "codex", "model": "gpt-5", "effort": "medium"},
        "version": "1.0",
        "subtasks": [
            {
                "id": "S1",
                "title": "Subtask 1",
                "description": "Test description",
                "worktreeStrategy": "isolated",
                "dependsOn": [],
                "filesHint": [],
                "prompt": "Test prompt",
            },
        ],
    }
    if "subtasks" in overrides:
        for st in overrides["subtasks"]:
            if "worktreeStrategy" not in st:
                st["worktreeStrategy"] = "isolated"
            if "filesHint" not in st:
                st["filesHint"] = []
            if "prompt" not in st:
                st["prompt"] = "Test"
            if "description" not in st:
                st["description"] = "Test description"
    payload.update(overrides)
    return Plan.from_dict(payload)


