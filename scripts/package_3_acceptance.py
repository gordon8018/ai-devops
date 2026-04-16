from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.bin.dispatch import build_execution_task
from orchestrator.bin.plan_schema import Plan
from packages.kernel.runtime.services import LaunchResult, PreparedWorkspace
from packages.shared.domain.models import AgentRun, AgentRunStatus, ContextPack, RiskProfile, WorkItem

ZOE_DAEMON_PATH = ROOT / "orchestrator" / "bin" / "zoe-daemon.py"


def load_zoe_daemon_module():
    bin_dir = str(ROOT / "orchestrator" / "bin")
    if bin_dir not in sys.path:
        sys.path.insert(0, bin_dir)

    spec = importlib.util.spec_from_file_location("zoe_daemon_package3_acceptance", ZOE_DAEMON_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["zoe_daemon_package3_acceptance"] = module
    spec.loader.exec_module(module)
    return module


def _make_session(task: dict) -> SimpleNamespace:
    work_item = WorkItem.from_legacy_task_input(task)
    context_pack = ContextPack(
        pack_id=f"ctx_{work_item.work_item_id}",
        work_item_id=work_item.work_item_id,
        repo_scope=("apps/**",),
        acceptance_criteria=("ship it",),
        risk_profile=RiskProfile.MEDIUM,
    )
    return SimpleNamespace(
        work_item=work_item,
        context_pack=context_pack,
        plan_request={
            "planId": "plan_acceptance_001",
            "context": {
                "workItem": work_item.to_dict(),
                "contextPack": context_pack.to_dict(),
            },
        },
    )


def check_queue_schema_unchanged() -> dict:
    # D1: queue payloads remain unchanged; execution session metadata is added lazily at spawn time.
    plan = Plan.from_dict(
        {
            "planId": "plan-acceptance",
            "repo": "acme/platform",
            "title": "Package 3 acceptance",
            "requestedBy": "acceptance",
            "requestedAt": 1234567890,
            "objective": "Validate package 3 queue compatibility",
            "routing": {"agent": "codex", "model": "gpt-5.3-codex", "effort": "medium"},
            "version": "1.0",
            "subtasks": [
                {
                    "id": "S1",
                    "title": "Subtask",
                    "description": "Keep queue schema unchanged",
                    "worktreeStrategy": "isolated",
                    "dependsOn": [],
                    "filesHint": [],
                    "prompt": "do it",
                }
            ],
        }
    )
    payload = build_execution_task(plan, plan.subtasks[0])
    metadata = payload["metadata"]
    return {
        "hasWorkItem": "workItem" in metadata,
        "hasContextPack": "contextPack" in metadata,
        "hasAgentRun": "agentRun" in metadata,
    }


def check_spawn_agent_enriches_metadata() -> dict:
    zoe_daemon = load_zoe_daemon_module()
    task = {
        "id": "task-p3-001",
        "repo": "acme/platform",
        "title": "Legacy queue task",
        "description": "Should lazy-build work item session",
        "prompt": "fix it",
    }
    session = _make_session(task)

    class StubWorkItemService:
        def create_legacy_session(self, task_input, *, base_dir=None):
            return session

        def prepare_agent_run(self, **kwargs):
            return AgentRun(
                run_id="run_acceptance_001",
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

    metadata = result["metadata"]
    return {
        "workItemId": metadata["workItem"]["workItemId"],
        "contextPackId": metadata["contextPack"]["packId"],
        "agentRunContextPackId": metadata["agentRun"]["contextPackId"],
    }


def check_dead_letter_behavior() -> dict:
    zoe_daemon = load_zoe_daemon_module()
    consumer = MagicMock()
    control_plane_store = MagicMock()

    with tempfile.TemporaryDirectory() as queue_dir_name:
        queue_root = Path(queue_dir_name)
        queue_file = queue_root / "task-bad.json"
        queue_file.write_text("{}", encoding="utf-8")
        consumer.list_queue_files.return_value = [queue_file]
        consumer.load_task.return_value = {
            "id": "task-bad",
            "repo": "acme/platform",
            "title": "Bad task",
            "description": "Will fail during prepare",
        }

        with patch.object(zoe_daemon, "init_db"), \
             patch.object(zoe_daemon, "configure_control_plane_dual_write", return_value=control_plane_store), \
             patch.object(zoe_daemon, "configure_runtime_persistence"), \
             patch.object(zoe_daemon, "start_api_server"), \
             patch.object(zoe_daemon, "ProcessGuardian") as mock_guardian_cls, \
             patch.object(zoe_daemon, "ReleaseWorker") as mock_release_worker_cls, \
             patch.object(zoe_daemon, "IncidentWorker") as mock_incident_worker_cls, \
             patch.object(zoe_daemon, "get_event_manager") as mock_get_event_manager, \
             patch.object(zoe_daemon, "QueueConsumer", return_value=consumer), \
             patch.object(zoe_daemon, "queue_dir", return_value=queue_root), \
             patch.object(zoe_daemon, "get_global_scheduler") as mock_get_scheduler, \
             patch.object(zoe_daemon, "get_running_tasks", return_value=[]), \
             patch.object(zoe_daemon, "get_task", return_value=None), \
             patch.object(
                 zoe_daemon,
                 "spawn_agent",
                 side_effect=zoe_daemon.MissingContextPackError("prepare failed"),
             ), \
             patch.object(zoe_daemon, "time") as mock_time:
            mock_guardian_cls.return_value = MagicMock(check_all=MagicMock(return_value={}))
            mock_release_worker_cls.return_value = MagicMock()
            mock_incident_worker_cls.return_value = MagicMock()
            mock_get_event_manager.return_value = MagicMock()
            mock_get_scheduler.return_value = MagicMock(schedule=MagicMock(return_value=[]))
            mock_time.time.return_value = 999999999
            mock_time.sleep.side_effect = KeyboardInterrupt()

            try:
                zoe_daemon.main()
            except KeyboardInterrupt:
                pass

        dead_file = queue_root / "dead" / "task-bad.json"
        err_file = queue_root / "dead" / "task-bad.err"
        return {
            "deadFileExists": dead_file.exists(),
            "errFileExists": err_file.exists(),
            "originalRemoved": not queue_file.exists(),
        }


def main() -> int:
    queue_schema = check_queue_schema_unchanged()
    enriched = check_spawn_agent_enriches_metadata()
    dead_letter = check_dead_letter_behavior()

    payload = {
        "queueSchema": queue_schema,
        "spawnAgent": enriched,
        "deadLetter": dead_letter,
    }
    print(payload)

    assert queue_schema == {
        "hasWorkItem": False,
        "hasContextPack": False,
        "hasAgentRun": False,
    }
    assert enriched["contextPackId"] == enriched["agentRunContextPackId"]
    assert dead_letter == {
        "deadFileExists": True,
        "errFileExists": True,
        "originalRemoved": True,
    }
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
