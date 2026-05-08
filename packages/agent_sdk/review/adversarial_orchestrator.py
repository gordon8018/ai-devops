"""Rotating adversarial review loop: implement → review → score → retry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from agents import Agent, Runner

from packages.agent_sdk.models.router import ModelRouter
from packages.agent_sdk.review.review_scorer import ReviewScore, ReviewScorer
from packages.agent_sdk.review.review_prompt import REVIEWER_SYSTEM_PROMPT, build_review_prompt
from packages.agent_sdk.runner.agent_factory import AgentFactory
from packages.agent_sdk.runner.context_bridge import ContextBridge
from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
from packages.shared.domain.models import AgentRun, AgentRunResult, AgentRunStatus, ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack

logger = logging.getLogger(__name__)

# Reviewer pool — alternate providers to maximise blind-spot coverage.
# Implementer provider is excluded from reviewer selection each round (Fix H7).
DEFAULT_REVIEWER_ROTATION: list[tuple[str, str]] = [
    ("anthropic", "claude-opus-4-6"),
    ("anthropic", "claude-sonnet-4-6"),
    ("openai",    "gpt-5.4"),
]

MAX_REVIEW_ROUNDS = 5
MAX_TURNS_IMPL = 50
MAX_TURNS_REVIEW = 5
_REVIEWER_SEMAPHORE_SIZE = 16  # reviewers are lightweight — use a separate wider semaphore


@dataclass(frozen=True)
class AdversarialReviewConfig:
    max_rounds: int = MAX_REVIEW_ROUNDS
    pass_threshold: int = 85
    stall_rounds: int = 2
    reviewer_rotation: tuple[tuple[str, str], ...] = tuple(
        (p, m) for p, m in DEFAULT_REVIEWER_ROTATION
    )


@dataclass
class AdversarialRoundResult:
    round_num: int
    review_score: ReviewScore
    implementation_output: str
    reviewer_model: str
    token_usage: dict[str, Any] = field(default_factory=dict)


class AdversarialReviewOrchestrator:
    """
    Implement → review → score loop with rotating reviewer models.

    Callers should use execute_with_review_and_rounds() which returns both the
    final AgentRunResult and the list of round results (needed for knowledge extraction).
    The orchestrator composes AgentExecutor._run_agent_once() rather than calling
    Runner.run() directly, preserving semaphore and token collection (Fix C5).
    """

    def __init__(
        self,
        executor: Any,  # AgentExecutor — avoid circular import with TYPE_CHECKING
        config: AdversarialReviewConfig | None = None,
        event_bus: Any = None,
    ):
        self._executor = executor
        self._config = config or AdversarialReviewConfig()
        self._event_bus = event_bus
        self._factory = AgentFactory()
        self._reviewer_semaphore = asyncio.Semaphore(_REVIEWER_SEMAPHORE_SIZE)

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event_type, payload)

    def _eligible_reviewers(self, impl_provider: str) -> list[tuple[str, str]]:
        """Return rotation list excluding impl_provider when alternatives exist."""
        rotation = list(self._config.reviewer_rotation)
        cross = [(p, m) for p, m in rotation if p != impl_provider]
        return cross if cross else rotation

    async def execute_with_review_and_rounds(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        plan_id: str,
        workspace_path: str,
    ) -> tuple[AgentRunResult, list[AdversarialRoundResult]]:
        """
        Run the adversarial review loop.
        Returns (AgentRunResult, list[AdversarialRoundResult]) so callers have
        access to the final implementation_output for knowledge extraction.
        """
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        impl_provider, impl_model = ModelRouter.resolve(task_type_value)
        eligible_reviewers = self._eligible_reviewers(impl_provider)

        all_findings: list[ReviewFinding] = []
        round_results: list[AdversarialRoundResult] = []
        prior_review_text = "None"
        stall_count = 0

        for review_round in range(self._config.max_rounds):
            # — Implementer run (via executor._run_agent_once — respects semaphore) —
            impl_output, impl_usage, impl_status = await self._run_implementer(
                subtask=subtask,
                context_pack=context_pack,
                work_item_id=work_item_id,
                workspace_path=workspace_path,
                prior_review=prior_review_text,
                round_num=review_round,
                impl_model=impl_model,
            )

            if impl_status == AgentRunStatus.FAILED:
                break

            # — Reviewer run (dedicated semaphore, not workspace semaphore) —
            reviewer_provider, reviewer_model = eligible_reviewers[
                review_round % len(eligible_reviewers)
            ]
            review_output, review_usage = await self._run_reviewer(
                subtask=subtask,
                implementation_output=impl_output,
                prior_feedback=prior_review_text,
                reviewer_model=reviewer_model,
                work_item_id=work_item_id,
                round_num=review_round,
            )

            review_score = ReviewScorer.parse(review_output, subtask_id=subtask.id)
            all_findings.extend(review_score.findings)

            round_result = AdversarialRoundResult(
                round_num=review_round,
                review_score=review_score,
                implementation_output=impl_output,
                reviewer_model=reviewer_model,
                token_usage={**impl_usage, **review_usage},
            )
            round_results.append(round_result)

            self._publish("adversarial_review.round_completed", {
                "subtask_id": subtask.id,
                "round": review_round,
                "score": review_score.score,
                "passed": review_score.passed,
                "reviewer_model": reviewer_model,
                "work_item_id": work_item_id,
            })

            if review_score.passed:
                self._publish("adversarial_review.passed", {
                    "subtask_id": subtask.id,
                    "final_score": review_score.score,
                    "rounds_taken": review_round + 1,
                })
                agent_run = AgentRun(
                    run_id=f"{subtask.id}-adversarial-round-{review_round}",
                    work_item_id=work_item_id,
                    context_pack_id=context_pack.pack_id,
                    agent=f"adversarial-{impl_model}",
                    model=impl_model,
                    status=AgentRunStatus.COMPLETED,
                )
                combined_usage = _merge_usage(round_results)
                return (
                    AgentRunResult(agent_run=agent_run, review_findings=all_findings, token_usage=combined_usage),
                    round_results,
                )

            # Stall detection (Fix H6)
            if len(round_results) >= 2:
                prev_score = round_results[-2].review_score.score
                if review_score.score <= prev_score:
                    stall_count += 1
                    if stall_count >= self._config.stall_rounds:
                        self._publish("adversarial_review.stalled", {
                            "subtask_id": subtask.id,
                            "round": review_round,
                            "score": review_score.score,
                        })
                        logger.warning(
                            "Adversarial review stalled at round %d (score=%d) for subtask %s",
                            review_round, review_score.score, subtask.id,
                        )
                        break
                else:
                    stall_count = 0

            prior_review_text = review_score.raw_output[:2000]

        self._publish("adversarial_review.exhausted", {
            "subtask_id": subtask.id,
            "rounds": len(round_results),
        })
        agent_run = AgentRun(
            run_id=f"{subtask.id}-adversarial-exhausted",
            work_item_id=work_item_id,
            context_pack_id=context_pack.pack_id,
            agent=f"adversarial-{impl_model}",
            model=impl_model,
            status=AgentRunStatus.FAILED,
        )
        return (
            AgentRunResult(agent_run=agent_run, review_findings=all_findings),
            round_results,
        )

    async def _run_implementer(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        workspace_path: str,
        prior_review: str,
        round_num: int,
        impl_model: str,
    ) -> tuple[str, dict[str, Any], AgentRunStatus]:
        agent = self._factory.build(subtask, context_pack)
        run_context = ContextBridge.to_run_context(
            work_item_id=work_item_id,
            plan_id="",
            workspace_path=workspace_path,
            event_bus=self._event_bus,
        )

        prompt = subtask.prompt or subtask.description
        if prior_review and prior_review != "None":
            prompt = (
                f"{prompt}\n\n"
                f"## Previous Review Feedback (round {round_num})\n"
                f"Address all issues below before submitting:\n{prior_review}"
            )

        try:
            output, usage = await self._executor._run_agent_once(
                agent=agent,
                prompt=prompt,
                run_context=run_context,
                model=impl_model,
                work_item_id=work_item_id,
                subtask_id=subtask.id,
            )
            return output, usage, AgentRunStatus.COMPLETED
        except Exception as e:
            self._publish("adversarial_review.impl_failed", {
                "subtask_id": subtask.id, "round": round_num, "error": str(e),
            })
            logger.warning("Implementer failed at round %d for subtask %s: %s", round_num, subtask.id, e)
            return "", {}, AgentRunStatus.FAILED

    async def _run_reviewer(
        self,
        subtask: Subtask,
        implementation_output: str,
        prior_feedback: str,
        reviewer_model: str,
        work_item_id: str,
        round_num: int,
    ) -> tuple[str, dict[str, Any]]:
        definition_of_done = "\n".join(subtask.definition_of_done) if subtask.definition_of_done else ""
        review_prompt_text = build_review_prompt(
            subtask_title=subtask.title,
            definition_of_done=definition_of_done,
            implementation_output=implementation_output,
            prior_feedback=prior_feedback,
        )
        reviewer_agent = Agent(
            name=f"{subtask.id}-reviewer-round-{round_num}",
            instructions=REVIEWER_SYSTEM_PROMPT,
            model=reviewer_model,
            tools=[],
        )

        async with self._reviewer_semaphore:
            try:
                start = time.monotonic()
                result = await Runner.run(
                    starting_agent=reviewer_agent,
                    input=review_prompt_text,
                    max_turns=MAX_TURNS_REVIEW,
                )
                duration = time.monotonic() - start
                usage = TokenUsageCollector.extract(result, model=reviewer_model, duration=duration)
                output_text = str(result.final_output) if result.final_output else ""
                return output_text, usage
            except Exception as e:
                logger.warning("Reviewer failed at round %d for subtask %s: %s", round_num, subtask.id, e)
                return f"ADVERSARIAL_RESULT: FAIL\n[HIGH] Reviewer agent failed: {e}", {}


def _merge_usage(round_results: list[AdversarialRoundResult]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for r in round_results:
        for k, v in r.token_usage.items():
            if isinstance(v, (int, float)):
                merged[k] = merged.get(k, 0) + v
    return merged
