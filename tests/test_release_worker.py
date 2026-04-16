from __future__ import annotations

from orchestrator.api.events import Event, EventManager, EventType
from apps.release_worker.service import ReleaseWorker


class RecordingFlagAdapter:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []

    def apply_stage(self, release_id: str, stage: str) -> None:
        self.applied.append((release_id, stage))


def test_release_worker_starts_rollout_on_ready_event() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_001",
                "status": "ready",
                "details": {"work_item_id": "wi_001"},
            },
            source="test",
        )
    )

    release = worker.get_release("wi_001")

    assert release is not None
    assert release["stage"] == "team-only"
    assert flag_adapter.applied == [("rel_wi_001", "team-only")]
    worker.stop()


def test_release_worker_rolls_back_on_guardrail_breach() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_002",
                "status": "ready",
                "details": {"work_item_id": "wi_002"},
            },
            source="test",
        )
    )
    event_manager.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={
                "type": "guardrail_breach",
                "work_item_id": "wi_002",
                "guardrails": {"error_rate": 0.07},
                "thresholds": {"error_rate": 0.05},
            },
            source="test",
        )
    )

    release = worker.get_release("wi_002")
    history = event_manager.get_history(limit=10)

    assert release is not None
    assert release["status"] == "rolled_back"
    assert release["rollbackReason"].startswith("guardrail breach")
    assert any(event["type"] == "alert" for event in history)
    worker.stop()
