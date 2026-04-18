# OpenAI Agents SDK Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate OpenAI Agents Python SDK into AI-DevOps as the agent execution engine, replacing shell script + tmux with in-process async SDK calls, adding MCP tools, guardrails, and tracing.

**Architecture:** SDK-Embedded (Approach B — Deep Fusion). Agents SDK `Runner.run()` replaces subprocess spawning inside the existing orchestrator loop. DAG planner, GlobalScheduler, QualityGate, Release, and Incident layers remain unchanged. New `packages/agent_sdk/` module encapsulates all SDK integration code.

**Tech Stack:** Python 3.11+, openai-agents SDK, LiteLLM (Anthropic adapter), MCP Python SDK, asyncio, pytest

**Spec:** `docs/superpowers/specs/2026-04-18-agents-sdk-integration-design.md`

---

## Chunk 1: Foundation — Dependencies, Domain Extensions, Package Scaffold

### Task 1: Install Dependencies and Verify SDK Import

**Files:**
- Modify: `pyproject.toml:11-14`
- Modify: `requirements.txt`

- [ ] **Step 1: Add SDK dependencies to pyproject.toml**

```toml
# pyproject.toml — replace dependencies list (lines 11-14)
dependencies = [
    "requests>=2.31",
    "schedule>=1.2",
    "openai-agents>=0.14",
    "litellm>=1.40",
    "mcp>=1.19",
]
```

- [ ] **Step 2: Update requirements.txt to match**

```
requests>=2.31
schedule>=1.2
openai-agents>=0.14
litellm>=1.40
mcp>=1.19
```

- [ ] **Step 3: Install and verify imports**

Run:
```bash
pip install -e ".[dev]" 2>&1 | tail -5
python -c "from agents import Agent, Runner; print('SDK OK')"
python -c "import litellm; print('LiteLLM OK')"
python -c "import mcp; print('MCP OK')"
```
Expected: All three print OK. If `from agents import` fails due to namespace collision, install with `pip install openai-agents` explicitly and retry.

- [ ] **Step 4: Run existing tests to confirm no breakage**

Run: `pytest -q 2>&1 | tail -5`
Expected: All existing tests pass, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "chore: add openai-agents, litellm, mcp dependencies"
```

---

### Task 2: Add TaskType Enum and task_type Field to Subtask

**Files:**
- Modify: `orchestrator/bin/plan_schema.py:1-5,90-102`
- Test: `tests/test_plan_schema.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan_schema.py`:

```python
def test_subtask_has_task_type_field():
    """Subtask should have a task_type field with default CODE_GENERATION."""
    from orchestrator.bin.plan_schema import Subtask, TaskType

    subtask = Subtask(
        id="s1",
        title="Test",
        description="Test subtask",
        agent="codex",
        model="gpt-5.4",
        effort="medium",
        worktree_strategy="shared",
    )
    assert subtask.task_type == TaskType.CODE_GENERATION


def test_task_type_enum_values():
    """TaskType enum should have all expected values."""
    from orchestrator.bin.plan_schema import TaskType

    expected = {
        "code_generation", "code_review", "bug_fix", "refactor",
        "documentation", "test_generation", "planning", "incident_analysis",
    }
    actual = {t.value for t in TaskType}
    assert actual == expected


def test_subtask_with_explicit_task_type():
    """Subtask should accept explicit task_type."""
    from orchestrator.bin.plan_schema import Subtask, TaskType

    subtask = Subtask(
        id="s1", title="Review", description="Code review",
        agent="claude", model="claude-opus-4-6", effort="low",
        worktree_strategy="shared", task_type=TaskType.CODE_REVIEW,
    )
    assert subtask.task_type == TaskType.CODE_REVIEW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_schema.py::test_subtask_has_task_type_field -v`
Expected: FAIL — `ImportError: cannot import name 'TaskType'`

- [ ] **Step 3: Implement TaskType enum and add field to Subtask**

In `orchestrator/bin/plan_schema.py`, add the import and enum before the `Subtask` class (after existing imports near line 5):

```python
from enum import Enum

