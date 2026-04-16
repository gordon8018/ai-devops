from __future__ import annotations

from packages.shared.domain.models import QualityRun, QualityRunStatus


class QualityGateRunner:
    """Aggregate explicit quality gate results into a structured QualityRun."""

    def run(self, *, work_item_id: str, gate_results: dict[str, dict]) -> QualityRun:
        total = len(gate_results)
        passed = sum(1 for result in gate_results.values() if result.get("passed"))
        status = QualityRunStatus.PASSED if passed == total else QualityRunStatus.FAILED
        summary = f"{passed}/{total} gates passed"

        return QualityRun(
            quality_run_id=f"qr_{work_item_id}_{total}",
            work_item_id=work_item_id,
            gate_type="composite",
            status=status,
            summary=summary,
            payload={"gates": gate_results, "passedCount": passed, "totalCount": total},
        )
