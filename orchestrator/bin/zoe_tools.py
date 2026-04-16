from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packages.shared.domain.models import AuditEvent
from packages.shared.domain.runtime_state import record_audit_event

from .db import get_task, merge_task_metadata, update_task
from .dispatch import archive_subtasks, default_base_dir, dispatch_plan_file, plan_dir, tasks_dir
from .errors import InvalidPlan, PlannerError, PolicyViolation
from .monitor_helpers import restart_agent as _restart_agent
from .planner_engine import ZoePlannerEngine
from .plan_schema import Plan, sanitize_identifier
from .task_spec import (
    TaskSpecError,
    load_task_spec_file,
    scoped_task_requires_task_spec,
    task_spec_to_task_input,
    validate_task_spec,
)

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


def _load_success_patterns(repo: str, *, base_dir: Path | None = None) -> list[dict]:
    """Load up to 3 recent success prompt templates for a repo."""
    import re as _re
    root = (base_dir or default_base_dir()) / ".clawdbot" / "prompt-templates" / repo.replace("/", "_")
    if not root.exists():
        return []
    files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    patterns = []
    for f in files:
        try:
            first_line = f.read_text(encoding="utf-8").splitlines()[0]
            attempts_match = _re.search(r"attempts=(\d+)", first_line)
            ts_match = _re.search(r"timestamp=(\d+)", first_line)
            patterns.append({
                "title": f.stem,
                "attemptCount": int(attempts_match.group(1)) if attempts_match else 0,
                "timestamp": int(ts_match.group(1)) if ts_match else 0,
            })
        except Exception:
            continue
    return patterns


def _inject_success_patterns(context: dict, *, repo: str, base_dir: Path | None = None) -> None:
    patterns = _load_success_patterns(repo, base_dir=base_dir)
    if patterns:
        context["successPatterns"] = patterns


def build_plan_request(task_input: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    task_input = dict(task_input)

    task_spec_payload = task_input.get("taskSpec")
    task_spec_file = task_input.get("taskSpecFile")
    if task_spec_file:
        try:
            task_spec_payload = load_task_spec_file(str(task_spec_file))
        except TaskSpecError as exc:
            raise InvalidPlan(str(exc)) from exc
    if isinstance(task_spec_payload, dict):
        try:
            validated_spec = validate_task_spec(task_spec_payload)
        except TaskSpecError as exc:
            raise InvalidPlan(str(exc)) from exc
        merged = task_spec_to_task_input(validated_spec)
        task_input = {
            **merged,
            **task_input,
            "repo": merged["repo"],
            "title": merged["title"],
            "description": merged["description"],
            "constraints": {**merged.get("constraints", {}), **dict(task_input.get("constraints") or {})},
            "context": {**merged.get("context", {}), **dict(task_input.get("context") or {})},
            "taskSpec": validated_spec,
        }

    if scoped_task_requires_task_spec(task_input) and not isinstance(task_input.get("taskSpec"), dict):
        raise InvalidPlan(
            "Scoped tasks must provide a valid TASK_SPEC via taskSpec or taskSpecFile. "
            "Do not dispatch allowedPaths/forbiddenPaths/mustTouch as free-form fields alone."
        )

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
    if isinstance(task_input.get("taskSpec"), dict):
        context.setdefault("taskSpec", dict(task_input["taskSpec"]))
    _inject_success_patterns(context, repo=repo, base_dir=base_dir)

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


def build_work_item_session(
    task_input: dict[str, Any],
    *,
    base_dir: Path | None = None,
):
    from packages.kernel.services.work_items import WorkItemService

    service = WorkItemService()
    session = service.create_legacy_session(task_input, base_dir=base_dir)
    record_audit_event(
        AuditEvent(
            audit_event_id=f"ae_{session.work_item.work_item_id}_legacy_build_{int(time.time() * 1000)}",
            entity_type="work_item",
            entity_id=session.work_item.work_item_id,
            action="legacy_entrypoint_used",
            payload={
                "entrypoint": "zoe_tools.build_work_item_session",
                "repo": session.work_item.repo,
                "title": session.work_item.title,
            },
        )
    )
    return session


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
    session = build_work_item_session(task_input, base_dir=base_dir)
    request_payload = session.plan_request
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


def task_status(
    *,
    task_id: str | None = None,
    plan_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    from .db import get_task, get_tasks_by_plan, get_all_tasks

    if task_id:
        item = get_task(task_id)
        if item is None:
            raise PlannerError(f"Task not found in registry: {task_id}")
        return {"task": item}

    if plan_id:
        matching = get_tasks_by_plan(plan_id)
        return {"planId": plan_id, "tasks": matching}

    return {"tasks": get_all_tasks(limit=100)}


def retry_task(
    task_id: str,
    *,
    reason: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Manually trigger a retry for a task.
    Reads the original prompt, appends retry directive, restarts the agent.
    Returns updated task dict.
    """
    task = get_task(task_id)
    if task is None:
        raise PlannerError(f"Task not found: {task_id}")

    valid_statuses = ("blocked", "agent_dead", "agent_failed")
    if task["status"] not in valid_statuses:
        raise PlannerError(
            f"Cannot retry task with status '{task['status']}'; "
            f"must be one of: {', '.join(valid_statuses)}"
        )

    attempts = task.get("attempts", 0) or 0
    max_attempts = task.get("max_attempts", 3) or 3
    if attempts >= max_attempts:
        raise PlannerError(
            f"Task has exceeded max attempts ({attempts}/{max_attempts})"
        )

    worktree = Path(task["worktree"])
    original_prompt = (worktree / "prompt.txt").read_text(encoding="utf-8")

    retry_n = attempts + 1
    retry_directive = (
        f"\n\nRERUN DIRECTIVE (Manual Retry #{retry_n}, reason: {reason or 'none'}):\n"
        "Make CI green. Read the failing logs, apply a minimal fix, push to the same branch."
    )
    retry_content = original_prompt + retry_directive
    prompt_filename = f"prompt.retry{retry_n}.txt"
    (worktree / prompt_filename).write_text(retry_content, encoding="utf-8")

    _restart_agent(task, worktree, prompt_filename)

    new_attempts = attempts + 1
    # 将重试上下文以增量方式写入 metadata，避免覆盖 planId/subtaskId。
    merge_task_metadata(
        task_id,
        {
            "lastRetryAt": int(time.time() * 1000),
            "lastRetryReason": reason or "",
        },
    )
    updates = {
        "attempts": new_attempts,
        "status": "running",
        "note": f"retry #{retry_n} triggered (manual)",
    }
    update_task(task_id, updates)

    return {**task, **updates}


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
