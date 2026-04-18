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
