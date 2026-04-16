from __future__ import annotations

from apps.incident_worker.service import IncidentWorker
from orchestrator.api.events import Event, EventManager, EventType


def test_incident_worker_clusters_duplicate_alerts_into_one_incident() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
        "details": {"service": "payments"},
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))

    incidents = worker.list_incidents()

    assert len(incidents) == 1
    assert incidents[0]["occurrenceCount"] == 2
    worker.stop()


def test_incident_worker_closes_incident_after_verify_event() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
        "details": {"service": "payments"},
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    incident = worker.list_incidents()[0]

    event_manager.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={"type": "incident_verify", "incident_id": incident["incidentId"], "resolved": True},
            source="test",
        )
    )

    updated = worker.get_incident(incident["incidentId"])

    assert updated is not None
    assert updated["status"] == "closed"
    worker.stop()
