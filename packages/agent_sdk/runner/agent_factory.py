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
