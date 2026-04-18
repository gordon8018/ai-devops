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
