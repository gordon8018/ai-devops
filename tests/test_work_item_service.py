from __future__ import annotations

import time

import pytest

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
