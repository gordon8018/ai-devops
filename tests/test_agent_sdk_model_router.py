from orchestrator.bin.plan_schema import TaskType


def test_code_generation_routes_to_openai_gpt_5_4():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("code_generation")

    assert provider == "openai"
    assert model == "gpt-5.4"


def test_code_review_routes_to_anthropic_claude_opus_4_6():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("code_review")

    assert provider == "anthropic"
    assert model == "claude-opus-4-6"


def test_documentation_routes_to_anthropic_claude_sonnet_4_6():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.resolve("documentation")

    assert provider == "anthropic"
    assert model == "claude-sonnet-4-6"


def test_unknown_type_falls_back_to_default_route():
    from packages.agent_sdk.models.router import DEFAULT_ROUTE, ModelRouter

    assert ModelRouter.resolve("unknown_type") == DEFAULT_ROUTE


def test_escalate_returns_stronger_model():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.escalate("gpt-5.4-mini")

    assert provider == "openai"
    assert model == "gpt-5.4"


def test_escalate_at_max_returns_same_model():
    from packages.agent_sdk.models.router import ModelRouter

    provider, model = ModelRouter.escalate("gpt-5.4")

    assert provider == "openai"
    assert model == "gpt-5.4"


def test_all_task_type_enum_values_have_routes():
    from packages.agent_sdk.models.router import TASK_ROUTE_TABLE

    for task_type in TaskType:
        assert task_type.value in TASK_ROUTE_TABLE, f"Missing route for {task_type.value}"
