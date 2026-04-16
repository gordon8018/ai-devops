from __future__ import annotations

from apps.incident_worker.service import IncidentWorker
from orchestrator.api.events import Event, EventManager, EventType
from packages.shared.domain.runtime_state import clear_runtime_state, list_audit_events


class InMemoryIncidentStore:
    def __init__(self) -> None:
        self.incidents: dict[str, dict] = {}

    def save_incident(self, incident: dict) -> None:
        self.incidents[incident["incidentId"]] = dict(incident)

    def get_incident(self, incident_id: str) -> dict | None:
        incident = self.incidents.get(incident_id)
        return dict(incident) if incident is not None else None

    def list_incidents(self) -> list[dict]:
        return [dict(incident) for incident in self.incidents.values()]

    def delete_incident(self, incident_id: str) -> None:
        self.incidents.pop(incident_id, None)


class FailOnUpdateIncidentStore(InMemoryIncidentStore):
    def __init__(self) -> None:
        super().__init__()
        self._fail_on_existing = False

    def save_incident(self, incident: dict) -> None:
        if self._fail_on_existing and incident["incidentId"] in self.incidents:
            raise RuntimeError("save incident update failed")
        super().save_incident(incident)


def test_incident_worker_clusters_duplicate_alerts_into_one_incident() -> None:
    clear_runtime_state()
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
    assert list_audit_events()[0]["actorId"] == "system:incident_worker"
    assert list_audit_events()[0]["actorType"] == "system"
    worker.stop()
    clear_runtime_state()


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


def test_incident_worker_reads_incidents_from_persistent_store_across_instances() -> None:
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
        "details": {"service": "payments"},
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    incident_id = worker.list_incidents()[0]["incidentId"]
    worker.stop()

    restored_worker = IncidentWorker(event_manager=EventManager(), persistence_store=store)

    restored = restored_worker.get_incident(incident_id)

    assert restored is not None
    assert restored["message"] == "Checkout timeout in payment service"


def test_incident_worker_promotes_source_system_and_dedup_key_to_top_level() -> None:
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
        "details": {"service": "payments"},
        "sourceSystem": "pagerduty",
        "dedupKey": "pd-alert-42",
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    incident = worker.list_incidents()[0]

    assert incident["sourceSystem"] == "pagerduty"
    assert incident["dedupKey"] == "pd-alert-42"
    # Must be top-level, never inside details / payload.
    assert "sourceSystem" not in incident.get("details", {})
    assert "dedupKey" not in incident.get("details", {})

    stored = store.incidents[incident["incidentId"]]
    assert stored["sourceSystem"] == "pagerduty"
    assert stored["dedupKey"] == "pd-alert-42"

    worker.stop()


def test_incident_worker_accepts_snake_case_source_system_and_dedup_key_aliases() -> None:
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
        "source_system": "datadog",
        "dedup_key": "dd-alert-77",
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    incident = worker.list_incidents()[0]

    assert incident["sourceSystem"] == "datadog"
    assert incident["dedupKey"] == "dd-alert-77"
    worker.stop()


def test_incident_worker_sets_source_system_and_dedup_key_to_none_when_absent() -> None:
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    payload = {
        "level": "error",
        "message": "Checkout timeout in payment service",
    }
    event_manager.publish(Event(event_type=EventType.ALERT, data=payload, source="test"))
    incident = worker.list_incidents()[0]

    assert incident["sourceSystem"] is None
    assert incident["dedupKey"] is None
    worker.stop()


def test_incident_worker_backfills_source_system_and_dedup_key_on_later_alert() -> None:
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    # First alert: identity fields missing — incident created with None values
    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )

    # Second alert, same fingerprint: identity fields now present
    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "sentry",
                "dedupKey": "sentry-event-99",
            },
            source="test",
        )
    )

    incident = worker.list_incidents()[0]

    assert incident["occurrenceCount"] == 2
    assert incident["sourceSystem"] == "sentry"
    assert incident["dedupKey"] == "sentry-event-99"
    # Store also reflects the backfilled values
    stored = store.get_incident(incident["incidentId"])
    assert stored is not None
    assert stored["sourceSystem"] == "sentry"
    assert stored["dedupKey"] == "sentry-event-99"
    worker.stop()


