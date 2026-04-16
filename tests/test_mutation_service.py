from __future__ import annotations

import pytest

from packages.shared.mutation.service import MutationService


def test_mutation_service_runs_state_then_audit_then_events() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()
    service.apply(
        persist=persist,
        audit=audit,
        publish_events=[publish],
    )

    assert calls == ["persist", "audit", "publish"]


def test_mutation_service_skips_audit_and_events_when_persist_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")
        raise RuntimeError("persist failed")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()

    with pytest.raises(RuntimeError, match="persist failed"):
        service.apply(persist=persist, audit=audit, publish_events=[publish])

    assert calls == ["persist"]


def test_mutation_service_rolls_back_when_audit_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")
        raise RuntimeError("audit failed")

    def rollback() -> None:
        calls.append("rollback")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()

    with pytest.raises(RuntimeError, match="audit failed"):
        service.apply(
            persist=persist,
            audit=audit,
            publish_events=[publish],
            rollback=rollback,
        )

    assert calls == ["persist", "audit", "rollback"]


def test_mutation_service_reraises_audit_failure_without_rollback() -> None:
    service = MutationService()

    with pytest.raises(RuntimeError, match="audit failed"):
        service.apply(
            persist=lambda: None,
            audit=lambda: (_ for _ in ()).throw(RuntimeError("audit failed")),
        )


def test_mutation_service_raises_when_event_publish_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")
        raise RuntimeError("publish failed")

    service = MutationService()

    with pytest.raises(RuntimeError, match="publish failed"):
        service.apply(
            persist=persist,
            audit=audit,
            publish_events=[publish],
        )

    assert calls == ["persist", "audit", "publish"]
