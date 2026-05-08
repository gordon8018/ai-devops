# Plan: Agent SDK — Adversarial Review + Knowledge Evolver + UI Testing

**Objective**: Port autoresearch's rotating adversarial review mechanism and CLAUDE.md self-evolution pattern into ai-devops's Agent SDK layer; add a UI testing module for visual verification of frontend subtasks.

**Repo**: gordon8018/ai-devops  
**Base branch**: main  
**Status**: DRAFT  
**Created**: 2026-05-08  
**Total Steps**: 5 (1 serial → 2 parallel → 1 serial → 1 serial)

---

## Background & Motivation

autoresearch (smallnest/autoresearch) has two mechanisms not present in ai-devops:

1. **Rotating adversarial review**: Different LLMs alternate between implementer and reviewer roles. Model A's blind spots are covered by Model B's review. Quality gate is LLM-scored (≥85/100 with 6-dimension rubric). In ai-devops today, `AgentExecutor.execute()` runs a single agent with no review loop.

2. **CLAUDE.md self-evolution**: After each successful iteration, the agent extracts reusable patterns and writes them to directory-level `CLAUDE.md` files. Since Claude Code reads these automatically on startup, subsequent WorkItems benefit from accumulated project knowledge — a zero-overhead knowledge flywheel.

3. **UI testing**: autoresearch's `lib/ui_verify.sh` auto-detects dev server commands, starts the server, captures screenshots via a multi-strategy cascade (Playwright → Chrome CDP → headless Chromium), and submits screenshots to an LLM for visual verification. ai-devops has no equivalent.

---

## Architecture Overview (after this plan)

```
packages/agent_sdk/
  review/                          ← NEW (Step 1)
    adversarial_orchestrator.py    # Impl→Review loop with rotation
    review_scorer.py               # Parse LLM output → ReviewScore
    review_prompt.py               # Reviewer system prompt templates
    __init__.py

  knowledge/                       ← NEW (Step 2a)
    knowledge_evolver.py           # Orchestrate extract + persist
    knowledge_extractor.py         # LLM call → ExtractedKnowledge
    claudemd_writer.py             # Atomic append to CLAUDE.md
    __init__.py

  ui_testing/                      ← NEW (Step 2b)
    server_detector.py             # Detect start cmd + port
    server_manager.py              # Start/stop/readiness polling
    screenshot_capture.py          # Multi-strategy screenshotter
    visual_verifier.py             # LLM visual verification
    ui_test_orchestrator.py        # Orchestrates full flow
    __init__.py

  models/
    router.py                      # +ui_verification, +adversarial_review routes

  runner/
    executor.py                    # +execute_with_review(), +_post_run_evolve()

  tools/
    registry.py                    # +ui_verification tool set
    builtin/
      ui_tools.py                  ← NEW (Step 2b)
```

---

## Step 1: AdversarialReviewOrchestrator

**Branch**: `feat/adversarial-review`  
**Depends on**: nothing (first step)  
**Model tier**: Strongest (Opus) for architecture  
**Parallel**: No — all later steps depend on this

### Context Brief

The existing `AgentExecutor.execute()` in `packages/agent_sdk/runner/executor.py` runs a single agent and returns `AgentRunResult`. There is no review loop. This step adds a new module `packages/agent_sdk/review/` with an orchestrator that wraps the single-run executor into a multi-round implement→review→score→retry cycle, using a rotating reviewer pool drawn from `packages/agent_sdk/models/router.py`.

Key files to read before starting:
- `packages/agent_sdk/runner/executor.py` — current execution engine
- `packages/agent_sdk/models/router.py` — `TASK_ROUTE_TABLE`, `ModelRouter.resolve()`
- `packages/agent_sdk/runner/agent_factory.py` — `AgentFactory.build()`
- `packages/shared/domain/models.py` — `AgentRun`, `ReviewFinding`, `AgentRunResult`

### Tasks

#### 1.1 Create `packages/agent_sdk/review/review_scorer.py`

```python
"""Parse free-text LLM review output into a structured ReviewScore."""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from packages.shared.domain.models import ReviewFinding

PASS_THRESHOLD = 85

_SCORE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(\d{1,3})\s*/\s*100\b"),          # "92/100"
    re.compile(r"Score:\s*\**(\d{1,3})\**/100"),      # "Score: **88**/100"
    re.compile(r"总分[：:]\s*(\d{1,3})\s*/\s*100"),   # Chinese "总分：92/100"
    re.compile(r"\b(\d{1,2})\s*/\s*10\b"),            # "9/10" → ×10
    re.compile(r"评分[：:]\s*(\d{1,3})"),              # "评分：88"
]

_SENTINEL_PASS = re.compile(r"ADVERSARIAL_RESULT\s*:\s*PASS", re.IGNORECASE)
_SENTINEL_FAIL = re.compile(r"ADVERSARIAL_RESULT\s*:\s*FAIL", re.IGNORECASE)

_SEVERITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("critical", re.compile(r"\[CRITICAL\](.+?)(?=\[|$)", re.DOTALL | re.IGNORECASE)),
    ("high",     re.compile(r"\[HIGH\](.+?)(?=\[|$)",     re.DOTALL | re.IGNORECASE)),
    ("medium",   re.compile(r"\[MEDIUM\](.+?)(?=\[|$)",   re.DOTALL | re.IGNORECASE)),
    ("low",      re.compile(r"\[LOW\](.+?)(?=\[|$)",      re.DOTALL | re.IGNORECASE)),
]


@dataclass(frozen=True)
class ReviewScore:
    score: int                               # 0–100
    passed: bool                             # score >= PASS_THRESHOLD and no CRITICAL
    findings: tuple[ReviewFinding, ...]
    raw_output: str
    sentinel_used: bool = False


class ReviewScorer:
    """Extract numeric score and findings from LLM reviewer output."""

    @staticmethod
    def parse(raw_output: str, subtask_id: str) -> ReviewScore:
        # 1. Sentinel check (last 10 non-empty lines)
        tail_lines = [l for l in raw_output.splitlines() if l.strip()][-10:]
        tail = "\n".join(tail_lines)
        if _SENTINEL_PASS.search(tail):
            return ReviewScore(score=100, passed=True, findings=(), raw_output=raw_output, sentinel_used=True)
        if _SENTINEL_FAIL.search(tail):
            findings = ReviewScorer._extract_findings(raw_output, subtask_id)
            return ReviewScore(score=0, passed=False, findings=findings, raw_output=raw_output, sentinel_used=True)

        # 2. Numeric score extraction (cascade through patterns)
        score: int | None = None
        for pattern in _SCORE_PATTERNS:
            m = pattern.search(raw_output)
            if m:
                raw_val = int(m.group(1))
                # Scale /10 scores
                score = raw_val * 10 if raw_val <= 10 else raw_val
                score = max(0, min(100, score))
                break

        if score is None:
            score = 0  # Cannot parse = treat as fail

        findings = ReviewScorer._extract_findings(raw_output, subtask_id)
        has_critical = any(f.severity == "critical" for f in findings)
        passed = (score >= PASS_THRESHOLD) and not has_critical

        return ReviewScore(score=score, passed=passed, findings=tuple(findings), raw_output=raw_output)

    @staticmethod
    def _extract_findings(raw_output: str, subtask_id: str) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for severity, pattern in _SEVERITY_PATTERNS:
            for i, m in enumerate(pattern.finditer(raw_output)):
                findings.append(ReviewFinding(
                    finding_id=f"{subtask_id}-review-{severity}-{i}",
                    category="review",
                    severity=severity,
                    message=m.group(1).strip()[:500],
                    source_guardrail="AdversarialReview",
                ))
        return findings
```

#### 1.2 Create `packages/agent_sdk/review/review_prompt.py`

