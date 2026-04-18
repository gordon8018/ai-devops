"""Phase 1 integration test: verify the full execution pipeline works end-to-end."""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class FakeUsage:
    input_tokens: int = 500
    output_tokens: int = 200
    total_tokens: int = 700


@dataclass
class FakeRunResult:
    final_output: str = "Feature implemented successfully"
    new_items: list = field(default_factory=list)
    last_agent: Any = None
    usage: FakeUsage = field(default_factory=FakeUsage)


@pytest.mark.asyncio
async def test_full_pipeline_subtask_to_agent_run():
    """Integration: Subtask -> AgentFactory -> AgentExecutor -> AgentRunResult."""
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack, AgentRunStatus
    from packages.kernel.events.bus import InMemoryEventBus
    from packages.agent_sdk.runner.executor import AgentExecutor, AgentRunResult

    subtask = Subtask(
        id="int-s1", title="Add feature", description="Add hello world",
        agent="codex", model="gpt-5.4", effort="low",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Tests pass",),
    )
    context_pack = ContextPack(pack_id="int-cp1", work_item_id="int-wi1", constraints={"allowedPaths": ["src/"]})
    bus = InMemoryEventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))
    executor = AgentExecutor(event_bus=bus)

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        result = await executor.execute(
            subtask=subtask, context_pack=context_pack,
            work_item_id="int-wi1", plan_id="int-plan1", workspace_path="/tmp/integration-test",
        )

    assert isinstance(result, AgentRunResult)
    assert result.agent_run.status == AgentRunStatus.COMPLETED
    assert result.agent_run.work_item_id == "int-wi1"
    assert result.agent_run.context_pack_id == "int-cp1"
    assert result.token_usage["input_tokens"] == 500
    assert result.token_usage["cost_estimate"] > 0

    event_types = [e.event_type for e in events]
    assert "agent_run.started" in event_types
    assert "agent_run.completed" in event_types


@pytest.mark.asyncio
async def test_pipeline_anthropic_routing():
    """Integration: code_review task routes to Anthropic model."""
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack, AgentRunStatus
    from packages.agent_sdk.runner.executor import AgentExecutor

    subtask = Subtask(
        id="int-s2", title="Review code", description="Review PR #42",
        agent="claude", model="claude-opus-4-6", effort="low",
        worktree_strategy="shared", task_type=TaskType.CODE_REVIEW,
        definition_of_done=("Review complete",),
    )
    context_pack = ContextPack(pack_id="int-cp2", work_item_id="int-wi2", constraints={"allowedPaths": ["src/"]})
    executor = AgentExecutor(event_bus=MagicMock())

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        result = await executor.execute(
            subtask=subtask, context_pack=context_pack,
            work_item_id="int-wi2", plan_id="int-plan2", workspace_path="/tmp/int-test",
        )

    assert result.agent_run.status == AgentRunStatus.COMPLETED
    assert "opus" in result.agent_run.model or "claude" in result.agent_run.model


@pytest.mark.asyncio
async def test_pipeline_agent_has_tools():
    """Integration: Agent built by factory has tools from ToolRegistry."""
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack
    from packages.agent_sdk.runner.agent_factory import AgentFactory

    subtask = Subtask(
        id="int-s3", title="Gen code", description="Generate code",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Done",),
    )
    context_pack = ContextPack(pack_id="cp3", work_item_id="wi3", constraints={"allowedPaths": ["src/"]})

    agent = AgentFactory().build(subtask, context_pack)
    assert agent.tools is not None
    assert len(agent.tools) > 0
    tool_names = {t.name for t in agent.tools}
    assert "read_file" in tool_names
    assert "run_tests" in tool_names


@pytest.mark.asyncio
async def test_pipeline_run_context_passed_to_runner():
    """Integration: RunContext is passed to Runner.run() via context parameter."""
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack
    from packages.agent_sdk.runner.executor import AgentExecutor

    subtask = Subtask(
        id="int-s4", title="Task", description="Do it",
        agent="codex", model="gpt-5.4", effort="low",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Done",),
    )
    context_pack = ContextPack(pack_id="cp4", work_item_id="wi4", constraints={"allowedPaths": ["src/"]})
    executor = AgentExecutor(event_bus=MagicMock())

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        await executor.execute(
            subtask=subtask, context_pack=context_pack,
            work_item_id="wi4", plan_id="plan4", workspace_path="/tmp/test",
        )

    assert MockRunner.run.call_count == 1
    call_kwargs = MockRunner.run.call_args.kwargs
    assert "context" in call_kwargs and call_kwargs["context"] is not None
