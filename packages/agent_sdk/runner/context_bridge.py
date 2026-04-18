"""Bridge between AI-DevOps context models and Agents SDK runtime inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrator.bin.plan_schema import Subtask
    from packages.shared.domain.models import ContextPack


@dataclass(slots=True, frozen=True)
class AgentRunContext:
    """Runtime metadata passed alongside an agent run."""

    work_item_id: str
    plan_id: str
    workspace_path: str
    event_bus: Any = None


class ContextBridge:
    """Builds instruction text and runtime context for an agent execution."""

    @staticmethod
    def to_instructions(subtask: Subtask, context_pack: ContextPack) -> str:
        sections = [f"## Task\n{subtask.description}"]

        constraint_lines = ContextBridge._format_constraints(context_pack.constraints)
        if constraint_lines:
            sections.append("## Constraints\n" + "\n".join(constraint_lines))

        definition_of_done = ContextBridge._format_bullets(subtask.definition_of_done)
        if definition_of_done:
            sections.append(f"## Definition of Done\n{definition_of_done}")

        acceptance_criteria = ContextBridge._format_bullets(context_pack.acceptance_criteria)
        if acceptance_criteria:
            sections.append(f"## Acceptance Criteria\n{acceptance_criteria}")

        known_failures = ContextBridge._format_bullets(context_pack.known_failures)
        if known_failures:
            sections.append(f"## Known Failures\n{known_failures}")

        risk_profile = getattr(context_pack.risk_profile, "value", context_pack.risk_profile)
        sections.append(f"## Risk Level\n{risk_profile}")

        return "\n\n".join(sections)

    @staticmethod
    def to_run_context(
        work_item_id: str,
        plan_id: str,
        workspace_path: str,
        event_bus: Any = None,
    ) -> AgentRunContext:
        return AgentRunContext(
            work_item_id=work_item_id,
            plan_id=plan_id,
            workspace_path=workspace_path,
            event_bus=event_bus,
        )

    @staticmethod
    def _format_constraints(constraints: dict[str, Any]) -> list[str]:
        lines: list[str] = []

        allowed_paths = ContextBridge._coerce_string_list(constraints.get("allowedPaths"))
        if allowed_paths:
            lines.append(f"Allowed paths: {', '.join(allowed_paths)}")

        forbidden_paths = ContextBridge._coerce_string_list(constraints.get("forbiddenPaths"))
        if forbidden_paths:
            lines.append(f"Forbidden paths (do not modify): {', '.join(forbidden_paths)}")

        must_touch = ContextBridge._coerce_string_list(constraints.get("mustTouch"))
        if must_touch:
            lines.append(f"Must touch: {', '.join(must_touch)}")

        return lines

    @staticmethod
    def _format_bullets(values: tuple[str, ...]) -> str:
        if not values:
            return ""
        return "\n".join(f"- {value}" for value in values)

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple)):
            return []
        return [str(item) for item in value if str(item).strip()]
