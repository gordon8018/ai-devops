from __future__ import annotations

import importlib
import os
import sys
import tempfile

from orchestrator.api.events import EventManager

from apps.console_api.service import (
    ConsoleApplicationService,
    WorkItemsApplicationService,
    get_global_console_service,
    get_global_work_items_service,
)
from packages.shared.domain.models import EvalRun, EvalRunStatus


class InMemoryControlPlaneStore:
    def __init__(self) -> None:
        self.work_items: dict[str, dict] = {}
        self.context_packs: dict[str, dict] = {}
        self.releases: dict[str, dict] = {}
        self.incidents: dict[str, dict] = {}

    def save_work_item(self, work_item) -> None:
        self.work_items[work_item.work_item_id] = work_item.to_dict()

    def save_context_pack(self, context_pack) -> None:
        self.context_packs[context_pack.work_item_id] = context_pack.to_dict()

    def get_work_item(self, work_item_id: str) -> dict | None:
        work_item = self.work_items.get(work_item_id)
        if work_item is None:
            return None
        context_pack = self.context_packs.get(work_item_id)
        return {
            "workItem": work_item,
            "contextPack": context_pack,
            "planRequest": {"context": {"contextPack": context_pack}},
        }

    def get_context_pack(self, work_item_id: str) -> dict | None:
        return self.context_packs.get(work_item_id)

    def list_work_items(self) -> list[dict]:
        return [self.get_work_item(work_item_id) for work_item_id in self.work_items]

    def save_release(self, release: dict) -> None:
        self.releases[release["workItemId"]] = dict(release)

    def get_release(self, work_item_id: str) -> dict | None:
        release = self.releases.get(work_item_id)
        return dict(release) if release is not None else None

    def list_releases(self) -> list[dict]:
        return [dict(release) for release in self.releases.values()]

    def save_incident(self, incident: dict) -> None:
        self.incidents[incident["incidentId"]] = dict(incident)

    def get_incident(self, incident_id: str) -> dict | None:
        incident = self.incidents.get(incident_id)
        return dict(incident) if incident is not None else None

    def list_incidents(self) -> list[dict]:
        return [dict(incident) for incident in self.incidents.values()]


def test_console_application_service_creates_platform_native_payload() -> None:
    recorded_audits: list[dict] = []
    service = WorkItemsApplicationService(audit_recorder=lambda event: recorded_audits.append(event.to_dict()))

    result = service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Create work item endpoint",
            "description": "Expose a first-class work item API",
            "constraints": {
                "allowedPaths": ["apps/console_api/**"],
                "mustTouch": ["apps/console_api/service.py"],
            },
            "context": {
                "filesHint": ["apps/console_api/service.py"],
                "acceptanceCriteria": ["Return workItem and contextPack payloads"],
            },
        }
    )

    assert result["workItem"]["repo"] == "acme/platform"
    assert result["contextPack"]["workItemId"] == result["workItem"]["workItemId"]
    assert result["planRequest"]["context"]["contextPack"]["packId"] == result["contextPack"]["packId"]
    assert recorded_audits[0]["action"] == "work_item_created"


def test_console_application_service_bridges_domain_events_to_event_manager() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    service = WorkItemsApplicationService()

    service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Bridge console events",
            "description": "Console path should publish bridged domain events",
        }
    )

    history = event_manager.get_history(limit=3)

    assert [event["eventName"] for event in history] == [
        "work_item.created",
        "context_pack.created",
        "plan.requested",
    ]


def test_console_application_service_returns_context_pack_by_work_item_id() -> None:
    service = WorkItemsApplicationService()
    result = service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Create work item endpoint",
            "description": "Expose a first-class work item API",
        }
    )

    context_pack = service.get_context_pack(result["workItem"]["workItemId"])

    assert context_pack is not None
    assert context_pack["packId"] == result["contextPack"]["packId"]


def test_console_application_service_reads_work_items_from_persistent_store_across_service_instances() -> None:
    store = InMemoryControlPlaneStore()
    writer = WorkItemsApplicationService(persistence_store=store)
    record = writer.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Persist work item endpoint",
            "description": "Reload from control plane store",
        }
    )

    reader = WorkItemsApplicationService(persistence_store=store)

    restored = reader.get_work_item(record["workItem"]["workItemId"])

    assert restored is not None
    assert restored["workItem"]["title"] == "Persist work item endpoint"
    assert restored["contextPack"]["workItemId"] == record["workItem"]["workItemId"]


