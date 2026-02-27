import json

from orchestrator.bin.dispatch import (
    archive_subtasks,
    dispatch_ready_subtasks,
    execution_task_id,
    topologically_sorted_subtask_ids,
)
from orchestrator.bin.plan_schema import Plan


def make_plan() -> Plan:
    return Plan.from_dict(
        {
            "planId": "1730000000000-demo-repo-refactor-auth",
            "repo": "demo/repo",
            "title": "Refactor auth flow",
            "requestedBy": "alice#1234",
            "requestedAt": 1730000000000,
            "objective": "Refactor the auth flow without breaking behavior.",
            "routing": {
                "agent": "codex",
                "model": "gpt-5.3-codex",
                "effort": "high",
            },
            "version": "1.0",
            "subtasks": [
                {
                    "id": "S1",
                    "title": "Extract auth helper",
                    "description": "Split the current auth code into a helper module.",
                    "worktreeStrategy": "isolated",
                    "dependsOn": [],
                    "prompt": "DoD: extract helper safely.\nBoundary: only touch auth implementation files.",
                },
                {
                    "id": "S2",
                    "title": "Wire consumers",
                    "description": "Update callers to use the new helper.",
                    "worktreeStrategy": "isolated",
                    "dependsOn": ["S1"],
                    "prompt": "DoD: wire consumers to the helper.\nBoundary: no unrelated refactors.",
                },
                {
                    "id": "S3",
                    "title": "Add regression tests",
                    "description": "Add regression coverage for the refactor.",
                    "worktreeStrategy": "isolated",
                    "dependsOn": ["S2"],
                    "prompt": "DoD: add focused regression tests.\nBoundary: stay in auth test files.",
                },
            ],
        }
    )


def test_dispatch_generates_queue_json_and_expected_fields(tmp_path) -> None:
    base_dir = tmp_path
    plan = make_plan()
    archive_subtasks(plan, base_dir)

    queued_paths = dispatch_ready_subtasks(plan, base_dir=base_dir, registry_items=[])

    assert len(queued_paths) == 1
    queue_path = queued_paths[0]
    assert queue_path.name == f"{execution_task_id(plan, plan.subtasks[0])}.json"

    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    assert payload["id"] == execution_task_id(plan, plan.subtasks[0])
    assert payload["repo"] == "demo/repo"
    assert payload["title"] == "Extract auth helper"
    assert payload["agent"] == "codex"
    assert payload["model"] == "gpt-5.3-codex"
    assert payload["effort"] == "high"
    assert payload["metadata"]["planId"] == plan.plan_id
    assert payload["metadata"]["subtaskId"] == "S1"
    assert payload["metadata"]["plannedBy"] == "zoe"


def test_topological_sort_and_dependency_dispatch(tmp_path) -> None:
    base_dir = tmp_path
    plan = make_plan()
    archive_subtasks(plan, base_dir)

    assert topologically_sorted_subtask_ids(plan) == ["S1", "S2", "S3"]

    first_batch = dispatch_ready_subtasks(plan, base_dir=base_dir, registry_items=[])
    assert [path.stem for path in first_batch] == [execution_task_id(plan, plan.subtasks[0])]

    registry_after_s1 = [
        {
            "id": execution_task_id(plan, plan.subtasks[0]),
            "status": "ready",
            "metadata": {
                "planId": plan.plan_id,
                "subtaskId": "S1",
            },
        }
    ]
    second_batch = dispatch_ready_subtasks(
        plan,
        base_dir=base_dir,
        registry_items=registry_after_s1,
    )
    assert [path.stem for path in second_batch] == [execution_task_id(plan, plan.subtasks[1])]