def test_incident_worker_ingests_second_alert_against_persisted_incident_after_restart() -> None:
    """After a restart, a new alert with the same fingerprint must update the
    persisted incident (increment count, backfill identity) instead of creating
    a duplicate record that overwrites history."""
    store = InMemoryIncidentStore()

    # First worker creates the incident, then stops (in-memory state lost)
    first_em = EventManager()
    first_em.clear_history()
    first = IncidentWorker(event_manager=first_em, persistence_store=store)
    first.start()
    first_em.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )
    first_incident = first.list_incidents()[0]
    first_incident_id = first_incident["incidentId"]
    assert first_incident["occurrenceCount"] == 1
    first.stop()

    # Restart: new worker, same store, same fingerprint alert with identity
    second_em = EventManager()
    second_em.clear_history()
    second = IncidentWorker(event_manager=second_em, persistence_store=store)
    second.start()
    second_em.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "sentry",
                "dedupKey": "sentry-restart-1",
            },
            source="test",
        )
    )

    stored = store.get_incident(first_incident_id)

    assert stored is not None
    assert stored["occurrenceCount"] == 2  # increment, not reset to 1
    assert stored["sourceSystem"] == "sentry"  # backfill works after restart
    assert stored["dedupKey"] == "sentry-restart-1"
    # Only one incident in the store — no duplicate created
    assert len(store.list_incidents()) == 1
    second.stop()


def test_incident_worker_verifies_persisted_incident_after_restart() -> None:
    """After a restart, a verify event must resolve through the store and
    actually close the persisted incident, instead of silently no-oping."""
    store = InMemoryIncidentStore()

    first_em = EventManager()
    first_em.clear_history()
    first = IncidentWorker(event_manager=first_em, persistence_store=store)
    first.start()
    first_em.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )
    first_incident_id = first.list_incidents()[0]["incidentId"]
    first.stop()

    # Restart worker, issue verify
    second_em = EventManager()
    second_em.clear_history()
    second = IncidentWorker(event_manager=second_em, persistence_store=store)
    second.start()
    second_em.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={
                "type": "incident_verify",
                "incident_id": first_incident_id,
                "resolved": True,
            },
            source="test",
        )
    )

    stored = store.get_incident(first_incident_id)

    assert stored is not None
    assert stored["status"] == "closed"
    second.stop()


def test_incident_worker_does_not_overwrite_existing_source_system_or_dedup_key() -> None:
    """First non-null value wins and sticks; a later alert with different
    sourceSystem/dedupKey must NOT overwrite the already-set identity fields."""
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "sentry",
                "dedupKey": "sentry-first",
            },
            source="test",
        )
    )
    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "datadog",
                "dedupKey": "datadog-second",
            },
            source="test",
        )
    )

    incident = worker.list_incidents()[0]

    assert incident["occurrenceCount"] == 2
    assert incident["sourceSystem"] == "sentry"
    assert incident["dedupKey"] == "sentry-first"
    worker.stop()


def test_incident_worker_does_not_persist_incident_when_open_audit_fails() -> None:
    clear_runtime_state()
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(
        event_manager=event_manager,
        persistence_store=store,
        audit_recorder=lambda _event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )

    assert worker.list_incidents() == []
    assert store.list_incidents() == []
    assert list_audit_events() == []
    worker.stop()
    clear_runtime_state()


def test_incident_worker_keeps_incident_open_when_close_audit_fails() -> None:
    clear_runtime_state()
    store = InMemoryIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()

    def conditional_audit(event) -> None:
        if event.action == "incident_closed":
            raise RuntimeError("close audit failed")

    worker = IncidentWorker(
        event_manager=event_manager,
        persistence_store=store,
        audit_recorder=conditional_audit,
    )
    worker.start()
    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )
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
    assert updated["status"] == "open"
    stored = store.get_incident(incident["incidentId"])
    assert stored is not None
    assert stored["status"] == "open"
    worker.stop()
    clear_runtime_state()


def test_incident_worker_rolls_back_update_when_persisting_existing_incident_fails() -> None:
    clear_runtime_state()
    store = FailOnUpdateIncidentStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager, persistence_store=store)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
            },
            source="test",
        )
    )
    incident_id = worker.list_incidents()[0]["incidentId"]
    store._fail_on_existing = True

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "sentry",
                "dedupKey": "sentry-event-rollback",
            },
            source="test",
        )
    )

    updated = worker.get_incident(incident_id)
    stored = store.get_incident(incident_id)

    assert updated is not None
    assert stored is not None
    assert updated["occurrenceCount"] == 1
    assert stored["occurrenceCount"] == 1
    assert updated["sourceSystem"] is None
    assert stored["sourceSystem"] is None
    assert updated["dedupKey"] is None
    assert stored["dedupKey"] is None
    worker.stop()
    clear_runtime_state()