def test_console_application_service_builds_mission_control_summary() -> None:
    work_items = WorkItemsApplicationService()
    record = work_items.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Create work item endpoint",
            "description": "Expose a first-class work item API",
        }
    )
    event_manager = EventManager()
    event_manager.clear_history()
    event_manager.publish_task_status(record["workItem"]["workItemId"], "ready", {}, source="test")
    service = ConsoleApplicationService(
        work_items_service=work_items,
        event_manager=event_manager,
        release_reader=lambda: [{"releaseId": "rel_001", "status": "rolling_out"}],
        incident_reader=lambda: [{"incidentId": "inc_001", "status": "open"}],
    )

    summary = service.get_mission_control()

    assert summary["workItems"]["total"] == 1
    assert summary["releases"]["total"] == 1
    assert summary["incidents"]["open"] == 1
    assert summary["recentEvents"][0]["type"] == "task_status"


def test_console_application_service_builds_task_workspace() -> None:
    work_items = WorkItemsApplicationService()
    record = work_items.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Create work item endpoint",
            "description": "Expose a first-class work item API",
        }
    )
    work_item_id = record["workItem"]["workItemId"]
    event_manager = EventManager()
    event_manager.clear_history()
    event_manager.publish_task_status(work_item_id, "running", {"step": "planning"}, source="test")
    service = ConsoleApplicationService(
        work_items_service=work_items,
        event_manager=event_manager,
        release_reader=lambda: [{"releaseId": "rel_001", "workItemId": work_item_id, "status": "rolling_out"}],
        incident_reader=lambda: [{"incidentId": "inc_001", "workItemId": work_item_id, "status": "open"}],
    )

    workspace = service.get_task_workspace(work_item_id)

    assert workspace is not None
    assert workspace["workItem"]["workItemId"] == work_item_id
    assert workspace["release"]["releaseId"] == "rel_001"
    assert workspace["incidents"][0]["incidentId"] == "inc_001"
    assert workspace["eventTimeline"][0]["data"]["status"] == "running"


def test_console_application_service_builds_release_and_incident_consoles() -> None:
    service = ConsoleApplicationService(
        work_items_service=WorkItemsApplicationService(),
        event_manager=EventManager(),
        release_reader=lambda: [
            {"releaseId": "rel_001", "workItemId": "wi_001", "status": "rolling_out", "stage": "beta"},
            {"releaseId": "rel_002", "workItemId": "wi_002", "status": "rolled_back", "stage": "5%"},
        ],
        incident_reader=lambda: [
            {"incidentId": "inc_001", "status": "open", "severity": "high"},
            {"incidentId": "inc_002", "status": "closed", "severity": "critical"},
        ],
    )

    release_console = service.get_release_console()
    incident_console = service.get_incident_console()

    assert release_console["total"] == 2
    assert release_console["byStatus"]["rolling_out"] == 1
    assert incident_console["total"] == 2
    assert incident_console["bySeverity"]["critical"] == 1


def test_console_application_service_builds_eval_console_from_event_history() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    event_manager.publish_task_status("wi_001", "ready", {}, source="test")
    event_manager.publish_task_status("wi_002", "failed", {}, source="test")
    event_manager.publish_alert("warning", "guardrail breach", {}, source="test")
    service = ConsoleApplicationService(
        work_items_service=WorkItemsApplicationService(),
        event_manager=event_manager,
        release_reader=lambda: [],
        incident_reader=lambda: [],
    )

    eval_console = service.get_eval_console()

    assert eval_console["taskStatusCounts"]["ready"] == 1
    assert eval_console["taskStatusCounts"]["failed"] == 1
    assert eval_console["alertCount"] == 1


def test_console_application_service_builds_eval_console_with_eval_runs_and_audit_summary() -> None:
    service = ConsoleApplicationService(
        work_items_service=WorkItemsApplicationService(),
        event_manager=EventManager(),
        release_reader=lambda: [],
        incident_reader=lambda: [],
        eval_run_reader=lambda: [
            EvalRun(
                eval_run_id="eval_001",
                work_item_id="wi_001",
                status=EvalRunStatus.PASSED,
                summary="healthy",
                payload={"successRate": 1.0},
            ).to_dict()
        ],
        audit_event_reader=lambda: [
            {"action": "work_item_created", "entityType": "work_item"},
            {"action": "release_started", "entityType": "release"},
            {"action": "release_started", "entityType": "release"},
        ],
    )

    eval_console = service.get_eval_console()

    assert eval_console["evalRuns"][0]["evalRunId"] == "eval_001"
    assert eval_console["auditSummary"]["total"] == 3
    assert eval_console["auditSummary"]["byAction"]["release_started"] == 2


