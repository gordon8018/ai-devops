from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import InvalidPlan
from .plan_schema import Plan


def _coerce_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _default_definition_of_done(task_input: Mapping[str, Any]) -> list[str]:
    constraints = task_input.get("constraints")
    dod: list[str] = [
        "Implement the requested change or investigation end-to-end.",
        "Preserve unrelated behavior and formatting.",
        "Run the most relevant local validation available before finishing.",
    ]
    if isinstance(constraints, dict):
        explicit = constraints.get("definitionOfDone")
        if isinstance(explicit, list):
            dod.extend(str(item).strip() for item in explicit if str(item).strip())
    return dod


def _default_prompt(
    *,
    repo: str,
    title: str,
    objective: str,
    constraints: Mapping[str, Any],
    definition_of_done: list[str],
    files_hint: list[str],
) -> str:
    lines = [
        "You are Zoe acting as the planning agent for this repository.",
        "",
        f"REPOSITORY: {repo}",
        f"TASK TITLE: {title}",
        "",
        "OBJECTIVE:",
        objective,
        "",
        "DEFINITION OF DONE:",
    ]
    lines.extend(f"- {item}" for item in definition_of_done)
    lines.extend(
        [
            "",
            "BOUNDARIES:",
            "- Do not access or print secrets, environment variables, or credentials.",
            "- Do not make unrelated refactors.",
            "- Prefer minimal, reversible changes.",
        ]
    )
    if constraints:
        lines.append("- Respect the explicit constraints attached to this task.")
    if files_hint:
        lines.extend(["", "FILES TO CHECK FIRST:"])
        lines.extend(f"- {item}" for item in files_hint)
    lines.extend(
        [
            "",
            "FIRST STEP:",
            "- Inspect the relevant files, write a short plan, then execute it.",
        ]
    )
    return "\n".join(lines)


@dataclass(slots=True)
class ZoePlannerEngine:
    """
    Internal planning engine for Zoe.

    Zoe itself is the planning agent, so plan generation lives inside the
    orchestrator instead of calling an external planner service.
    """

    def plan(self, task_input: Mapping[str, Any]) -> Plan:
        repo = _coerce_text(task_input.get("repo"))
        title = _coerce_text(task_input.get("title"))
        objective = _coerce_text(task_input.get("objective") or task_input.get("description"))
        requested_by = _coerce_text(task_input.get("requestedBy"))
        version = _coerce_text(task_input.get("version"))
        plan_id = _coerce_text(task_input.get("planId"))

        if not repo or not title or not objective or not requested_by or not version or not plan_id:
            raise InvalidPlan("Planner request is missing required fields")

        requested_at = task_input.get("requestedAt")
        if not isinstance(requested_at, int):
            raise InvalidPlan("Planner request requestedAt must be an integer")

        routing = task_input.get("routing") if isinstance(task_input.get("routing"), dict) else {}
        constraints = task_input.get("constraints") if isinstance(task_input.get("constraints"), dict) else {}
        context = task_input.get("context") if isinstance(task_input.get("context"), dict) else {}
        files_hint = context.get("filesHint")
        if not isinstance(files_hint, list):
            files_hint = []
        files_hint = [str(item).strip() for item in files_hint if str(item).strip()]

        definition_of_done = _default_definition_of_done(task_input)
        subtask = {
            "id": "S1",
            "title": title,
            "description": objective,
            "agent": _coerce_text(routing.get("agent") or "codex"),
            "model": _coerce_text(routing.get("model") or "gpt-5.3-codex"),
            "effort": _coerce_text(routing.get("effort") or "medium"),
            "worktreeStrategy": "isolated",
            "dependsOn": [],
            "filesHint": files_hint,
            "prompt": _default_prompt(
                repo=repo,
                title=title,
                objective=objective,
                constraints=constraints,
                definition_of_done=definition_of_done,
                files_hint=files_hint,
            ),
            "definitionOfDone": definition_of_done,
        }

        payload = {
            "planId": plan_id,
            "repo": repo,
            "title": title,
            "requestedBy": requested_by,
            "requestedAt": requested_at,
            "objective": objective,
            "constraints": constraints,
            "context": context,
            "routing": routing,
            "version": version,
            "subtasks": [subtask],
        }
        return Plan.from_dict(payload)
