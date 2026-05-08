"""Bridge between Agents SDK tracing and AI-DevOps InMemoryEventBus."""

from __future__ import annotations

from typing import Any

_EVENT_MAP: dict[str, str] = {
    "agent.start": "agent_run.started", "agent.end": "agent_run.completed",
    "llm.generation.start": "agent_run.llm_call", "llm.generation.end": "agent_run.llm_response",
    "tool.call": "agent_run.tool_called", "tool.result": "agent_run.tool_result",
    "guardrail.triggered": "agent_run.guardrail_triggered", "handoff": "agent_run.handoff",
    # Adversarial review events
    "adversarial_review.round_completed": "agent_run.review_round",
    "adversarial_review.passed":          "agent_run.review_passed",
    "adversarial_review.exhausted":       "agent_run.review_exhausted",
    "adversarial_review.stalled":         "agent_run.review_stalled",
    "adversarial_review.impl_failed":     "agent_run.review_impl_failed",
    # Knowledge evolver events
    "knowledge.evolved":                  "agent_run.knowledge_evolved",
    # UI test events
    "ui_test.server_detected":            "agent_run.ui_server_detected",
    "ui_test.server_ready":               "agent_run.ui_server_ready",
    "ui_test.screenshot_captured":        "agent_run.ui_screenshot",
    "ui_test.completed":                  "agent_run.ui_test_completed",
    "ui_test.server_stopped":             "agent_run.ui_server_stopped",
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
