"""Agent execution engine wrapping Agents SDK Runner with retry and recovery."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

from agents import Agent, Runner
from agents.exceptions import MaxTurnsExceeded

from packages.agent_sdk.guardrails.input_guards import BoundaryGuard, PromptInjectionGuard
from packages.agent_sdk.models.router import ModelRouter
from packages.agent_sdk.runner.agent_factory import AgentFactory
from packages.agent_sdk.runner.context_bridge import ContextBridge, AgentRunContext
from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
from packages.shared.domain.models import AgentRun, AgentRunResult, AgentRunStatus, ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack
    from packages.agent_sdk.review.adversarial_orchestrator import AdversarialReviewConfig
    from packages.agent_sdk.ui_testing.visual_verifier import UITestResult

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [30, 90, 270]
MAX_TURNS = 50
MAX_CONCURRENT_SUBTASKS = 8


def _log_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("Background knowledge task failed: %s", task.exception())


class AgentExecutor:
    """Executes agent runs with retry, model escalation, and event publishing."""

    def __init__(self, event_bus: Any = None, max_concurrent: int = MAX_CONCURRENT_SUBTASKS):
        self._factory = AgentFactory()
        self._event_bus = event_bus
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._background_tasks: set[asyncio.Task] = set()

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event_type, payload)

    async def drain_background_tasks(self) -> None:
        """Await all pending background tasks. Call before shutdown."""
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    async def _run_agent_once(
        self,
        agent: Agent,
        prompt: str,
        run_context: AgentRunContext,
        model: str,
        work_item_id: str,
        subtask_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """
        Single guarded Runner invocation — respects semaphore and token collection.
        Does NOT catch exceptions; callers handle retry/escalation.
        Used by AdversarialReviewOrchestrator to compose without bypassing guardrails.
        """
        async with self._semaphore:
            self._publish("agent_run.started", {
                "subtask_id": subtask_id, "model": model, "work_item_id": work_item_id,
            })
            start_time = time.monotonic()
            result = await Runner.run(
                starting_agent=agent,
                input=prompt,
                context=run_context,
                max_turns=MAX_TURNS,
            )
            duration = time.monotonic() - start_time
            usage = TokenUsageCollector.extract(result, model=model, duration=duration)
            output_text = str(result.final_output) if result.final_output else ""
            self._publish("agent_run.completed", {
                "subtask_id": subtask_id, "model": model,
                "duration": round(duration, 2), **usage,
            })
            return output_text, usage

    async def execute(
        self, subtask: Subtask, context_pack: ContextPack,
        work_item_id: str, plan_id: str, workspace_path: str,
    ) -> AgentRunResult:
        """Single-agent execution with retry, escalation, and guardrails."""
        agent = self._factory.build(subtask, context_pack)
        run_context = ContextBridge.to_run_context(
            work_item_id=work_item_id,
            plan_id=plan_id,
            workspace_path=workspace_path,
            event_bus=self._event_bus,
        )
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        provider, current_model = ModelRouter.resolve(task_type_value)

        review_findings: list[ReviewFinding] = []
        boundary_result = BoundaryGuard.check(
            constraints=context_pack.constraints,
            definition_of_done=subtask.definition_of_done,
        )
        if boundary_result.tripwire_triggered:
            agent_run = AgentRun(
                run_id=f"{subtask.id}-run-guardrail-blocked",
                work_item_id=work_item_id,
                context_pack_id=context_pack.pack_id,
                agent=agent.name, model=current_model,
                status=AgentRunStatus.FAILED,
            )
            review_findings.append(ReviewFinding(
                finding_id=f"{subtask.id}-boundary",
                category="boundary", severity="critical",
                message=boundary_result.message,
                source_guardrail="BoundaryGuard",
            ))
            self._publish("agent_run.guardrail_triggered", {
                "subtask_id": subtask.id, "guardrail": "BoundaryGuard",
                "message": boundary_result.message,
            })
            return AgentRunResult(agent_run=agent_run, review_findings=review_findings)

        injection_result = PromptInjectionGuard.check(subtask.prompt or subtask.description)
        if injection_result.tripwire_triggered:
            agent_run = AgentRun(
                run_id=f"{subtask.id}-run-injection-blocked",
                work_item_id=work_item_id,
                context_pack_id=context_pack.pack_id,
                agent=agent.name, model=current_model,
                status=AgentRunStatus.FAILED,
            )
            review_findings.append(ReviewFinding(
                finding_id=f"{subtask.id}-injection",
                category="security", severity="critical",
                message=injection_result.message,
                source_guardrail="PromptInjectionGuard",
            ))
            self._publish("agent_run.guardrail_triggered", {
                "subtask_id": subtask.id, "guardrail": "PromptInjectionGuard",
                "message": injection_result.message,
            })
            return AgentRunResult(agent_run=agent_run, review_findings=review_findings)

        async with self._semaphore:
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

    async def execute_with_review(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        plan_id: str,
        workspace_path: str,
        review_config: AdversarialReviewConfig | None = None,
        evolve_knowledge: bool = True,
    ) -> AgentRunResult:
        """
        Execute subtask with adversarial review loop.
        Routes ui_verification tasks to UITestOrchestrator.
        On success, optionally triggers background CLAUDE.md knowledge evolution.
        """
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)

        if task_type_value == "ui_verification":
            return await self._execute_ui_verification(subtask, context_pack, work_item_id, workspace_path)

        # Input guardrails (same as execute())
        boundary_result = BoundaryGuard.check(
            constraints=context_pack.constraints,
            definition_of_done=subtask.definition_of_done,
        )
        if boundary_result.tripwire_triggered:
            agent = self._factory.build(subtask, context_pack)
            _, model = ModelRouter.resolve(task_type_value)
            agent_run = AgentRun(
                run_id=f"{subtask.id}-review-guardrail-blocked",
                work_item_id=work_item_id,
                context_pack_id=context_pack.pack_id,
                agent=agent.name, model=model,
                status=AgentRunStatus.FAILED,
            )
            self._publish("agent_run.guardrail_triggered", {
                "subtask_id": subtask.id, "guardrail": "BoundaryGuard",
                "message": boundary_result.message,
            })
            return AgentRunResult(
                agent_run=agent_run,
                review_findings=[ReviewFinding(
                    finding_id=f"{subtask.id}-boundary",
                    category="boundary", severity="critical",
                    message=boundary_result.message,
                    source_guardrail="BoundaryGuard",
                )],
            )

        injection_result = PromptInjectionGuard.check(subtask.prompt or subtask.description)
        if injection_result.tripwire_triggered:
            agent = self._factory.build(subtask, context_pack)
            _, model = ModelRouter.resolve(task_type_value)
            agent_run = AgentRun(
                run_id=f"{subtask.id}-review-injection-blocked",
                work_item_id=work_item_id,
                context_pack_id=context_pack.pack_id,
                agent=agent.name, model=model,
                status=AgentRunStatus.FAILED,
            )
            self._publish("agent_run.guardrail_triggered", {
                "subtask_id": subtask.id, "guardrail": "PromptInjectionGuard",
                "message": injection_result.message,
            })
            return AgentRunResult(
                agent_run=agent_run,
                review_findings=[ReviewFinding(
                    finding_id=f"{subtask.id}-injection",
                    category="security", severity="critical",
                    message=injection_result.message,
                    source_guardrail="PromptInjectionGuard",
                )],
            )

        # Lazy import to avoid circular dependency (executor ← orchestrator ← executor)
        from packages.agent_sdk.review.adversarial_orchestrator import AdversarialReviewOrchestrator

        orchestrator = AdversarialReviewOrchestrator(
            executor=self,
            config=review_config,
            event_bus=self._event_bus,
        )
        result, round_results = await orchestrator.execute_with_review_and_rounds(
            subtask=subtask,
            context_pack=context_pack,
            work_item_id=work_item_id,
            plan_id=plan_id,
            workspace_path=workspace_path,
        )

        if evolve_knowledge and result.agent_run.status == AgentRunStatus.COMPLETED and round_results:
            last_impl_output = round_results[-1].implementation_output
            task = asyncio.create_task(
                self._evolve_knowledge(result, last_impl_output, subtask, work_item_id, workspace_path)
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            task.add_done_callback(_log_task_exception)

        return result

    async def _evolve_knowledge(
        self,
        result: AgentRunResult,
        implementation_output: str,
        subtask: Subtask,
        work_item_id: str,
        workspace_path: str,
    ) -> None:
        from packages.agent_sdk.knowledge.knowledge_evolver import KnowledgeEvolver
        evolver = KnowledgeEvolver(event_bus=self._event_bus)
        await evolver.evolve(
            result=result,
            implementation_output=implementation_output,
            subtask_title=subtask.title,
            work_item_id=work_item_id,
            workspace_path=workspace_path,
        )

    async def _execute_ui_verification(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        workspace_path: str,
    ) -> AgentRunResult:
        from packages.agent_sdk.ui_testing.ui_test_orchestrator import UITestOrchestrator
        orchestrator = UITestOrchestrator(event_bus=self._event_bus)
        ui_result: UITestResult = await orchestrator.run(subtask, workspace_path)
        status = AgentRunStatus.COMPLETED if ui_result.passed else AgentRunStatus.FAILED
        agent_run = AgentRun(
            run_id=f"{subtask.id}-ui-test",
            work_item_id=work_item_id,
            context_pack_id=context_pack.pack_id,
            agent="UITestOrchestrator",
            model="claude-opus-4-6",
            status=status,
        )
        return AgentRunResult(agent_run=agent_run, review_findings=list(ui_result.findings))
