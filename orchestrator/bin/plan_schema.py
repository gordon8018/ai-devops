from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any

from .errors import InvalidPlan

ALLOWED_AGENTS = {"codex", "claude"}
ALLOWED_EFFORTS = {"low", "medium", "high"}
ALLOWED_WORKTREE_STRATEGIES = {"shared", "isolated"}
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PROMPT_MAX_CHARS = 20_000


def sanitize_identifier(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-_")
    return sanitized or "task"


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidPlan(f"Missing or invalid string field: {key}")
    return value.strip()


def _optional_string(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InvalidPlan(f"Invalid string field: {key}")
    return value.strip()


def _optional_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InvalidPlan(f"Invalid object field: {key}")
    return value


def _optional_string_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise InvalidPlan(f"Invalid string array field: {key}")
    return tuple(item.strip() for item in value)


@dataclass(slots=True, frozen=True)
class RoutingDefaults:
    agent: str | None = None
    model: str | None = None
    effort: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoutingDefaults":
        agent = _optional_string(data, "agent")
        model = _optional_string(data, "model")
        effort = _optional_string(data, "effort")
        if agent and agent not in ALLOWED_AGENTS:
            raise InvalidPlan(f"Unsupported routing.agent: {agent}")
        if effort and effort not in ALLOWED_EFFORTS:
            raise InvalidPlan(f"Unsupported routing.effort: {effort}")
        return cls(agent=agent, model=model, effort=effort)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.agent:
            payload["agent"] = self.agent
        if self.model:
            payload["model"] = self.model
        if self.effort:
            payload["effort"] = self.effort
        return payload


@dataclass(slots=True, frozen=True)
class Subtask:
    id: str
    title: str
    description: str
    agent: str
    model: str
    effort: str
    worktree_strategy: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    files_hint: tuple[str, ...] = field(default_factory=tuple)
    prompt: str = ""
    definition_of_done: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, data: dict[str, Any], routing: RoutingDefaults) -> "Subtask":
        subtask_id = _require_string(data, "id")
        if not IDENTIFIER_RE.match(subtask_id):
            raise InvalidPlan(f"Invalid subtask id: {subtask_id}")

        agent = _optional_string(data, "agent") or routing.agent
        model = _optional_string(data, "model") or routing.model
        effort = _optional_string(data, "effort") or routing.effort

        if not agent or agent not in ALLOWED_AGENTS:
            raise InvalidPlan(f"Invalid or missing agent for subtask {subtask_id}")
        if not model:
            raise InvalidPlan(f"Missing model for subtask {subtask_id}")
        if not effort or effort not in ALLOWED_EFFORTS:
            raise InvalidPlan(f"Invalid or missing effort for subtask {subtask_id}")

        worktree_strategy = _require_string(data, "worktreeStrategy")
        if worktree_strategy not in ALLOWED_WORKTREE_STRATEGIES:
            raise InvalidPlan(
                f"Invalid worktreeStrategy for subtask {subtask_id}: {worktree_strategy}"
            )

        prompt = _require_string(data, "prompt")
        if len(prompt) > PROMPT_MAX_CHARS:
            raise InvalidPlan(
                f"Prompt too long for subtask {subtask_id}: {len(prompt)} > {PROMPT_MAX_CHARS}"
            )

        depends_on = _optional_string_list(data, "dependsOn")
        files_hint = _optional_string_list(data, "filesHint")
        definition_of_done = _optional_string_list(data, "definitionOfDone")

        return cls(
            id=subtask_id,
            title=_require_string(data, "title"),
            description=_require_string(data, "description"),
            agent=agent,
            model=model,
            effort=effort,
            worktree_strategy=worktree_strategy,
            depends_on=depends_on,
            files_hint=files_hint,
            prompt=prompt,
            definition_of_done=definition_of_done,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "agent": self.agent,
            "model": self.model,
            "effort": self.effort,
            "worktreeStrategy": self.worktree_strategy,
            "dependsOn": list(self.depends_on),
            "filesHint": list(self.files_hint),
            "prompt": self.prompt,
            "definitionOfDone": list(self.definition_of_done),
        }


@dataclass(slots=True, frozen=True)
class Plan:
    plan_id: str
    repo: str
    title: str
    requested_by: str
    requested_at: int
    objective: str
    constraints: dict[str, Any]
    context: dict[str, Any]
    subtasks: tuple[Subtask, ...]
    routing: RoutingDefaults
    version: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        if not isinstance(data, dict):
            raise InvalidPlan("Plan payload must be an object")

        plan_id = _require_string(data, "planId")
        if not IDENTIFIER_RE.match(plan_id):
            raise InvalidPlan(f"Invalid planId: {plan_id}")

        requested_at = data.get("requestedAt")
        if not isinstance(requested_at, int):
            raise InvalidPlan("requestedAt must be an integer in milliseconds")

        routing = RoutingDefaults.from_dict(_optional_dict(data, "routing"))

        raw_subtasks = data.get("subtasks")
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            raise InvalidPlan("subtasks must be a non-empty array")

        subtasks = tuple(
            Subtask.from_dict(item, routing)
            for item in raw_subtasks
            if isinstance(item, dict)
        )
        if len(subtasks) != len(raw_subtasks):
            raise InvalidPlan("Each subtask must be an object")

        cls._validate_dependencies(subtasks)

        return cls(
            plan_id=plan_id,
            repo=_require_string(data, "repo"),
            title=_require_string(data, "title"),
            requested_by=_require_string(data, "requestedBy"),
            requested_at=requested_at,
            objective=_require_string(data, "objective"),
            constraints=_optional_dict(data, "constraints"),
            context=_optional_dict(data, "context"),
            subtasks=subtasks,
            routing=routing,
            version=_require_string(data, "version"),
        )

    @staticmethod
    def _validate_dependencies(subtasks: tuple[Subtask, ...]) -> None:
        subtask_ids = [subtask.id for subtask in subtasks]
        if len(subtask_ids) != len(set(subtask_ids)):
            raise InvalidPlan("Subtask ids must be unique inside a plan")

        known = set(subtask_ids)
        indegree = {subtask.id: 0 for subtask in subtasks}
        adjacency = {subtask.id: [] for subtask in subtasks}

        for subtask in subtasks:
            for dep in subtask.depends_on:
                if dep not in known:
                    raise InvalidPlan(
                        f"Subtask {subtask.id} depends on unknown subtask {dep}"
                    )
                adjacency[dep].append(subtask.id)
                indegree[subtask.id] += 1

        queue = deque(subtask_id for subtask_id in subtask_ids if indegree[subtask_id] == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for child in adjacency[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if visited != len(subtasks):
            raise InvalidPlan("Subtask dependency graph contains a cycle")

    @property
    def subtasks_by_id(self) -> dict[str, Subtask]:
        return {subtask.id: subtask for subtask in self.subtasks}

    def topologically_sorted_subtasks(self) -> list[Subtask]:
        indegree = {subtask.id: len(subtask.depends_on) for subtask in self.subtasks}
        adjacency = {subtask.id: [] for subtask in self.subtasks}
        original_order = {subtask.id: index for index, subtask in enumerate(self.subtasks)}
        for subtask in self.subtasks:
            for dep in subtask.depends_on:
                adjacency[dep].append(subtask.id)

        ready = [
            subtask.id for subtask in self.subtasks if indegree[subtask.id] == 0
        ]
        ready.sort(key=original_order.get)

        ordered: list[Subtask] = []
        while ready:
            current = ready.pop(0)
            ordered.append(self.subtasks_by_id[current])
            for child in adjacency[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
            ready.sort(key=original_order.get)

        if len(ordered) != len(self.subtasks):
            raise InvalidPlan("Subtask dependency graph contains a cycle")
        return ordered

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "planId": self.plan_id,
            "repo": self.repo,
            "title": self.title,
            "requestedBy": self.requested_by,
            "requestedAt": self.requested_at,
            "objective": self.objective,
            "constraints": self.constraints,
            "context": self.context,
            "subtasks": [subtask.to_dict() for subtask in self.subtasks],
            "version": self.version,
        }
        routing = self.routing.to_dict()
        if routing:
            payload["routing"] = routing
        return payload

    def write_json(self, path: Path) -> None:
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_plan(path: Path) -> Plan:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidPlan(f"Plan file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InvalidPlan(f"Plan file is not valid JSON: {path}") from exc
    return Plan.from_dict(payload)
