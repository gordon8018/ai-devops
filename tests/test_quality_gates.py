from __future__ import annotations

from packages.quality.gates.service import QualityGateRunner
from packages.shared.domain.models import QualityRunStatus


def test_quality_gate_runner_returns_failed_quality_run_when_any_gate_fails() -> None:
    runner = QualityGateRunner()

    result = runner.run(
        work_item_id="wi_001",
        gate_results={
            "lint": {"passed": True, "summary": "lint clean"},
            "unit": {"passed": False, "summary": "2 tests failed"},
        },
    )

    assert result.status is QualityRunStatus.FAILED
    assert result.payload["gates"]["unit"]["passed"] is False


def test_quality_gate_runner_returns_passed_quality_run_when_all_gates_pass() -> None:
    runner = QualityGateRunner()

    result = runner.run(
        work_item_id="wi_002",
        gate_results={
            "lint": {"passed": True, "summary": "lint clean"},
            "unit": {"passed": True, "summary": "tests passed"},
        },
    )

    assert result.status is QualityRunStatus.PASSED
    assert "2/2" in result.summary
