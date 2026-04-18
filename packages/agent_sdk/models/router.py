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

_ESCALATION: list[tuple[str, str]] = [
    ("openai", "gpt-5.4-mini"),
    ("openai", "gpt-5.4"),
    ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "claude-opus-4-6"),
]


def _parse_override(value: str) -> tuple[str, str] | None:
    for delimiter in ("/", ":", ","):
        if delimiter in value:
            provider, model = value.split(delimiter, 1)
            provider = provider.strip()
            model = model.strip()
            if provider and model:
                return provider, model
    return None


def _provider_for_model(current_model: str) -> str:
    for provider, model in _ESCALATION:
        if model == current_model:
            return provider

    for provider, model in TASK_ROUTE_TABLE.values():
        if model == current_model:
            return provider

    if DEFAULT_ROUTE[1] == current_model:
        return DEFAULT_ROUTE[0]

    return DEFAULT_ROUTE[0]


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
    def escalate(current_model: str) -> tuple[str, str]:
        for index, route in enumerate(_ESCALATION):
            provider, model = route
            if model != current_model:
                continue
            if index < len(_ESCALATION) - 1:
                next_provider, next_model = _ESCALATION[index + 1]
                if next_provider == provider:
                    return next_provider, next_model
            return provider, model

        return _provider_for_model(current_model), current_model
