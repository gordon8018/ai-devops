from __future__ import annotations

from dataclasses import dataclass
import json
import time
from pathlib import Path
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class PreparedWorkspace:
    repo_root: Path
    worktree: Path
    prompt_file: Path
    task_spec_file: Path | None
    scope_manifest_file: Path | None
    sparse_checkout_applied: bool


@dataclass(slots=True, frozen=True)
class LaunchResult:
    execution_mode: str
    tmux_session: str | None
    process_id: int | None


class QueueConsumer:
    def __init__(self, queue_dir: Path) -> None:
        self.queue_dir = queue_dir

    def list_queue_files(self) -> list[Path]:
        return sorted(self.queue_dir.glob("*.json"))

    def load_task(self, queue_file: Path) -> dict[str, Any]:
        payload = json.loads(queue_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"Invalid queue payload: {queue_file}")
        return payload


class WorkspaceManager:
    def __init__(
        self,
        *,
        ensure_repo_fn: Callable[[str], Path],
        create_worktree_fn: Callable[[Path, str], Path],
        write_scope_manifest_fn: Callable[[Path, Path, dict], Path],
        apply_sparse_checkout_fn: Callable[[Path, Path, dict], bool],
    ) -> None:
        self._ensure_repo = ensure_repo_fn
        self._create_worktree = create_worktree_fn
        self._write_scope_manifest = write_scope_manifest_fn
        self._apply_sparse_checkout = apply_sparse_checkout_fn

    def prepare_workspace(self, task: dict[str, Any], *, branch: str) -> PreparedWorkspace:
        repo_root = self._ensure_repo(task["repo"])
        worktree = self._create_worktree(repo_root, branch)

        prompt_file = worktree / "prompt.txt"
        prompt_file.write_text(str(task.get("prompt") or ""), encoding="utf-8")

        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        task_spec_payload = metadata.get("taskSpec") if isinstance(metadata.get("taskSpec"), dict) else None
        task_spec_file: Path | None = None
        scope_manifest_file: Path | None = None
        sparse_checkout_applied = False
        if task_spec_payload is not None:
            task_spec_file = worktree / "task-spec.json"
            task_spec_file.write_text(json.dumps(task_spec_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            scope_manifest_file = self._write_scope_manifest(worktree, repo_root, task_spec_payload)
            sparse_checkout_applied = self._apply_sparse_checkout(repo_root, worktree, task_spec_payload)

        return PreparedWorkspace(
            repo_root=repo_root,
            worktree=worktree,
            prompt_file=prompt_file,
            task_spec_file=task_spec_file,
            scope_manifest_file=scope_manifest_file,
            sparse_checkout_applied=sparse_checkout_applied,
        )


class AgentLauncher:
    def __init__(
        self,
        *,
        runner_for_agent_fn: Callable[[str], Path],
        launch_process_fn: Callable[[Path, dict[str, Any], Path, Path, Path | None], tuple[str, str | None, int | None]],
    ) -> None:
        self._runner_for_agent = runner_for_agent_fn
        self._launch_process = launch_process_fn

    def launch(
        self,
        task: dict[str, Any],
        *,
        worktree: Path,
        prompt_file: Path,
        task_spec_file: Path | None,
    ) -> LaunchResult:
        agent = str(task.get("agent", "codex"))
        runner = self._runner_for_agent(agent)
        execution_mode, tmux_session, process_id = self._launch_process(
            runner,
            task,
            worktree,
            prompt_file,
            task_spec_file,
        )
        return LaunchResult(
            execution_mode=execution_mode,
            tmux_session=tmux_session,
            process_id=process_id,
        )


class RunStateRecorder:
    def __init__(self, *, now_ms_fn: Callable[[], int] | None = None) -> None:
        self._now_ms = now_ms_fn or (lambda: int(time.time() * 1000))

    def build_running_task_record(
        self,
        *,
        task: dict[str, Any],
        branch: str,
        worktree: Path,
        execution_mode: str,
        tmux_session: str | None,
        process_id: int | None,
        prompt_file: Path,
        task_spec_file: Path | None,
        scope_manifest_file: Path | None,
        sparse_checkout_applied: bool,
        agent: str,
        model: str,
        effort: str,
    ) -> dict[str, Any]:
        metadata = task.get("metadata", {}) if isinstance(task.get("metadata"), dict) else {}
        return {
            "id": task["id"],
            "repo": task["repo"],
            "title": task.get("title", ""),
            "branch": branch,
            "worktree": str(worktree),
            "tmuxSession": tmux_session,
            "processId": process_id,
            "executionMode": execution_mode,
            "agent": agent,
            "model": model,
            "effort": effort,
            "status": "running",
            "startedAt": self._now_ms(),
            "notifyOnComplete": True,
            "metadata": metadata,
            "planId": metadata.get("planId"),
            "subtaskId": metadata.get("subtaskId"),
            "worktreeStrategy": metadata.get("worktreeStrategy"),
            "promptSource": "task.prompt" if task.get("prompt") else "prompt_compiler",
            "attempts": 0,
            "maxAttempts": int(task.get("maxAttempts", 3)),
            "promptFile": str(prompt_file),
            "taskSpecFile": str(task_spec_file) if task_spec_file else None,
            "scopeManifestFile": str(scope_manifest_file) if scope_manifest_file else None,
            "sparseCheckoutApplied": sparse_checkout_applied,
            "lastFailure": None,
            "pr": None,
            "prUrl": None,
            "completedAt": None,
            "note": None,
        }
