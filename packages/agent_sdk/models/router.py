"""Task-type based model routing for agent SDK workloads."""

from __future__ import annotations

import os

TASK_ROUTE_TABLE: dict[str, tuple[str, str]] = {
    "code_generation": ("openai", "gpt-5.4"),
    "code_review": ("anthropic", "claude-opus-4-6"),
    "bug_fix": ("openai", "gpt-5.4"),
    "refactor": ("openai", "gpt-5.4"),
    "documentation": ("anthropic", "claude-sonnet-4-6"),
    "test_generation": ("openai", "gpt-5.4-mini"),
    "planning": ("anthropic", "claude-opus-4-6"),
    "incident_analysis": ("anthropic", "claude-opus-4-6"),
}

DEFAULT_ROUTE: tuple[str, str] = ("openai", "gpt-5.4")

_ESCALATION: dict[str, list[str]] = {
    "openai": ["gpt-5.4-mini", "gpt-5.4"],
    "anthropic": ["claude-sonnet-4-6", "claude-opus-4-6"],
}


def _parse_override(value: str) -> tuple[str, str] | None:
    for delimiter in ("/", ":", ","):
        if delimiter in value:
            provider, model = value.split(delimiter, 1)
            provider = provider.strip()
            model = model.strip()
            if provider and model:
                return provider, model
    return None


class ModelRouter:
    """Resolve task types to models and support escalation to stronger models."""

    @staticmethod
    def resolve(task_type: str) -> tuple[str, str]:
        override = os.getenv(f"ROUTE_{task_type.upper()}")
        if override:
            parsed = _parse_override(override)
            if parsed is not None:
                return parsed

        return TASK_ROUTE_TABLE.get(task_type, DEFAULT_ROUTE)

    @staticmethod
    def escalate(provider: str, current_model: str) -> tuple[str, str]:
        """Escalate to the next stronger model within the same provider."""
        ladder = _ESCALATION.get(provider, [])
        if current_model not in ladder:
            return provider, current_model
        idx = ladder.index(current_model)
        if idx < len(ladder) - 1:
            return provider, ladder[idx + 1]
        return provider, current_model
