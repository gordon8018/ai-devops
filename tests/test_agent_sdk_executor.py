import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType
    defaults = dict(
        id="s1", title="Task", description="Do thing",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Done",),
    )
    defaults.update(overrides)
    return Subtask(**defaults)


def _make_context_pack(**overrides):
    from packages.shared.domain.models import ContextPack
    defaults = dict(pack_id="cp-001", work_item_id="wi-001", constraints={"allowedPaths": ["src/"]})
    defaults.update(overrides)
    return ContextPack(**defaults)


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    total_tokens: int = 150


@dataclass
class FakeRunResult:
    final_output: str = "done"
    new_items: list = field(default_factory=list)
    last_agent: Any = None
    usage: FakeUsage = field(default_factory=FakeUsage)


@pytest.mark.asyncio
async def test_executor_returns_agent_run_result_on_success():
    from packages.agent_sdk.runner.executor import AgentExecutor, AgentRunResult

    mock_bus = MagicMock()
    executor = AgentExecutor(event_bus=mock_bus)

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        result = await executor.execute(
            subtask=_make_subtask(), context_pack=_make_context_pack(),
            work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/ws",
        )

    assert isinstance(result, AgentRunResult)
    assert result.agent_run.status.value == "completed"


@pytest.mark.asyncio
async def test_executor_retries_on_failure():
    from packages.agent_sdk.runner.executor import AgentExecutor

    mock_bus = MagicMock()
    executor = AgentExecutor(event_bus=mock_bus)
    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("transient error")
        return FakeRunResult()

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(side_effect=side_effect)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute(
                subtask=_make_subtask(), context_pack=_make_context_pack(),
                work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/ws",
            )

    assert result.agent_run.status.value == "completed"
    assert call_count == 3


@pytest.mark.asyncio
async def test_executor_returns_failed_after_max_retries():
    from packages.agent_sdk.runner.executor import AgentExecutor

    mock_bus = MagicMock()
    executor = AgentExecutor(event_bus=mock_bus)

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(side_effect=RuntimeError("permanent"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute(
                subtask=_make_subtask(), context_pack=_make_context_pack(),
                work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/ws",
            )

    assert result.agent_run.status.value == "failed"
