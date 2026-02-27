from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from .errors import DispatchError
from .plan_schema import Plan, Subtask, load_plan, sanitize_identifier


def default_base_dir() -> Path:
    return Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))


def queue_dir(base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    return root / "orchestrator" / "queue"


def registry_file(base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    return root / ".clawdbot" / "active-tasks.json"


def tasks_dir(base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    return root / "tasks"


def plan_dir(plan: Plan, base_dir: Path | None = None) -> Path:
    return tasks_dir(base_dir) / plan.plan_id


def subtask_archive_path(plan: Plan, subtask: Subtask, base_dir: Path | None = None) -> Path:
    return plan_dir(plan, base_dir) / "subtasks" / f"{subtask.id}.json"


def dispatch_state_path(plan: Plan, base_dir: Path | None = None) -> Path:
    return plan_dir(plan, base_dir) / "dispatch-state.json"


def execution_task_id(plan: Plan, subtask: Subtask) -> str:
    return sanitize_identifier(f"{plan.plan_id}-{subtask.id}")


def load_registry(registry_path: Path) -> list[dict[str, Any]]:
    if not registry_path.exists():
        return []
    return json.loads(registry_path.read_text(encoding="utf-8"))


def load_dispatch_state(plan: Plan, base_dir: Path | None = None) -> dict[str, Any]:
    state_path = dispatch_state_path(plan, base_dir)
    if not state_path.exists():
        return {"planId": plan.plan_id, "dispatched": {}}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_dispatch_state(plan: Plan, state: dict[str, Any], base_dir: Path | None = None) -> None:
    state_path = dispatch_state_path(plan, base_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def ready_subtask_ids(plan: Plan, registry_items: list[dict[str, Any]]) -> set[str]:
    ready: set[str] = set()
    for item in registry_items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if metadata.get("planId") != plan.plan_id:
            continue
        if item.get("status") == "ready" and isinstance(metadata.get("subtaskId"), str):
            ready.add(metadata["subtaskId"])
    return ready


def topologically_sorted_subtask_ids(plan: Plan) -> list[str]:
    return [subtask.id for subtask in plan.topologically_sorted_subtasks()]


def build_execution_task(plan: Plan, subtask: Subtask, planned_by: str = "openclaw") -> dict[str, Any]:
    return {
        "id": execution_task_id(plan, subtask),
        "repo": plan.repo,
        "title": subtask.title,
        "description": subtask.description,
        "agent": subtask.agent,
        "model": subtask.model,
        "effort": subtask.effort,
        "prompt": subtask.prompt,
        "requested_by": plan.requested_by,
        "requested_at": plan.requested_at,
        "metadata": {
            "planId": plan.plan_id,
            "subtaskId": subtask.id,
            "dependsOn": list(subtask.depends_on),
            "worktreeStrategy": subtask.worktree_strategy,
            "filesHint": list(subtask.files_hint),
            "plannedBy": planned_by,
            "definitionOfDone": list(subtask.definition_of_done),
            "planVersion": plan.version,
            "objective": plan.objective,
            "constraints": plan.constraints,
            "context": plan.context,
        },
    }


def archive_subtasks(plan: Plan, base_dir: Path | None = None) -> None:
    for subtask in plan.subtasks:
        archive_path = subtask_archive_path(plan, subtask, base_dir)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        payload = subtask.to_dict()
        payload["planId"] = plan.plan_id
        if archive_path.exists():
            existing = json.loads(archive_path.read_text(encoding="utf-8"))
            payload["dispatch"] = existing.get("dispatch", {})
        else:
            payload["dispatch"] = {"state": "planned", "queuedTaskId": None, "queuedAt": None}
        archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_subtask_archive(
    plan: Plan,
    subtask: Subtask,
    *,
    state: str,
    queued_task_id: str | None,
    queued_at: int | None,
    base_dir: Path | None = None,
) -> None:
    archive_path = subtask_archive_path(plan, subtask, base_dir)
    if archive_path.exists():
        payload = json.loads(archive_path.read_text(encoding="utf-8"))
    else:
        payload = subtask.to_dict()
        payload["planId"] = plan.plan_id
    payload["dispatch"] = {
        "state": state,
        "queuedTaskId": queued_task_id,
        "queuedAt": queued_at,
    }
    archive_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def dispatch_ready_subtasks(
    plan: Plan,
    *,
    base_dir: Path | None = None,
    registry_items: list[dict[str, Any]] | None = None,
) -> list[Path]:
    root = base_dir or default_base_dir()
    queue_root = queue_dir(root)
    queue_root.mkdir(parents=True, exist_ok=True)
    registry_items = registry_items if registry_items is not None else load_registry(registry_file(root))
    state = load_dispatch_state(plan, root)
    dispatched = state.setdefault("dispatched", {})
    completed = ready_subtask_ids(plan, registry_items)

    queued_paths: list[Path] = []
    for subtask in plan.topologically_sorted_subtasks():
        if dispatched.get(subtask.id, {}).get("state") == "queued":
            continue
        if not all(dep in completed for dep in subtask.depends_on):
            continue

        task_payload = build_execution_task(plan, subtask)
        queue_path = queue_root / f"{task_payload['id']}.json"
        queue_path.write_text(json.dumps(task_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        timestamp = int(time.time() * 1000)
        dispatched[subtask.id] = {
            "state": "queued",
            "queuedTaskId": task_payload["id"],
            "queuedAt": timestamp,
        }
        update_subtask_archive(
            plan,
            subtask,
            state="queued",
            queued_task_id=task_payload["id"],
            queued_at=timestamp,
            base_dir=root,
        )
        queued_paths.append(queue_path)

    save_dispatch_state(plan, state, root)
    return queued_paths


def watch_and_dispatch(
    plan: Plan,
    *,
    base_dir: Path | None = None,
    poll_interval_sec: float = 5.0,
    max_loops: int | None = None,
) -> list[Path]:
    root = base_dir or default_base_dir()
    all_queued: list[Path] = []
    loops = 0
    while True:
        all_queued.extend(dispatch_ready_subtasks(plan, base_dir=root))
        state = load_dispatch_state(plan, root)
        dispatched = state.get("dispatched", {})
        if len(dispatched) == len(plan.subtasks):
            return all_queued
        loops += 1
        if max_loops is not None and loops >= max_loops:
            return all_queued
        time.sleep(poll_interval_sec)


def dispatch_plan_file(
    plan_file: Path,
    *,
    base_dir: Path | None = None,
    watch: bool = False,
    poll_interval_sec: float = 5.0,
) -> list[Path]:
    plan = load_plan(plan_file)
    archive_subtasks(plan, base_dir)
    if watch:
        return watch_and_dispatch(plan, base_dir=base_dir, poll_interval_sec=poll_interval_sec)
    return dispatch_ready_subtasks(plan, base_dir=base_dir)


def load_plan_for_dispatch(plan_file: Path) -> Plan:
    if not plan_file.exists():
        raise DispatchError(f"Plan file not found: {plan_file}")
    return load_plan(plan_file)