```python
"""System prompt templates for the reviewer role."""

from __future__ import annotations

REVIEWER_SYSTEM_PROMPT = """\
You are a rigorous senior code reviewer conducting an adversarial review.
Your goal is to catch bugs, security issues, and quality problems the implementer may have missed.

## Scoring Rubric (total: 100 points)
- Correctness (35): Does the implementation meet all requirements?
- Test Quality (25): Are tests meaningful, not just passing for the sake of it?
- Code Quality (20): Is the code readable, maintainable, within size limits?
- Security (10): No secrets, no injection, no unsafe patterns?
- Performance (10): No N+1 queries, no unbounded operations?

## Output Format
1. Score each dimension explicitly.
2. Final score as: `Score: XX/100`
3. Flag issues as: `[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]` followed by description.
4. End with sentinel: `ADVERSARIAL_RESULT: PASS` or `ADVERSARIAL_RESULT: FAIL`

A score >= 85 with no CRITICAL issues = PASS. Otherwise = FAIL.
"""

REVIEW_REQUEST_TEMPLATE = """\
## Implementation to Review

**Subtask**: {subtask_title}
**Requirements**: {definition_of_done}
**Previous review feedback** (if any): {prior_feedback}

## Agent Output
{implementation_output}

Review the above implementation against the rubric. Be adversarial — find what the implementer missed.
"""


def build_review_prompt(
    subtask_title: str,
    definition_of_done: str,
    implementation_output: str,
    prior_feedback: str = "None",
) -> str:
    return REVIEW_REQUEST_TEMPLATE.format(
        subtask_title=subtask_title,
        definition_of_done=definition_of_done,
        implementation_output=implementation_output[:8000],  # cap to avoid overflow
        prior_feedback=prior_feedback,
    )
```

#### 1.3 Create `packages/agent_sdk/review/adversarial_orchestrator.py`

```python
"""Rotating adversarial review loop: impl → review → score → retry."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from agents import Agent, Runner

from packages.agent_sdk.models.router import ModelRouter
from packages.agent_sdk.review.review_scorer import ReviewScore, ReviewScorer
from packages.agent_sdk.review.review_prompt import (
    REVIEWER_SYSTEM_PROMPT, build_review_prompt,
)
from packages.agent_sdk.runner.agent_factory import AgentFactory
from packages.agent_sdk.runner.context_bridge import ContextBridge
from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
from packages.shared.domain.models import AgentRun, AgentRunResult, AgentRunStatus, ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack

# Reviewer rotation pool — different providers/models to maximize blind-spot coverage
DEFAULT_REVIEWER_ROTATION: list[tuple[str, str]] = [
    ("anthropic", "claude-opus-4-6"),    # Round 0: Opus — deep reasoning reviewer
    ("anthropic", "claude-sonnet-4-6"),  # Round 1: Sonnet — faster, different priors
    ("openai",    "gpt-5.4"),           # Round 2: Cross-provider — catches OpenAI-specific patterns
]

MAX_REVIEW_ROUNDS = 5
MAX_TURNS_PER_RUN = 50


@dataclass(frozen=True)
class AdversarialReviewConfig:
    max_rounds: int = MAX_REVIEW_ROUNDS
    pass_threshold: int = 85
    reviewer_rotation: tuple[tuple[str, str], ...] = tuple(DEFAULT_REVIEWER_ROTATION)


@dataclass
class AdversarialRoundResult:
    round_num: int
    review_score: ReviewScore
    implementation_output: str
    reviewer_model: str
    token_usage: dict[str, Any] = field(default_factory=dict)


class AdversarialReviewOrchestrator:
    """
    Wraps AgentExecutor in an implement→review→score loop.
    Different reviewer models rotate each round to cover model-specific blind spots.
    """

    def __init__(
        self,
        config: AdversarialReviewConfig | None = None,
        event_bus: Any = None,
    ):
        self._config = config or AdversarialReviewConfig()
        self._event_bus = event_bus
        self._factory = AgentFactory()

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event_type, payload)

    async def execute_with_review_and_rounds(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        plan_id: str,
        workspace_path: str,
    ) -> tuple[AgentRunResult, list[AdversarialRoundResult]]:
        """
        Run the adversarial review loop:
        1. Implementer agent runs the subtask
        2. Reviewer agent (rotating) scores the output
        3. If score < threshold, feed review back to implementer and retry
        4. Return (AgentRunResult, list[AdversarialRoundResult]) so callers can
           access the final implementation_output for knowledge extraction.
        """
        all_findings: list[ReviewFinding] = []
        round_results: list[AdversarialRoundResult] = []
        prior_review_text = "None"

        for review_round in range(self._config.max_rounds):
            # — Implementer run —
            impl_output, impl_usage, impl_status = await self._run_implementer(
                subtask=subtask,
                context_pack=context_pack,
                work_item_id=work_item_id,
                workspace_path=workspace_path,
                prior_review=prior_review_text,
                round_num=review_round,
            )

            if impl_status == AgentRunStatus.FAILED:
                break

            # — Reviewer run (rotating model) —
            reviewer_provider, reviewer_model = self._config.reviewer_rotation[
                review_round % len(self._config.reviewer_rotation)
            ]
            review_output, review_usage = await self._run_reviewer(
                subtask=subtask,
                implementation_output=impl_output,
                prior_feedback=prior_review_text,
                reviewer_provider=reviewer_provider,
                reviewer_model=reviewer_model,
                work_item_id=work_item_id,
                round_num=review_round,
            )

            # — Score —
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
                task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
                _, impl_model = ModelRouter.resolve(task_type_value)
                agent_run = AgentRun(
                    run_id=f"{subtask.id}-adversarial-round-{review_round}",
                    work_item_id=work_item_id,
                    context_pack_id=context_pack.pack_id,
                    agent=f"adversarial-{impl_model}",
                    model=impl_model,
                    status=AgentRunStatus.COMPLETED,
                )
                combined_usage = {}
                for r in round_results:
                    for k, v in r.token_usage.items():
                        combined_usage[k] = combined_usage.get(k, 0) + (v if isinstance(v, (int, float)) else 0)
                return AgentRunResult(
                    agent_run=agent_run,
                    review_findings=all_findings,
                    token_usage=combined_usage,
                ), round_results

            # Feed review back for next round
            prior_review_text = review_score.raw_output[:2000]

        # Exhausted rounds — return failed result with all findings
        self._publish("adversarial_review.exhausted", {
            "subtask_id": subtask.id,
            "rounds": self._config.max_rounds,
        })
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        _, impl_model = ModelRouter.resolve(task_type_value)
        agent_run = AgentRun(
            run_id=f"{subtask.id}-adversarial-exhausted",
            work_item_id=work_item_id,
            context_pack_id=context_pack.pack_id,
            agent=f"adversarial-{impl_model}",
            model=impl_model,
            status=AgentRunStatus.FAILED,
        )
        return AgentRunResult(agent_run=agent_run, review_findings=all_findings), round_results

    async def _run_implementer(
        self,
        subtask: Subtask,
        context_pack: ContextPack,
        work_item_id: str,
        workspace_path: str,
        prior_review: str,
        round_num: int,
    ) -> tuple[str, dict[str, Any], AgentRunStatus]:
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        _, model = ModelRouter.resolve(task_type_value)
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
            start = time.monotonic()
            result = await Runner.run(
                starting_agent=agent,
                input=prompt,
                context=run_context,
                max_turns=MAX_TURNS_PER_RUN,
            )
            duration = time.monotonic() - start
            usage = TokenUsageCollector.extract(result, model=model, duration=duration)
            output_text = str(result.final_output) if result.final_output else ""
            return output_text, usage, AgentRunStatus.COMPLETED
        except Exception as e:
            self._publish("adversarial_review.impl_failed", {
                "subtask_id": subtask.id, "round": round_num, "error": str(e),
            })
            return "", {}, AgentRunStatus.FAILED

    async def _run_reviewer(
        self,
        subtask: Subtask,
        implementation_output: str,
        prior_feedback: str,
        reviewer_provider: str,
        reviewer_model: str,
        work_item_id: str,
        round_num: int,
    ) -> tuple[str, dict[str, Any]]:
        definition_of_done = "\n".join(subtask.definition_of_done) if subtask.definition_of_done else ""
        review_prompt = build_review_prompt(
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

        try:
            start = time.monotonic()
            result = await Runner.run(
                starting_agent=reviewer_agent,
                input=review_prompt,
                max_turns=5,
            )
            duration = time.monotonic() - start
            usage = TokenUsageCollector.extract(result, model=reviewer_model, duration=duration)
            output_text = str(result.final_output) if result.final_output else ""
            return output_text, usage
        except Exception:
            return "ADVERSARIAL_RESULT: FAIL\n[HIGH] Reviewer agent failed to produce output.", {}
```

