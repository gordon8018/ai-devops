import json

from orchestrator.bin.zoe_tools import list_plans, plan_and_dispatch_task, task_status


def make_task_input() -> dict[str, object]:
    return {
        "repo": "demo-repo",
        "title": "Fix auth flow",
        "description": "Fix the auth flow and add regression coverage.",
        "agent": "codex",
        "model": "gpt-5.3-codex",
        "effort": "high",
        "requested_by": "alice#1234",
        "requested_at": 1730000000000,
    }


def test_plan_and_dispatch_task_archives_plan_and_queues_first_subtask(tmp_path, monkeypatch) -> None:
    base = tmp_path / "ai-devops"
    repo_root = base / "repos" / "demo-repo"
    (repo_root / "src" / "auth").mkdir(parents=True)
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / "src" / "auth" / "session.ts").write_text("export const session = {};\n", encoding="utf-8")
    (repo_root / "tests" / "test_auth.ts").write_text("console.log('test')\n", encoding="utf-8")
    monkeypatch.setenv("AI_DEVOPS_HOME", str(base))

    result = plan_and_dispatch_task(make_task_input(), base_dir=base)

    assert result.plan.plan_id
    assert result.plan_path.exists()
    assert len(result.queued_paths) == 1
    queue_payload = json.loads(result.queued_paths[0].read_text(encoding="utf-8"))
    assert queue_payload["metadata"]["plannedBy"] == "zoe"
    assert queue_payload["metadata"]["planId"] == result.plan.plan_id


def test_task_status_and_list_plans_read_tool_layer_state(tmp_path) -> None:
    base = tmp_path / "ai-devops"
    tasks_root = base / "tasks" / "1730000000000-demo-repo-fix-auth"
    tasks_root.mkdir(parents=True)
    (tasks_root / "plan.json").write_text(
        json.dumps(
            {
                "planId": "1730000000000-demo-repo-fix-auth",
                "repo": "demo-repo",
                "title": "Fix auth flow",
                "requestedBy": "alice#1234",
                "requestedAt": 1730000000000,
                "objective": "Fix auth flow",
                "constraints": {},
                "context": {},
                "routing": {"agent": "codex", "model": "gpt-5.3-codex", "effort": "high"},
                "version": "1.0",
                "subtasks": [
                    {
                        "id": "S1",
                        "title": "Land the primary implementation",
                        "description": "Fix auth flow",
                        "agent": "codex",
                        "model": "gpt-5.3-codex",
                        "effort": "high",
                        "worktreeStrategy": "isolated",
                        "dependsOn": [],
                        "filesHint": ["src/auth/session.ts"],
                        "prompt": "DoD: fix auth.\nBoundary: stay scoped.",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    registry_path = base / ".clawdbot" / "active-tasks.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            [
                {
                    "id": "1730000000000-demo-repo-fix-auth-S1",
                    "status": "running",
                    "metadata": {
                        "planId": "1730000000000-demo-repo-fix-auth",
                        "subtaskId": "S1",
                    },
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    plans_result = list_plans(base_dir=base, limit=5)
    assert plans_result["plans"][0]["planId"] == "1730000000000-demo-repo-fix-auth"

    status_result = task_status(plan_id="1730000000000-demo-repo-fix-auth", base_dir=base)
    assert status_result["tasks"][0]["id"] == "1730000000000-demo-repo-fix-auth-S1"