class TaskType(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"
    TEST_GENERATION = "test_generation"
    PLANNING = "planning"
    INCIDENT_ANALYSIS = "incident_analysis"
```

Add field to `Subtask` dataclass (after `definition_of_done` field, line 102):

```python
    task_type: TaskType = TaskType.CODE_GENERATION
```

- [ ] **Step 4: Run all plan_schema tests to verify they pass**

Run: `pytest tests/test_plan_schema.py -v`
Expected: All tests PASS including the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/plan_schema.py tests/test_plan_schema.py
git commit -m "feat: add TaskType enum and task_type field to Subtask"
```

---

### Task 3: Add ReviewFinding Domain Object

**Files:**
- Modify: `packages/shared/domain/models.py:1-10,214`
- Test: `tests/test_domain_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_domain_models.py`:

```python
def test_review_finding_creation():
    """ReviewFinding should be a frozen dataclass with required fields."""
    from packages.shared.domain.models import ReviewFinding

    finding = ReviewFinding(
        finding_id="rf-001",
        category="security",
        severity="high",
        message="Detected hardcoded API key",
        source_guardrail="SecretLeakGuard",
    )
    assert finding.finding_id == "rf-001"
    assert finding.category == "security"
    assert finding.severity == "high"
    assert finding.message == "Detected hardcoded API key"
    assert finding.source_guardrail == "SecretLeakGuard"
    assert finding.metadata == {}


def test_review_finding_is_frozen():
    """ReviewFinding should be immutable."""
    from packages.shared.domain.models import ReviewFinding
    import pytest

    finding = ReviewFinding(
        finding_id="rf-001", category="security", severity="high",
        message="test", source_guardrail="TestGuard",
    )
    with pytest.raises(AttributeError):
        finding.severity = "low"


def test_review_finding_with_metadata():
    """ReviewFinding should accept optional metadata."""
    from packages.shared.domain.models import ReviewFinding

    finding = ReviewFinding(
        finding_id="rf-002", category="safety", severity="medium",
        message="eval() detected", source_guardrail="CodeSafetyGuard",
        metadata={"line": 42, "file": "main.py"},
    )
    assert finding.metadata == {"line": 42, "file": "main.py"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_domain_models.py::test_review_finding_creation -v`
Expected: FAIL — `ImportError: cannot import name 'ReviewFinding'`

- [ ] **Step 3: Add ReviewFinding dataclass to models.py**

After the `AgentRun` dataclass (after line 214 in `packages/shared/domain/models.py`):

```python
@dataclass(slots=True, frozen=True)
class ReviewFinding:
    """A finding from a guardrail or code review check."""
    finding_id: str
    category: str
    severity: str
    message: str
    source_guardrail: str
    metadata: dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_domain_models.py -v -k review_finding`
Expected: All 3 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/shared/domain/models.py tests/test_domain_models.py
git commit -m "feat: add ReviewFinding frozen dataclass to domain models"
```

---

### Task 4: Create agent_sdk Package Scaffold

**Files:**
- Create: `packages/agent_sdk/__init__.py`
- Create: `packages/agent_sdk/models/__init__.py`
- Create: `packages/agent_sdk/runner/__init__.py`
- Create: `packages/agent_sdk/tools/__init__.py`
- Create: `packages/agent_sdk/tools/builtin/__init__.py`
- Create: `packages/agent_sdk/tools/mcp_servers/__init__.py`
- Create: `packages/agent_sdk/guardrails/__init__.py`
- Create: `packages/agent_sdk/tracing/__init__.py`

- [ ] **Step 1: Create directory structure and init files**

Run:
```bash
mkdir -p packages/agent_sdk/models
mkdir -p packages/agent_sdk/runner
mkdir -p packages/agent_sdk/tools/builtin
mkdir -p packages/agent_sdk/tools/mcp_servers
mkdir -p packages/agent_sdk/guardrails
mkdir -p packages/agent_sdk/tracing
```

- [ ] **Step 2: Write __init__.py for top-level package**

Create `packages/agent_sdk/__init__.py`:

```python
"""OpenAI Agents SDK integration for AI-DevOps."""
```

- [ ] **Step 3: Write empty __init__.py for all sub-packages**

Create these files, each with an empty docstring:
- `packages/agent_sdk/models/__init__.py`
- `packages/agent_sdk/runner/__init__.py`
- `packages/agent_sdk/tools/__init__.py`
- `packages/agent_sdk/tools/builtin/__init__.py`
- `packages/agent_sdk/tools/mcp_servers/__init__.py`
- `packages/agent_sdk/guardrails/__init__.py`
- `packages/agent_sdk/tracing/__init__.py`

- [ ] **Step 4: Verify the package is importable**

Run: `python -c "import packages.agent_sdk; print('agent_sdk package OK')"`
Expected: Prints `agent_sdk package OK`

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/
git commit -m "chore: scaffold packages/agent_sdk/ directory structure"
```

---

## Chunk 2: Phase 1 Core — Model Router, Context Bridge, Agent Factory

### Task 5: Implement Model Router with Task-Type Routing Table

**Files:**
- Create: `packages/agent_sdk/models/router.py`
- Test: `tests/test_agent_sdk_model_router.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_model_router.py`:

```python
import pytest


def test_router_resolves_code_generation_to_openai():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("code_generation")
    assert provider == "openai"
    assert model == "gpt-5.4"


def test_router_resolves_code_review_to_anthropic():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("code_review")
    assert provider == "anthropic"
    assert model == "claude-opus-4-6"


def test_router_resolves_documentation_to_anthropic_sonnet():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("documentation")
    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"


def test_router_unknown_type_falls_back_to_default():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("unknown_type")
    assert provider == "openai"
    assert model == "gpt-5.4"


def test_router_escalate_returns_stronger_model():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.escalate("openai", "gpt-5.4-mini")
    assert provider == "openai"
    assert model == "gpt-5.4"


def test_router_escalate_already_strongest_returns_same():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.escalate("openai", "gpt-5.4")
    assert provider == "openai"
    assert model == "gpt-5.4"


def test_router_all_task_types_have_routes():
    from packages.agent_sdk.models.router import ModelRouter, TASK_ROUTE_TABLE
    from orchestrator.bin.plan_schema import TaskType

    for task_type in TaskType:
        assert task_type.value in TASK_ROUTE_TABLE, f"Missing route for {task_type.value}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_model_router.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ModelRouter**

Create `packages/agent_sdk/models/router.py`:

```python
"""Task-type based model routing for dual LLM providers."""

from __future__ import annotations

import os

TASK_ROUTE_TABLE: dict[str, tuple[str, str]] = {
    "code_generation":   ("openai",    "gpt-5.4"),
    "code_review":       ("anthropic", "claude-opus-4-6"),
    "bug_fix":           ("openai",    "gpt-5.4"),
    "refactor":          ("openai",    "gpt-5.4"),
    "documentation":     ("anthropic", "claude-sonnet-4-6"),
    "test_generation":   ("openai",    "gpt-5.4-mini"),
    "planning":          ("anthropic", "claude-opus-4-6"),
    "incident_analysis": ("anthropic", "claude-opus-4-6"),
}

DEFAULT_ROUTE: tuple[str, str] = ("openai", "gpt-5.4")

_ESCALATION: dict[str, list[str]] = {
    "openai": ["gpt-5.4-mini", "gpt-5.4"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6"],
}


class ModelRouter:
    """Resolves task_type to (provider, model) and supports model escalation."""

    @staticmethod
    def resolve(task_type: str) -> tuple[str, str]:
        override_key = f"ROUTE_{task_type.upper()}"
        override = os.environ.get(override_key)
        if override and ":" in override:
            provider, model = override.split(":", 1)
            return provider, model
        return TASK_ROUTE_TABLE.get(task_type, DEFAULT_ROUTE)

    @staticmethod
    def escalate(provider: str, current_model: str) -> tuple[str, str]:
        ladder = _ESCALATION.get(provider, [])
        if current_model not in ladder:
            return provider, current_model
        idx = ladder.index(current_model)
        if idx < len(ladder) - 1:
            return provider, ladder[idx + 1]
        return provider, current_model
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_model_router.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/models/router.py tests/test_agent_sdk_model_router.py
git commit -m "feat: implement ModelRouter with task-type routing table"
```

---

### Task 6: Implement ContextBridge

**Files:**
- Create: `packages/agent_sdk/runner/context_bridge.py`
- Test: `tests/test_agent_sdk_context_bridge.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_context_bridge.py`:

```python
def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType
    defaults = dict(
        id="s1", title="Add login", description="Implement login feature",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Tests pass", "No lint errors"),
    )
    defaults.update(overrides)
    return Subtask(**defaults)


def _make_context_pack(**overrides):
    from packages.shared.domain.models import ContextPack
    defaults = dict(
        pack_id="cp-001", work_item_id="wi-001",
        constraints={"allowedPaths": ["src/"], "forbiddenPaths": ["secrets/"], "mustTouch": ["src/login.py"]},
        acceptance_criteria=("Tests pass",),
        known_failures=("Login timeout on slow networks",),
    )
    defaults.update(overrides)
    return ContextPack(**defaults)


def test_to_instructions_contains_task_description():
    from packages.agent_sdk.runner.context_bridge import ContextBridge
    subtask = _make_subtask(description="Implement login feature")
    context_pack = _make_context_pack()
    instructions = ContextBridge.to_instructions(subtask, context_pack)
    assert "Implement login feature" in instructions


def test_to_instructions_contains_constraints():
    from packages.agent_sdk.runner.context_bridge import ContextBridge
    subtask = _make_subtask()
    context_pack = _make_context_pack()
    instructions = ContextBridge.to_instructions(subtask, context_pack)
    assert "src/" in instructions
    assert "secrets/" in instructions
    assert "src/login.py" in instructions


def test_to_instructions_contains_definition_of_done():
    from packages.agent_sdk.runner.context_bridge import ContextBridge
    subtask = _make_subtask(definition_of_done=("All tests pass", "Coverage > 80%"))
    context_pack = _make_context_pack()
    instructions = ContextBridge.to_instructions(subtask, context_pack)
    assert "All tests pass" in instructions
    assert "Coverage > 80%" in instructions


def test_to_instructions_contains_known_failures():
    from packages.agent_sdk.runner.context_bridge import ContextBridge
    subtask = _make_subtask()
    context_pack = _make_context_pack(known_failures=("OOM on large files",))
    instructions = ContextBridge.to_instructions(subtask, context_pack)
    assert "OOM on large files" in instructions


def test_to_run_context_contains_metadata():
    from packages.agent_sdk.runner.context_bridge import ContextBridge
    run_ctx = ContextBridge.to_run_context(
        work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/workspace",
    )
    assert run_ctx.work_item_id == "wi-001"
    assert run_ctx.plan_id == "plan-001"
    assert run_ctx.workspace_path == "/tmp/workspace"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_context_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ContextBridge**

Create `packages/agent_sdk/runner/context_bridge.py`:

```python
"""Bridge between AI-DevOps ContextPack and Agents SDK Agent instructions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack


@dataclass
class AgentRunContext:
    """Runtime metadata passed to RunContextWrapper. Not sent to LLM."""
    work_item_id: str
    plan_id: str
    workspace_path: str
    event_bus: Any = None


class ContextBridge:
    """Converts ContextPack + Subtask into Agent instructions and runtime context."""

    @staticmethod
    def to_instructions(subtask: Subtask, context_pack: ContextPack) -> str:
        sections: list[str] = []

        sections.append(f"## Task\n{subtask.description}")

        constraints = context_pack.constraints
        if constraints:
            allowed = constraints.get("allowedPaths", [])
            forbidden = constraints.get("forbiddenPaths", [])
            must_touch = constraints.get("mustTouch", [])
            parts: list[str] = []
            if allowed:
                parts.append(f"Allowed paths: {', '.join(allowed)}")
            if forbidden:
                parts.append(f"Forbidden paths (DO NOT modify): {', '.join(forbidden)}")
            if must_touch:
                parts.append(f"Must touch: {', '.join(must_touch)}")
            if parts:
                sections.append("## Constraints\n" + "\n".join(parts))

        if subtask.definition_of_done:
            items = "\n".join(f"- {d}" for d in subtask.definition_of_done)
            sections.append(f"## Definition of Done\n{items}")

        if context_pack.acceptance_criteria:
            items = "\n".join(f"- {a}" for a in context_pack.acceptance_criteria)
            sections.append(f"## Acceptance Criteria\n{items}")

        if context_pack.known_failures:
            items = "\n".join(f"- {f}" for f in context_pack.known_failures)
            sections.append(f"## Known Failures\n{items}")

        risk = context_pack.risk_profile
        sections.append(f"## Risk Level\n{risk.value if hasattr(risk, 'value') else risk}")

        return "\n\n".join(sections)

    @staticmethod
    def to_run_context(
        work_item_id: str, plan_id: str, workspace_path: str, event_bus: Any = None,
    ) -> AgentRunContext:
        return AgentRunContext(
            work_item_id=work_item_id, plan_id=plan_id,
            workspace_path=workspace_path, event_bus=event_bus,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_context_bridge.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/runner/context_bridge.py tests/test_agent_sdk_context_bridge.py
git commit -m "feat: implement ContextBridge for hybrid context injection"
```

---

### Task 7: Implement AgentFactory

**Files:**
- Create: `packages/agent_sdk/runner/agent_factory.py`
- Test: `tests/test_agent_sdk_agent_factory.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_agent_factory.py`:

```python
def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType
    defaults = dict(
        id="s1", title="Add login", description="Implement login",
        agent="codex", model="gpt-5.4", effort="medium",
        worktree_strategy="shared", task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Tests pass",),
    )
    defaults.update(overrides)
    return Subtask(**defaults)


def _make_context_pack(**overrides):
    from packages.shared.domain.models import ContextPack
    defaults = dict(pack_id="cp-001", work_item_id="wi-001", constraints={"allowedPaths": ["src/"]})
    defaults.update(overrides)
    return ContextPack(**defaults)


def test_factory_builds_agent_with_correct_name():
    from packages.agent_sdk.runner.agent_factory import AgentFactory
    factory = AgentFactory()
    agent = factory.build(_make_subtask(id="s1"), _make_context_pack())
    assert agent.name == "s1-code_generation"


def test_factory_builds_agent_with_instructions():
    from packages.agent_sdk.runner.agent_factory import AgentFactory
    factory = AgentFactory()
    agent = factory.build(_make_subtask(description="Build the thing"), _make_context_pack())
    assert "Build the thing" in agent.instructions


def test_factory_uses_router_for_model():
    from packages.agent_sdk.runner.agent_factory import AgentFactory
    factory = AgentFactory()
    agent = factory.build(_make_subtask(task_type="code_review"), _make_context_pack())
    assert agent.model is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_agent_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AgentFactory**

Create `packages/agent_sdk/runner/agent_factory.py`:

```python
"""Build Agents SDK Agent instances from Subtask + ContextPack."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agents import Agent

from packages.agent_sdk.models.router import ModelRouter
from packages.agent_sdk.runner.context_bridge import ContextBridge

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack


class AgentFactory:
    """Constructs Agent instances from AI-DevOps domain objects."""

    def build(self, subtask: Subtask, context_pack: ContextPack) -> Agent:
        task_type = subtask.task_type
        task_type_value = task_type.value if hasattr(task_type, "value") else str(task_type)
        _provider, model_name = ModelRouter.resolve(task_type_value)
        instructions = ContextBridge.to_instructions(subtask, context_pack)
        return Agent(
            name=f"{subtask.id}-{task_type_value}",
            instructions=instructions,
            model=model_name,
        )

    def build_with_escalated_model(
        self, subtask: Subtask, context_pack: ContextPack,
        current_provider: str, current_model: str,
    ) -> Agent:
        _provider, escalated_model = ModelRouter.escalate(current_provider, current_model)
        instructions = ContextBridge.to_instructions(subtask, context_pack)
        task_type_value = subtask.task_type.value if hasattr(subtask.task_type, "value") else str(subtask.task_type)
        return Agent(
            name=f"{subtask.id}-{task_type_value}-escalated",
            instructions=instructions,
            model=escalated_model,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_agent_factory.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/runner/agent_factory.py tests/test_agent_sdk_agent_factory.py
git commit -m "feat: implement AgentFactory to build Agent from Subtask"
```

---

### Task 8: Implement AgentExecutor with Retry and Recovery

**Files:**
- Create: `packages/agent_sdk/runner/executor.py`
- Test: `tests/test_agent_sdk_executor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_executor.py`:

```python
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
    defaults = dict(pack_id="cp-001", work_item_id="wi-001")
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
    mock_bus.publish = MagicMock()
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
    mock_bus.publish = MagicMock()
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
    mock_bus.publish = MagicMock()
    executor = AgentExecutor(event_bus=mock_bus)

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(side_effect=RuntimeError("permanent"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await executor.execute(
                subtask=_make_subtask(), context_pack=_make_context_pack(),
                work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/ws",
            )

    assert result.agent_run.status.value == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_executor.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement AgentExecutor**

Create `packages/agent_sdk/runner/executor.py`:

```python
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
                        max_turns=MAX_TURNS,
                    )
                    duration = time.monotonic() - start_time

                    usage = {}
                    if hasattr(result, "usage") and result.usage is not None:
                        usage = {
                            "input_tokens": getattr(result.usage, "input_tokens", 0),
                            "output_tokens": getattr(result.usage, "output_tokens", 0),
                            "total_tokens": getattr(result.usage, "total_tokens", 0),
                            "model": current_model,
                            "duration_seconds": round(duration, 2),
                            "attempts": attempt + 1,
                        }

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_executor.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Run full test suite to confirm no regressions**

Run: `pytest -q 2>&1 | tail -5`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/agent_sdk/runner/executor.py tests/test_agent_sdk_executor.py
git commit -m "feat: implement AgentExecutor with retry, escalation, and events"
```

---

## Chunk 3: Phase 1 Integration — AgentLauncher Rewire and Event Types

### Task 9: Rewire AgentLauncher to Use AgentExecutor

**Files:**
- Modify: `packages/kernel/runtime/services.py:83-114`
- Test: `tests/test_kernel_runtime_services.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_kernel_runtime_services.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_sdk_agent_launcher_delegates_to_executor():
    from packages.kernel.runtime.services import SdkAgentLauncher
    from packages.agent_sdk.runner.executor import AgentRunResult
    from packages.shared.domain.models import AgentRun, AgentRunStatus

    fake_result = AgentRunResult(
        agent_run=AgentRun(
            run_id="r1", work_item_id="wi-001", context_pack_id="cp-001",
            agent="test", model="gpt-5.4", status=AgentRunStatus.COMPLETED,
        ),
    )
    mock_executor = MagicMock()
    mock_executor.execute = AsyncMock(return_value=fake_result)
    launcher = SdkAgentLauncher(executor=mock_executor)

    result = await launcher.launch_async(
        subtask=MagicMock(id="s1", task_type=MagicMock(value="code_generation"), prompt="do it", description="do it"),
        context_pack=MagicMock(pack_id="cp-001"),
        work_item_id="wi-001", plan_id="plan-001", workspace_path="/tmp/ws",
    )

    assert result.agent_run.status == AgentRunStatus.COMPLETED
    mock_executor.execute.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kernel_runtime_services.py::test_sdk_agent_launcher_delegates_to_executor -v`
Expected: FAIL — `ImportError: cannot import name 'SdkAgentLauncher'`

- [ ] **Step 3: Add SdkAgentLauncher to services.py**

Add after the existing `AgentLauncher` class (around line 115) in `packages/kernel/runtime/services.py`:

```python
class SdkAgentLauncher:
    """Agent launcher that delegates to AgentExecutor (SDK-based)."""

    def __init__(self, executor):
        self._executor = executor

    async def launch_async(self, subtask, context_pack, work_item_id, plan_id, workspace_path):
        return await self._executor.execute(
            subtask=subtask, context_pack=context_pack,
            work_item_id=work_item_id, plan_id=plan_id, workspace_path=workspace_path,
        )
```

- [ ] **Step 4: Run all runtime services tests**

Run: `pytest tests/test_kernel_runtime_services.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/kernel/runtime/services.py tests/test_kernel_runtime_services.py
git commit -m "feat: add SdkAgentLauncher bridging kernel to AgentExecutor"
```

---

### Task 10: Extend EventBus with Agent Trace Event Types

**Files:**
- Modify: `packages/kernel/events/bus.py`
- Test: `tests/test_kernel_event_bus.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_kernel_event_bus.py`:

```python
def test_agent_trace_events_constant_has_all_types():
    from packages.kernel.events.bus import AGENT_TRACE_EVENTS

    expected = {
        "agent_run.started", "agent_run.completed", "agent_run.failed",
        "agent_run.max_turns", "agent_run.llm_call", "agent_run.llm_response",
        "agent_run.tool_called", "agent_run.tool_result",
        "agent_run.guardrail_triggered", "agent_run.handoff",
    }
    assert expected == AGENT_TRACE_EVENTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_kernel_event_bus.py::test_agent_trace_events_constant_has_all_types -v`
Expected: FAIL — `ImportError: cannot import name 'AGENT_TRACE_EVENTS'`

- [ ] **Step 3: Add AGENT_TRACE_EVENTS constant to bus.py**

Add to `packages/kernel/events/bus.py` (after imports, before EventEnvelope class):

```python
AGENT_TRACE_EVENTS: frozenset[str] = frozenset({
    "agent_run.started", "agent_run.completed", "agent_run.failed",
    "agent_run.max_turns", "agent_run.llm_call", "agent_run.llm_response",
    "agent_run.tool_called", "agent_run.tool_result",
    "agent_run.guardrail_triggered", "agent_run.handoff",
})
```

- [ ] **Step 4: Run all event bus tests**

Run: `pytest tests/test_kernel_event_bus.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/kernel/events/bus.py tests/test_kernel_event_bus.py
git commit -m "feat: add AGENT_TRACE_EVENTS constant to event bus"
```

---

### Task 11: Phase 1 Integration Test

**Files:**
- Create: `tests/test_agent_sdk_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_agent_sdk_integration.py`:

```python
"""Integration test: verify the full Phase 1 pipeline works end-to-end."""

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
    bus.subscribe("agent_run.started", lambda e: events.append(e))
    bus.subscribe("agent_run.completed", lambda e: events.append(e))
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
    assert result.token_usage["input_tokens"] == 500
    event_types = [e.event_type for e in events]
    assert "agent_run.started" in event_types
    assert "agent_run.completed" in event_types
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_agent_sdk_integration.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest -q 2>&1 | tail -5`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_sdk_integration.py
git commit -m "test: add Phase 1 integration tests for SDK execution pipeline"
```

---

## Chunk 4: Phase 2 — Tool Ecosystem and MCP Server

### Task 12: Implement Built-in FunctionTools

**Files:**
- Create: `packages/agent_sdk/tools/builtin/file_tools.py`
- Create: `packages/agent_sdk/tools/builtin/command_tools.py`
- Test: `tests/test_agent_sdk_tools.py`

- [ ] **Step 1: Write failing tests for file and command tools**

Create `tests/test_agent_sdk_tools.py`:

```python
import pytest


def test_read_file_returns_content(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import read_file_impl
    test_file = tmp_path / "hello.py"
    test_file.write_text("print('hello')")
    result = read_file_impl(str(test_file), str(tmp_path))
    assert "print('hello')" in result


def test_read_file_rejects_outside_workspace(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import read_file_impl
    with pytest.raises(PermissionError):
        read_file_impl("/etc/passwd", str(tmp_path))


def test_write_file_creates_content(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import write_file_impl
    target = str(tmp_path / "new.py")
    result = write_file_impl(target, "x = 1", str(tmp_path))
    assert (tmp_path / "new.py").read_text() == "x = 1"


def test_write_file_rejects_outside_workspace(tmp_path):
    from packages.agent_sdk.tools.builtin.file_tools import write_file_impl
    with pytest.raises(PermissionError):
        write_file_impl("/tmp/evil.py", "bad", str(tmp_path))


def test_run_command_whitelisted(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    result = run_command_impl("echo hello", str(tmp_path))
    assert "hello" in result


def test_run_command_rejects_non_whitelisted(tmp_path):
    from packages.agent_sdk.tools.builtin.command_tools import run_command_impl
    with pytest.raises(PermissionError):
        run_command_impl("curl http://evil.com", str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_tools.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement file_tools.py**

Create `packages/agent_sdk/tools/builtin/file_tools.py`:

```python
"""File system tools with workspace boundary enforcement."""

from __future__ import annotations

from pathlib import Path


def _validate_path(file_path: str, workspace: str) -> Path:
    resolved = Path(file_path).resolve()
    ws_resolved = Path(workspace).resolve()
    if not str(resolved).startswith(str(ws_resolved)):
        raise PermissionError(f"Path {file_path} is outside workspace {workspace}")
    return resolved


def read_file_impl(file_path: str, workspace: str) -> str:
    resolved = _validate_path(file_path, workspace)
    if not resolved.exists():
        return f"Error: File {file_path} does not exist"
    return resolved.read_text(encoding="utf-8")


def write_file_impl(file_path: str, content: str, workspace: str) -> str:
    resolved = _validate_path(file_path, workspace)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {file_path}"


def list_directory_impl(dir_path: str, workspace: str) -> str:
    resolved = _validate_path(dir_path, workspace)
    if not resolved.is_dir():
        return f"Error: {dir_path} is not a directory"
    entries = sorted(str(p.relative_to(resolved)) for p in resolved.iterdir())
    return "\n".join(entries) if entries else "(empty directory)"
```

- [ ] **Step 4: Implement command_tools.py**

Create `packages/agent_sdk/tools/builtin/command_tools.py`:

```python
"""Shell command tools with whitelist enforcement."""

from __future__ import annotations

import subprocess

COMMAND_WHITELIST = frozenset({
    "echo", "cat", "head", "tail", "wc", "sort", "uniq", "diff",
    "ls", "find", "grep", "rg",
    "git", "pytest", "python", "node", "npm", "npx", "make",
    "pip", "pip3", "flake8", "mypy", "ruff", "black",
})

TOOL_TIMEOUT = 120


def run_command_impl(command: str, workspace: str, timeout: int = TOOL_TIMEOUT) -> str:
    first_word = command.strip().split()[0] if command.strip() else ""
    base = first_word.split("/")[-1]
    if base not in COMMAND_WHITELIST:
        raise PermissionError(
            f"Command '{base}' is not whitelisted. Allowed: {', '.join(sorted(COMMAND_WHITELIST))}"
        )
    try:
        result = subprocess.run(
            command, shell=True, cwd=workspace, capture_output=True,
            text=True, timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[stderr]: {result.stderr}" if result.stderr else ""
            output += f"\n[exit code]: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_tools.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/agent_sdk/tools/builtin/file_tools.py packages/agent_sdk/tools/builtin/command_tools.py tests/test_agent_sdk_tools.py
git commit -m "feat: implement file and command tools with security boundaries"
```

---

### Task 13: Implement Tool Registry

**Files:**
- Create: `packages/agent_sdk/tools/registry.py`
- Test: `tests/test_agent_sdk_tool_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_tool_registry.py`:

```python
def test_registry_returns_common_tools_for_any_type():
    from packages.agent_sdk.tools.registry import ToolRegistry
    tools = ToolRegistry.resolve("code_generation")
    tool_names = {t.name for t in tools}
    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "run_command" in tool_names


def test_registry_returns_task_specific_tools():
    from packages.agent_sdk.tools.registry import ToolRegistry
    tools = ToolRegistry.resolve("code_generation")
    tool_names = {t.name for t in tools}
    assert "run_tests" in tool_names


def test_registry_unknown_type_returns_common_tools():
    from packages.agent_sdk.tools.registry import ToolRegistry
    tools = ToolRegistry.resolve("unknown_type")
    tool_names = {t.name for t in tools}
    assert "read_file" in tool_names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent_sdk_tool_registry.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ToolRegistry**

Create `packages/agent_sdk/tools/registry.py`:

```python
"""Tool registry that resolves task type to available FunctionTools."""

from __future__ import annotations

from agents import function_tool

from packages.agent_sdk.tools.builtin.file_tools import read_file_impl, write_file_impl, list_directory_impl
from packages.agent_sdk.tools.builtin.command_tools import run_command_impl


@function_tool
def read_file(file_path: str, workspace: str = ".") -> str:
    """Read the contents of a file within the workspace."""
    return read_file_impl(file_path, workspace)

@function_tool
def write_file(file_path: str, content: str, workspace: str = ".") -> str:
    """Write content to a file within the workspace."""
    return write_file_impl(file_path, content, workspace)

@function_tool
def list_directory(dir_path: str = ".", workspace: str = ".") -> str:
    """List files and directories within the workspace."""
    return list_directory_impl(dir_path, workspace)

@function_tool
def run_command(command: str, workspace: str = ".") -> str:
    """Run a whitelisted shell command in the workspace."""
    return run_command_impl(command, workspace)

@function_tool
def search_code(pattern: str, workspace: str = ".", file_glob: str = "") -> str:
    """Search for a pattern in code files."""
    cmd = f"grep -rn '{pattern}' ."
    if file_glob:
        cmd = f"grep -rn --include='{file_glob}' '{pattern}' ."
    return run_command_impl(cmd, workspace)

@function_tool
def run_tests(test_path: str = "", workspace: str = ".") -> str:
    """Run the test suite using pytest."""
    cmd = f"pytest -q {test_path}" if test_path else "pytest -q"
    return run_command_impl(cmd, workspace)

@function_tool
def lint_check(workspace: str = ".") -> str:
    """Run linting checks."""
    return run_command_impl("ruff check .", workspace)

@function_tool
def type_check(workspace: str = ".") -> str:
    """Run type checking."""
    return run_command_impl("mypy .", workspace)

@function_tool
def git_diff(workspace: str = ".") -> str:
    """Show git diff of current changes."""
    return run_command_impl("git diff", workspace)

@function_tool
def git_log(count: int = 10, workspace: str = ".") -> str:
    """Show recent git log entries."""
    return run_command_impl(f"git log --oneline -n {count}", workspace)

@function_tool
def coverage_report(workspace: str = ".") -> str:
    """Run tests with coverage report."""
    return run_command_impl("pytest --cov --cov-report=term-missing -q", workspace)


_COMMON_TOOLS = [read_file, write_file, list_directory, run_command, search_code]

_TASK_TOOLS: dict[str, list] = {
    "code_generation": [run_tests, lint_check, type_check],
    "code_review":     [git_diff],
    "bug_fix":         [run_tests, git_log],
    "refactor":        [run_tests, type_check],
    "test_generation": [run_tests, coverage_report],
    "documentation":   [],
    "planning":        [],
    "incident_analysis": [git_log],
}


class ToolRegistry:
    @staticmethod
    def resolve(task_type: str) -> list:
        extras = _TASK_TOOLS.get(task_type, [])
        return _COMMON_TOOLS + extras
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_tool_registry.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/tools/registry.py tests/test_agent_sdk_tool_registry.py
git commit -m "feat: implement ToolRegistry with common and task-specific tools"
```

---

### Task 14: Implement ContextPack MCP Server

**Files:**
- Create: `packages/agent_sdk/tools/mcp_servers/context_server.py`
- Test: `tests/test_agent_sdk_mcp_context_server.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_mcp_context_server.py`:

```python
def test_context_server_exposes_resources():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack

    pack = ContextPack(
        pack_id="cp-1", work_item_id="wi-1",
        repo_scope=("src/main.py", "src/utils.py"),
        recent_changes=("abc123: fix bug",),
    )
    server = ContextPackServer(pack)
    resources = server.list_resources()
    resource_names = {r["name"] for r in resources}
    assert "code-graph" in resource_names
    assert "recent-changes" in resource_names
    assert "documentation" in resource_names


def test_context_server_get_resource_returns_data():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack

    pack = ContextPack(pack_id="cp-1", work_item_id="wi-1", recent_changes=("abc123: fix login bug",))
    server = ContextPackServer(pack)
    data = server.get_resource("recent-changes")
    assert "abc123" in data


def test_context_server_get_unknown_resource():
    from packages.agent_sdk.tools.mcp_servers.context_server import ContextPackServer
    from packages.shared.domain.models import ContextPack

    pack = ContextPack(pack_id="cp-1", work_item_id="wi-1")
    server = ContextPackServer(pack)
    data = server.get_resource("nonexistent")
    assert "unknown" in data.lower()
```

- [ ] **Step 2: Run tests, verify fail, then implement**

Run: `pytest tests/test_agent_sdk_mcp_context_server.py -v`
Expected: FAIL

- [ ] **Step 3: Implement ContextPackServer**

Create `packages/agent_sdk/tools/mcp_servers/context_server.py`:

```python
"""MCP Server wrapper around ContextPack for on-demand context queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.shared.domain.models import ContextPack


class ContextPackServer:
    def __init__(self, context_pack: ContextPack):
        self._pack = context_pack

    def list_resources(self) -> list[dict[str, str]]:
        return [
            {"name": "code-graph", "uri": "context://code-graph"},
            {"name": "recent-changes", "uri": "context://recent-changes"},
            {"name": "documentation", "uri": "context://documentation"},
            {"name": "known-failures", "uri": "context://known-failures"},
            {"name": "success-patterns", "uri": "context://success-patterns"},
        ]

    def get_resource(self, name: str) -> str:
        handlers = {
            "code-graph": lambda: ("Files in scope:\n" + "\n".join(f"- {f}" for f in self._pack.repo_scope)) if self._pack.repo_scope else "(no code graph available)",
            "recent-changes": lambda: ("Recent changes:\n" + "\n".join(f"- {c}" for c in self._pack.recent_changes)) if self._pack.recent_changes else "(no recent changes)",
            "documentation": lambda: "\n\n".join(self._pack.docs) if self._pack.docs else "(no documentation available)",
            "known-failures": lambda: ("Known failures:\n" + "\n".join(f"- {f}" for f in self._pack.known_failures)) if self._pack.known_failures else "(no known failures)",
            "success-patterns": lambda: "(success patterns not yet migrated)",
        }
        handler = handlers.get(name)
        return handler() if handler else f"Unknown resource: {name}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_mcp_context_server.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/tools/mcp_servers/context_server.py tests/test_agent_sdk_mcp_context_server.py
git commit -m "feat: implement ContextPackServer for MCP-style context queries"
```

---

## Chunk 5: Phase 3 — Quality Guardrails

### Task 15: Implement Input Guardrails

**Files:**
- Create: `packages/agent_sdk/guardrails/input_guards.py`
- Test: `tests/test_agent_sdk_input_guards.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_input_guards.py`:

```python
def test_boundary_guard_passes_with_valid_constraints():
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard
    result = BoundaryGuard.check(constraints={"allowedPaths": ["src/"]}, definition_of_done=("Tests pass",))
    assert result.tripwire_triggered is False


def test_boundary_guard_trips_when_constraints_empty():
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard
    result = BoundaryGuard.check(constraints={}, definition_of_done=())
    assert result.tripwire_triggered is True


def test_sensitive_data_guard_detects_api_key():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("Config: AKIAIOSFODNN7EXAMPLE")
    assert result.tripwire_triggered is False
    assert len(result.warnings) > 0


def test_sensitive_data_guard_passes_clean_input():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("Normal code: x = 1 + 2")
    assert result.tripwire_triggered is False
    assert len(result.warnings) == 0


def test_sensitive_data_guard_detects_github_token():
    from packages.agent_sdk.guardrails.input_guards import SensitiveDataGuard
    result = SensitiveDataGuard.check("token = 'ghp_1234567890abcdefghijklmnopqrstuvwxyz'")
    assert len(result.warnings) > 0
```

- [ ] **Step 2: Run tests, verify fail, then implement**

- [ ] **Step 3: Implement input guardrails**

Create `packages/agent_sdk/guardrails/input_guards.py`:

```python
"""Input guardrails for agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    tripwire_triggered: bool
    message: str = ""
    warnings: tuple[str, ...] = ()


_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub Token", re.compile(r"ghp_[a-zA-Z0-9]{36}")),
    ("GitHub OAuth", re.compile(r"gho_[a-zA-Z0-9]{36}")),
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("Generic API Key", re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"][a-zA-Z0-9]{20,}", re.IGNORECASE)),
    ("Generic Secret", re.compile(r"(?:secret|password|passwd|pwd)\s*[:=]\s*['\"][^\s'\"]{8,}", re.IGNORECASE)),
    ("Slack Token", re.compile(r"xox[baprs]-[a-zA-Z0-9-]+")),
]


class BoundaryGuard:
    @staticmethod
    def check(constraints: dict, definition_of_done: tuple[str, ...]) -> GuardrailResult:
        issues: list[str] = []
        if not constraints:
            issues.append("constraints dict is empty")
        if not constraints.get("allowedPaths"):
            issues.append("allowedPaths is missing or empty")
        if not definition_of_done:
            issues.append("definition_of_done is empty")
        if issues:
            return GuardrailResult(tripwire_triggered=True, message=f"Boundary check failed: {'; '.join(issues)}")
        return GuardrailResult(tripwire_triggered=False)


class SensitiveDataGuard:
    @staticmethod
    def check(text: str) -> GuardrailResult:
        warnings: list[str] = []
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                warnings.append(f"Potential {name} detected in input")
        return GuardrailResult(tripwire_triggered=False, warnings=tuple(warnings))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_input_guards.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/guardrails/input_guards.py tests/test_agent_sdk_input_guards.py
git commit -m "feat: implement BoundaryGuard and SensitiveDataGuard input guardrails"
```

---

### Task 16: Implement Output Guardrails

**Files:**
- Create: `packages/agent_sdk/guardrails/output_guards.py`
- Test: `tests/test_agent_sdk_output_guards.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_output_guards.py`:

```python
import pytest


def test_secret_leak_guard_detects_aws_key():
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard
    result = SecretLeakGuard.check("config = 'AKIAIOSFODNN7EXAMPLE'")
    assert result.tripwire_triggered is True


def test_secret_leak_guard_passes_clean_output():
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard
    result = SecretLeakGuard.check("def hello(): return 'world'")
    assert result.tripwire_triggered is False


def test_code_safety_guard_detects_eval():
    from packages.agent_sdk.guardrails.output_guards import CodeSafetyGuard
    result = CodeSafetyGuard.check("result = eval(user_input)")
    assert result.tripwire_triggered is False
    assert len(result.risks) > 0


def test_code_safety_guard_passes_safe_code():
    from packages.agent_sdk.guardrails.output_guards import CodeSafetyGuard
    result = CodeSafetyGuard.check("x = [1, 2, 3]\nprint(sum(x))")
    assert len(result.risks) == 0


def test_forbidden_path_guard_detects_violation():
    from packages.agent_sdk.guardrails.output_guards import ForbiddenPathGuard
    result = ForbiddenPathGuard.check(
        written_paths=["src/main.py", "secrets/keys.json"], forbidden_paths=["secrets/"],
    )
    assert result.tripwire_triggered is True


def test_forbidden_path_guard_passes_allowed_paths():
    from packages.agent_sdk.guardrails.output_guards import ForbiddenPathGuard
    result = ForbiddenPathGuard.check(
        written_paths=["src/main.py"], forbidden_paths=["secrets/"],
    )
    assert result.tripwire_triggered is False
```

- [ ] **Step 2: Run tests, verify fail, then implement**

- [ ] **Step 3: Implement output guardrails**

Create `packages/agent_sdk/guardrails/output_guards.py`:

```python
"""Output guardrails for agent execution results."""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.agent_sdk.guardrails.input_guards import _SECRET_PATTERNS


@dataclass(frozen=True)
class SecretLeakResult:
    tripwire_triggered: bool
    message: str = ""

@dataclass(frozen=True)
class CodeSafetyResult:
    tripwire_triggered: bool = False
    risks: tuple[str, ...] = ()

@dataclass(frozen=True)
class ForbiddenPathResult:
    tripwire_triggered: bool
    message: str = ""
    violations: tuple[str, ...] = ()


_DANGEROUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eval() usage", re.compile(r"\beval\s*\(")),
    ("exec() usage", re.compile(r"\bexec\s*\(")),
    ("shell=True in subprocess", re.compile(r"shell\s*=\s*True")),
    ("rm -rf command", re.compile(r"rm\s+-rf\s")),
    ("chmod 777", re.compile(r"chmod\s+777")),
]


class SecretLeakGuard:
    @staticmethod
    def check(text: str) -> SecretLeakResult:
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                return SecretLeakResult(tripwire_triggered=True, message=f"Secret leak detected: {name}")
        return SecretLeakResult(tripwire_triggered=False)


class CodeSafetyGuard:
    @staticmethod
    def check(text: str) -> CodeSafetyResult:
        risks = tuple(name for name, pattern in _DANGEROUS_PATTERNS if pattern.search(text))
        return CodeSafetyResult(risks=risks)


class ForbiddenPathGuard:
    @staticmethod
    def check(written_paths: list[str], forbidden_paths: list[str]) -> ForbiddenPathResult:
        violations = tuple(
            f"{w} violates {f}" for w in written_paths for f in forbidden_paths
            if w.startswith(f) or w == f
        )
        if violations:
            return ForbiddenPathResult(tripwire_triggered=True, message=f"{len(violations)} violations", violations=violations)
        return ForbiddenPathResult(tripwire_triggered=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_output_guards.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/guardrails/output_guards.py tests/test_agent_sdk_output_guards.py
git commit -m "feat: implement SecretLeakGuard, CodeSafetyGuard, ForbiddenPathGuard"
```

---

## Chunk 6: Phase 4 — Observability Bridge and Final Verification

### Task 17: Implement Tracing Event Bridge

**Files:**
- Create: `packages/agent_sdk/tracing/event_bridge.py`
- Test: `tests/test_agent_sdk_event_bridge.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_event_bridge.py`:

```python
from unittest.mock import MagicMock


def test_bridge_maps_agent_start_event():
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    bus = MagicMock()
    bridge = AgentTraceBridge(event_bus=bus, sensitive_data=False)
    bridge.on_trace_event("agent.start", {"agent_name": "s1"})
    bus.publish.assert_called_once()
    assert bus.publish.call_args[0][0] == "agent_run.started"


def test_bridge_skips_unknown_events():
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    bus = MagicMock()
    bridge = AgentTraceBridge(event_bus=bus, sensitive_data=False)
    bridge.on_trace_event("unknown.event", {})
    bus.publish.assert_not_called()


def test_bridge_strips_sensitive_data_when_disabled():
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    bus = MagicMock()
    bridge = AgentTraceBridge(event_bus=bus, sensitive_data=False)
    bridge.on_trace_event("llm.generation.end", {"model": "gpt-5.4", "output": "secret text", "tokens": 500})
    payload = bus.publish.call_args[0][1]
    assert "output" not in payload
    assert payload.get("tokens") == 500


def test_bridge_includes_sensitive_data_when_enabled():
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    bus = MagicMock()
    bridge = AgentTraceBridge(event_bus=bus, sensitive_data=True)
    bridge.on_trace_event("llm.generation.end", {"model": "gpt-5.4", "output": "LLM response", "tokens": 500})
    payload = bus.publish.call_args[0][1]
    assert payload.get("output") == "LLM response"
```

- [ ] **Step 2: Run tests, verify fail, then implement**

- [ ] **Step 3: Implement AgentTraceBridge**

Create `packages/agent_sdk/tracing/event_bridge.py`:

```python
"""Bridge between Agents SDK tracing and AI-DevOps InMemoryEventBus."""

from __future__ import annotations

from typing import Any

_EVENT_MAP: dict[str, str] = {
    "agent.start": "agent_run.started", "agent.end": "agent_run.completed",
    "llm.generation.start": "agent_run.llm_call", "llm.generation.end": "agent_run.llm_response",
    "tool.call": "agent_run.tool_called", "tool.result": "agent_run.tool_result",
    "guardrail.triggered": "agent_run.guardrail_triggered", "handoff": "agent_run.handoff",
}

_SENSITIVE_FIELDS = frozenset({"input", "output", "prompt", "response", "content", "arguments"})


class AgentTraceBridge:
    def __init__(self, event_bus: Any, sensitive_data: bool = False):
        self._bus = event_bus
        self._sensitive_data = sensitive_data

    def on_trace_event(self, sdk_event_type: str, data: dict[str, Any]) -> None:
        mapped = _EVENT_MAP.get(sdk_event_type)
        if mapped is None:
            return
        payload = dict(data) if self._sensitive_data else {k: v for k, v in data.items() if k not in _SENSITIVE_FIELDS}
        self._bus.publish(mapped, payload)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_event_bridge.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/tracing/event_bridge.py tests/test_agent_sdk_event_bridge.py
git commit -m "feat: implement AgentTraceBridge for SDK-to-EventBus tracing"
```

---

### Task 18: Implement Token Usage Collector

**Files:**
- Create: `packages/agent_sdk/tracing/usage_collector.py`
- Test: `tests/test_agent_sdk_usage_collector.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_sdk_usage_collector.py`:

```python
from dataclasses import dataclass


def test_collector_extracts_usage():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    @dataclass
    class FakeUsage:
        input_tokens: int = 1000
        output_tokens: int = 500
        total_tokens: int = 1500

    @dataclass
    class FakeResult:
        usage: FakeUsage = None

    usage = TokenUsageCollector.extract(FakeResult(usage=FakeUsage()), model="gpt-5.4", duration=12.5)
    assert usage["input_tokens"] == 1000
    assert usage["model"] == "gpt-5.4"


def test_collector_handles_missing_usage():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    @dataclass
    class FakeResult:
        usage: None = None

    usage = TokenUsageCollector.extract(FakeResult(), model="gpt-5.4", duration=5.0)
    assert usage["input_tokens"] == 0


def test_collector_aggregates():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    runs = [
        {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "model": "gpt-5.4", "duration_seconds": 5.0},
        {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300, "model": "claude-opus-4-6", "duration_seconds": 8.0},
    ]
    agg = TokenUsageCollector.aggregate(runs)
    assert agg["total_tokens"] == 450
    assert agg["run_count"] == 2
```

- [ ] **Step 2: Run tests, verify fail, then implement**

- [ ] **Step 3: Implement TokenUsageCollector**

Create `packages/agent_sdk/tracing/usage_collector.py`:

```python
"""Token usage extraction and aggregation."""

from __future__ import annotations

from typing import Any


class TokenUsageCollector:
    @staticmethod
    def extract(result: Any, model: str, duration: float) -> dict[str, Any]:
        usage = getattr(result, "usage", None)
        return {
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            "model": model,
            "duration_seconds": round(duration, 2),
        }

    @staticmethod
    def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total_input_tokens": sum(r.get("input_tokens", 0) for r in runs),
            "total_output_tokens": sum(r.get("output_tokens", 0) for r in runs),
            "total_tokens": sum(r.get("total_tokens", 0) for r in runs),
            "total_duration_seconds": round(sum(r.get("duration_seconds", 0) for r in runs), 2),
            "run_count": len(runs),
            "models_used": list({r.get("model", "unknown") for r in runs}),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent_sdk_usage_collector.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/agent_sdk/tracing/usage_collector.py tests/test_agent_sdk_usage_collector.py
git commit -m "feat: implement TokenUsageCollector for usage extraction and aggregation"
```

---

### Task 19: Full Pipeline Integration Test

**Files:**
- Create: `tests/test_agent_sdk_full_pipeline.py`

- [ ] **Step 1: Write the full pipeline test**

Create `tests/test_agent_sdk_full_pipeline.py`:

```python
"""Full pipeline integration test spanning all 4 phases."""

import asyncio
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
    from orchestrator.bin.plan_schema import Subtask, TaskType
    from packages.shared.domain.models import ContextPack, AgentRunStatus
    from packages.kernel.events.bus import InMemoryEventBus
    from packages.agent_sdk.runner.executor import AgentExecutor
    from packages.agent_sdk.tools.registry import ToolRegistry
    from packages.agent_sdk.guardrails.input_guards import BoundaryGuard, SensitiveDataGuard
    from packages.agent_sdk.guardrails.output_guards import SecretLeakGuard, CodeSafetyGuard, ForbiddenPathGuard
    from packages.agent_sdk.tracing.event_bridge import AgentTraceBridge
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    subtask = Subtask(
        id="full-s1", title="Add feature", description="Add hello world",
        agent="codex", model="gpt-5.4", effort="low", worktree_strategy="shared",
        task_type=TaskType.CODE_GENERATION, definition_of_done=("Tests pass",),
    )
    context_pack = ContextPack(
        pack_id="full-cp1", work_item_id="full-wi1",
        constraints={"allowedPaths": ["src/"], "forbiddenPaths": ["secrets/"], "mustTouch": ["src/hello.py"]},
    )

    # Phase 2: Tools resolve
    tools = ToolRegistry.resolve("code_generation")
    assert any(t.name == "run_tests" for t in tools)

    # Phase 3: Guardrails pass
    assert BoundaryGuard.check(context_pack.constraints, subtask.definition_of_done).tripwire_triggered is False
    assert SensitiveDataGuard.check(subtask.description).tripwire_triggered is False
    assert SecretLeakGuard.check("def hello(): return 'world'").tripwire_triggered is False
    assert len(CodeSafetyGuard.check("def hello(): return 'world'").risks) == 0
    assert ForbiddenPathGuard.check(["src/hello.py"], ["secrets/"]).tripwire_triggered is False

    # Phase 1: Execute
    bus = InMemoryEventBus()
    events = []
    bus.subscribe("agent_run.started", lambda e: events.append(e))
    bus.subscribe("agent_run.completed", lambda e: events.append(e))

    with patch("packages.agent_sdk.runner.executor.Runner") as MockRunner:
        MockRunner.run = AsyncMock(return_value=FakeRunResult())
        result = await AgentExecutor(event_bus=bus).execute(
            subtask=subtask, context_pack=context_pack,
            work_item_id="full-wi1", plan_id="full-plan1", workspace_path="/tmp/full",
        )

    assert result.agent_run.status == AgentRunStatus.COMPLETED

    # Phase 4: Tracing + usage
    AgentTraceBridge(event_bus=bus, sensitive_data=False).on_trace_event("tool.call", {"tool_name": "read_file"})
    usage = TokenUsageCollector.extract(FakeRunResult(), model="gpt-5.4", duration=10.0)
    assert usage["total_tokens"] == 1200

    assert any(e.event_type == "agent_run.started" for e in events)
    assert any(e.event_type == "agent_run.completed" for e in events)
```

- [ ] **Step 2: Run and verify**

Run: `pytest tests/test_agent_sdk_full_pipeline.py -v`
Expected: PASS

- [ ] **Step 3: Run complete test suite**

Run: `pytest -q 2>&1 | tail -10`
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_agent_sdk_full_pipeline.py
git commit -m "test: add full pipeline integration test across all 4 phases"
```

---

### Task 20: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `pytest --tb=short -q`
Expected: All tests pass.

- [ ] **Step 2: Verify package structure**

Run: `find packages/agent_sdk -name "*.py" | sort`

Expected:
```
packages/agent_sdk/__init__.py
packages/agent_sdk/guardrails/__init__.py
packages/agent_sdk/guardrails/input_guards.py
packages/agent_sdk/guardrails/output_guards.py
packages/agent_sdk/models/__init__.py
packages/agent_sdk/models/router.py
packages/agent_sdk/runner/__init__.py
packages/agent_sdk/runner/agent_factory.py
packages/agent_sdk/runner/context_bridge.py
packages/agent_sdk/runner/executor.py
packages/agent_sdk/tools/__init__.py
packages/agent_sdk/tools/builtin/__init__.py
packages/agent_sdk/tools/builtin/command_tools.py
packages/agent_sdk/tools/builtin/file_tools.py
packages/agent_sdk/tools/mcp_servers/__init__.py
packages/agent_sdk/tools/mcp_servers/context_server.py
packages/agent_sdk/tools/registry.py
packages/agent_sdk/tracing/__init__.py
packages/agent_sdk/tracing/event_bridge.py
packages/agent_sdk/tracing/usage_collector.py
```

- [ ] **Step 3: Verify all test files**

Run: `find tests -name "test_agent_sdk*" | sort`

Expected:
```
tests/test_agent_sdk_agent_factory.py
tests/test_agent_sdk_context_bridge.py
tests/test_agent_sdk_event_bridge.py
tests/test_agent_sdk_executor.py
tests/test_agent_sdk_full_pipeline.py
tests/test_agent_sdk_input_guards.py
tests/test_agent_sdk_integration.py
tests/test_agent_sdk_mcp_context_server.py
tests/test_agent_sdk_model_router.py
tests/test_agent_sdk_output_guards.py
tests/test_agent_sdk_tool_registry.py
tests/test_agent_sdk_tools.py
tests/test_agent_sdk_usage_collector.py
```

- [ ] **Step 4: Final commit**

```bash
git status
# Commit any remaining changes
```