def test_console_application_service_builds_governance_summary_for_legacy_cutover() -> None:
    work_items = WorkItemsApplicationService()
    work_items.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Legacy bridge still active",
            "description": "Track governance state",
        }
    )
    service = ConsoleApplicationService(
        work_items_service=work_items,
        event_manager=EventManager(),
        release_reader=lambda: [],
        incident_reader=lambda: [],
        eval_run_reader=lambda: [],
        audit_event_reader=lambda: [
            {
                "action": "legacy_entrypoint_used",
                "entityType": "work_item",
                "payload": {"entrypoint": "zoe_tools.build_work_item_session"},
            },
            {
                "action": "work_item_created",
                "entityType": "work_item",
                "payload": {"repo": "acme/platform"},
            },
        ],
    )

    eval_console = service.get_eval_console()

    assert eval_console["governance"]["legacyEntrypoints"]["total"] == 1
    assert eval_console["governance"]["legacyEntrypoints"]["byEntrypoint"]["zoe_tools.build_work_item_session"] == 1
    assert eval_console["governance"]["workItemSources"]["legacy_task_input"] == 1
    assert eval_console["governance"]["cutoverReadiness"]["ready"] is False
    assert eval_console["governance"]["cutoverReadiness"]["blockingReasons"] == [
        "legacy_entrypoints_active",
        "legacy_work_items_present",
    ]


def test_console_application_service_exposes_governance_console() -> None:
    service = ConsoleApplicationService(
        work_items_service=WorkItemsApplicationService(),
        event_manager=EventManager(),
        release_reader=lambda: [],
        incident_reader=lambda: [],
        eval_run_reader=lambda: [],
        audit_event_reader=lambda: [
            {
                "action": "legacy_entrypoint_used",
                "entityType": "work_item",
                "payload": {"entrypoint": "zoe_tools.build_work_item_session"},
            },
            {
                "action": "incident_opened",
                "entityType": "incident",
                "payload": {"incidentId": "inc_001"},
            },
        ],
    )

    governance = service.get_governance_console()

    assert governance["legacyEntrypoints"]["total"] == 1
    assert governance["auditSummary"]["byAction"]["incident_opened"] == 1
    assert governance["cutoverReadiness"]["ready"] is False


def test_global_console_service_shares_work_item_state_with_work_items_api_service() -> None:
    work_items = get_global_work_items_service()
    console = get_global_console_service()

    record = work_items.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Shared singleton state",
            "description": "Console should see items created through the work-items API service",
        }
    )

    mission_control = console.get_mission_control()

    assert mission_control["workItems"]["total"] >= 1
    assert record["workItem"]["workItemId"]


def test_console_eval_console_reads_task_status_events_emitted_by_sqlite_updates_across_process_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        original_home = os.environ.get("AI_DEVOPS_HOME")
        os.environ["AI_DEVOPS_HOME"] = tmpdir
        try:
            import orchestrator.api.events as events_mod
            import orchestrator.bin.db as db_mod

            importlib.reload(events_mod)
            importlib.reload(db_mod)
            events_mod.EventManager._instance = None
            db_mod.init_db()
            db_mod.insert_task(
                {
                    "id": "task-sqlite-ready",
                    "repo": "acme/platform",
                    "title": "Ready from sqlite update",
                    "status": "queued",
                }
            )

            event_manager = events_mod.EventManager()
            event_manager.clear_history()
            db_mod.update_task_status("task-sqlite-ready", "ready", "runner completed")

            # Simulate the API process not sharing the runner process in-memory EventManager state.
            event_manager._event_history.clear()

            service = ConsoleApplicationService(
                work_items_service=WorkItemsApplicationService(),
                event_manager=event_manager,
                release_reader=lambda: [],
                incident_reader=lambda: [],
            )

            eval_console = service.get_eval_console()

            assert eval_console["taskStatusCounts"]["ready"] == 1
        finally:
            events_mod.EventManager._instance = None
            if original_home is None:
                os.environ.pop("AI_DEVOPS_HOME", None)
            else:
                os.environ["AI_DEVOPS_HOME"] = original_home
