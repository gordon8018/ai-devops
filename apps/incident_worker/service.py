from __future__ import annotations

from typing import Any, Callable
import time

from orchestrator.api.events import Event, EventManager, EventType
from packages.incident.triage.service import TriageEngine
from packages.incident.verify.service import VerifyEngine
from packages.shared.domain.control_plane import ensure_control_plane_store
from packages.shared.domain.models import AuditEvent
from packages.shared.domain.runtime_state import record_audit_event

_GLOBAL_INCIDENT_WORKER: "IncidentWorker | None" = None


class IncidentWorker:
    """Consume alerts, cluster incidents, and close them after verification."""

    def __init__(
        self,
        *,
        event_manager: EventManager,
        triage_engine: TriageEngine | None = None,
        verify_engine: VerifyEngine | None = None,
        persistence_store: Any | None = None,
    ) -> None:
        self._event_manager = event_manager
        self._triage_engine = triage_engine or TriageEngine()
        self._verify_engine = verify_engine or VerifyEngine()
        self._persistence_store = persistence_store or ensure_control_plane_store()
        self._incidents: dict[str, dict[str, Any]] = {}
        self._unsubscribe: Callable[[], None] | None = None

    def _store(self) -> Any | None:
        return self._persistence_store or ensure_control_plane_store()

    def start(self) -> None:
        global _GLOBAL_INCIDENT_WORKER
        if self._unsubscribe is None:
            self._unsubscribe = self._event_manager.subscribe(
                self._handle_event,
                event_types=[EventType.ALERT, EventType.SYSTEM],
            )
            _GLOBAL_INCIDENT_WORKER = self

    def stop(self) -> None:
        global _GLOBAL_INCIDENT_WORKER
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
            if _GLOBAL_INCIDENT_WORKER is self:
                _GLOBAL_INCIDENT_WORKER = None

    def list_incidents(self) -> list[dict[str, Any]]:
        store = self._store()
        if store is not None and hasattr(store, "list_incidents"):
            incidents = list(store.list_incidents())
            if incidents:
                return incidents
        return list(self._incidents.values())

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        store = self._store()
        if store is not None and hasattr(store, "get_incident"):
            incident = store.get_incident(incident_id)
            if incident is not None:
                return incident
        return self._incidents.get(incident_id)

    def _handle_event(self, event: Event) -> None:
        if event.event_type is EventType.ALERT:
            self._ingest_alert(event.data)
            return
        if event.event_type is EventType.SYSTEM:
            self._verify_incident(event.data)

    def _ingest_alert(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message") or "").strip()
        if not message:
            return
        incident_id = self._triage_engine.fingerprint(message)
        # PR-0.4: resolve through the store so a restarted worker sees previously
        # persisted incidents instead of treating them as new.
        incident = self.get_incident(incident_id)
        source_system = (
            str(payload.get("sourceSystem") or payload.get("source_system") or "").strip()
            or None
        )
        dedup_key = (
            str(payload.get("dedupKey") or payload.get("dedup_key") or "").strip()
            or None
        )
        if incident is None:
            incident = {
                "incidentId": incident_id,
                "message": message,
                "severity": self._triage_engine.score(
                    level=str(payload.get("level") or "warning"),
                    message=message,
                ),
                "status": "open",
                "occurrenceCount": 0,
                "details": payload.get("details") or {},
                "sourceSystem": source_system,
                "dedupKey": dedup_key,
            }
            self._incidents[incident_id] = incident
            store = self._store()
            if store is not None and hasattr(store, "save_incident"):
                store.save_incident(incident)
            record_audit_event(
                AuditEvent(
                    audit_event_id=f"ae_{incident_id}_opened_{int(time.time() * 1000)}",
                    entity_type="incident",
                    entity_id=incident_id,
                    action="incident_opened",
                    payload={"severity": incident["severity"], "message": message},
                )
            )
        else:
            # PR-0.4: first non-null identity value wins and sticks. If a later
            # alert finally carries sourceSystem / dedupKey while the existing
            # incident has None, backfill — but never overwrite an already-set
            # value even if the new alert brings a different one.
            if source_system is not None and not incident.get("sourceSystem"):
                incident["sourceSystem"] = source_system
            if dedup_key is not None and not incident.get("dedupKey"):
                incident["dedupKey"] = dedup_key
            # Keep the in-memory cache coherent with the (possibly store-fetched)
            # incident so subsequent operations see the mutated copy.
            self._incidents[incident_id] = incident
        incident["occurrenceCount"] += 1
        store = self._store()
        if store is not None and hasattr(store, "save_incident"):
            store.save_incident(incident)

    def _verify_incident(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "incident_verify":
            return
        incident_id = str(payload.get("incident_id") or "").strip()
        # PR-0.4: resolve through the store so a restarted worker can verify
        # incidents opened in prior runs.
        incident = self.get_incident(incident_id)
        if incident is None:
            return
        if self._verify_engine.should_close(resolved=bool(payload.get("resolved"))):
            incident["status"] = "closed"
            self._incidents[incident_id] = incident
            store = self._store()
            if store is not None and hasattr(store, "save_incident"):
                store.save_incident(incident)
            record_audit_event(
                AuditEvent(
                    audit_event_id=f"ae_{incident_id}_closed_{int(time.time() * 1000)}",
                    entity_type="incident",
                    entity_id=incident_id,
                    action="incident_closed",
                    payload={"resolved": True},
                )
            )


def get_global_incident_worker() -> IncidentWorker | None:
    return _GLOBAL_INCIDENT_WORKER
