from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import time
import subprocess
from typing import Any

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home

try:
    from .db import init_db, get_all_tasks
except ImportError:
    from db import init_db, get_all_tasks

try:
    from .errors import DispatchError
    from .plan_schema import Plan, Subtask, load_plan, sanitize_identifier
except ImportError:
    from errors import DispatchError
    from plan_schema import Plan, Subtask, load_plan, sanitize_identifier


def default_base_dir() -> Path:
    return ai_devops_home()


def _dispatch_queue_dir(base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    return root / "orchestrator" / "queue"


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


def _daemon_running() -> bool:
    proc = subprocess.run(
        ["pgrep", "-f", "orchestrator/bin/zoe-daemon.py"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def _repo_checkout_exists(repo: str, base_dir: Path) -> bool:
    target = base_dir / "repos" / repo
    return (target / ".git").is_dir() or (target / ".git").is_file()


def preflight_dispatch(plan: Plan, base_dir: Path) -> None:
    if not _daemon_running():
        raise DispatchError(
            "Cannot dispatch plan: zoe-daemon.py is not running. "
            "Start the local worker before using plan_and_dispatch_task or dispatch_plan."
        )
    if not _repo_checkout_exists(plan.repo, base_dir):
        raise DispatchError(
            f"Cannot dispatch plan: repo checkout not found at {base_dir / 'repos' / plan.repo}. "
            "Clone or link the repo there first."
        )


def load_dispatch_state(plan: Plan, base_dir: Path | None = None) -> dict[str, Any]:
    state_path = dispatch_state_path(plan, base_dir)
    if not state_path.exists():
        return {"planId": plan.plan_id, "dispatched": {}}
    return json.loads(state_path.read_text(encoding="utf-8"))


def save_dispatch_state(plan: Plan, state: dict[str, Any], base_dir: Path | None = None) -> None:
    state_path = dispatch_state_path(plan, base_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _constraint_path_list(raw: dict[str, Any] | None, *keys: str) -> list[str]:
    if not isinstance(raw, dict):
        return []
    values: list[str] = []
    for key in keys:
        items = raw.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            text = str(item).strip()
            if text:
                values.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _path_matches_constraint(path: str, rule: str, worktree: Path) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    candidate_paths = {normalized}
    try:
        abs_path = (worktree / normalized).resolve()
        candidate_paths.add(str(abs_path).replace("\\", "/"))
    except OSError:
        pass

    normalized_rule = rule.replace("\\", "/").rstrip("/")
    if not normalized_rule:
        return False
    if any(ch in normalized_rule for ch in "*?["):
        patterns = {normalized_rule}
        if normalized_rule.endswith("/**"):
            patterns.add(normalized_rule[:-3])
            patterns.add(normalized_rule[:-3] + "/*")
        return any(any(fnmatch.fnmatch(candidate, pat) for pat in patterns) for candidate in candidate_paths)

    return any(
        candidate == normalized_rule or candidate.startswith(normalized_rule + "/")
        for candidate in candidate_paths
    )


def _build_task_spec(plan: Plan, subtask: Subtask) -> dict[str, Any]:
    constraints = plan.constraints if isinstance(plan.constraints, dict) else {}
    return {
        "repo": plan.repo,
        "planId": plan.plan_id,
        "subtaskId": subtask.id,
        "subtaskTitle": subtask.title,
        "filesHint": list(subtask.files_hint),
        "allowedPaths": _constraint_path_list(constraints, "allowedPaths"),
        "forbiddenPaths": _constraint_path_list(constraints, "forbiddenPaths", "blockedPaths"),
        "mustTouch": _constraint_path_list(constraints, "mustTouch", "requiredTouchedPaths"),
        "definitionOfDone": list(subtask.definition_of_done),
    }


def _validate_subtask_scope(plan: Plan, subtask: Subtask, base_dir: Path) -> None:
    constraints = plan.constraints if isinstance(plan.constraints, dict) else {}
    allowed = _constraint_path_list(constraints, "allowedPaths")
    forbidden = _constraint_path_list(constraints, "forbiddenPaths", "blockedPaths")
    must_touch = _constraint_path_list(constraints, "mustTouch", "requiredTouchedPaths")
    if not (allowed or forbidden or must_touch):
        return

    worktree = base_dir / "repos" / plan.repo
    files_hint = list(subtask.files_hint)
    if not files_hint:
        raise DispatchError(
            f"Cannot dispatch {subtask.id}: scoped task has no filesHint/taskSpec targets."
        )

    outside_allowed = [
        path for path in files_hint
        if allowed and not any(_path_matches_constraint(path, rule, worktree) for rule in allowed)
    ]
    if outside_allowed:
        raise DispatchError(
            f"Cannot dispatch {subtask.id}: filesHint outside allowedPaths: {', '.join(outside_allowed[:5])}"
        )

    forbidden_hits = [
        path for path in files_hint
        if any(_path_matches_constraint(path, rule, worktree) for rule in forbidden)
    ]
    if forbidden_hits:
        raise DispatchError(
            f"Cannot dispatch {subtask.id}: filesHint intersects forbidden paths: {', '.join(forbidden_hits[:5])}"
        )

    if must_touch and not any(
        any(_path_matches_constraint(path, rule, worktree) for rule in must_touch)
        for path in files_hint
    ):
        raise DispatchError(
            f"Cannot dispatch {subtask.id}: filesHint misses required mustTouch paths."
        )


def _validate_plan_id_collision(plan: Plan, base_dir: Path) -> None:
    """防止不同计划复用同一 planId，导致依赖链串扰。"""
    archived_plan_file = plan_dir(plan, base_dir) / "plan.json"
    if not archived_plan_file.exists():
        return
    try:
        archived_payload = json.loads(archived_plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DispatchError(f"Invalid archived plan file: {archived_plan_file}") from exc
    if not isinstance(archived_payload, dict):
        raise DispatchError(f"Invalid archived plan payload: {archived_plan_file}")
    if _canonical_json(archived_payload) != _canonical_json(plan.to_dict()):
        raise DispatchError(
            f"planId collision detected for {plan.plan_id}: "
            f"existing archived plan differs from {plan_dir(plan, base_dir) / 'plan.json'}"
        )


# Statuses that indicate a subtask's execution task has reached a terminal
# success state.  Both "ready" (CI green, PR open) and "merged" (PR merged)
# unblock downstream dependencies.
_COMPLETED_STATUSES: frozenset[str] = frozenset({"ready", "merged"})


def _extract_plan_metadata(raw_meta: Any) -> dict[str, Any]:
    if isinstance(raw_meta, str):
        try:
            parsed = json.loads(raw_meta)
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    if isinstance(raw_meta, dict):
        return raw_meta
    return {}


def ready_subtask_ids(plan: Plan, registry_items: list[dict[str, Any]]) -> set[str]:
    known_subtasks = {subtask.id for subtask in plan.subtasks}
    ready: set[str] = set()
    for item in registry_items:
        metadata = _extract_plan_metadata(item.get("metadata"))
        if metadata.get("planId") != plan.plan_id:
            continue
        subtask_id = metadata.get("subtaskId")
        if not isinstance(subtask_id, str) or subtask_id not in known_subtasks:
            continue
        if item.get("status") in _COMPLETED_STATUSES:
            ready.add(subtask_id)
    return ready


def topologically_sorted_subtask_ids(plan: Plan) -> list[str]:
    return [subtask.id for subtask in plan.topologically_sorted_subtasks()]


def build_execution_task(plan: Plan, subtask: Subtask, planned_by: str = "zoe") -> dict[str, Any]:
    task_spec = _build_task_spec(plan, subtask)
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
            "taskSpec": task_spec,
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
    queue_root = _dispatch_queue_dir(root)
    queue_root.mkdir(parents=True, exist_ok=True)
    if registry_items is None:
        try:
            init_db()
            registry_items = get_all_tasks(limit=1000)
        except Exception:
            registry_items = []
    state = load_dispatch_state(plan, root)
    dispatched = state.setdefault("dispatched", {})
    completed = ready_subtask_ids(plan, registry_items)

    queued_paths: list[Path] = []
    for subtask in plan.topologically_sorted_subtasks():
        if dispatched.get(subtask.id, {}).get("state") == "queued":
            continue
        if not all(dep in completed for dep in subtask.depends_on):
            continue

        _validate_subtask_scope(plan, subtask, root)
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
    root = base_dir or default_base_dir()
    _validate_plan_id_collision(plan, root)
    preflight_dispatch(plan, root)
    archive_subtasks(plan, root)
    if watch:
        return watch_and_dispatch(plan, base_dir=root, poll_interval_sec=poll_interval_sec)
    return dispatch_ready_subtasks(plan, base_dir=root)


def load_plan_for_dispatch(plan_file: Path) -> Plan:
    if not plan_file.exists():
        raise DispatchError(f"Plan file not found: {plan_file}")
    return load_plan(plan_file)
