from __future__ import annotations

from packages.quality.policy.service import PolicyEngine
from packages.shared.domain.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


def _work_item(priority: WorkItemPriority = WorkItemPriority.MEDIUM) -> WorkItem:
    return WorkItem(
        work_item_id="wi_001",
        type=WorkItemType.FEATURE,
        title="Update auth rules",
        goal="Tighten auth checks",
        priority=priority,
        status=WorkItemStatus.PLANNING,
        repo="acme/platform",
    )


def test_policy_engine_requires_approval_for_sensitive_paths() -> None:
    engine = PolicyEngine()

    decision = engine.evaluate(
        _work_item(),
        touched_paths=("services/auth/service.py", "apps/api/server.py"),
    )

    assert decision.requires_approval is True
    assert decision.risk_level == "high"
    assert "auth" in decision.reason


def test_policy_engine_marks_critical_priority_as_manual_approval() -> None:
    engine = PolicyEngine()

    decision = engine.evaluate(
        _work_item(priority=WorkItemPriority.CRITICAL),
        touched_paths=("packages/kernel/runtime/services.py",),
    )

    assert decision.requires_approval is True
    assert decision.risk_level == "critical"
