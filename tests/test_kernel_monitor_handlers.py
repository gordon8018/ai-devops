from __future__ import annotations

import time

from pathlib import Path

from packages.kernel.monitor.handlers import (
    AgentDeathHandler,
    HandlerContext,
    PRCreatedHandler,
    ReadyStateHandler,
    RetryHandler,
    StaleTaskHandler,
    TimeoutHandler,
)


def make_context(task: dict) -> HandlerContext:
    updates: list[tuple[str, dict]] = []
    notifications: list[str] = []
    events: list[tuple[str, dict]] = []
    return HandlerContext(
        task=task,
        update_task=lambda task_id, payload: updates.append((task_id, payload)),
        notify=lambda message: notifications.append(message),
        emit_event=lambda event_type, payload: events.append((event_type, payload)),
        now_ms=int(time.time() * 1000),
        updates_sink=updates,
        notifications_sink=notifications,
        events_sink=events,
    )


def test_timeout_handler_marks_task_timeout() -> None:
    started_at = int(time.time() * 1000) - 31 * 60 * 1000
    context = make_context(
        {
            "id": "task-timeout",
            "title": "Long running task",
            "repo": "acme/platform",
            "startedAt": started_at,
        }
    )

    handled = TimeoutHandler(timeout_minutes_fn=lambda task: 30).handle(context)

    assert handled is True
    assert context.updates_sink[-1][1]["status"] == "timeout"


def test_stale_handler_marks_task_log_stale() -> None:
    context = make_context(
        {
            "id": "task-stale",
            "title": "Stale task",
            "repo": "acme/platform",
        }
    )

    handled = StaleTaskHandler(check_stale_fn=lambda task_id, threshold_minutes: True).handle(context)

    assert handled is True
    assert context.updates_sink[-1][1]["status"] == "log_stale"


def test_agent_death_handler_marks_missing_runtime_as_dead() -> None:
    context = make_context(
        {
            "id": "task-dead",
            "status": "running",
            "executionMode": "process",
            "processId": 4321,
        }
    )

    handled = AgentDeathHandler(
        process_alive_fn=lambda pid: False,
        tmux_alive_fn=lambda session: False,
    ).handle(context)

    assert handled is True
    assert context.updates_sink[-1][1]["status"] == "agent_dead"


def test_pr_created_handler_updates_task_and_emits_event() -> None:
    reviewed: list[tuple[str, int, Path]] = []
    worktree = Path("/tmp/worktree")
    context = make_context(
        {
            "id": "task-pr",
            "status": "running",
            "worktree": str(worktree),
        }
    )
    pr = {"number": 42, "url": "https://example/pr/42"}

    handled = PRCreatedHandler(
        review_pr_fn=lambda task_id, pr_number, repo_dir: reviewed.append((task_id, pr_number, repo_dir))
    ).handle(context, pr)

    assert handled is True
    assert context.updates_sink[-1][1]["status"] == "pr_created"
    assert context.events_sink[-1][0] == "task_status"
    assert reviewed == [("task-pr", 42, worktree)]


def test_ready_state_handler_marks_ready_and_emits_event() -> None:
    saved: list[tuple[str, str, str, Path, int]] = []
    context = make_context(
        {
            "id": "task-ready",
            "repo": "acme/platform",
            "title": "Ready task",
            "prUrl": "https://example/pr/1",
        }
    )
    notified_ready: set[str] = set()

    handled = ReadyStateHandler(
        save_success_pattern_fn=lambda **kwargs: saved.append(
            (kwargs["repo"], kwargs["task_id"], kwargs["title"], kwargs["worktree"], kwargs["attempts"])
        )
    ).handle(
        context,
        notified_ready=notified_ready,
        worktree=Path("/tmp/worktree"),
    )

    assert handled is True
    assert context.updates_sink[-1][1]["status"] == "ready"
    assert context.events_sink[-1][0] == "task_status"
    assert "task-ready" in notified_ready
    assert saved[0][1] == "task-ready"


def test_retry_handler_restarts_agent_and_emits_event() -> None:
    writes: list[tuple[str, str, str]] = []
    restarts: list[tuple[str, Path, str]] = []
    context = make_context(
        {
            "id": "task-retry",
            "repo": "acme/platform",
            "title": "Retry task",
            "branch": "feat/retry",
            "worktree": "/tmp/worktree",
            "attempts": 0,
            "maxAttempts": 3,
            "prUrl": "https://example/pr/2",
        }
    )

    handled = RetryHandler(
        write_failure_log_fn=lambda repo, task_id, fail_summary, ci_detail: writes.append((repo, task_id, fail_summary)),
        latest_run_failure_fn=lambda worktree, branch: "ci detail",
        build_retry_prompt_fn=lambda task, retry_n, fail_summary, ci_detail: Path("/tmp/worktree/prompt.retry1.txt"),
        restart_agent_fn=lambda task, worktree, prompt_filename: restarts.append((task["id"], worktree, prompt_filename)),
    ).handle(context, fail_summary="tests:FAILURE")

    assert handled is True
    assert context.task["attempts"] == 1
    assert context.updates_sink[-1][1]["status"] == "running"
    assert context.events_sink[-1][0] == "task_status"
    assert writes == [("acme/platform", "task-retry", "tests:FAILURE")]
    assert restarts == [("task-retry", Path("/tmp/worktree"), "prompt.retry1.txt")]
