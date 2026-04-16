from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RollbackDecision:
    should_rollback: bool
    reason: str


class RollbackController:
    """Evaluate guardrail metrics against rollback thresholds."""

    def evaluate(self, *, guardrails: dict[str, float], thresholds: dict[str, float]) -> RollbackDecision:
        for metric_name, threshold in thresholds.items():
            value = guardrails.get(metric_name)
            if value is None:
                continue
            if value > threshold:
                return RollbackDecision(
                    should_rollback=True,
                    reason=f"guardrail breach: {metric_name}={value} > {threshold}",
                )

        return RollbackDecision(should_rollback=False, reason="all guardrails within thresholds")