#### 1.4 Create `packages/agent_sdk/review/__init__.py`

```python
from packages.agent_sdk.review.adversarial_orchestrator import (
    AdversarialReviewOrchestrator,
    AdversarialReviewConfig,
    DEFAULT_REVIEWER_ROTATION,
)
from packages.agent_sdk.review.review_scorer import ReviewScorer, ReviewScore
```

### Verification

```bash
cd /path/to/ai-devops
python -c "from packages.agent_sdk.review import AdversarialReviewOrchestrator; print('import ok')"
pytest tests/agent_sdk/test_adversarial_orchestrator.py -v
```

### Exit Criteria

- [ ] `packages/agent_sdk/review/` module imports without error
- [ ] `ReviewScorer.parse()` correctly extracts scores from the 5 pattern variants (unit tested)
- [ ] `AdversarialReviewOrchestrator.execute_with_review()` completes with mocked `Runner.run`
- [ ] Reviewer rotation cycles correctly: round 0 → Opus, round 1 → Sonnet, round 2 → GPT
- [ ] All new tests pass; existing 812 tests still pass

### Rollback

Delete `packages/agent_sdk/review/` — no existing files were modified in this step.

---

## Step 2a: KnowledgeEvolver (CLAUDE.md Self-Evolution)

**Branch**: `feat/knowledge-evolver`  
**Depends on**: Step 1  
**Model tier**: Default (Sonnet)  
**Parallel with**: Step 2b (no shared files)

### Context Brief

This step adds `packages/agent_sdk/knowledge/` — a module that fires after a successful `AdversarialReviewOrchestrator.execute_with_review()` to extract reusable patterns from the agent's work and persist them to `CLAUDE.md` files in the workspace. Claude Code reads `CLAUDE.md` files automatically, so this creates a cross-WorkItem knowledge flywheel at zero framework cost.

Key files to read before starting:
- `packages/agent_sdk/review/adversarial_orchestrator.py` — the `AgentRunResult` it returns
- `packages/agent_sdk/runner/context_bridge.py` — `workspace_path` field
- `packages/shared/domain/models.py` — `AgentRun`, `AgentRunResult`

### Tasks

#### 2a.1 Create `packages/agent_sdk/knowledge/knowledge_extractor.py`

```python
"""LLM call to extract structured reusable knowledge from agent output."""

from __future__ import annotations

from dataclasses import dataclass
from agents import Agent, Runner


EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge distillation assistant. Given an agent's implementation output, extract only:
1. Reusable patterns (things that worked well and should be repeated)
2. Gotchas (traps, non-obvious behaviors, things to avoid)
3. Decisions (architectural or design choices made and why)

Format output as JSON:
{
  "patterns": ["..."],
  "gotchas":  ["..."],
  "decisions": ["..."]
}

Be specific and concrete. Omit generic advice. Each entry ≤ 150 chars.
Max 5 items per category. Output ONLY the JSON object.
"""


@dataclass(frozen=True)
class ExtractedKnowledge:
    patterns: tuple[str, ...]
    gotchas: tuple[str, ...]
    decisions: tuple[str, ...]

    def is_empty(self) -> bool:
        return not (self.patterns or self.gotchas or self.decisions)


class KnowledgeExtractor:
    """Call an LLM to extract structured knowledge from implementation output."""

    @staticmethod
    async def extract(
        implementation_output: str,
        subtask_title: str,
        extractor_model: str = "claude-sonnet-4-6",
    ) -> ExtractedKnowledge:
        import json

        agent = Agent(
            name="knowledge-extractor",
            instructions=EXTRACTION_SYSTEM_PROMPT,
            model=extractor_model,
            tools=[],
        )
        prompt = f"Subtask: {subtask_title}\n\nImplementation output:\n{implementation_output[:6000]}"

        try:
            result = await Runner.run(starting_agent=agent, input=prompt, max_turns=3)
            raw = str(result.final_output or "").strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            return ExtractedKnowledge(
                patterns=tuple(str(x)[:150] for x in data.get("patterns", [])[:5]),
                gotchas=tuple(str(x)[:150] for x in data.get("gotchas", [])[:5]),
                decisions=tuple(str(x)[:150] for x in data.get("decisions", [])[:5]),
            )
        except Exception:
            return ExtractedKnowledge(patterns=(), gotchas=(), decisions=())
```

#### 2a.2 Create `packages/agent_sdk/knowledge/claudemd_writer.py`

```python
"""Atomic append of extracted knowledge to CLAUDE.md files."""

from __future__ import annotations

import fcntl
import hashlib
import os
from datetime import datetime
from pathlib import Path

from packages.agent_sdk.knowledge.knowledge_extractor import ExtractedKnowledge

MAX_CLAUDEMD_BYTES = 50 * 1024  # 50KB cap before archiving
SECTION_HEADER = "## Patterns (auto-accumulated by AI-DevOps)\n"
ARCHIVE_SUFFIX = ".archive"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


class ClaudeMDWriter:
    """Thread-safe append of knowledge entries to CLAUDE.md."""

    @staticmethod
    def write(
        workspace_path: str,
        knowledge: ExtractedKnowledge,
        work_item_id: str,
        subtask_id: str,
        timestamp: str | None = None,
    ) -> bool:
        """Append knowledge to {workspace_path}/CLAUDE.md. Returns True if written."""
        if knowledge.is_empty():
            return False

        ts = timestamp or datetime.utcnow().strftime("%Y-%m-%d")
        entry = ClaudeMDWriter._format_entry(knowledge, work_item_id, subtask_id, ts)
        entry_hash = _content_hash(entry)

        claudemd_path = Path(workspace_path) / "CLAUDE.md"

        with open(claudemd_path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.seek(0)
                existing = f.read()

                # Dedup: skip if this exact hash already present
                if entry_hash in existing:
                    return False

                # Rotate if file exceeds size cap
                if len(existing.encode()) > MAX_CLAUDEMD_BYTES:
                    ClaudeMDWriter._rotate(claudemd_path, existing)
                    existing = ""

                # Ensure section header exists
                if SECTION_HEADER not in existing:
                    f.write(f"\n\n{SECTION_HEADER}\n")

                f.write(f"\n<!-- hash:{entry_hash} -->\n{entry}\n")
                return True
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def _format_entry(
        knowledge: ExtractedKnowledge,
        work_item_id: str,
        subtask_id: str,
        ts: str,
    ) -> str:
        lines = [f"### [{ts}] {work_item_id} / {subtask_id}"]
        if knowledge.patterns:
            lines.append("**Patterns:**")
            lines.extend(f"- {p}" for p in knowledge.patterns)
        if knowledge.gotchas:
            lines.append("**Gotchas:**")
            lines.extend(f"- {g}" for g in knowledge.gotchas)
        if knowledge.decisions:
            lines.append("**Decisions:**")
            lines.extend(f"- {d}" for d in knowledge.decisions)
        return "\n".join(lines)

    @staticmethod
    def _rotate(path: Path, existing_content: str) -> None:
        """Move current CLAUDE.md content to archive file."""
        archive_path = path.with_suffix(ARCHIVE_SUFFIX)
        with open(archive_path, "a") as af:
            af.write(f"\n\n# Archived {datetime.utcnow().isoformat()}\n")
            af.write(existing_content)
        # Truncate main file to just the header
        path.write_text(f"# Project Knowledge\n\n{SECTION_HEADER}\n")
```

#### 2a.3 Create `packages/agent_sdk/knowledge/knowledge_evolver.py`

