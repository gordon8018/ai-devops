from __future__ import annotations

from packages.release.rollback.service import RollbackController


def test_rollback_controller_triggers_on_guardrail_breach() -> None:
    controller = RollbackController()

    decision = controller.evaluate(
        guardrails={"error_rate": 0.08, "latency_p95_ms": 320},
        thresholds={"error_rate": 0.05, "latency_p95_ms": 400},
    )

    assert decision.should_rollback is True
    assert "error_rate" in decision.reason


def test_rollback_controller_allows_rollout_when_guardrails_hold() -> None:
    controller = RollbackController()

    decision = controller.evaluate(
        guardrails={"error_rate": 0.02, "latency_p95_ms": 320},
        thresholds={"error_rate": 0.05, "latency_p95_ms": 400},
    )

    assert decision.should_rollback is False
