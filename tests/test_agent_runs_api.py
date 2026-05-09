"""Tests for GET /api/agent-runs endpoint."""
from __future__ import annotations

import pytest
from packages.shared.domain.runtime_state import (
    clear_runtime_state,
    list_agent_runs,
    record_agent_run,
)
from packages.shared.domain.models import AgentRun, AgentRunStatus


@pytest.fixture(autouse=True)
def reset_state():
    clear_runtime_state()
    yield
    clear_runtime_state()


def test_list_agent_runs_empty():
    assert list_agent_runs() == []


def test_record_and_list_agent_run():
    run = AgentRun(
        run_id="run_test_001",
        work_item_id="wi_test_001",
        context_pack_id="cp_test_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.RUNNING,
        planned_steps=("plan", "implement", "test"),
    )
    record_agent_run(run)
    runs = list_agent_runs()
    assert len(runs) == 1
    assert runs[0]["runId"] == "run_test_001"
    assert runs[0]["agent"] == "codex"
    assert runs[0]["status"] == "running"


def test_record_agent_run_deduplicates_by_run_id():
    run = AgentRun(
        run_id="run_dedup",
        work_item_id="wi_001",
        context_pack_id="cp_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.PENDING,
        planned_steps=(),
    )
    record_agent_run(run)
    updated = AgentRun(
        run_id="run_dedup",
        work_item_id="wi_001",
        context_pack_id="cp_001",
        agent="codex",
        model="gpt-5.3-codex",
        status=AgentRunStatus.COMPLETED,
        planned_steps=(),
    )
    record_agent_run(updated)
    runs = list_agent_runs()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
