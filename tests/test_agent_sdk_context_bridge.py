from __future__ import annotations


def _make_subtask(**overrides):
    from orchestrator.bin.plan_schema import Subtask, TaskType

    defaults = dict(
        id="s1",
        title="Add login",
        description="Implement login feature",
        agent="codex",
        model="gpt-5.4",
        effort="medium",
        worktree_strategy="shared",
        task_type=TaskType.CODE_GENERATION,
        definition_of_done=("Tests pass", "No lint errors"),
    )
    defaults.update(overrides)
    return Subtask(**defaults)


def _make_context_pack(**overrides):
    from packages.shared.domain.models import ContextPack

    defaults = dict(
        pack_id="cp-001",
        work_item_id="wi-001",
        constraints={
            "allowedPaths": ["src/"],
            "forbiddenPaths": ["secrets/"],
            "mustTouch": ["src/login.py"],
        },
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


def test_to_run_context_contains_metadata_fields():
    from packages.agent_sdk.runner.context_bridge import ContextBridge

    event_bus = object()

    run_context = ContextBridge.to_run_context(
        work_item_id="wi-001",
        plan_id="plan-001",
        workspace_path="/tmp/workspace",
        event_bus=event_bus,
    )

    assert run_context.work_item_id == "wi-001"
    assert run_context.plan_id == "plan-001"
    assert run_context.workspace_path == "/tmp/workspace"
    assert run_context.event_bus is event_bus