```python
"""Orchestrate knowledge extraction and CLAUDE.md persistence after successful runs."""

from __future__ import annotations

import asyncio
from typing import Any

from packages.agent_sdk.knowledge.knowledge_extractor import KnowledgeExtractor
from packages.agent_sdk.knowledge.claudemd_writer import ClaudeMDWriter
from packages.shared.domain.models import AgentRunResult, AgentRunStatus


class KnowledgeEvolver:
    """
    Post-run hook: extracts reusable patterns from successful agent output
    and appends them to CLAUDE.md for cross-WorkItem knowledge accumulation.

    Fire-and-forget: callers should await or background this; errors are suppressed
    so knowledge persistence never blocks the main execution path.
    """

    def __init__(self, event_bus: Any = None, extractor_model: str = "claude-sonnet-4-6"):
        self._event_bus = event_bus
        self._extractor_model = extractor_model

    async def evolve(
        self,
        result: AgentRunResult,
        implementation_output: str,
        subtask_title: str,
        work_item_id: str,
        workspace_path: str,
    ) -> bool:
        """
        Extract knowledge from implementation_output and write to CLAUDE.md.
        Returns True if knowledge was written. Always swallows exceptions.
        """
        if result.agent_run.status != AgentRunStatus.COMPLETED:
            return False
        if not implementation_output.strip():
            return False

        try:
            knowledge = await KnowledgeExtractor.extract(
                implementation_output=implementation_output,
                subtask_title=subtask_title,
                extractor_model=self._extractor_model,
            )
            written = ClaudeMDWriter.write(
                workspace_path=workspace_path,
                knowledge=knowledge,
                work_item_id=work_item_id,
                subtask_id=result.agent_run.run_id,
            )
            if self._event_bus and written:
                self._event_bus.publish("knowledge.evolved", {
                    "work_item_id": work_item_id,
                    "subtask_id": result.agent_run.run_id,
                    "patterns": len(knowledge.patterns),
                    "gotchas": len(knowledge.gotchas),
                    "decisions": len(knowledge.decisions),
                })
            return written
        except Exception:
            return False
```

#### 2a.4 Create `packages/agent_sdk/knowledge/__init__.py`

```python
from packages.agent_sdk.knowledge.knowledge_evolver import KnowledgeEvolver
from packages.agent_sdk.knowledge.knowledge_extractor import KnowledgeExtractor, ExtractedKnowledge
from packages.agent_sdk.knowledge.claudemd_writer import ClaudeMDWriter
```

### Verification

```bash
python -c "from packages.agent_sdk.knowledge import KnowledgeEvolver; print('import ok')"
pytest tests/agent_sdk/test_knowledge_evolver.py -v
# Verify CLAUDE.md is written correctly:
python -c "
from packages.agent_sdk.knowledge.claudemd_writer import ClaudeMDWriter
from packages.agent_sdk.knowledge.knowledge_extractor import ExtractedKnowledge
k = ExtractedKnowledge(patterns=('use asyncpg not psycopg2',), gotchas=('set connection_timeout=5',), decisions=())
ClaudeMDWriter.write('/tmp/test_ws', k, 'WI-001', 'sub-001')
print(open('/tmp/test_ws/CLAUDE.md').read())
"
```

### Exit Criteria

- [ ] `KnowledgeExtractor.extract()` returns `ExtractedKnowledge` from mocked `Runner.run`
- [ ] `ClaudeMDWriter.write()` appends correctly and deduplicates by content hash
- [ ] `ClaudeMDWriter._rotate()` moves content to `.archive` when size cap exceeded
- [ ] `KnowledgeEvolver.evolve()` returns `False` silently on failed `AgentRunResult`
- [ ] CLAUDE.md file has correct section header and entry format
- [ ] All new tests pass; existing 812 tests still pass

### Rollback

Delete `packages/agent_sdk/knowledge/` — no existing files modified.

---

## Step 2b: UITestModule

**Branch**: `feat/ui-testing`  
**Depends on**: Step 1  
**Model tier**: Strongest (Opus) for visual verifier (vision capability required)  
**Parallel with**: Step 2a (no shared files)

### Context Brief

This step adds `packages/agent_sdk/ui_testing/` — a module triggered when a subtask has `task_type == "ui_verification"`. It auto-detects the workspace's dev server start command and port, starts the server, captures a screenshot using a multi-strategy cascade (Playwright → Chrome CDP → headless Chromium), submits the screenshot to an Anthropic vision-capable model for visual verification against the subtask's definition_of_done, and returns a `UITestResult`.

Key files to read before starting:
- `packages/agent_sdk/tools/registry.py` — `_TASK_TOOLS` dict, `ToolRegistry.resolve()`
- `packages/agent_sdk/tools/builtin/command_tools.py` — `run_command_impl` pattern for safety
- `packages/agent_sdk/models/router.py` — add `"ui_verification"` route

### Tasks

#### 2b.1 Create `packages/agent_sdk/ui_testing/server_detector.py`

```python
"""Detect dev server start command and port from workspace."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServerConfig:
    start_cmd: str
    port: int
    env: dict[str, str]
    framework: str


_PORT_PATTERNS: list[re.Pattern] = [
    re.compile(r"PORT\s*=\s*(\d{4,5})"),
    re.compile(r'"port"\s*:\s*(\d{4,5})'),
    re.compile(r"port\s*=\s*(\d{4,5})"),
    re.compile(r":(\d{4,5})"),
]

_DEFAULT_PORTS: dict[str, int] = {
    "next": 3000, "vite": 5173, "react-scripts": 3000,
    "vue": 5173, "nuxt": 3000, "svelte": 5173,
    "flask": 5000, "django": 8000, "fastapi": 8000,
    "go": 8080, "rust": 8080, "node": 3000,
}

_START_CMD_CANDIDATES: list[tuple[str, str, str]] = [
    # (detection file, start command, framework)
    ("package.json",      "npm run dev",      "node"),
    ("vite.config.ts",    "npm run dev",      "vite"),
    ("vite.config.js",    "npm run dev",      "vite"),
    ("next.config.js",    "npm run dev",      "next"),
    ("next.config.ts",    "npm run dev",      "next"),
    ("manage.py",         "python manage.py runserver 0.0.0.0:8000", "django"),
    ("app.py",            "python app.py",    "flask"),
    ("main.py",           "python main.py",   "fastapi"),
    ("Cargo.toml",        "cargo run",        "rust"),
    ("go.mod",            "go run .",         "go"),
)


class ServerDetector:
    @staticmethod
    def detect(workspace_path: str) -> ServerConfig | None:
        ws = Path(workspace_path)

        for detection_file, default_cmd, framework in _START_CMD_CANDIDATES:
            if (ws / detection_file).exists():
                # Try to read custom start command from package.json
                start_cmd = default_cmd
                if detection_file == "package.json":
                    start_cmd = ServerDetector._read_npm_dev_script(ws) or default_cmd

                port = ServerDetector._detect_port(ws, framework)
                env = ServerDetector._build_env(port)
                return ServerConfig(start_cmd=start_cmd, port=port, env=env, framework=framework)

        return None

    @staticmethod
    def _read_npm_dev_script(ws: Path) -> str | None:
        try:
            data = json.loads((ws / "package.json").read_text())
            scripts = data.get("scripts", {})
            return f"npm run {next(iter(scripts))}" if scripts else None
        except Exception:
            return None

    @staticmethod
    def _detect_port(ws: Path, framework: str) -> int:
        # Check .env files
        for env_file in [".env.local", ".env", ".env.development"]:
            env_path = ws / env_file
            if env_path.exists():
                content = env_path.read_text()
                for pattern in _PORT_PATTERNS:
                    m = pattern.search(content)
                    if m:
                        return int(m.group(1))

        # Check config files for port declarations
        for config in ["vite.config.ts", "vite.config.js", "next.config.js"]:
            cfg_path = ws / config
            if cfg_path.exists():
                content = cfg_path.read_text()
                for pattern in _PORT_PATTERNS:
                    m = pattern.search(content)
                    if m:
                        return int(m.group(1))

        return _DEFAULT_PORTS.get(framework, 3000)

    @staticmethod
    def _build_env(port: int) -> dict[str, str]:
        env = dict(os.environ)
        env["PORT"] = str(port)
        env["CI"] = "false"        # Prevent CI-mode that skips server start
        env["BROWSER"] = "none"    # Prevent auto-opening browser
        return env
```

#### 2b.2 Create `packages/agent_sdk/ui_testing/server_manager.py`

