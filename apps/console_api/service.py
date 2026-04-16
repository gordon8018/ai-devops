from __future__ import annotations

from typing import Any, Callable
import time

from orchestrator.api.events import Event, EventManager, EventType, get_event_manager

from apps.incident_worker.service import get_global_incident_worker
from apps.release_worker.service import get_global_release_worker
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import WorkItemService
from packages.quality.evals.service import EvalEngine
from packages.shared.domain.control_plane import ensure_control_plane_store
from packages.shared.domain.models import AuditEvent
from packages.shared.mutation import MutationService
from packages.shared.domain.runtime_state import (
    list_audit_events,
    list_eval_runs,
    record_audit_event,
    record_eval_run,
)


class WorkItemsApplicationService:
    """Bootstrap BFF-facing service for platform-native work item creation."""

    def __init__(
        self,
        *,
        audit_recorder: Callable[[AuditEvent], None] | None = None,
        persistence_store: Any | None = None,
    ) -> None:
        self._event_bus = InMemoryEventBus()
        self._event_manager = get_event_manager()
        self._service = WorkItemService(
            event_bus=self._event_bus,
            context_assembler=ContextPackAssembler(),
        )
        self._records: dict[str, dict] = {}
        self._audit_recorder = audit_recorder or record_audit_event
        self._persistence_store = persistence_store or ensure_control_plane_store()
        self._mutations = MutationService()

    def _store(self) -> Any | None:
        return self._persistence_store or ensure_control_plane_store()

    def create_work_item(self, payload: dict) -> dict:
        pending_events = []
        unsubscribe = self._event_bus.subscribe(pending_events.append)
        try:
            session = self._service.create_legacy_session(payload)
        finally:
            unsubscribe()
        record = {
            "workItem": session.work_item.to_dict(),
            "contextPack": session.context_pack.to_dict(),
            "planRequest": session.plan_request,
        }
        store = self._store()

        def persist() -> None:
            self._records[session.work_item.work_item_id] = record
            if store is not None:
                if hasattr(store, "save_work_item"):
                    store.save_work_item(session.work_item)
                if hasattr(store, "save_context_pack"):
                    store.save_context_pack(session.context_pack)

        def audit() -> None:
            self._audit_recorder(
                AuditEvent(
                    audit_event_id=f"ae_{session.work_item.work_item_id}_created_{int(time.time() * 1000)}",
                    entity_type="work_item",
                    entity_id=session.work_item.work_item_id,
                    action="work_item_created",
                    payload={"repo": session.work_item.repo, "title": session.work_item.title},
                    actor_id="human:console",
                    actor_type="human",
                )
            )

        publish_events = [
            lambda envelope=envelope: self._event_manager.publish(
                Event(
                    event_type=EventType.SYSTEM,
                    event_name=envelope.event_type,
                    data=dict(envelope.payload),
                    source=envelope.source,
                    actor_id=envelope.actor_id,
                    actor_type=envelope.actor_type,
                )
            )
            for envelope in pending_events
        ]

        def rollback() -> None:
            self._records.pop(session.work_item.work_item_id, None)
            if store is not None:
                if hasattr(store, "delete_work_item"):
                    store.delete_work_item(session.work_item.work_item_id)
                if hasattr(store, "delete_context_pack"):
                    store.delete_context_pack(session.work_item.work_item_id)

        self._mutations.apply(
            persist=persist,
            audit=audit,
            publish_events=publish_events,
            rollback=rollback,
        )
        return record

    def get_work_item(self, work_item_id: str) -> dict | None:
        record = self._records.get(work_item_id)
        if record is not None:
            return record
        store = self._store()
        if store is not None and hasattr(store, "get_work_item"):
            return store.get_work_item(work_item_id)
        return None

    def get_context_pack(self, work_item_id: str) -> dict | None:
        record = self._records.get(work_item_id)
        if record is None:
            store = self._store()
            if store is not None and hasattr(store, "get_context_pack"):
                return store.get_context_pack(work_item_id)
            return None
        return record.get("contextPack")

    def list_work_items(self) -> list[dict]:
        store = self._store()
        persisted = (
            list(store.list_work_items())
            if store is not None and hasattr(store, "list_work_items")
            else []
        )
        merged = {record["workItem"]["workItemId"]: record for record in persisted}
        merged.update({record["workItem"]["workItemId"]: record for record in self._records.values()})
        return list(merged.values())


