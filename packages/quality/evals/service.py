from __future__ import annotations

from packages.shared.domain.models import EvalRun, EvalRunStatus


class EvalEngine:
    """Build structured eval runs from recent platform events."""

    def evaluate_work_item(self, *, work_item_id: str, events: list[dict]) -> EvalRun:
        def _matches_work_item(event: dict) -> bool:
            data = dict(event.get("data") or {})
            details = dict(data.get("details") or {})
            return any(
                candidate == work_item_id
                for candidate in (
                    data.get("task_id"),
                    data.get("work_item_id"),
                    details.get("task_id"),
                    details.get("work_item_id"),
                )
            )

        relevant = [
            event
            for event in events
            if _matches_work_item(event)
        ]
        task_statuses = [
            event.get("data", {}).get("status")
            for event in relevant
            if event.get("type") == "task_status"
        ]
        status_counts = {
            status: task_statuses.count(status)
            for status in set(task_statuses)
            if status is not None
        }
        alert_count = sum(1 for event in relevant if event.get("type") == "alert")
        if status_counts.get("failed"):
            status = EvalRunStatus.FAILED
        else:
            status = EvalRunStatus.PASSED

        return EvalRun(
            eval_run_id=f"eval_{work_item_id}",
            work_item_id=work_item_id,
            status=status,
            summary=f"{len(task_statuses)} task events, {alert_count} alerts",
            payload={
                "taskStatusCounts": status_counts,
                "alertCount": alert_count,
            },
        )
