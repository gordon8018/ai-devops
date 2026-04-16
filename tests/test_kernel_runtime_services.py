from __future__ import annotations

import json
from pathlib import Path

from packages.kernel.runtime.services import (
    AgentLauncher,
    QueueConsumer,
    RunStateRecorder,
    WorkspaceManager,
)


def test_queue_consumer_loads_json_task_payload(tmp_path) -> None:
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    task_file = queue_dir / "task-001.json"
    task_file.write_text(json.dumps({"id": "task-001", "repo": "acme/platform"}), encoding="utf-8")

    consumer = QueueConsumer(queue_dir)
    queued = consumer.list_queue_files()
    task = consumer.load_task(queued[0])

    assert queued == [task_file]
    assert task["id"] == "task-001"


def test_workspace_manager_prepares_prompt_and_task_contract_files(tmp_path) -> None:
    repo_root = tmp_path / "repos" / "acme" / "platform"
    repo_root.mkdir(parents=True)
    worktree = tmp_path / "worktrees" / "task-001"
    worktree.mkdir(parents=True)

    manager = WorkspaceManager(
        ensure_repo_fn=lambda repo: repo_root,
        create_worktree_fn=lambda repo, branch: worktree,
        write_scope_manifest_fn=lambda wt, root, spec: wt / ".task-contract" / "scope-manifest.json",
        apply_sparse_checkout_fn=lambda root, wt, spec: True,
    )

    prepared = manager.prepare_workspace(
        {
            "id": "task-001",
            "repo": "acme/platform",
            "prompt": "do the work",
            "metadata": {
                "taskSpec": {
                    "allowedPaths": ["packages/kernel/**"],
                    "mustTouch": ["packages/kernel/runtime/services.py"],
                }
            },
        },
        branch="feat/task-001",
    )

    assert prepared.repo_root == repo_root
    assert prepared.worktree == worktree
    assert prepared.prompt_file.read_text(encoding="utf-8") == "do the work"
    assert prepared.task_spec_file is not None
    assert prepared.sparse_checkout_applied is True


def test_agent_launcher_delegates_to_launch_process_function(tmp_path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    prompt_file = worktree / "prompt.txt"
    prompt_file.write_text("hello", encoding="utf-8")

    launcher = AgentLauncher(
        runner_for_agent_fn=lambda agent: Path(f"/tmp/{agent}-runner.sh"),
        launch_process_fn=lambda runner, task, wt, prompt, task_spec: ("tmux", "agent-task-001", None),
    )

    launched = launcher.launch(
        {
            "id": "task-001",
            "agent": "codex",
            "model": "gpt-5.3-codex",
            "effort": "high",
        },
        worktree=worktree,
        prompt_file=prompt_file,
        task_spec_file=None,
    )

    assert launched.execution_mode == "tmux"
    assert launched.tmux_session == "agent-task-001"
    assert launched.process_id is None


def test_run_state_recorder_builds_running_task_record() -> None:
    recorder = RunStateRecorder(now_ms_fn=lambda: 1710000000000)

    record = recorder.build_running_task_record(
        task={"id": "task-001", "repo": "acme/platform", "title": "Bootstrap runtime"},
        branch="feat/task-001",
        worktree=Path("/tmp/wt"),
        execution_mode="process",
        tmux_session=None,
        process_id=1234,
        prompt_file=Path("/tmp/wt/prompt.txt"),
        task_spec_file=Path("/tmp/wt/task-spec.json"),
        scope_manifest_file=Path("/tmp/wt/.task-contract/scope-manifest.json"),
        sparse_checkout_applied=True,
        agent="codex",
        model="gpt-5.3-codex",
        effort="high",
    )

    assert record["status"] == "running"
    assert record["processId"] == 1234
    assert record["taskSpecFile"].endswith("task-spec.json")
    assert record["scopeManifestFile"].endswith("scope-manifest.json")
    assert record["startedAt"] == 1710000000000
