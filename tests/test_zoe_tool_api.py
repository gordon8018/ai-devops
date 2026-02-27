from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_API = REPO_ROOT / "orchestrator" / "bin" / "zoe_tool_api.py"


def test_schema_exposes_expected_tool_contracts() -> None:
    completed = subprocess.run(
        [sys.executable, str(TOOL_API), "schema"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    tool_names = {item["name"] for item in payload["tools"]}
    assert "plan_task" in tool_names
    assert "plan_and_dispatch_task" in tool_names
    assert "dispatch_plan" in tool_names
    assert "task_status" in tool_names
    assert "list_plans" in tool_names


def test_invoke_executes_list_plans_request(tmp_path) -> None:
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
        ),
        encoding="utf-8",
    )
    request_payload = {
        "tool": "list_plans",
        "args": {"limit": 3},
    }

    completed = subprocess.run(
        [sys.executable, str(TOOL_API), "invoke"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        input=json.dumps(request_payload, ensure_ascii=False),
        env={**os.environ, "AI_DEVOPS_HOME": str(base)},
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["tool"] == "list_plans"
    assert payload["result"]["plans"][0]["planId"] == "1730000000000-demo-repo-fix-auth"
