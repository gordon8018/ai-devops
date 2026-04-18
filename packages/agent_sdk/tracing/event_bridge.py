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
