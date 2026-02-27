from orchestrator.bin.planner_engine import ZoePlannerEngine


def make_task_input(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "planId": "1730000000000-agent-mission-control-refactor-auth-flow",
        "repo": "agent-mission-control",
        "title": "Refactor auth flow and update docs",
        "requestedBy": "alice#1234",
        "requestedAt": 1730000000000,
        "objective": (
            "Refactor the auth flow, wire the new session helper through the API layer, "
            "add regression coverage, and update the operator documentation."
        ),
        "constraints": {
            "definitionOfDone": ["Keep the auth behavior backward compatible."],
        },
        "context": {
            "filesHint": [
                "src/auth/session.py",
                "src/api/routes/auth.py",
                "tests/test_auth_flow.py",
                "README.md",
            ]
        },
        "routing": {
            "agent": "codex",
            "model": "gpt-5.3-codex",
            "effort": "high",
        },
        "version": "1.0",
    }
    payload.update(overrides)
    return payload


def test_complex_code_task_splits_into_multiple_ordered_subtasks() -> None:
    plan = ZoePlannerEngine().plan(make_task_input())

    assert [subtask.id for subtask in plan.subtasks] == ["S1", "S2", "S3", "S4"]
    assert [subtask.title for subtask in plan.subtasks] == [
        "Prepare the implementation surface",
        "Land the primary implementation",
        "Add validation and regression coverage",
        "Update documentation and handoff notes",
    ]
    assert [subtask.depends_on for subtask in plan.subtasks] == [
        (),
        ("S1",),
        ("S2",),
        ("S3",),
    ]
    assert all(subtask.worktree_strategy == "isolated" for subtask in plan.subtasks)
    assert plan.subtasks[0].files_hint == ("src/auth/session.py", "src/api/routes/auth.py")
    assert plan.subtasks[1].files_hint == ("src/api/routes/auth.py", "src/auth/session.py")
    assert plan.subtasks[2].files_hint[0] == "tests/test_auth_flow.py"
    assert "src/auth/session.py" in plan.subtasks[2].files_hint
    assert plan.subtasks[3].files_hint == ("README.md",)
    assert plan.context["planner"]["strategy"] == "phased-v1"
    assert plan.context["planner"]["subtaskCount"] == 4


def test_simple_code_task_still_generates_implementation_and_validation() -> None:
    plan = ZoePlannerEngine().plan(
        make_task_input(
            title="Fix login timeout",
            objective="Fix the login timeout handling for expired sessions.",
            context={"filesHint": ["src/auth/session.py", "tests/test_session_timeout.py"]},
        )
    )

    assert [subtask.id for subtask in plan.subtasks] == ["S1", "S2"]
    assert [subtask.title for subtask in plan.subtasks] == [
        "Land the primary implementation",
        "Add validation and regression coverage",
    ]
    assert plan.subtasks[1].depends_on == ("S1",)
    assert plan.subtasks[0].files_hint == ("src/auth/session.py",)
    assert plan.subtasks[1].files_hint[0] == "tests/test_session_timeout.py"
    assert "src/auth/session.py" in plan.subtasks[1].files_hint


def test_analysis_task_is_not_misclassified_as_docs_only() -> None:
    plan = ZoePlannerEngine().plan(
        make_task_input(
            title="检查开发进度",
            objective="阅读项目代码和文档，确认当前开发进度",
            context={},
        )
    )

    assert [subtask.id for subtask in plan.subtasks] == ["S1"]
    assert plan.subtasks[0].title == "Analyze the current state"
    assert "docs/" not in plan.subtasks[0].files_hint
    assert any(path != "README.md" for path in plan.subtasks[0].files_hint)
    assert plan.context["planner"]["analysisOnly"] is True
    assert plan.context["planner"]["docsOnly"] is False


def test_analysis_task_discovers_repo_entry_files_when_no_files_hint(tmp_path, monkeypatch) -> None:
    base = tmp_path / "ai-devops"
    repo_root = base / "repos" / "demo-repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "scripts").mkdir(parents=True)
    (repo_root / "README.md").write_text("demo", encoding="utf-8")
    (repo_root / "package.json").write_text("{}", encoding="utf-8")
    (repo_root / "src" / "main.ts").write_text("export {};\n", encoding="utf-8")
    (repo_root / "scripts" / "worker.ts").write_text("console.log('ok')\n", encoding="utf-8")
    monkeypatch.setenv("AI_DEVOPS_HOME", str(base))

    plan = ZoePlannerEngine().plan(
        {
            "planId": "1730000000000-demo-repo-check-status",
            "repo": "demo-repo",
            "title": "检查进度",
            "requestedBy": "alice#1234",
            "requestedAt": 1730000000000,
            "objective": "阅读当前代码和文档，确认当前开发进度。",
            "constraints": {},
            "context": {},
            "routing": {
                "agent": "codex",
                "model": "gpt-5.3-codex",
                "effort": "medium",
            },
            "version": "1.0",
        }
    )

    assert plan.subtasks[0].title == "Analyze the current state"
    assert "README.md" in plan.subtasks[0].files_hint
    assert "package.json" in plan.subtasks[0].files_hint
    assert "src/main.ts" in plan.subtasks[0].files_hint


def test_code_task_discovers_implementation_and_test_files_when_no_files_hint(tmp_path, monkeypatch) -> None:
    base = tmp_path / "ai-devops"
    repo_root = base / "repos" / "demo-repo"
    (repo_root / "src" / "auth").mkdir(parents=True)
    (repo_root / "tests").mkdir(parents=True)
    (repo_root / "package.json").write_text("{}", encoding="utf-8")
    (repo_root / "src" / "auth" / "session.ts").write_text("export const session = {};\n", encoding="utf-8")
    (repo_root / "src" / "auth" / "routes.ts").write_text("export const routes = {};\n", encoding="utf-8")
    (repo_root / "tests" / "test_auth.ts").write_text("console.log('test')\n", encoding="utf-8")
    monkeypatch.setenv("AI_DEVOPS_HOME", str(base))

    plan = ZoePlannerEngine().plan(
        {
            "planId": "1730000000000-demo-repo-fix-auth",
            "repo": "demo-repo",
            "title": "修复现存错误",
            "requestedBy": "alice#1234",
            "requestedAt": 1730000000000,
            "objective": "运行当前代码，修复存在的错误",
            "constraints": {},
            "context": {},
            "routing": {
                "agent": "codex",
                "model": "gpt-5.3-codex",
                "effort": "medium",
            },
            "version": "1.0",
        }
    )

    assert [subtask.title for subtask in plan.subtasks] == [
        "Land the primary implementation",
        "Add validation and regression coverage",
    ]
    assert "src/auth/session.ts" in plan.subtasks[0].files_hint
    assert "src/auth/routes.ts" in plan.subtasks[0].files_hint
    assert plan.subtasks[1].files_hint[0] == "tests/test_auth.ts"
    assert "src/auth/session.ts" in plan.subtasks[1].files_hint or "src/auth/routes.ts" in plan.subtasks[1].files_hint
