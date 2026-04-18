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