```python
"""Start, wait for readiness, and stop a dev server process."""

from __future__ import annotations

import asyncio
import shlex
import socket
import subprocess
import time
from dataclasses import dataclass

from packages.agent_sdk.ui_testing.server_detector import ServerConfig

READINESS_TIMEOUT_S = 60
POLL_INTERVAL_S = 1.0


@dataclass
class ServerProcess:
    proc: subprocess.Popen
    port: int
    url: str


class ServerManager:

    @staticmethod
    async def start_and_wait(config: ServerConfig, workspace_path: str) -> ServerProcess:
        """Start the dev server and wait for it to accept connections."""
        cmd = shlex.split(config.start_cmd)
        proc = subprocess.Popen(
            cmd,
            cwd=workspace_path,
            env=config.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        url = f"http://localhost:{config.port}"
        deadline = time.monotonic() + READINESS_TIMEOUT_S

        while time.monotonic() < deadline:
            if ServerManager._port_open("localhost", config.port):
                return ServerProcess(proc=proc, port=config.port, url=url)
            await asyncio.sleep(POLL_INTERVAL_S)

        proc.terminate()
        raise TimeoutError(
            f"Dev server did not start on port {config.port} within {READINESS_TIMEOUT_S}s. "
            f"Command: {config.start_cmd}"
        )

    @staticmethod
    def stop(server_proc: ServerProcess) -> None:
        try:
            server_proc.proc.terminate()
            server_proc.proc.wait(timeout=5)
        except Exception:
            server_proc.proc.kill()

    @staticmethod
    def _port_open(host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            return False
```

#### 2b.3 Create `packages/agent_sdk/ui_testing/screenshot_capture.py`

```python
"""Multi-strategy screenshot capture with graceful fallback."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class ScreenshotCapture:
    """
    Capture screenshots using a cascade of strategies:
    1. Playwright (async, most reliable)
    2. Chrome DevTools Protocol (if Chrome is available)
    3. Headless Chromium CLI
    4. Headless Chrome CLI
    Raises RuntimeError if all strategies fail.
    """

    @staticmethod
    async def capture(url: str, output_path: str | None = None) -> str:
        """Returns path to the saved screenshot PNG."""
        if output_path is None:
            output_path = os.path.join(tempfile.mkdtemp(), "screenshot.png")

        strategies = [
            ScreenshotCapture._capture_playwright,
            ScreenshotCapture._capture_chrome_cdp,
            ScreenshotCapture._capture_chromium_headless,
            ScreenshotCapture._capture_chrome_headless,
        ]

        last_error = RuntimeError("No screenshot strategy available")
        for strategy in strategies:
            try:
                result = await strategy(url, output_path)
                if result and Path(result).exists():
                    return result
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"All screenshot strategies failed. Last error: {last_error}")

    @staticmethod
    async def capture_as_base64(url: str) -> str:
        path = await ScreenshotCapture.capture(url)
        return base64.b64encode(Path(path).read_bytes()).decode()

    @staticmethod
    async def _capture_playwright(url: str, output_path: str) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 800})
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.screenshot(path=output_path, full_page=False)
            await browser.close()
        return output_path

    @staticmethod
    async def _capture_chrome_cdp(url: str, output_path: str) -> str | None:
        chrome_bin = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if not chrome_bin:
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                chrome_bin, "--headless=new", "--disable-gpu",
                f"--screenshot={output_path}",
                f"--window-size=1280,800",
                "--no-sandbox", "--disable-dev-shm-usage",
                url,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=tmpdir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=20)
        return output_path if Path(output_path).exists() else None

    @staticmethod
    async def _capture_chromium_headless(url: str, output_path: str) -> str | None:
        chromium_bin = shutil.which("chromium") or shutil.which("chromium-browser")
        if not chromium_bin:
            return None
        return await ScreenshotCapture._run_headless_binary(chromium_bin, url, output_path)

    @staticmethod
    async def _capture_chrome_headless(url: str, output_path: str) -> str | None:
        chrome_bin = shutil.which("chrome")
        if not chrome_bin:
            return None
        return await ScreenshotCapture._run_headless_binary(chrome_bin, url, output_path)

    @staticmethod
    async def _run_headless_binary(binary: str, url: str, output_path: str) -> str | None:
        cmd = [
            binary, "--headless", "--disable-gpu",
            f"--screenshot={output_path}", "--window-size=1280,800",
            "--no-sandbox", url,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=20)
        return output_path if Path(output_path).exists() else None
```

#### 2b.4 Create `packages/agent_sdk/ui_testing/visual_verifier.py`

```python
"""LLM visual verification of screenshots against definition_of_done."""

from __future__ import annotations

from dataclasses import dataclass, field
from packages.shared.domain.models import ReviewFinding

VISUAL_VERIFIER_SYSTEM_PROMPT = """\
You are a frontend QA engineer reviewing a screenshot of a web application.
You will be given:
1. A screenshot (image)
2. The definition of done (acceptance criteria)

Evaluate whether the screenshot meets the acceptance criteria.

## Output Format
- Score: XX/100
- [CRITICAL] / [HIGH] / [MEDIUM] / [LOW] issue descriptions
- End with: VISUAL_RESULT: PASS or VISUAL_RESULT: FAIL

Score >= 85 with no CRITICAL = PASS.
"""


@dataclass(frozen=True)
class UITestResult:
    passed: bool
    score: int
    findings: tuple[ReviewFinding, ...]
    screenshot_path: str
    raw_output: str


class VisualVerifier:
    """Submit screenshot to an Anthropic vision model for visual QA."""

    @staticmethod
    async def verify(
        screenshot_path: str,
        definition_of_done: str,
        subtask_id: str,
        model: str = "claude-opus-4-6",
    ) -> UITestResult:
        import base64
        import re
        from pathlib import Path
        from agents import Agent, Runner

        image_data = base64.standard_b64encode(Path(screenshot_path).read_bytes()).decode()

        agent = Agent(
            name=f"{subtask_id}-visual-verifier",
            instructions=VISUAL_VERIFIER_SYSTEM_PROMPT,
            model=model,
            tools=[],
        )

        # Build multimodal input — image + text
        input_payload = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_data,
                },
            },
            {
                "type": "text",
                "text": f"## Definition of Done\n{definition_of_done}\n\nDoes the screenshot meet these criteria?",
            },
        ]

        try:
            result = await Runner.run(starting_agent=agent, input=input_payload, max_turns=3)
            raw = str(result.final_output or "")
        except Exception as e:
            raw = f"VISUAL_RESULT: FAIL\n[HIGH] Visual verifier failed: {e}"

        # Parse score
        score = 0
        m = re.search(r"\b(\d{1,3})\s*/\s*100\b", raw)
        if m:
            score = max(0, min(100, int(m.group(1))))

        # Check sentinel
        passed = bool(re.search(r"VISUAL_RESULT\s*:\s*PASS", raw, re.IGNORECASE))
        if re.search(r"VISUAL_RESULT\s*:\s*FAIL", raw, re.IGNORECASE):
            passed = False

        # Extract findings
        findings: list[ReviewFinding] = []
        for severity in ("critical", "high", "medium", "low"):
            for i, m2 in enumerate(re.finditer(rf"\[{severity.upper()}\](.+?)(?=\[|$)", raw, re.DOTALL | re.IGNORECASE)):
                findings.append(ReviewFinding(
                    finding_id=f"{subtask_id}-visual-{severity}-{i}",
                    category="ui_test",
                    severity=severity,
                    message=m2.group(1).strip()[:500],
                    source_guardrail="VisualVerifier",
                ))

        return UITestResult(
            passed=passed,
            score=score,
            findings=tuple(findings),
            screenshot_path=screenshot_path,
            raw_output=raw,
        )
```

#### 2b.5 Create `packages/agent_sdk/ui_testing/ui_test_orchestrator.py`

