from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.console_api.service import WorkItemsApplicationService
from apps.incident_worker.service import IncidentWorker
from apps.release_worker.service import ReleaseWorker
from orchestrator.api.events import Event, EventManager, EventType
from packages.shared.domain.runtime_state import clear_runtime_state


class ControlPlaneStore:
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
        return {
            "workItem": work_item,
            "contextPack": self.context_packs.get(work_item_id),
            "planRequest": {"context": {"contextPack": self.context_packs.get(work_item_id)}},
        }

    def list_work_items(self) -> list[dict]:
        return [self.get_work_item(work_item_id) for work_item_id in self.work_items]

    def delete_work_item(self, work_item_id: str) -> None:
        self.work_items.pop(work_item_id, None)

    def delete_context_pack(self, work_item_id: str) -> None:
        self.context_packs.pop(work_item_id, None)

    def save_release(self, release: dict) -> None:
        self.releases[release["workItemId"]] = dict(release)

    def get_release(self, work_item_id: str) -> dict | None:
        release = self.releases.get(work_item_id)
        return dict(release) if release is not None else None

    def delete_release(self, work_item_id: str) -> None:
        self.releases.pop(work_item_id, None)

    def save_incident(self, incident: dict) -> None:
        self.incidents[incident["incidentId"]] = dict(incident)

    def get_incident(self, incident_id: str) -> dict | None:
        incident = self.incidents.get(incident_id)
        return dict(incident) if incident is not None else None

    def list_incidents(self) -> list[dict]:
        return [dict(incident) for incident in self.incidents.values()]

    def delete_incident(self, incident_id: str) -> None:
        self.incidents.pop(incident_id, None)


class RecordingFlagAdapter:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []

    def apply_stage(self, release_id: str, stage: str) -> None:
        self.applied.append((release_id, stage))


def check_console_path() -> dict:
    manager = EventManager()
    manager.clear_history()
    store = ControlPlaneStore()
    service = WorkItemsApplicationService(persistence_store=store)
    record = service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Package 2 acceptance",
            "description": "Console mutation path should persist before publish",
        }
    )
    persisted = store.get_work_item(record["workItem"]["workItemId"])
    history = manager.get_history(limit=10)

    failing_store = ControlPlaneStore()
    failing_service = WorkItemsApplicationService(
        persistence_store=failing_store,
        audit_recorder=lambda _event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    manager.clear_history()
    try:
        failing_service.create_work_item(
            {
                "repo": "acme/platform",
                "title": "Package 2 audit rollback",
                "description": "Audit failure should roll back store and events",
            }
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("console audit failure should raise")

    return {
        "persisted": persisted is not None,
        "eventNames": [event.get("eventName") for event in history],
        "rollbackStoreEmpty": failing_store.list_work_items() == [],
        "rollbackEventsEmpty": manager.get_history(limit=10) == [],
    }


def check_release_path() -> dict:
    manager = EventManager()
    manager.clear_history()
    store = ControlPlaneStore()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(
        event_manager=manager,
        persistence_store=store,
        flag_adapter=flag_adapter,
        audit_recorder=lambda _event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    worker.start()
    manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_pkg2_release",
                "status": "ready",
                "details": {"work_item_id": "wi_pkg2_release"},
            },
            source="acceptance",
        )
    )
    result = {
        "releaseExists": worker.get_release("wi_pkg2_release") is not None,
        "storeReleaseExists": store.get_release("wi_pkg2_release") is not None,
        "flagCalls": list(flag_adapter.applied),
    }
    worker.stop()
    return result


def check_incident_path() -> dict:
    manager = EventManager()
    manager.clear_history()
    store = ControlPlaneStore()

    def conditional_audit(event) -> None:
        if event.action == "incident_closed":
            raise RuntimeError("close audit failed")

    worker = IncidentWorker(
        event_manager=manager,
        persistence_store=store,
        audit_recorder=conditional_audit,
    )
    worker.start()
    manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="acceptance",
        )
    )
    incident = worker.list_incidents()[0]
    manager.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={"type": "incident_verify", "incident_id": incident["incidentId"], "resolved": True},
            source="acceptance",
        )
    )
    updated = worker.get_incident(incident["incidentId"])
    stored = store.get_incident(incident["incidentId"])
    worker.stop()
    return {
        "incidentId": incident["incidentId"],
        "status": updated["status"] if updated else None,
        "storedStatus": stored["status"] if stored else None,
    }


def main() -> int:
    clear_runtime_state()
    console_result = check_console_path()
    release_result = check_release_path()
    incident_result = check_incident_path()

    payload = {
        "console": console_result,
        "release": release_result,
        "incident": incident_result,
    }
    print(payload)

    assert console_result["persisted"] is True
    assert console_result["eventNames"] == [
        "work_item.created",
        "context_pack.created",
        "plan.requested",
    ]
    assert console_result["rollbackStoreEmpty"] is True
    assert console_result["rollbackEventsEmpty"] is True
    assert release_result["releaseExists"] is False
    assert release_result["storeReleaseExists"] is False
    assert release_result["flagCalls"] == []
    assert incident_result["status"] == "open"
    assert incident_result["storedStatus"] == "open"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
