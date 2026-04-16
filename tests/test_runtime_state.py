from __future__ import annotations

from packages.shared.domain.models import AuditEvent, EvalRun, EvalRunStatus
from packages.shared.domain.runtime_state import (
    clear_runtime_state,
    configure_runtime_persistence,
    list_audit_events,
    list_eval_runs,
    record_audit_event,
    record_eval_run,
)


class RecordingStore:
    def __init__(self) -> None:
        self.audit_events: list[dict] = []
        self.eval_runs: list[dict] = []

    def save_audit_event(self, audit_event: AuditEvent) -> None:
        self.audit_events.append(audit_event.to_dict())

    def save_eval_run(self, eval_run: EvalRun) -> None:
        self.eval_runs.append(eval_run.to_dict())

    def list_audit_events(self) -> list[dict]:
        return list(self.audit_events)

    def list_eval_runs(self) -> list[dict]:
        return list(self.eval_runs)


def test_runtime_state_mirrors_audit_events_and_eval_runs_to_persistent_store() -> None:
    clear_runtime_state()
    store = RecordingStore()
    configure_runtime_persistence(store=store)

    record_audit_event(
        AuditEvent(
            audit_event_id="ae_001",
            entity_type="work_item",
            entity_id="wi_001",
            action="work_item_created",
            payload={"repo": "acme/platform"},
        )
    )
    record_eval_run(
        EvalRun(
            eval_run_id="eval_001",
            work_item_id="wi_001",
            status=EvalRunStatus.PASSED,
            summary="healthy",
            payload={"successRate": 1.0},
        )
    )

    assert list_audit_events()[0]["auditEventId"] == "ae_001"
    assert list_eval_runs()[0]["evalRunId"] == "eval_001"
    assert store.audit_events[0]["action"] == "work_item_created"
    assert store.eval_runs[0]["status"] == "passed"

    configure_runtime_persistence(store=None)
    clear_runtime_state()


def test_runtime_state_does_not_persist_unchanged_eval_run_twice() -> None:
    clear_runtime_state()
    store = RecordingStore()
    configure_runtime_persistence(store=store)
    eval_run = EvalRun(
        eval_run_id="eval_001",
        work_item_id="wi_001",
        status=EvalRunStatus.PASSED,
        summary="healthy",
        payload={"successRate": 1.0},
    )

    record_eval_run(eval_run)
    record_eval_run(eval_run)

    assert len(list_eval_runs()) == 1
    assert len(store.eval_runs) == 1

    configure_runtime_persistence(store=None)
    clear_runtime_state()


def test_runtime_state_reads_audit_events_and_eval_runs_from_persistent_store() -> None:
    clear_runtime_state()
    store = RecordingStore()
    store.audit_events.append(
        AuditEvent(
            audit_event_id="ae_001",
            entity_type="work_item",
            entity_id="wi_001",
            action="work_item_created",
            payload={"repo": "acme/platform"},
        ).to_dict()
    )
    store.eval_runs.append(
        EvalRun(
            eval_run_id="eval_001",
            work_item_id="wi_001",
            status=EvalRunStatus.PASSED,
            summary="healthy",
            payload={"successRate": 1.0},
        ).to_dict()
    )
    configure_runtime_persistence(store=store)

    assert list_audit_events()[0]["auditEventId"] == "ae_001"
    assert list_eval_runs()[0]["evalRunId"] == "eval_001"

    configure_runtime_persistence(store=None)
    clear_runtime_state()
