"""Agent execution engine wrapping Agents SDK Runner with retry and recovery."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from agents import Agent, Runner
from agents.exceptions import MaxTurnsExceeded

from packages.agent_sdk.models.router import ModelRouter
from packages.agent_sdk.runner.agent_factory import AgentFactory
from packages.agent_sdk.runner.context_bridge import ContextBridge
from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
from packages.shared.domain.models import AgentRun, AgentRunStatus, ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [30, 90, 270]
MAX_TURNS = 50
MAX_CONCURRENT_SUBTASKS = 8

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBTASKS)
    return _semaphore


@dataclass
class AgentRunResult:
    """Mutable wrapper around immutable AgentRun + guardrail findings."""
    agent_run: AgentRun
    review_findings: list[ReviewFinding] = field(default_factory=list)
    token_usage: dict[str, Any] = field(default_factory=dict)


class AgentExecutor:
    """Executes agent runs with retry, model escalation, and event publishing."""

    def __init__(self, event_bus: Any = None):
        self._factory = AgentFactory()
        self._event_bus = event_bus

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event_type, payload)

    async def execute(
        self, subtask: Subtask, context_pack: ContextPack,
        work_item_id: str, plan_id: str, workspace_path: str,
    ) -> AgentRunResult:
        agent = self._factory.build(subtask, context_pack)
        run_context = ContextBridge.to_run_context(
            work_item_id=work_item_id,
            plan_id=plan_id,
            workspace_path=workspace_path,
            event_bus=self._event_bus,
        )
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        provider, current_model = ModelRouter.resolve(task_type_value)

        async with _get_semaphore():
            for attempt in range(MAX_ATTEMPTS):
                try:
                    self._publish("agent_run.started", {
                        "subtask_id": subtask.id, "attempt": attempt + 1,
                        "model": current_model, "work_item_id": work_item_id,
                    })

                    start_time = time.monotonic()
                    result = await Runner.run(
                        starting_agent=agent,
                        input=subtask.prompt or subtask.description,
                        context=run_context,
                        max_turns=MAX_TURNS,
                    )
                    duration = time.monotonic() - start_time

                    usage = TokenUsageCollector.extract(result, model=current_model, duration=duration)

                    agent_run = AgentRun(
                        run_id=f"{subtask.id}-run-{attempt + 1}",
                        work_item_id=work_item_id,
                        context_pack_id=context_pack.pack_id,
                        agent=agent.name, model=current_model,
                        status=AgentRunStatus.COMPLETED,
                    )
                    self._publish("agent_run.completed", {
                        "subtask_id": subtask.id, "model": current_model,
                        "duration": round(duration, 2), **usage,
                    })
                    return AgentRunResult(agent_run=agent_run, token_usage=usage)

                except MaxTurnsExceeded:
                    self._publish("agent_run.max_turns", {
                        "subtask_id": subtask.id, "attempt": attempt + 1, "model": current_model,
                    })
                    provider, current_model = ModelRouter.escalate(provider, current_model)
                    agent = self._factory.build_with_escalated_model(
                        subtask, context_pack, provider, current_model,
                    )

                except Exception as e:
                    self._publish("agent_run.failed", {
                        "subtask_id": subtask.id, "attempt": attempt + 1, "error": str(e),
                    })
                    if attempt < MAX_ATTEMPTS - 1:
                        await asyncio.sleep(BACKOFF_SECONDS[attempt])
                    else:
                        agent_run = AgentRun(
                            run_id=f"{subtask.id}-run-failed",
                            work_item_id=work_item_id,
                            context_pack_id=context_pack.pack_id,
                            agent=agent.name, model=current_model,
                            status=AgentRunStatus.FAILED,
                        )
                        return AgentRunResult(agent_run=agent_run)

        agent_run = AgentRun(
            run_id=f"{subtask.id}-run-unreachable",
            work_item_id=work_item_id,
            context_pack_id=context_pack.pack_id,
            agent=agent.name, model=current_model,
            status=AgentRunStatus.FAILED,
        )
        return AgentRunResult(agent_run=agent_run)
