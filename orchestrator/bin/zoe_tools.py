from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dispatch import archive_subtasks, default_base_dir, dispatch_plan_file, plan_dir, registry_file, tasks_dir
from .errors import InvalidPlan, PlannerError, PolicyViolation
from .planner_engine import ZoePlannerEngine
from .plan_schema import Plan, sanitize_identifier

SCHEMA_VERSION = "1.0"
RISK_PATTERNS = {
    "secret_exfiltration": re.compile(
        r"(exfiltrate|dump|print|show|cat).{0,40}(secret|token|env|environment|ssh|credential)",
        re.IGNORECASE,
    ),
    "dangerous_command": re.compile(
        r"(rm\s+-rf|chmod\s+777|curl.+\|\s*sh|wget.+\|\s*sh)",
        re.IGNORECASE,
    ),
}


@dataclass(slots=True, frozen=True)
class PlanTaskResult:
    plan: Plan
    plan_path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "planFile": str(self.plan_path),
        }


@dataclass(slots=True, frozen=True)
class DispatchPlanResult:
    plan_file: Path
    queued_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "planFile": str(self.plan_file),
            "queued": [str(path) for path in self.queued_paths],
            "queuedCount": len(self.queued_paths),
        }


@dataclass(slots=True, frozen=True)
class PlanAndDispatchResult:
    plan: Plan
    plan_path: Path
    queued_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "planFile": str(self.plan_path),
            "queued": [str(path) for path in self.queued_paths],
            "queuedCount": len(self.queued_paths),
        }


def generate_plan_id(repo: str, title: str, requested_at_ms: int) -> str:
    timestamp = str(requested_at_ms)
    repo_part = sanitize_identifier(repo.replace("/", "-"))
    slug = sanitize_identifier(title.lower())[:48]
    return sanitize_identifier(f"{timestamp}-{repo_part}-{slug}")


def detect_risk_flags(objective: str) -> list[str]:
    return [name for name, pattern in RISK_PATTERNS.items() if pattern.search(objective)]


def validate_task_policy(task_input: dict[str, Any]) -> list[str]:
    objective = str(task_input.get("objective") or task_input.get("description") or "")
    flags = detect_risk_flags(objective)
    if flags:
        raise PolicyViolation(f"Task blocked by planner policy: {', '.join(flags)}")
    return flags


def build_plan_request(task_input: dict[str, Any]) -> dict[str, Any]:
    requested_at = int(task_input.get("requested_at") or task_input.get("requestedAt") or 0)
    if requested_at <= 0:
        requested_at = int(time.time() * 1000)

    requested_by = str(task_input.get("requested_by") or task_input.get("requestedBy") or "unknown")
    repo = str(task_input.get("repo") or "").strip()
    title = str(task_input.get("title") or "").strip()
    objective = str(task_input.get("objective") or task_input.get("description") or "").strip()
    if not repo or not title or not objective:
        raise InvalidPlan("Task input must include repo, title, and description/objective")

    plan_id = str(task_input.get("planId") or generate_plan_id(repo, title, requested_at))
    routing = {
        "agent": str(task_input.get("agent") or "codex").strip(),
        "model": str(task_input.get("model") or "gpt-5.3-codex").strip(),
        "effort": str(task_input.get("effort") or "medium").strip(),
    }
    constraints = dict(task_input.get("constraints") or {})
    constraints.setdefault(
        "systemPolicy",
        {
            "secretsAccess": "forbidden",
            "dangerousCommands": "forbidden",
            "networkUsage": "explicitly justify before use",
        },
    )

    risk_flags = validate_task_policy({"objective": objective})
    context = dict(task_input.get("context") or {})
    context.setdefault("riskFlags", risk_flags)

    return {
        "planId": plan_id,
        "repo": repo,
        "title": title,
        "requestedBy": requested_by,
        "requestedAt": requested_at,
        "objective": objective,
        "constraints": constraints,
        "context": context,
        "routing": routing,
        "version": SCHEMA_VERSION,
        "systemCapabilities": {
            "agents": [
                {"name": "codex", "models": ["gpt-5.3-codex"]},
                {"name": "claude", "models": ["claude-sonnet-4"]},
            ],
            "worktreeStrategies": ["shared", "isolated"],
        },
        "includeFailureContext": bool(task_input.get("includeFailureContext", False)),
    }


