from __future__ import annotations

from packages.quality.evals.service import EvalEngine
from packages.shared.domain.models import EvalRunStatus


def test_eval_engine_builds_eval_run_from_task_events() -> None:
    engine = EvalEngine()

    eval_run = engine.evaluate_work_item(
        work_item_id="wi_001",
        events=[
            {"type": "task_status", "data": {"task_id": "wi_001", "status": "running"}},
            {"type": "task_status", "data": {"task_id": "wi_001", "status": "ready"}},
            {"type": "alert", "data": {"work_item_id": "wi_001", "message": "guardrail breach"}},
        ],
    )

    assert eval_run.status is EvalRunStatus.PASSED
    assert eval_run.payload["taskStatusCounts"]["running"] == 1
    assert eval_run.payload["taskStatusCounts"]["ready"] == 1
    assert eval_run.payload["alertCount"] == 1


def test_eval_engine_ignores_alerts_for_other_work_items() -> None:
    engine = EvalEngine()

    eval_run = engine.evaluate_work_item(
        work_item_id="wi_001",
        events=[
            {"type": "task_status", "data": {"task_id": "wi_001", "status": "running"}},
            {"type": "alert", "data": {"work_item_id": "wi_002", "message": "guardrail breach"}},
            {"type": "alert", "data": {"task_id": "wi_002", "message": "incident opened"}},
        ],
    )

    assert eval_run.status is EvalRunStatus.PASSED
    assert eval_run.payload["taskStatusCounts"]["running"] == 1
    assert eval_run.payload["alertCount"] == 0
