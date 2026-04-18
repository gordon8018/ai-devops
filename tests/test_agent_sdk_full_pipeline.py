"""Full pipeline integration test spanning all 4 phases."""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class FakeUsage:
    input_tokens: int = 800
    output_tokens: int = 400
    total_tokens: int = 1200


@dataclass
class FakeRunResult:
    final_output: str = "def hello(): return 'world'"
    new_items: list = field(default_factory=list)
    last_agent: Any = None
    usage: FakeUsage = field(default_factory=FakeUsage)


@pytest.mark.asyncio
async def test_full_pipeline_all_phases():
    """Integration: all 4 phases work together end-to-end."""
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack, AgentRunStatus
    from packages.kernel.events.bus import InMemoryEventBus, AGENT_TRACE_EVENTS
    from packages.kernel.runtime.services import SdkAgentLauncher
    from packages.agent_sdk.runner.executor import AgentExecutor
    from packages.agent_sdk.tools.registry import ToolRegistry
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard, SensitiveDataGuard, PromptInjectionGuard
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard, CodeSafetyGuard, ForbiddenPathGuard, OutputFormatGuard
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer

    # Setup
    subtask = Subtask(
        id="full-s1", title="Add feature", description="Add hello world",
        agent="codex", model="gpt-5.4", effort="low", worktree_strategy="shared",
        task_type=TaskType.CODE_GENERATION, definition_of_done=("Tests pass",),
    )
    context_pack = ContextPack(
        pack_id="full-cp1", work_item_id="full-wi1",
        constraints={"allowedPaths": ["src/"], "forbiddenPaths": ["secrets/"], "mustTouch": ["src/hello.py"]},
        repo_scope=("src/hello.py",), recent_changes=("abc: init",),
    )

    # Phase 2: Tools resolve correctly
    tools = ToolRegistry.resolve("code_generation")
    assert any(t.name == "run_tests" for t in tools)
    assert any(t.name == "read_file" for t in tools)

    # Phase 2: MCP Server exposes resources
    mcp = ContextPackServer(context_pack)
    resources = mcp.list_resources()
    assert len(resources) == 5
    assert "abc" in mcp.get_resource("recent-changes")

    # Phase 3: Input guardrails pass clean input
    assert BoundaryGuard.check(context_pack.constraints, subtask.definition_of_done).tripwire_triggered is False
    assert SensitiveDataGuard.check(subtask.description).tripwire_triggered is False
    assert PromptInjectionGuard.check(subtask.description).tripwire_triggered is False

    # Phase 3: Output guardrails pass clean output
    agent_output = "def hello(): return 'world'"
    assert SecretLeakGuard.check(agent_output).tripwire_triggered is False
    assert len(CodeSafetyGuard.check(agent_output).risks) == 0
    assert ForbiddenPathGuard.check(["src/hello.py"], ["secrets/"]).tripwire_triggered is False
    assert len(OutputFormatGuard.check({"result": "ok"}, ["result"]).risks) == 0

    # Phase 1: Execute via SdkAgentLauncher -> AgentExecutor
    bus = InMemoryEventBus()
    events = []
    bus.subscribe(lambda e: events.append(e))

    executor = AgentExecutor(event_bus=bus)
    launcher = SdkAgentLauncher(executor=executor)

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        result = await launcher.launch_async(
            subtask=subtask, context_pack=context_pack,
            work_item_id="full-wi1", plan_id="full-plan1", workspace_path="/tmp/full",
        )

    assert result.agent_run.status == AgentRunStatus.COMPLETED
    assert result.token_usage["cost_estimate"] > 0

    # Phase 4: Tracing bridge maps events
    bridge = AgentTraceBridge(event_bus=bus, sensitive_data=False)
    bridge.on_trace_event("tool.call", {"tool_name": "read_file"})

    # Phase 4: Usage aggregation
    agg = TokenUsageCollector.aggregate([result.token_usage])
    assert agg["total_tokens"] == 1200
    assert agg["run_count"] == 1

    # Phase 4: Verify AGENT_TRACE_EVENTS constant
    assert "agent_run.started" in AGENT_TRACE_EVENTS
    assert "agent_run.tool_called" in AGENT_TRACE_EVENTS

    # Verify events were published
    event_types = [e.event_type for e in events]
    assert "agent_run.started" in event_types
    assert "agent_run.completed" in event_types
    assert "agent_run.tool_called" in event_types  # from trace bridge