def save_plan(plan: Plan, *, base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    target_dir = plan_dir(plan, root)
    target_dir.mkdir(parents=True, exist_ok=True)
    plan_path = target_dir / "plan.json"
    plan.write_json(plan_path)
    archive_subtasks(plan, root)
    return plan_path


def plan_task(
    task_input: dict[str, Any],
    *,
    engine: ZoePlannerEngine | None = None,
    base_dir: Path | None = None,
) -> PlanTaskResult:
    planner = engine or ZoePlannerEngine()
    request_payload = build_plan_request(task_input)
    plan = planner.plan(request_payload)
    plan_path = save_plan(plan, base_dir=base_dir)
    return PlanTaskResult(plan=plan, plan_path=plan_path)


def dispatch_plan(
    plan_file: Path,
    *,
    base_dir: Path | None = None,
    watch: bool = False,
    poll_interval_sec: float = 5.0,
) -> DispatchPlanResult:
    queued = dispatch_plan_file(
        plan_file,
        base_dir=base_dir,
        watch=watch,
        poll_interval_sec=poll_interval_sec,
    )
    return DispatchPlanResult(plan_file=plan_file, queued_paths=tuple(queued))


def plan_and_dispatch_task(
    task_input: dict[str, Any],
    *,
    engine: ZoePlannerEngine | None = None,
    base_dir: Path | None = None,
    watch: bool = False,
    poll_interval_sec: float = 5.0,
) -> PlanAndDispatchResult:
    plan_result = plan_task(task_input, engine=engine, base_dir=base_dir)
    dispatch_result = dispatch_plan(
        plan_result.plan_path,
        base_dir=base_dir,
        watch=watch,
        poll_interval_sec=poll_interval_sec,
    )
    return PlanAndDispatchResult(
        plan=plan_result.plan,
        plan_path=plan_result.plan_path,
        queued_paths=dispatch_result.queued_paths,
    )


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidPlan(f"Task file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InvalidPlan(f"Task file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise InvalidPlan("Task file must contain a JSON object")
    return payload


def _load_registry(base_dir: Path | None = None) -> list[dict[str, Any]]:
    path = registry_file(base_dir)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlannerError(f"Registry file is not valid JSON: {path}") from exc
    if not isinstance(payload, list):
        raise PlannerError(f"Registry file must contain a JSON array: {path}")
    return [item for item in payload if isinstance(item, dict)]


def task_status(
    *,
    task_id: str | None = None,
    plan_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    items = _load_registry(base_dir)
    if task_id:
        for item in items:
            if item.get("id") == task_id:
                return {"task": item}
        raise PlannerError(f"Task not found in registry: {task_id}")

    if plan_id:
        matching = [
            item for item in items
            if isinstance(item.get("metadata"), dict)
            and item["metadata"].get("planId") == plan_id
        ]
        return {"planId": plan_id, "tasks": matching}

    return {"tasks": items}


def list_plans(*, base_dir: Path | None = None, limit: int = 10) -> dict[str, Any]:
    root = tasks_dir(base_dir)
    if not root.exists():
        return {"plans": []}

    entries: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        plan_file = path / "plan.json"
        if not plan_file.exists():
            continue
        try:
            payload = json.loads(plan_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        entries.append(
            {
                "planId": payload.get("planId"),
                "repo": payload.get("repo"),
                "title": payload.get("title"),
                "requestedBy": payload.get("requestedBy"),
                "requestedAt": payload.get("requestedAt"),
                "subtaskCount": len(payload.get("subtasks") or []),
                "planFile": str(plan_file),
            }
        )
        if len(entries) >= limit:
            break
    return {"plans": entries}

