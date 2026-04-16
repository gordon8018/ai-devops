from __future__ import annotations

from dataclasses import dataclass

from packages.shared.domain.models import WorkItem, WorkItemPriority


@dataclass(slots=True, frozen=True)
class PolicyDecision:
    requires_approval: bool
    risk_level: str
    reason: str


class PolicyEngine:
    """Apply explicit approval policy for risky changes."""

    HIGH_RISK_KEYWORDS = ("auth", "payment", "permission", "migration", "infra", "terraform")

    def evaluate(self, work_item: WorkItem, *, touched_paths: tuple[str, ...]) -> PolicyDecision:
        if work_item.priority is WorkItemPriority.CRITICAL:
            return PolicyDecision(
                requires_approval=True,
                risk_level="critical",
                reason="critical priority work item requires manual approval",
            )

        for path in touched_paths:
            lowered = path.lower()
            for keyword in self.HIGH_RISK_KEYWORDS:
                if keyword in lowered:
                    return PolicyDecision(
                        requires_approval=True,
                        risk_level="high",
                        reason=f"sensitive path matched policy keyword: {keyword}",
                    )

        return PolicyDecision(
            requires_approval=False,
            risk_level="low" if work_item.priority is WorkItemPriority.LOW else "medium",
            reason="no sensitive paths matched approval policy",
        )
