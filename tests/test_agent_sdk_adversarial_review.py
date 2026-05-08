"""Tests for the adversarial review module."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from packages.agent_sdk.review.review_scorer import ReviewScorer, ReviewScore, PASS_THRESHOLD
from packages.agent_sdk.review.review_prompt import build_review_prompt, REVIEWER_SYSTEM_PROMPT
from packages.agent_sdk.review.adversarial_orchestrator import (
    AdversarialReviewConfig,
    AdversarialReviewOrchestrator,
    DEFAULT_REVIEWER_ROTATION,
    _merge_usage,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType
    defaults = dict(
        id="s1", title="Auth Task", description="Implement auth",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Tests pass", "No secrets in code"),
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
    final_output: str = "Implementation complete."
    new_items: list = field(default_factory=list)
    last_agent: Any = None
    usage: FakeUsage = field(default_factory=FakeUsage)


def _make_executor(impl_output: str = "Implementation complete."):
    """Return a mock executor with _run_agent_once returning impl_output."""
    executor = MagicMock()
    executor._run_agent_once = AsyncMock(return_value=(impl_output, {"input_tokens": 100}))
    executor._semaphore = asyncio.Semaphore(8)
    return executor


# ── ReviewScorer ────────────────────────────────────────────────────────────

class TestReviewScorer:
    def test_parses_xx_of_100(self):
        raw = "Looks good. Score: 92/100\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 92
        assert score.passed is True

    def test_parses_bold_score(self):
        raw = "Score: **88**/100\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 88
        assert score.passed is True

    def test_parses_chinese_total(self):
        raw = "总分：85/100\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 85
        assert score.passed is True

    def test_parses_out_of_10_scaled(self):
        raw = "Overall: 9/10\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 90
        assert score.passed is True

    def test_parses_chinese_score_label(self):
        raw = "评分：88\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 88

    def test_sentinel_pass_makes_run_pass_regardless_of_score(self):
        # Sentinel PASS is authoritative for passed; numeric score is still preserved
        raw = "Score: 40/100\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.passed is True          # sentinel wins
        assert score.score == 40             # numeric value preserved for observability
        assert score.sentinel_used is True

    def test_sentinel_pass_defaults_score_100_when_no_numeric(self):
        raw = "Looks great!\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.passed is True
        assert score.score == 100            # default when no numeric found

    def test_sentinel_fail_in_tail(self):
        raw = "Score: 92/100\n\n\nADVERSARIAL_RESULT: FAIL"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 92             # numeric preserved
        assert score.passed is False         # sentinel wins
        assert score.sentinel_used is True

    def test_critical_blocks_pass_at_high_score(self):
        raw = "Score: 90/100\n[CRITICAL] SQL injection in query builder\nADVERSARIAL_RESULT: FAIL"
        score = ReviewScorer.parse(raw, "s1")
        assert score.passed is False
        assert any(f.severity == "critical" for f in score.findings)

    def test_extracts_multi_severity_findings(self):
        raw = (
            "Score: 70/100\n"
            "[CRITICAL] Missing auth check\n"
            "[HIGH] N+1 query in loop\n"
            "[MEDIUM] Variable name unclear\n"
            "[LOW] Trailing whitespace\n"
            "ADVERSARIAL_RESULT: FAIL"
        )
        score = ReviewScorer.parse(raw, "s1")
        severities = [f.severity for f in score.findings]
        assert "critical" in severities
        assert "high" in severities
        assert "medium" in severities
        assert "low" in severities

    def test_unparseable_output_scores_zero(self):
        score = ReviewScorer.parse("gibberish with no numbers", "s1")
        assert score.score == 0
        assert score.passed is False

    def test_score_clamped_to_100(self):
        raw = "Score: 999/100\nADVERSARIAL_RESULT: PASS"
        score = ReviewScorer.parse(raw, "s1")
        assert score.score == 100

    def test_finding_ids_include_subtask_id(self):
        raw = "Score: 60/100\n[HIGH] Bad code\nADVERSARIAL_RESULT: FAIL"
        score = ReviewScorer.parse(raw, "subtask-xyz")
        assert all("subtask-xyz" in f.finding_id for f in score.findings)


# ── build_review_prompt ─────────────────────────────────────────────────────

class TestBuildReviewPrompt:
    def test_includes_subtask_title(self):
        prompt = build_review_prompt("Auth module", "Tests pass", "impl output")
        assert "Auth module" in prompt

    def test_includes_definition_of_done(self):
        prompt = build_review_prompt("T", "Tests pass\nNo secrets", "impl")
        assert "Tests pass" in prompt

    def test_truncates_long_implementation(self):
        long_impl = "x" * 10000
        prompt = build_review_prompt("T", "DoD", long_impl)
        assert len(prompt) < 15000

    def test_prior_feedback_included(self):
        prompt = build_review_prompt("T", "DoD", "impl", prior_feedback="Fix the SQL query")
        assert "Fix the SQL query" in prompt


# ── Reviewer rotation ───────────────────────────────────────────────────────

class TestReviewerRotation:
    def _make_orchestrator(self, executor=None):
        return AdversarialReviewOrchestrator(
            executor=executor or _make_executor(),
            config=AdversarialReviewConfig(),
            event_bus=None,
        )

    def test_rotation_order(self):
        orch = self._make_orchestrator()
        # impl_provider = "openai" → eligible reviewers are only anthropic entries
        eligible = orch._eligible_reviewers("openai")
        for p, _ in eligible:
            assert p == "anthropic"

    def test_rotation_falls_back_to_all_when_no_cross_provider(self):
        config = AdversarialReviewConfig(
            reviewer_rotation=(("openai", "gpt-5.4"),),
        )
        orch = AdversarialReviewOrchestrator(executor=_make_executor(), config=config)
        eligible = orch._eligible_reviewers("openai")
        assert len(eligible) == 1
        assert eligible[0] == ("openai", "gpt-5.4")

    def test_cross_provider_excludes_impl_provider(self):
        orch = self._make_orchestrator()
        eligible = orch._eligible_reviewers("openai")
        assert all(p != "openai" for p, _ in eligible)

    def test_eligible_cycles_correctly(self):
        orch = self._make_orchestrator()
        eligible = orch._eligible_reviewers("openai")
        r0 = eligible[0 % len(eligible)]
        r1 = eligible[1 % len(eligible)]
        assert r0 != r1 or len(eligible) == 1


# ── AdversarialReviewOrchestrator integration ────────────────────────────────

class TestAdversarialOrchestrator:
    @pytest.fixture
    def subtask(self):
        return _make_subtask()

    @pytest.fixture
    def context_pack(self):
        return _make_context_pack()

    @pytest.mark.asyncio
    async def test_passes_on_first_round(self, subtask, context_pack):
        executor = _make_executor("Implementation done.")
        orch = AdversarialReviewOrchestrator(executor=executor, event_bus=None)

        passing_review = "Score: 90/100\nADVERSARIAL_RESULT: PASS"

        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=passing_review)
            result, rounds = await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        from packages.shared.domain.models import AgentRunStatus
        assert result.agent_run.status == AgentRunStatus.COMPLETED
        assert len(rounds) == 1
        assert rounds[0].review_score.passed is True

    @pytest.mark.asyncio
    async def test_retries_on_fail_then_passes(self, subtask, context_pack):
        executor = _make_executor("Implementation done.")
        orch = AdversarialReviewOrchestrator(executor=executor, event_bus=None)

        fail_review = "Score: 60/100\n[HIGH] Missing tests\nADVERSARIAL_RESULT: FAIL"
        pass_review = "Score: 91/100\nADVERSARIAL_RESULT: PASS"
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeRunResult(final_output=fail_review)
            return FakeRunResult(final_output=pass_review)

        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", side_effect=side_effect):
            result, rounds = await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        from packages.shared.domain.models import AgentRunStatus
        assert result.agent_run.status == AgentRunStatus.COMPLETED
        assert len(rounds) == 2
        assert rounds[0].review_score.passed is False
        assert rounds[1].review_score.passed is True

    @pytest.mark.asyncio
    async def test_exhausts_all_rounds_on_persistent_fail(self, subtask, context_pack):
        executor = _make_executor("Implementation done.")
        config = AdversarialReviewConfig(max_rounds=3, stall_rounds=99)  # disable stall
        orch = AdversarialReviewOrchestrator(executor=executor, config=config, event_bus=None)

        fail_review = "Score: 55/100\n[HIGH] Still broken\nADVERSARIAL_RESULT: FAIL"

        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=fail_review)
            result, rounds = await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        from packages.shared.domain.models import AgentRunStatus
        assert result.agent_run.status == AgentRunStatus.FAILED
        assert len(rounds) == 3

    @pytest.mark.asyncio
    async def test_stall_detection_stops_early(self, subtask, context_pack):
        executor = _make_executor("impl")
        config = AdversarialReviewConfig(max_rounds=5, stall_rounds=2)
        orch = AdversarialReviewOrchestrator(executor=executor, config=config, event_bus=None)

        # Same score every round → stall after 2 non-improving rounds
        stall_review = "Score: 65/100\n[HIGH] Same issue\nADVERSARIAL_RESULT: FAIL"

        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=stall_review)
            result, rounds = await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        # Should stop before max_rounds=5
        assert len(rounds) < 5

    @pytest.mark.asyncio
    async def test_prior_review_injected_into_next_impl_prompt(self, subtask, context_pack):
        captured_prompts: list[str] = []

        async def capturing_run_agent_once(agent, prompt, run_context, model, work_item_id, subtask_id):
            captured_prompts.append(prompt)
            return "impl output", {}

        executor = MagicMock()
        executor._run_agent_once = AsyncMock(side_effect=capturing_run_agent_once)

        config = AdversarialReviewConfig(max_rounds=2, stall_rounds=99)
        orch = AdversarialReviewOrchestrator(executor=executor, config=config, event_bus=None)

        fail_review = "Score: 60/100\n[HIGH] Fix the tests\nADVERSARIAL_RESULT: FAIL"
        pass_review = "Score: 95/100\nADVERSARIAL_RESULT: PASS"
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return FakeRunResult(final_output=fail_review if call_count == 1 else pass_review)

        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", side_effect=side_effect):
            await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        assert len(captured_prompts) >= 2
        # Second impl prompt should contain prior review feedback
        assert "Fix the tests" in captured_prompts[1] or "Previous Review Feedback" in captured_prompts[1]

    @pytest.mark.asyncio
    async def test_events_published_on_pass(self, subtask, context_pack):
        executor = _make_executor("impl output")
        bus = MagicMock()
        orch = AdversarialReviewOrchestrator(executor=executor, event_bus=bus)

        pass_review = "Score: 90/100\nADVERSARIAL_RESULT: PASS"
        with patch("packages.agent_sdk.review.adversarial_orchestrator.Runner.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = FakeRunResult(final_output=pass_review)
            await orch.execute_with_review_and_rounds(
                subtask=subtask, context_pack=context_pack,
                work_item_id="wi-001", plan_id="pl-001", workspace_path="/tmp",
            )

        published_types = [call.args[0] for call in bus.publish.call_args_list]
        assert "adversarial_review.round_completed" in published_types
        assert "adversarial_review.passed" in published_types


# ── _merge_usage ─────────────────────────────────────────────────────────────

class TestMergeUsage:
    def test_sums_numeric_values(self):
        from packages.agent_sdk.review.adversarial_orchestrator import AdversarialRoundResult
        r1 = AdversarialRoundResult(0, MagicMock(), "impl", "model", {"input_tokens": 100, "cost": 0.02})
        r2 = AdversarialRoundResult(1, MagicMock(), "impl", "model", {"input_tokens": 200, "cost": 0.04})
        merged = _merge_usage([r1, r2])
        assert merged["input_tokens"] == 300
        assert abs(merged["cost"] - 0.06) < 1e-9

    def test_ignores_non_numeric(self):
        from packages.agent_sdk.review.adversarial_orchestrator import AdversarialRoundResult
        r1 = AdversarialRoundResult(0, MagicMock(), "impl", "model", {"model": "gpt-5.4", "tokens": 50})
        merged = _merge_usage([r1])
        assert merged["tokens"] == 50
        assert "model" not in merged  # non-numeric skipped
