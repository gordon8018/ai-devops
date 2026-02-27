import pytest

from orchestrator.bin.errors import InvalidPlan
from orchestrator.bin.plan_schema import PROMPT_MAX_CHARS, Plan


def make_plan_payload() -> dict:
    return {
        "planId": "1730000000000-demo-repo-fix-login",
        "repo": "demo/repo",
        "title": "Fix login flow",
        "requestedBy": "alice#1234",
        "requestedAt": 1730000000000,
        "objective": "Fix the login flow and add coverage.",
        "constraints": {"doNotTouch": ["infra/"]},
        "context": {"notes": ["AUTH-12"]},
        "routing": {
            "agent": "codex",
            "model": "gpt-5.3-codex",
            "effort": "medium",
        },
        "version": "1.0",
        "subtasks": [
            {
                "id": "S1",
                "title": "Investigate auth regression",
                "description": "Inspect the login path and identify the failing branch.",
                "worktreeStrategy": "isolated",
                "dependsOn": [],
                "filesHint": ["app/auth.py"],
                "prompt": "DoD: identify the failing path and patch it.\nBoundary: do not touch infra/.",
                "definitionOfDone": ["Login succeeds for valid credentials."],
            },
            {
                "id": "S2",
                "title": "Add regression test",
                "description": "Add a focused unit test for the failing login case.",
                "worktreeStrategy": "isolated",
                "dependsOn": ["S1"],
                "filesHint": ["tests/test_auth.py"],
                "prompt": "DoD: add regression coverage.\nBoundary: keep the change scoped to auth tests.",
                "definitionOfDone": ["Regression test fails before the fix and passes after."],
            },
        ],
    }


def test_valid_plan_passes() -> None:
    plan = Plan.from_dict(make_plan_payload())

    assert plan.plan_id == "1730000000000-demo-repo-fix-login"
    assert [subtask.agent for subtask in plan.subtasks] == ["codex", "codex"]
    assert [subtask.model for subtask in plan.subtasks] == ["gpt-5.3-codex", "gpt-5.3-codex"]
    assert [subtask.id for subtask in plan.topologically_sorted_subtasks()] == ["S1", "S2"]


def test_depends_on_unknown_subtask_fails() -> None:
    payload = make_plan_payload()
    payload["subtasks"][1]["dependsOn"] = ["S9"]

    with pytest.raises(InvalidPlan, match="unknown subtask"):
        Plan.from_dict(payload)


def test_depends_on_cycle_fails() -> None:
    payload = make_plan_payload()
    payload["subtasks"][0]["dependsOn"] = ["S2"]

    with pytest.raises(InvalidPlan, match="cycle"):
        Plan.from_dict(payload)


def test_prompt_limit_fails() -> None:
    payload = make_plan_payload()
    payload["subtasks"][0]["prompt"] = "x" * (PROMPT_MAX_CHARS + 1)

    with pytest.raises(InvalidPlan, match="Prompt too long"):
        Plan.from_dict(payload)
