from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class HandlerContext:
    task: dict
    update_task: Callable[[str, dict], None]
    notify: Callable[[str], None]
    now_ms: int
    emit_event: Callable[[str, dict], None] | None = None
    updates_sink: list[tuple[str, dict]] = field(default_factory=list)
    notifications_sink: list[str] = field(default_factory=list)
    events_sink: list[tuple[str, dict]] = field(default_factory=list)

    def apply_update(self, payload: dict) -> None:
        task_id = self.task.get("id")
        self.update_task(task_id, payload)
        self.updates_sink.append((task_id, payload))
        self.task.update(payload)

    def send_notification(self, message: str) -> None:
        self.notify(message)
        self.notifications_sink.append(message)

    def publish(self, event_type: str, payload: dict) -> None:
        if self.emit_event is not None:
            self.emit_event(event_type, payload)
        self.events_sink.append((event_type, payload))


class TimeoutHandler:
    def __init__(self, *, timeout_minutes_fn: Callable[[dict], int | None]) -> None:
        self._timeout_minutes = timeout_minutes_fn

    def handle(self, context: HandlerContext) -> bool:
        task = context.task
        started_at = task.get("started_at") or task.get("startedAt")
        last_activity = task.get("last_activity_at") or task.get("lastActivityAt")
        timeout_minutes = self._timeout_minutes(task)
        if not started_at or not timeout_minutes:
            return False
        activity_time = last_activity or started_at
        elapsed_minutes = (context.now_ms - activity_time) / 60000
        if elapsed_minutes <= timeout_minutes:
            return False
        context.apply_update(
            {
                "status": "timeout",
                "completed_at": context.now_ms,
                "note": f"Task exceeded timeout of {timeout_minutes} minutes (elapsed: {int(elapsed_minutes)} min)",
            }
        )
        context.publish("task_status", {"task_id": task.get("id"), "status": "timeout"})
        return True


class StaleTaskHandler:
    def __init__(self, *, check_stale_fn: Callable[[str, int], bool]) -> None:
        self._check_stale = check_stale_fn

    def handle(self, context: HandlerContext) -> bool:
        task_id = context.task.get("id")
        if not task_id:
            return False
        if not self._check_stale(task_id, 30):
            return False
        context.apply_update({"status": "log_stale", "note": "Task stale: no heartbeat for >30 minutes"})
        context.publish("task_status", {"task_id": task_id, "status": "log_stale"})
        return True


class AgentDeathHandler:
    def __init__(
        self,
        *,
        process_alive_fn: Callable[[int | None], bool],
        tmux_alive_fn: Callable[[str | None], bool],
    ) -> None:
        self._process_alive = process_alive_fn
        self._tmux_alive = tmux_alive_fn

    def handle(self, context: HandlerContext) -> bool:
        task = context.task
        if task.get("status") != "running":
            return False
        execution_mode = task.get("executionMode") or task.get("execution_mode", "tmux")
        session = task.get("tmuxSession") or task.get("tmux_session")
        process_id = task.get("processId") or task.get("process_id")
        alive = self._process_alive(process_id) if execution_mode == "process" else bool(session) and self._tmux_alive(session)
        if alive:
            return False
        note = "background process not found" if execution_mode == "process" else "tmux session not found"
        context.apply_update({"status": "agent_dead", "note": note})
        context.publish("task_status", {"task_id": task.get("id"), "status": "agent_dead"})
        return True


class PRCreatedHandler:
    def __init__(self, *, review_pr_fn: Callable[[str, int, Path], None]) -> None:
        self._review_pr = review_pr_fn

    def handle(self, context: HandlerContext, pr: dict) -> bool:
        task = context.task
        if not pr or task.get("status") != "running":
            return False
        pr_number = pr.get("number")
        pr_url = pr.get("url")
        context.apply_update({"status": "pr_created", "pr_number": pr_number, "pr_url": pr_url})
        context.publish("task_status", {"task_id": task.get("id"), "status": "pr_created", "pr_number": pr_number})
        if pr_number and task.get("worktree"):
            self._review_pr(task["id"], pr_number, Path(task["worktree"]))
        return True


class ReadyStateHandler:
    def __init__(self, *, save_success_pattern_fn: Callable[..., None]) -> None:
        self._save_success_pattern = save_success_pattern_fn

    def handle(self, context: HandlerContext, *, notified_ready: set[str], worktree: Path) -> bool:
        task = context.task
        task_id = task.get("id")
        if not task_id or task_id in notified_ready:
            return False
        context.apply_update(
            {
                "status": "ready",
                "completed_at": context.now_ms,
                "note": "checks passed and mergeable clean",
            }
        )
        context.publish("task_status", {"task_id": task_id, "status": "ready"})
        self._save_success_pattern(
            repo=task.get("repo", ""),
            task_id=task_id,
            title=task.get("title", task_id),
            worktree=worktree,
            attempts=int(task.get("attempts", 0)),
        )
        notified_ready.add(task_id)
        return True


class RetryHandler:
    def __init__(
        self,
        *,
        write_failure_log_fn: Callable[[str, str, str, str], None],
        latest_run_failure_fn: Callable[[Path, str], str | None],
        build_retry_prompt_fn: Callable[[dict, int, str, str], Path],
        restart_agent_fn: Callable[[dict, Path, str], None],
    ) -> None:
        self._write_failure_log = write_failure_log_fn
        self._latest_run_failure = latest_run_failure_fn
        self._build_retry_prompt = build_retry_prompt_fn
        self._restart_agent = restart_agent_fn

    def handle(self, context: HandlerContext, *, fail_summary: str) -> bool:
        task = context.task
        task_id = task.get("id")
        worktree = Path(task.get("worktree", ""))
        branch = str(task.get("branch", ""))
        attempts = int(task.get("attempts", 0))
        max_attempts = int(task.get("maxAttempts") or task.get("max_attempts", 3))
        if not task_id or not fail_summary:
            return False
        if attempts >= max_attempts:
            context.apply_update({"status": "blocked", "note": "max retries reached"})
            context.publish("task_status", {"task_id": task_id, "status": "blocked"})
            return True

        retry_n = attempts + 1
        ci_detail = self._latest_run_failure(worktree, branch) or ""
        self._write_failure_log(task.get("repo", ""), task_id, fail_summary, ci_detail)
        retry_prompt_path = self._build_retry_prompt(task, retry_n, fail_summary, ci_detail)
        self._restart_agent(task, worktree, retry_prompt_path.name)
        context.apply_update({"attempts": retry_n, "status": "running", "note": f"retry #{retry_n} triggered"})
        context.publish("task_status", {"task_id": task_id, "status": "running", "attempts": retry_n})
        return True
