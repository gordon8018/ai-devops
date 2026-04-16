from __future__ import annotations

import time

import pytest

from orchestrator.api.events import EventManager
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import MissingContextPackError, MissingQualityRunError, WorkItemService
from packages.shared.domain.models import AgentRunStatus, QualityRun, QualityRunStatus, WorkItemStatus, WorkItemType


def test_create_legacy_session_builds_work_item_context_pack_and_plan_request() -> None:
    bus = InMemoryEventBus()
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())

    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Add rollout guardrails",
            "description": "Implement guardrail metrics and rollout checks",
            "requested_by": "tester",
            "requested_at": int(time.time() * 1000),
            "constraints": {
                "allowedPaths": ["packages/release/**"],
                "mustTouch": ["packages/release/rollout.py"],
            },
            "context": {
                "filesHint": ["packages/release/rollout.py"],
                "acceptanceCriteria": [
                    "Add rollout guardrail metrics",
                    "Keep existing retry safety checks",
                ],
                "knownFailures": ["prior rollout retried without metric thresholds"],
                "docs": ["docs/architecture/release.md"],
            },
        }
    )

    assert session.work_item.type is WorkItemType.FEATURE
    assert session.work_item.repo == "acme/platform"
    assert session.context_pack.work_item_id == session.work_item.work_item_id
    assert session.context_pack.repo_scope == (
        "packages/release/**",
        "packages/release/rollout.py",
    )
    assert session.context_pack.acceptance_criteria == (
        "Add rollout guardrail metrics",
        "Keep existing retry safety checks",
    )
    assert session.plan_request["context"]["contextPack"]["packId"] == session.context_pack.pack_id
    assert session.plan_request["context"]["workItem"]["workItemId"] == session.work_item.work_item_id
    assert [event.event_type for event in bus.history()] == [
        "work_item.created",
        "context_pack.created",
        "plan.requested",
    ]


def test_prepare_agent_run_requires_context_pack() -> None:
    service = WorkItemService(event_bus=InMemoryEventBus(), context_assembler=ContextPackAssembler())
    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Fix incident flow",
            "description": "Repair incident reopen workflow",
        }
    )

    with pytest.raises(MissingContextPackError):
        service.prepare_agent_run(
            work_item=session.work_item,
            context_pack=None,
            agent="codex",
            model="gpt-5.3-codex",
        )


def test_create_legacy_session_bridges_domain_events_to_event_manager() -> None:
    manager = EventManager()
    manager.clear_history()
    bus = InMemoryEventBus(event_manager=manager)
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())

    service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Bridge work item events",
            "description": "Ensure domain events leave kernel bus",
        }
    )

    history = manager.get_history(limit=3)

    assert [event["eventName"] for event in history] == [
        "work_item.created",
        "context_pack.created",
        "plan.requested",
    ]
    assert all(event["source"] == "kernel.work_items" for event in history)
    assert all(event["actorId"] == "system:kernel" for event in history)
    assert all(event["actorType"] == "system" for event in history)


def test_prepare_agent_run_binds_context_pack_and_starts_pending() -> None:
    bus = InMemoryEventBus()
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())
    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Index repo routes",
            "description": "Create context indexing for routes",
        }
    )

    run = service.prepare_agent_run(
        work_item=session.work_item,
        context_pack=session.context_pack,
        agent="codex",
        model="gpt-5.3-codex",
        planned_steps=("index", "pack"),
    )

    assert run.context_pack_id == session.context_pack.pack_id
    assert run.status is AgentRunStatus.PENDING
    assert run.planned_steps == ("index", "pack")
    assert bus.history()[-1].event_type == "agent_run.prepared"


def test_release_transition_requires_quality_run() -> None:
    service = WorkItemService(event_bus=InMemoryEventBus(), context_assembler=ContextPackAssembler())
    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Release canary rollout",
            "description": "Ship rollout controls safely",
        }
    )

    with pytest.raises(MissingQualityRunError):
        service.transition_work_item_status(
            session.work_item,
            target_status=WorkItemStatus.RELEASED,
            quality_run=None,
        )


def test_release_transition_accepts_passed_quality_run() -> None:
    service = WorkItemService(event_bus=InMemoryEventBus(), context_assembler=ContextPackAssembler())
    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Close guarded release",
            "description": "Require quality evidence before close",
        }
    )
    quality_run = QualityRun(
        quality_run_id="qr_001",
        work_item_id=session.work_item.work_item_id,
        gate_type="test",
        status=QualityRunStatus.PASSED,
        summary="Targeted checks passed",
    )

    transitioned = service.transition_work_item_status(
        session.work_item,
        target_status=WorkItemStatus.CLOSED,
        quality_run=quality_run,
    )

    assert transitioned.status is WorkItemStatus.CLOSED


def test_work_item_from_legacy_task_input_preserves_dedup_key() -> None:
    from packages.shared.domain.models import WorkItem

    work_item_camel = WorkItem.from_legacy_task_input(
        {
            "repo": "acme/platform",
            "title": "Dedup via camelCase",
            "description": "Should preserve dedupKey from camelCase input",
            "dedupKey": "incident-42",
        }
    )
    assert work_item_camel.dedup_key == "incident-42"
    assert work_item_camel.to_dict()["dedupKey"] == "incident-42"

    work_item_snake = WorkItem.from_legacy_task_input(
        {
            "repo": "acme/platform",
            "title": "Dedup via snake_case",
            "description": "Should also accept snake_case dedup_key",
            "dedup_key": "  incident-42  ",
        }
    )
    assert work_item_snake.dedup_key == "incident-42"

    work_item_empty = WorkItem.from_legacy_task_input(
        {
            "repo": "acme/platform",
            "title": "Missing dedup key",
            "description": "Empty/whitespace dedup keys should drop to None",
            "dedup_key": "   ",
        }
    )
    assert work_item_empty.dedup_key is None
    assert work_item_empty.to_dict()["dedupKey"] is None

    work_item_absent = WorkItem.from_legacy_task_input(
        {
            "repo": "acme/platform",
            "title": "Absent dedup key",
            "description": "No dedup key at all",
        }
    )
    assert work_item_absent.dedup_key is None
    assert work_item_absent.to_dict()["dedupKey"] is None