def _default_release_reader() -> list[dict]:
    store = ensure_control_plane_store()
    if store is not None and hasattr(store, "list_releases"):
        releases = list(store.list_releases())
        if releases:
            return releases
    worker = get_global_release_worker()
    if worker is None:
        return []
    return worker.list_releases()


def _default_incident_reader() -> list[dict]:
    store = ensure_control_plane_store()
    if store is not None and hasattr(store, "list_incidents"):
        incidents = list(store.list_incidents())
        if incidents:
            return incidents
    worker = get_global_incident_worker()
    if worker is None:
        return []
    return worker.list_incidents()


def _default_audit_event_reader() -> list[dict]:
    return list_audit_events()


def _default_eval_run_reader() -> list[dict]:
    return list_eval_runs()


class ConsoleApplicationService:
    """BFF-facing aggregation service for Mission Control and Task Workspace."""

    def __init__(
        self,
        *,
        work_items_service: WorkItemsApplicationService | None = None,
        event_manager: EventManager | None = None,
        release_reader: Callable[[], list[dict]] | None = None,
        incident_reader: Callable[[], list[dict]] | None = None,
        eval_run_reader: Callable[[], list[dict]] | None = None,
        audit_event_reader: Callable[[], list[dict]] | None = None,
    ) -> None:
        self._work_items_service = work_items_service or WorkItemsApplicationService()
        self._event_manager = event_manager or get_event_manager()
        self._release_reader = release_reader or _default_release_reader
        self._incident_reader = incident_reader or _default_incident_reader
        self._eval_run_reader = eval_run_reader or _default_eval_run_reader
        self._audit_event_reader = audit_event_reader or _default_audit_event_reader
        self._eval_engine = EvalEngine()

    @staticmethod
    def _build_governance_summary(work_items: list[dict], audit_events: list[dict]) -> dict:
        legacy_events = [event for event in audit_events if event.get("action") == "legacy_entrypoint_used"]
        entrypoints = [
            str(event.get("payload", {}).get("entrypoint") or "unknown")
            for event in legacy_events
        ]
        legacy_by_entrypoint = {
            entrypoint: entrypoints.count(entrypoint)
            for entrypoint in set(entrypoints)
        }
        sources = [
            record.get("workItem", {}).get("source", "unknown")
            for record in work_items
        ]
        work_item_sources = {
            source: sources.count(source)
            for source in set(sources)
        }

        blocking_reasons: list[str] = []
        if legacy_events:
            blocking_reasons.append("legacy_entrypoints_active")
        if work_item_sources.get("legacy_task_input", 0) > 0:
            blocking_reasons.append("legacy_work_items_present")

        return {
            "legacyEntrypoints": {
                "total": len(legacy_events),
                "byEntrypoint": legacy_by_entrypoint,
            },
            "workItemSources": work_item_sources,
            "cutoverReadiness": {
                "ready": not blocking_reasons,
                "blockingReasons": blocking_reasons,
            },
        }

    def get_mission_control(self) -> dict:
        work_items = self._work_items_service.list_work_items()
        releases = self._release_reader()
        incidents = self._incident_reader()
        recent_events = self._event_manager.get_history(limit=10)
        work_item_statuses = [record["workItem"].get("status", "unknown") for record in work_items]

        return {
            "workItems": {
                "total": len(work_items),
                "byStatus": {status: work_item_statuses.count(status) for status in set(work_item_statuses)},
            },
            "releases": {
                "total": len(releases),
                "active": sum(1 for release in releases if release.get("status") not in {"rolled_back", "closed"}),
            },
            "incidents": {
                "total": len(incidents),
                "open": sum(1 for incident in incidents if incident.get("status") != "closed"),
            },
            "recentEvents": recent_events,
        }

    def get_task_workspace(self, work_item_id: str) -> dict | None:
        record = self._work_items_service.get_work_item(work_item_id)
        if record is None:
            return None

        release = next(
            (item for item in self._release_reader() if item.get("workItemId") == work_item_id),
            None,
        )
        incidents = [item for item in self._incident_reader() if item.get("workItemId") == work_item_id]
        event_timeline = [
            item
            for item in self._event_manager.get_history(limit=100)
            if item.get("data", {}).get("task_id") == work_item_id
            or item.get("data", {}).get("work_item_id") == work_item_id
            or item.get("data", {}).get("details", {}).get("work_item_id") == work_item_id
        ]

        return {
            "workItem": record["workItem"],
            "contextPack": record["contextPack"],
            "planRequest": record["planRequest"],
            "eventTimeline": event_timeline,
            "release": release,
            "incidents": incidents,
        }

    def get_release_console(self) -> dict:
        releases = self._release_reader()
        statuses = [item.get("status", "unknown") for item in releases]
        return {
            "total": len(releases),
            "byStatus": {status: statuses.count(status) for status in set(statuses)},
            "items": releases,
        }

    def get_incident_console(self) -> dict:
        incidents = self._incident_reader()
        severities = [item.get("severity", "unknown") for item in incidents]
        return {
            "total": len(incidents),
            "bySeverity": {severity: severities.count(severity) for severity in set(severities)},
            "items": incidents,
        }

    def get_eval_console(self) -> dict:
        events = self._event_manager.get_history(limit=200)
        task_statuses = [
            event.get("data", {}).get("status")
            for event in events
            if event.get("type") == "task_status"
        ]
        task_status_counts = {
            status: task_statuses.count(status)
            for status in set(task_statuses)
            if status is not None
        }
        work_items = self._work_items_service.list_work_items()
        if work_items:
            for record in work_items:
                work_item_id = record["workItem"]["workItemId"]
                eval_run = self._eval_engine.evaluate_work_item(work_item_id=work_item_id, events=events)
                record_eval_run(eval_run)
        eval_runs = self._eval_run_reader()
        audit_events = self._audit_event_reader()
        actions = [event.get("action", "unknown") for event in audit_events]
        return {
            "taskStatusCounts": task_status_counts,
            "alertCount": sum(1 for event in events if event.get("type") == "alert"),
            "totalEvents": len(events),
            "evalRuns": eval_runs,
            "auditSummary": {
                "total": len(audit_events),
                "byAction": {action: actions.count(action) for action in set(actions)},
            },
            "governance": self._build_governance_summary(work_items, audit_events),
        }

    def get_governance_console(self) -> dict:
        work_items = self._work_items_service.list_work_items()
        audit_events = self._audit_event_reader()
        actions = [event.get("action", "unknown") for event in audit_events]
        governance = self._build_governance_summary(work_items, audit_events)
        return {
            **governance,
            "auditSummary": {
                "total": len(audit_events),
                "byAction": {action: actions.count(action) for action in set(actions)},
            },
        }


_GLOBAL_WORK_ITEMS_SERVICE = WorkItemsApplicationService()
_GLOBAL_CONSOLE_SERVICE = ConsoleApplicationService(work_items_service=_GLOBAL_WORK_ITEMS_SERVICE)


def get_global_work_items_service() -> WorkItemsApplicationService:
    return _GLOBAL_WORK_ITEMS_SERVICE


def get_global_console_service() -> ConsoleApplicationService:
    return _GLOBAL_CONSOLE_SERVICE
