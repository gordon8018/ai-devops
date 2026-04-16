from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from packages.kernel.runtime.services import LaunchResult, PreparedWorkspace
from packages.shared.domain.models import AgentRun, AgentRunStatus, ContextPack, RiskProfile, WorkItem


SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
ZOE_DAEMON_PATH = BASE / "orchestrator" / "bin" / "zoe-daemon.py"


def load_zoe_daemon_module():
    bin_dir = str(BASE / "orchestrator" / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)

    spec = importlib.util.spec_from_file_location("zoe_daemon_entrypoint_guard", ZOE_DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["zoe_daemon_entrypoint_guard"] = module
    spec.loader.exec_module(module)
    return module


def _make_session(task: dict) -> SimpleNamespace:
    work_item = WorkItem.from_legacy_task_input(task)
    context_pack = ContextPack(
        pack_id="ctx_test_001",
        work_item_id=work_item.work_item_id,
        repo_scope=("apps/**",),
        acceptance_criteria=("ship it",),
        risk_profile=RiskProfile.MEDIUM,
    )
    return SimpleNamespace(
        work_item=work_item,
        context_pack=context_pack,
        plan_request={
            "planId": "plan_test_001",
            "context": {
                "workItem": work_item.to_dict(),
                "contextPack": context_pack.to_dict(),
            },
        },
    )


def test_spawn_agent_builds_work_item_session_for_legacy_queue_task() -> None:
    zoe_daemon = load_zoe_daemon_module()
    task = {
        "id": "task-001",
        "repo": "acme/platform",
        "title": "Legacy queue task",
        "description": "Should lazy-build work item session",
        "prompt": "fix it",
    }
    session = _make_session(task)
    create_calls: list[dict] = []

    class StubWorkItemService:
        def create_legacy_session(self, task_input, *, base_dir=None):
            create_calls.append(dict(task_input))
            return session

        def prepare_agent_run(self, **kwargs):
            return AgentRun(
                run_id="run_test_001",
                work_item_id=session.work_item.work_item_id,
                context_pack_id=session.context_pack.pack_id,
                agent="codex",
                model="gpt-5.3-codex",
                status=AgentRunStatus.PENDING,
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with (
            tempfile.TemporaryDirectory() as repo_dir,
            tempfile.TemporaryDirectory() as wt_dir,
        ):
            repo_root = Path(repo_dir)
            worktree = Path(wt_dir)
            prepared = PreparedWorkspace(
                repo_root=repo_root,
                worktree=worktree,
                prompt_file=worktree / "prompt.txt",
                task_spec_file=None,
                scope_manifest_file=None,
                sparse_checkout_applied=False,
            )
            launched = LaunchResult(
                execution_mode="process",
                tmux_session=None,
                process_id=1234,
            )

            class StubWorkspaceManager:
                def __init__(self, **kwargs):
                    pass

                def prepare_workspace(self, task, *, branch):
                    prepared.prompt_file.write_text(task["prompt"], encoding="utf-8")
                    return prepared

            class StubAgentLauncher:
                def __init__(self, **kwargs):
                    pass

                def launch(self, task, *, worktree, prompt_file, task_spec_file):
                    return launched

            class StubRunStateRecorder:
                def build_running_task_record(self, **kwargs):
                    return {"metadata": kwargs["task"].get("metadata", {})}

            zoe_daemon.WorkItemService = StubWorkItemService
            zoe_daemon.WorkspaceManager = StubWorkspaceManager
            zoe_daemon.AgentLauncher = StubAgentLauncher
            zoe_daemon.RunStateRecorder = StubRunStateRecorder
            zoe_daemon.ensure_repo = lambda repo: repo_root
            zoe_daemon.create_worktree = lambda repo_root, branch: worktree

            result = zoe_daemon.spawn_agent(task)

    assert create_calls, "spawn_agent must lazy-build a legacy session before launch"
    assert result["metadata"]["workItem"]["workItemId"] == session.work_item.work_item_id
    assert result["metadata"]["contextPack"]["packId"] == session.context_pack.pack_id


def test_spawn_agent_prepares_agent_run_before_launch() -> None:
    zoe_daemon = load_zoe_daemon_module()
    task = {
        "id": "task-prepare-001",
        "repo": "acme/platform",
        "title": "Prepare agent run",
        "description": "Should validate through prepare_agent_run",
        "prompt": "fix it",
    }
    session = _make_session(task)
    prepared_runs: list[dict] = []

    class StubWorkItemService:
        def create_legacy_session(self, task_input, *, base_dir=None):
            return session

        def prepare_agent_run(self, **kwargs):
            prepared_runs.append(dict(kwargs))
            return AgentRun(
                run_id="run_test_002",
                work_item_id=session.work_item.work_item_id,
                context_pack_id=session.context_pack.pack_id,
                agent="codex",
                model="gpt-5.3-codex",
                status=AgentRunStatus.PENDING,
            )

    with (
        tempfile.TemporaryDirectory() as repo_dir,
        tempfile.TemporaryDirectory() as wt_dir,
    ):
        repo_root = Path(repo_dir)
        worktree = Path(wt_dir)
        prepared = PreparedWorkspace(
            repo_root=repo_root,
            worktree=worktree,
            prompt_file=worktree / "prompt.txt",
            task_spec_file=None,
            scope_manifest_file=None,
            sparse_checkout_applied=False,
        )

        class StubWorkspaceManager:
            def __init__(self, **kwargs):
                pass

            def prepare_workspace(self, task, *, branch):
                prepared.prompt_file.write_text(task["prompt"], encoding="utf-8")
                return prepared

        class StubAgentLauncher:
            def __init__(self, **kwargs):
                pass

            def launch(self, task, *, worktree, prompt_file, task_spec_file):
                return LaunchResult("process", None, 4321)

        class StubRunStateRecorder:
            def build_running_task_record(self, **kwargs):
                return {"metadata": kwargs["task"].get("metadata", {})}

        zoe_daemon.WorkItemService = StubWorkItemService
        zoe_daemon.WorkspaceManager = StubWorkspaceManager
        zoe_daemon.AgentLauncher = StubAgentLauncher
        zoe_daemon.RunStateRecorder = StubRunStateRecorder
        zoe_daemon.ensure_repo = lambda repo: repo_root
        zoe_daemon.create_worktree = lambda repo_root, branch: worktree

        result = zoe_daemon.spawn_agent(task)

    assert prepared_runs, "spawn_agent must call prepare_agent_run before launch"
    assert result["metadata"]["agentRun"]["contextPackId"] == session.context_pack.pack_id


def test_spawn_agent_reuses_existing_execution_session_metadata() -> None:
    zoe_daemon = load_zoe_daemon_module()
    task = {
        "id": "task-existing-001",
        "repo": "acme/platform",
        "title": "Existing session",
        "description": "Should not rebuild execution session metadata",
        "prompt": "fix it",
        "metadata": {
            "workItem": {"workItemId": "wi_existing_001"},
            "contextPack": {"packId": "ctx_existing_001"},
            "planRequest": {"planId": "plan_existing_001"},
            "agentRun": {
                "runId": "run_existing_001",
                "workItemId": "wi_existing_001",
                "contextPackId": "ctx_existing_001",
                "agent": "codex",
                "model": "gpt-5.3-codex",
                "status": "pending",
            },
        },
    }

    class StubWorkItemService:
        def create_legacy_session(self, task_input, *, base_dir=None):
            raise AssertionError("existing execution metadata should not rebuild a legacy session")

        def prepare_agent_run(self, **kwargs):
            raise AssertionError("existing execution metadata should not rebuild an agent run")

    with (
        tempfile.TemporaryDirectory() as repo_dir,
        tempfile.TemporaryDirectory() as wt_dir,
    ):
        repo_root = Path(repo_dir)
        worktree = Path(wt_dir)
        prepared = PreparedWorkspace(
            repo_root=repo_root,
            worktree=worktree,
            prompt_file=worktree / "prompt.txt",
            task_spec_file=None,
            scope_manifest_file=None,
            sparse_checkout_applied=False,
        )

        class StubWorkspaceManager:
            def __init__(self, **kwargs):
                pass

            def prepare_workspace(self, task, *, branch):
                prepared.prompt_file.write_text(task["prompt"], encoding="utf-8")
                return prepared

        class StubAgentLauncher:
            def __init__(self, **kwargs):
                pass

            def launch(self, task, *, worktree, prompt_file, task_spec_file):
                return LaunchResult("process", None, 4321)

        class StubRunStateRecorder:
            def build_running_task_record(self, **kwargs):
                return {"metadata": kwargs["task"].get("metadata", {})}

        zoe_daemon.WorkItemService = StubWorkItemService
        zoe_daemon.WorkspaceManager = StubWorkspaceManager
        zoe_daemon.AgentLauncher = StubAgentLauncher
        zoe_daemon.RunStateRecorder = StubRunStateRecorder
        zoe_daemon.ensure_repo = lambda repo: repo_root
        zoe_daemon.create_worktree = lambda repo_root, branch: worktree

        result = zoe_daemon.spawn_agent(task)

    assert result["metadata"]["workItem"]["workItemId"] == "wi_existing_001"
    assert result["metadata"]["contextPack"]["packId"] == "ctx_existing_001"
    assert result["metadata"]["agentRun"]["runId"] == "run_existing_001"