```python
"""End-to-end UI test: detect server → start → screenshot → verify → stop."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from packages.agent_sdk.ui_testing.server_detector import ServerDetector
from packages.agent_sdk.ui_testing.server_manager import ServerManager
from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
from packages.agent_sdk.ui_testing.visual_verifier import VisualVerifier, UITestResult
from packages.shared.domain.models import ReviewFinding

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask


class UITestOrchestrator:
    """
    Orchestrates the full UI test flow for a frontend subtask.
    Data flow:
      ServerDetector → ServerManager → ScreenshotCapture → VisualVerifier
    Always stops the server in a finally block.
    """

    def __init__(self, event_bus: Any = None, verifier_model: str = "claude-opus-4-6"):
        self._event_bus = event_bus
        self._verifier_model = verifier_model

    def _publish(self, event_type: str, payload: dict) -> None:
        if self._event_bus:
            self._event_bus.publish(event_type, payload)

    async def run(self, subtask: Subtask, workspace_path: str) -> UITestResult:
        # 1. Detect server config
        config = ServerDetector.detect(workspace_path)
        if config is None:
            return UITestResult(
                passed=False, score=0,
                findings=(ReviewFinding(
                    finding_id=f"{subtask.id}-ui-no-server",
                    category="ui_test", severity="high",
                    message="No dev server detected in workspace. Add package.json, manage.py, or equivalent.",
                    source_guardrail="UITestOrchestrator",
                ),),
                screenshot_path="",
                raw_output="Server detection failed.",
            )

        self._publish("ui_test.server_detected", {
            "subtask_id": subtask.id,
            "framework": config.framework,
            "port": config.port,
            "cmd": config.start_cmd,
        })

        server_proc = None
        try:
            # 2. Start server and wait for readiness
            server_proc = await ServerManager.start_and_wait(config, workspace_path)
            self._publish("ui_test.server_ready", {"subtask_id": subtask.id, "url": server_proc.url})

            # 3. Capture screenshot
            screenshot_path = await ScreenshotCapture.capture(server_proc.url)
            self._publish("ui_test.screenshot_captured", {
                "subtask_id": subtask.id, "path": screenshot_path,
            })

            # 4. Visual verification
            definition_of_done = "\n".join(subtask.definition_of_done) if subtask.definition_of_done else ""
            result = await VisualVerifier.verify(
                screenshot_path=screenshot_path,
                definition_of_done=definition_of_done,
                subtask_id=subtask.id,
                model=self._verifier_model,
            )

            self._publish("ui_test.completed", {
                "subtask_id": subtask.id,
                "passed": result.passed,
                "score": result.score,
            })
            return result

        except TimeoutError as e:
            return UITestResult(
                passed=False, score=0,
                findings=(ReviewFinding(
                    finding_id=f"{subtask.id}-ui-timeout",
                    category="ui_test", severity="critical",
                    message=str(e),
                    source_guardrail="UITestOrchestrator",
                ),),
                screenshot_path="",
                raw_output=str(e),
            )
        finally:
            if server_proc:
                ServerManager.stop(server_proc)
                self._publish("ui_test.server_stopped", {"subtask_id": subtask.id})
```

#### 2b.6 Create `packages/agent_sdk/ui_testing/tools/ui_tools.py`

```python
"""FunctionTools for UI testing — exposed to agents via ToolRegistry."""

from agents import function_tool
from packages.agent_sdk.tools.builtin.command_tools import run_command_impl


@function_tool
async def capture_screenshot(url: str, output_path: str = "/tmp/screenshot.png") -> str:
    """Capture a screenshot of the given URL. Returns the path to the saved PNG."""
    from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
    try:
        path = await ScreenshotCapture.capture(url, output_path)
        return f"Screenshot saved to: {path}"
    except Exception as e:
        return f"Screenshot failed: {e}"


@function_tool
def detect_dev_server(workspace: str = ".") -> str:
    """Detect the dev server start command and port for the workspace."""
    from packages.agent_sdk.ui_testing.server_detector import ServerDetector
    config = ServerDetector.detect(workspace)
    if config is None:
        return "No dev server detected."
    return f"Framework: {config.framework}, Port: {config.port}, Command: {config.start_cmd}"
```

#### 2b.7 Create `packages/agent_sdk/ui_testing/__init__.py`

```python
from packages.agent_sdk.ui_testing.ui_test_orchestrator import UITestOrchestrator
from packages.agent_sdk.ui_testing.visual_verifier import UITestResult, VisualVerifier
from packages.agent_sdk.ui_testing.server_detector import ServerDetector, ServerConfig
from packages.agent_sdk.ui_testing.screenshot_capture import ScreenshotCapture
```

### Verification

```bash
python -c "from packages.agent_sdk.ui_testing import UITestOrchestrator; print('import ok')"
pytest tests/agent_sdk/test_ui_test_orchestrator.py -v
# Smoke test server detector:
python -c "
from packages.agent_sdk.ui_testing.server_detector import ServerDetector
import tempfile, os, json
ws = tempfile.mkdtemp()
pkg = {'scripts': {'dev': 'vite'}, 'dependencies': {'vite': '^4'}}
open(os.path.join(ws, 'package.json'), 'w').write(json.dumps(pkg))
open(os.path.join(ws, 'vite.config.ts'), 'w').write('export default {server:{port:5173}}')
cfg = ServerDetector.detect(ws)
print(cfg)
"
```

### Exit Criteria

- [ ] `UITestOrchestrator.run()` returns `UITestResult` with `passed=False` when no server detected
- [ ] `ServerDetector.detect()` identifies framework + port from `package.json` + `vite.config.ts`
- [ ] `ScreenshotCapture` gracefully returns `None` per strategy when binary unavailable (mocked)
- [ ] `VisualVerifier.verify()` parses score + sentinel from mocked LLM output
- [ ] `UITestOrchestrator.run()` always calls `ServerManager.stop()` in finally block (no leaked procs)
- [ ] All new tests pass; existing 812 tests still pass

### Rollback

Delete `packages/agent_sdk/ui_testing/` — no existing files modified.

---

## Step 3: Integration & Wiring

**Branch**: `feat/agent-sdk-integration`  
**Depends on**: Steps 2a and 2b (both must be merged)  
**Model tier**: Default (Sonnet)  
**Parallel**: No — touches shared files

### Context Brief

This step wires the three new modules into the existing execution path. It modifies:
- `packages/agent_sdk/runner/executor.py` — add `execute_with_review()` and post-run `_evolve_knowledge()` hook
- `packages/agent_sdk/models/router.py` — add `"ui_verification"` route
- `packages/agent_sdk/tools/registry.py` — add `"ui_verification"` tool set
- `packages/agent_sdk/__init__.py` — re-export new public types

### Tasks

#### 3.1 Update `packages/agent_sdk/runner/executor.py`

Add to `AgentExecutor`:

```python
# New imports (add at top)
from packages.agent_sdk.review.adversarial_orchestrator import (
    AdversarialReviewOrchestrator, AdversarialReviewConfig,
    AdversarialRoundResult,
)
from packages.agent_sdk.knowledge.knowledge_evolver import KnowledgeEvolver
from packages.agent_sdk.ui_testing.ui_test_orchestrator import UITestOrchestrator
from packages.agent_sdk.ui_testing.visual_verifier import UITestResult

# Add these methods to AgentExecutor class:

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
    On success, optionally trigger background knowledge evolution.
    For ui_verification task type, delegates to UITestOrchestrator.
    """
    task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)

    # UI verification takes a separate path
    if task_type_value == "ui_verification":
        return await self._execute_ui_verification(subtask, context_pack, work_item_id, workspace_path)

    orchestrator = AdversarialReviewOrchestrator(
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

    if evolve_knowledge and result.agent_run.status == AgentRunStatus.COMPLETED:
        # Pass the final round's implementation output — not the run_id
        last_impl_output = round_results[-1].implementation_output if round_results else ""
        asyncio.ensure_future(
            self._evolve_knowledge(result, last_impl_output, subtask, work_item_id, workspace_path)
        )

    return result

async def _evolve_knowledge(
    self,
    result: AgentRunResult,
    implementation_output: str,
    subtask: Subtask,
    work_item_id: str,
    workspace_path: str,
) -> None:
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
    return AgentRunResult(
        agent_run=agent_run,
        review_findings=list(ui_result.findings),
    )
```

#### 3.2 Update `packages/agent_sdk/models/router.py`

```python
# Add to TASK_ROUTE_TABLE:
"ui_verification": ("anthropic", "claude-opus-4-6"),   # Vision required
"adversarial_review": ("anthropic", "claude-opus-4-6"), # Deep reasoning reviewer
```

#### 3.3 Update `packages/agent_sdk/tools/registry.py`

```python
# Add import at top:
from packages.agent_sdk.ui_testing.tools.ui_tools import capture_screenshot, detect_dev_server

# Add to _TASK_TOOLS:
"ui_verification": [capture_screenshot, detect_dev_server],
```

#### 3.4 Add new event types to `packages/agent_sdk/tracing/event_bridge.py`

```python
# Add to _EVENT_MAP:
"adversarial_review.round_completed": "agent_run.review_round",
"adversarial_review.passed": "agent_run.review_passed",
"adversarial_review.exhausted": "agent_run.review_exhausted",
"knowledge.evolved": "agent_run.knowledge_evolved",
"ui_test.completed": "agent_run.ui_test_completed",
```

