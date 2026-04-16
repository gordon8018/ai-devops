from __future__ import annotations

from typing import Any, Callable
import time

from orchestrator.api.events import Event, EventManager, EventType
from packages.incident.triage.service import TriageEngine
from packages.incident.verify.service import VerifyEngine
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
    ) -> None:
        self._event_manager = event_manager
        self._triage_engine = triage_engine or TriageEngine()
        self._verify_engine = verify_engine or VerifyEngine()
        self._incidents: dict[str, dict[str, Any]] = {}
        self._unsubscribe: Callable[[], None] | None = None

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
        return list(self._incidents.values())

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
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
        incident = self._incidents.get(incident_id)
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
            }
            self._incidents[incident_id] = incident
            record_audit_event(
                AuditEvent(
                    audit_event_id=f"ae_{incident_id}_opened_{int(time.time() * 1000)}",
                    entity_type="incident",
                    entity_id=incident_id,
                    action="incident_opened",
                    payload={"severity": incident["severity"], "message": message},
                )
            )
        incident["occurrenceCount"] += 1

    def _verify_incident(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "incident_verify":
            return
        incident_id = str(payload.get("incident_id") or "").strip()
        incident = self._incidents.get(incident_id)
        if incident is None:
            return
        if self._verify_engine.should_close(resolved=bool(payload.get("resolved"))):
            incident["status"] = "closed"
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
