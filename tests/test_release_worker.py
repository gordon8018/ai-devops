from __future__ import annotations

from orchestrator.api.events import Event, EventManager, EventType
from apps.release_worker.service import ReleaseWorker
from packages.shared.domain.runtime_state import clear_runtime_state, list_audit_events


class InMemoryReleaseStore:
    def __init__(self) -> None:
        self.releases: dict[str, dict] = {}

    def save_release(self, release: dict) -> None:
        self.releases[release["workItemId"]] = dict(release)

    def get_release(self, work_item_id: str) -> dict | None:
        release = self.releases.get(work_item_id)
        return dict(release) if release is not None else None

    def list_releases(self) -> list[dict]:
        return [dict(release) for release in self.releases.values()]


class RecordingFlagAdapter:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []

    def apply_stage(self, release_id: str, stage: str) -> None:
        self.applied.append((release_id, stage))


def test_release_worker_starts_rollout_on_ready_event() -> None:
    clear_runtime_state()
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
    assert list_audit_events()[-1]["actorId"] == "system:release_worker"
    assert list_audit_events()[-1]["actorType"] == "system"
    worker.stop()
    clear_runtime_state()


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


def test_release_worker_advance_moves_stage_to_full_and_marks_succeeded() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_advance",
                "status": "ready",
                "details": {"work_item_id": "wi_advance"},
            },
            source="test",
        )
    )

    for _ in range(5):
        worker.advance("wi_advance")

    release = worker.get_release("wi_advance")

    assert release is not None
    assert release["stage"] == "full"
    assert release["status"] == "succeeded"
    assert flag_adapter.applied == [
        ("rel_wi_advance", "team-only"),
        ("rel_wi_advance", "beta"),
        ("rel_wi_advance", "1%"),
        ("rel_wi_advance", "5%"),
        ("rel_wi_advance", "20%"),
        ("rel_wi_advance", "full"),
    ]
    worker.stop()


def test_release_worker_advance_is_noop_after_rollback() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_rb",
                "status": "ready",
                "details": {"work_item_id": "wi_rb"},
            },
            source="test",
        )
    )
    event_manager.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={
                "type": "guardrail_breach",
                "work_item_id": "wi_rb",
                "guardrails": {"error_rate": 0.07},
                "thresholds": {"error_rate": 0.05},
            },
            source="test",
        )
    )

    worker.advance("wi_rb")

    release = worker.get_release("wi_rb")

    assert release is not None
    assert release["status"] == "rolled_back"
    assert release["stage"] == "team-only"
    worker.stop()


def test_release_worker_advance_returns_none_for_unknown_work_item() -> None:
    worker = ReleaseWorker(event_manager=EventManager(), flag_adapter=RecordingFlagAdapter())
    worker.start()
    assert worker.advance("wi_does_not_exist") is None
    worker.stop()


def test_release_worker_persists_succeeded_state_to_store() -> None:
    store = InMemoryReleaseStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = ReleaseWorker(
        event_manager=event_manager,
        flag_adapter=RecordingFlagAdapter(),
        persistence_store=store,
    )
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_succ",
                "status": "ready",
                "details": {"work_item_id": "wi_succ"},
            },
            source="test",
        )
    )
    for _ in range(5):
        worker.advance("wi_succ")

    stored = store.get_release("wi_succ")
    assert stored is not None
    assert stored["stage"] == "full"
    assert stored["status"] == "succeeded"
    worker.stop()


def test_release_worker_persists_intermediate_stages_to_store() -> None:
    store = InMemoryReleaseStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = ReleaseWorker(
        event_manager=event_manager,
        flag_adapter=RecordingFlagAdapter(),
        persistence_store=store,
    )
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_mid",
                "status": "ready",
                "details": {"work_item_id": "wi_mid"},
            },
            source="test",
        )
    )
    worker.advance("wi_mid")
    worker.advance("wi_mid")

    stored = store.get_release("wi_mid")
    assert stored is not None
    assert stored["stage"] == "1%"
    assert stored["status"] == "rolling_out"
    worker.stop()


def test_release_worker_does_not_reset_existing_release_on_duplicate_ready_event() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    ready_event = Event(
        event_type=EventType.TASK_STATUS,
        data={
            "task_id": "wi_dup_ready",
            "status": "ready",
            "details": {"work_item_id": "wi_dup_ready"},
        },
        source="test",
    )
    event_manager.publish(ready_event)
    worker.advance("wi_dup_ready")
    worker.advance("wi_dup_ready")

    event_manager.publish(ready_event)

    release = worker.get_release("wi_dup_ready")

    assert release is not None
    assert release["stage"] == "1%"
    assert release["status"] == "rolling_out"
    assert flag_adapter.applied == [
        ("rel_wi_dup_ready", "team-only"),
        ("rel_wi_dup_ready", "beta"),
        ("rel_wi_dup_ready", "1%"),
    ]
    worker.stop()


def test_release_worker_reads_releases_from_persistent_store_across_instances() -> None:
    store = InMemoryReleaseStore()
    event_manager = EventManager()
    event_manager.clear_history()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=RecordingFlagAdapter(), persistence_store=store)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_003",
                "status": "ready",
                "details": {"work_item_id": "wi_003"},
            },
            source="test",
        )
    )
    worker.stop()

    restored_worker = ReleaseWorker(
        event_manager=EventManager(),
        flag_adapter=RecordingFlagAdapter(),
        persistence_store=store,
    )

    release = restored_worker.get_release("wi_003")

    assert release is not None
    assert release["releaseId"] == "rel_wi_003"


def test_release_worker_rolls_back_persisted_release_after_restart() -> None:
    store = InMemoryReleaseStore()
    event_manager = EventManager()
    event_manager.clear_history()
    first_worker = ReleaseWorker(
        event_manager=event_manager,
        flag_adapter=RecordingFlagAdapter(),
        persistence_store=store,
    )
    first_worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={
                "task_id": "wi_persisted_rb",
                "status": "ready",
                "details": {"work_item_id": "wi_persisted_rb"},
            },
            source="test",
        )
    )
    first_worker.stop()

    restarted_worker = ReleaseWorker(
        event_manager=event_manager,
        flag_adapter=RecordingFlagAdapter(),
        persistence_store=store,
    )
    restarted_worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.SYSTEM,
            data={
                "type": "guardrail_breach",
                "work_item_id": "wi_persisted_rb",
                "guardrails": {"error_rate": 0.07},
                "thresholds": {"error_rate": 0.05},
            },
            source="test",
        )
    )

    release = restarted_worker.get_release("wi_persisted_rb")

    assert release is not None
    assert release["status"] == "rolled_back"
    restarted_worker.stop()