### Verification

```bash
# Full import check
python -c "
from packages.agent_sdk.runner.executor import AgentExecutor
from packages.agent_sdk.models.router import ModelRouter
print(ModelRouter.resolve('ui_verification'))     # → ('anthropic', 'claude-opus-4-6')
print(ModelRouter.resolve('adversarial_review'))  # → ('anthropic', 'claude-opus-4-6')
from packages.agent_sdk.tools.registry import ToolRegistry
print([t.__name__ for t in ToolRegistry.resolve('ui_verification')])
"
# Full regression
pytest -q
```

### Exit Criteria

- [ ] `ModelRouter.resolve('ui_verification')` returns `('anthropic', 'claude-opus-4-6')`
- [ ] `AgentExecutor.execute_with_review()` method exists and calls `AdversarialReviewOrchestrator`
- [ ] `AgentExecutor._execute_ui_verification()` delegates to `UITestOrchestrator`
- [ ] New event types are mapped in `AgentTraceBridge`
- [ ] All 812 + new tests pass

### Rollback

Revert the 4 changed files via `git checkout HEAD packages/agent_sdk/runner/executor.py packages/agent_sdk/models/router.py packages/agent_sdk/tools/registry.py packages/agent_sdk/tracing/event_bridge.py`

---

## Step 4: Full Test Suite

**Branch**: `feat/agent-sdk-tests`  
**Depends on**: Step 3  
**Model tier**: Default  
**Parallel**: No

### Context Brief

Add comprehensive tests for all new modules. Target: 80%+ coverage on new code. The existing test suite is in `tests/` and uses pytest + mock. Follow patterns from existing tests.

### Tasks

#### 4.1 `tests/agent_sdk/test_adversarial_orchestrator.py`

Key test cases:
- `test_review_scorer_parses_numeric_score()` — all 5 regex patterns
- `test_review_scorer_sentinel_pass()` — ADVERSARIAL_RESULT: PASS in tail
- `test_review_scorer_sentinel_fail()` — ADVERSARIAL_RESULT: FAIL in tail
- `test_review_scorer_critical_blocks_pass()` — score=90 but [CRITICAL] → passed=False
- `test_orchestrator_passes_on_first_round()` — mock Runner.run to return passing score
- `test_orchestrator_retries_on_fail_then_passes()` — fail round 0, pass round 1
- `test_orchestrator_exhausts_rounds()` — all rounds fail → FAILED status
- `test_reviewer_rotation_cycles()` — verify round 0/1/2/3 use correct models
- `test_prior_review_injected_into_prompt()` — verify prompt contains prior review on round > 0

#### 4.2 `tests/agent_sdk/test_knowledge_evolver.py`

Key test cases:
- `test_extractor_parses_valid_json()` — mock Runner returns clean JSON
- `test_extractor_handles_markdown_fenced_json()` — strips ```json fence
- `test_extractor_returns_empty_on_parse_error()` — malformed JSON → empty knowledge
- `test_writer_appends_to_new_file()` — creates CLAUDE.md with section header
- `test_writer_deduplicates_by_hash()` — same entry written twice → appears once
- `test_writer_rotates_on_size_exceeded()` — oversized file → archived + new file
- `test_evolver_skips_failed_runs()` — FAILED status → no write
- `test_evolver_swallows_exceptions()` — extractor throws → evolve returns False gracefully
- `test_evolver_publishes_event_on_success()` — event_bus receives knowledge.evolved

#### 4.3 `tests/agent_sdk/test_ui_test_orchestrator.py`

Key test cases:
- `test_server_detector_node_project()` — workspace with package.json → NodeConfig
- `test_server_detector_django_project()` — workspace with manage.py → DjangoConfig
- `test_server_detector_returns_none_for_empty()` — no known files → None
- `test_server_detector_reads_port_from_env_file()` — .env with PORT=4000
- `test_screenshot_capture_uses_playwright()` — mock playwright → returns path
- `test_screenshot_capture_falls_back_on_playwright_import_error()` — no playwright → tries next
- `test_visual_verifier_parses_pass()` — VISUAL_RESULT: PASS → passed=True
- `test_visual_verifier_parses_fail_with_findings()` — [CRITICAL] → passed=False
- `test_orchestrator_no_server_detected()` — returns UITestResult.passed=False
- `test_orchestrator_stops_server_on_exception()` — server.stop() called even if capture throws
- `test_orchestrator_publishes_events()` — event_bus receives ui_test.completed

#### 4.4 `tests/agent_sdk/test_executor_integration.py`

Key test cases:
- `test_execute_with_review_delegates_to_orchestrator()` — verify orchestrator called
- `test_execute_with_review_ui_task_delegates_to_ui_orchestrator()` — ui_verification path
- `test_execute_with_review_triggers_knowledge_evolution()` — evolve_knowledge=True
- `test_execute_with_review_skips_evolution_on_fail()` — FAILED → no evolve

### Verification

```bash
pytest tests/agent_sdk/ -v --cov=packages/agent_sdk --cov-report=term-missing
# Target: coverage >= 80% on new files
pytest -q  # full regression — all 812+ must still pass
```

### Exit Criteria

- [ ] All test cases in 4.1–4.4 pass
- [ ] New code coverage ≥ 80%
- [ ] Total test count ≥ 812 + new tests
- [ ] `pytest -q` exits 0

### Rollback

Delete new test files — no source files modified.

---

---

## Critical Fixes (incorporated from adversarial review)

### Fix C1 — Replace `asyncio.ensure_future` with a bounded task registry

`asyncio.ensure_future()` in `KnowledgeEvolver` is unsafe: the task can be GC'd, silently drop learnings, or raise `RuntimeError: no running event loop` on shutdown.

**Replacement in `AgentExecutor`:**

```python
# Add to AgentExecutor.__init__:
self._background_tasks: set[asyncio.Task] = set()

# Replace asyncio.ensure_future() in execute_with_review():
task = asyncio.create_task(
    self._evolve_knowledge(result, last_impl_output, subtask, work_item_id, workspace_path)
)
self._background_tasks.add(task)
task.add_done_callback(self._background_tasks.discard)
task.add_done_callback(lambda t: _log_task_exception(t))

# Add to AgentExecutor:
async def drain_background_tasks(self) -> None:
    """Await all pending background tasks. Call before shutdown."""
    if self._background_tasks:
        await asyncio.gather(*self._background_tasks, return_exceptions=True)

