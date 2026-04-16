from __future__ import annotations

from packages.shared.domain.control_plane import ensure_control_plane_store
from packages.shared.domain.models import AuditEvent, EvalRun

_AUDIT_EVENTS: list[dict] = []
_EVAL_RUNS: list[dict] = []
_PERSISTENCE_STORE = None


def configure_runtime_persistence(*, store=None) -> None:
    global _PERSISTENCE_STORE
    _PERSISTENCE_STORE = store


def record_audit_event(event: AuditEvent) -> None:
    _AUDIT_EVENTS.append(event.to_dict())
    if _PERSISTENCE_STORE is not None:
        _PERSISTENCE_STORE.save_audit_event(event)


def list_audit_events() -> list[dict]:
    store = _PERSISTENCE_STORE or ensure_control_plane_store()
    persisted = list(store.list_audit_events()) if store is not None and hasattr(store, "list_audit_events") else []
    merged = {
        event.get("auditEventId"): event
        for event in persisted + list(_AUDIT_EVENTS)
        if event.get("auditEventId")
    }
    return list(merged.values())


def record_eval_run(eval_run: EvalRun) -> None:
    incoming = eval_run.to_dict()
    existing = next((item for item in _EVAL_RUNS if item.get("evalRunId") == eval_run.eval_run_id), None)
    filtered = [item for item in _EVAL_RUNS if item.get("evalRunId") != eval_run.eval_run_id]
    filtered.append(incoming)
    _EVAL_RUNS.clear()
    _EVAL_RUNS.extend(filtered)
    if _PERSISTENCE_STORE is not None and existing != incoming:
        _PERSISTENCE_STORE.save_eval_run(eval_run)


def list_eval_runs() -> list[dict]:
    store = _PERSISTENCE_STORE or ensure_control_plane_store()
    persisted = list(store.list_eval_runs()) if store is not None and hasattr(store, "list_eval_runs") else []
    merged = {
        event.get("evalRunId"): event
        for event in persisted + list(_EVAL_RUNS)
        if event.get("evalRunId")
    }
    return list(merged.values())


def clear_runtime_state() -> None:
    _AUDIT_EVENTS.clear()
    _EVAL_RUNS.clear()