def _log_task_exception(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        import logging
        logging.getLogger(__name__).warning("Background knowledge task failed: %s", task.exception())
```

### Fix C2 — Replace `fcntl.flock` with `asyncio.Lock` + atomic write

`fcntl.flock` is POSIX-only, blocks the event loop, and doesn't serialize async coroutines sharing the same fd.

**Replacement in `ClaudeMDWriter`:**

```python
import asyncio
import os
import tempfile
from pathlib import Path

_FILE_LOCKS: dict[str, asyncio.Lock] = {}

def _get_lock(path: str) -> asyncio.Lock:
    if path not in _FILE_LOCKS:
        _FILE_LOCKS[path] = asyncio.Lock()
    return _FILE_LOCKS[path]

# ClaudeMDWriter.write() becomes async:
@staticmethod
async def write(workspace_path: str, knowledge: ExtractedKnowledge, ...) -> bool:
    claudemd_path = str(Path(workspace_path) / "CLAUDE.md")
    async with _get_lock(claudemd_path):
        # Read existing content
        existing = await asyncio.to_thread(_read_file, claudemd_path)
        if entry_hash in existing:
            return False
        if len(existing.encode()) > MAX_CLAUDEMD_BYTES:
            await asyncio.to_thread(_rotate, Path(claudemd_path), existing)
            existing = ""
        new_content = _build_new_content(existing, entry, entry_hash)
        # Atomic write: write to tmp then os.replace
        await asyncio.to_thread(_atomic_write, claudemd_path, new_content)
        return True

def _atomic_write(path: str, content: str) -> None:
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        os.unlink(tmp_path)
        raise
```

`KnowledgeEvolver.evolve()` and `ClaudeMDWriter.write()` are now `async`.

### Fix C3 — Screenshot size guard + SDK vision contract

Inline base64 of a 1440×900 PNG is ~1–3MB and can exhaust token budgets. Add a downscale + size cap before sending.

**Add to `ScreenshotCapture`:**

```python
MAX_IMAGE_BYTES = 256 * 1024  # 256KB after compression

@staticmethod
async def capture_and_compress(url: str, output_path: str | None = None) -> str:
    """Capture screenshot and resize if larger than MAX_IMAGE_BYTES."""
    path = await ScreenshotCapture.capture(url, output_path)
    size = Path(path).stat().st_size
    if size > MAX_IMAGE_BYTES:
        await asyncio.to_thread(ScreenshotCapture._downscale, path, MAX_IMAGE_BYTES)
    return path

@staticmethod
def _downscale(path: str, max_bytes: int) -> None:
    try:
        from PIL import Image
        with Image.open(path) as img:
            scale = (max_bytes / Path(path).stat().st_size) ** 0.5
            new_size = (int(img.width * scale), int(img.height * scale))
            img.resize(new_size, Image.LANCZOS).save(path, optimize=True)
    except ImportError:
        pass  # PIL not available — send as-is; provider will 413 if too large
```

`VisualVerifier.verify()` uses `capture_and_compress()` instead of `capture()`.

The Agents SDK vision input format (Anthropic provider):
```python
{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<base64>"}}
```
This is the correct Anthropic content block format. Verify against the installed SDK version before execution.

### Fix C4 — Explicit process lifecycle in `UITestOrchestrator` and `ScreenshotCapture`

`ScreenshotCapture._capture_playwright` already uses `async with async_playwright()` — the Playwright context handles cleanup. For subprocess-based strategies, `_run_headless_binary` must add:

```python
@staticmethod
async def _run_headless_binary(binary: str, url: str, output_path: str) -> str | None:
    proc = await asyncio.create_subprocess_exec(...)
    try:
        await asyncio.wait_for(proc.wait(), timeout=20)
    except asyncio.TimeoutError:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=5)
        return None
    return output_path if Path(output_path).exists() else None
```

`UITestOrchestrator.run()` already uses `try/finally → ServerManager.stop()`. `ServerManager.stop()` must add:

```python
@staticmethod
def stop(server_proc: ServerProcess) -> None:
    try:
        server_proc.proc.terminate()
        server_proc.proc.wait(timeout=10)  # increased from 5
    except subprocess.TimeoutExpired:
        server_proc.proc.kill()
        server_proc.proc.wait(timeout=2)
    except Exception:
        pass
```

### Fix C5 — Orchestrator must compose `AgentExecutor._run_agent_once()`, not bypass it

Calling `Runner.run()` directly in `AdversarialReviewOrchestrator` bypasses the semaphore, guardrails, retry/escalation, and token collection already in `AgentExecutor`.

**Refactor: extract `_run_agent_once` from `AgentExecutor`:**

```python
# New private helper in AgentExecutor (replaces the try block in execute()):
async def _run_agent_once(
    self,
    agent: Agent,
    prompt: str,
    run_context: AgentRunContext,
    model: str,
    work_item_id: str,
    subtask_id: str,
) -> tuple[str, dict[str, Any]]:
    """Single guarded runner invocation — respects semaphore + token collection."""
    async with self._semaphore:
        start = time.monotonic()
        result = await Runner.run(
            starting_agent=agent,
            input=prompt,
            context=run_context,
            max_turns=MAX_TURNS,
        )
        duration = time.monotonic() - start
        usage = TokenUsageCollector.extract(result, model=model, duration=duration)
        output_text = str(result.final_output) if result.final_output else ""
        return output_text, usage
```

`AdversarialReviewOrchestrator.__init__` takes `executor: AgentExecutor` and calls `executor._run_agent_once()` instead of `Runner.run()` directly. The reviewer skips the semaphore (it is a lightweight LLM call, not a workspace-modifying task) — use a separate lightweight semaphore `asyncio.Semaphore(16)` for reviewer calls.

### Fix H6 — Convergence guard: stall detection

Add to `AdversarialReviewConfig`:
```python
stall_rounds: int = 2  # Abort if score doesn't improve after N rounds
```

In the review loop:
```python
if review_round > 0:
    prev_score = round_results[-2].review_score.score if len(round_results) >= 2 else 0
    if review_score.score <= prev_score:
        stall_count += 1
        if stall_count >= config.stall_rounds:
            self._publish("adversarial_review.stalled", {...})
            break
    else:
        stall_count = 0
```

### Fix H7 — Enforce reviewer ≠ implementer

Add to `_run_reviewer()`:
```python
# Ensure reviewer is from a different provider than implementer
impl_provider, _ = ModelRouter.resolve(task_type_value)
eligible_reviewers = [
    (p, m) for (p, m) in self._config.reviewer_rotation
    if p != impl_provider or len(self._config.reviewer_rotation) == 1
]
reviewer_provider, reviewer_model = eligible_reviewers[review_round % len(eligible_reviewers)]
```

### Fix H8 — Guard CLAUDE.md writes against injection

In `KnowledgeEvolver.evolve()`, before writing:
```python
from packages.agent_sdk.guardrails.input_guards import PromptInjectionGuard

for field_values in [knowledge.patterns, knowledge.gotchas, knowledge.decisions]:
    for entry in field_values:
        if PromptInjectionGuard.check(entry).tripwire_triggered:
            logging.getLogger(__name__).warning(
                "Knowledge entry blocked by PromptInjectionGuard: %.100s", entry
            )
            return False  # Reject entire batch on any hit
```

### Fix H9 — Split Step 3 into Step 3a + Step 3b

Step 3 was too large. It is now split:
- **Step 3a**: Extract `_run_agent_once` from `AgentExecutor`, add `drain_background_tasks`
- **Step 3b**: Wire `execute_with_review`, `_execute_ui_verification`, route table, tools registry

---

## Step Dependency Summary (revised)

```
Step 1: feat/adversarial-review          [serial - foundation]
    ↓
Step 2a: feat/knowledge-evolver          [parallel ─┐
Step 2b: feat/ui-testing                 [parallel ─┤ no shared files
                                                     ↓
Step 3a: feat/executor-refactor          [serial - extract _run_agent_once]
    ↓
Step 3b: feat/agent-sdk-integration      [serial - wire everything]
    ↓
Step 4:  feat/agent-sdk-tests            [serial - full coverage]
```

**Steps 2a and 2b can be executed by parallel agents** — they touch completely disjoint file trees.

---

## Invariants (checked after every step)

1. `pytest -q` exits 0 — no regressions
2. `python -c "from packages.agent_sdk import *"` — no import errors
3. No modification to `packages/shared/domain/models.py` — domain models are immutable
4. No hardcoded API keys or secrets in any new file
5. All new functions have type annotations
6. No function > 50 lines (excluding docstrings + blank lines)

---

## New Event Types Published

| Event | Published by | Payload fields |
|-------|-------------|----------------|
| `adversarial_review.round_completed` | `AdversarialReviewOrchestrator` | subtask_id, round, score, passed, reviewer_model |
| `adversarial_review.passed` | `AdversarialReviewOrchestrator` | subtask_id, final_score, rounds_taken |
| `adversarial_review.exhausted` | `AdversarialReviewOrchestrator` | subtask_id, rounds |
| `adversarial_review.impl_failed` | `AdversarialReviewOrchestrator` | subtask_id, round, error |
| `knowledge.evolved` | `KnowledgeEvolver` | work_item_id, subtask_id, patterns, gotchas, decisions |
| `ui_test.server_detected` | `UITestOrchestrator` | subtask_id, framework, port, cmd |
| `ui_test.server_ready` | `UITestOrchestrator` | subtask_id, url |
| `ui_test.screenshot_captured` | `UITestOrchestrator` | subtask_id, path |
| `ui_test.completed` | `UITestOrchestrator` | subtask_id, passed, score |
| `ui_test.server_stopped` | `UITestOrchestrator` | subtask_id |

---

## Plan Mutation Protocol

To split a step: create `step-N-a` and `step-N-b` entries, add dependency edge, note reason here.  
To skip a step: mark `SKIPPED: <reason>` and verify downstream steps still have valid dependencies.  
To reorder: re-draw dependency graph above; verify invariants hold at each step boundary.  
All mutations must be logged in this section with date and author.
