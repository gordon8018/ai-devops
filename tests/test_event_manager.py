from __future__ import annotations

import importlib
import os
import tempfile

from orchestrator.api.events import Event, EventManager, EventType


def test_event_to_dict_includes_event_name_and_actor_fields() -> None:
    event = Event(
        event_type=EventType.SYSTEM,
        event_name="work_item.created",
        data={"workItemId": "wi_001"},
        source="kernel",
        actor_id="system:kernel",
        actor_type="system",
    )

    payload = event.to_dict()

    assert payload["type"] == "system"
    assert payload["eventName"] == "work_item.created"
    assert payload["actorId"] == "system:kernel"
    assert payload["actorType"] == "system"


def test_event_to_dict_omits_event_name_when_unset() -> None:
    event = Event(
        event_type=EventType.SYSTEM,
        data={"workItemId": "wi_001"},
        source="kernel",
    )

    payload = event.to_dict()

    assert "eventName" not in payload


def test_event_manager_get_history_supports_limit_slicing() -> None:
    manager = EventManager()
    manager.clear_history()

    manager.publish_task_status("task_001", "running", {})
    manager.publish_task_status("task_002", "ready", {})

    history = manager.get_history(limit=1)

    assert len(history) == 1
    assert history[0]["data"]["task_id"] == "task_002"


def test_publish_task_status_sets_default_actor_and_legacy_event_name() -> None:
    manager = EventManager()
    manager.clear_history()

    manager.publish_task_status("task_001", "ready", {"work_item_id": "wi_001"}, source="test")

    history = manager.get_history(limit=1)

    assert history[0]["type"] == "task_status"
    assert history[0]["eventName"] == "task.status_changed"
    assert history[0]["actorId"] == "system:legacy"
    assert history[0]["actorType"] == "system"


def test_event_manager_reads_shared_journal_when_in_memory_history_is_empty() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        original_home = os.environ.get("AI_DEVOPS_HOME")
        os.environ["AI_DEVOPS_HOME"] = tmpdir
        try:
            import orchestrator.api.events as events_mod

            importlib.reload(events_mod)
            events_mod.EventManager._instance = None

            manager = events_mod.EventManager()
            manager.clear_history()
            manager.publish_task_status("task_003", "ready", {"source": "runner"})
            manager._event_history.clear()

            history = manager.get_history(limit=10)

            assert len(history) == 1
            assert history[0]["data"]["task_id"] == "task_003"
            assert history[0]["data"]["status"] == "ready"
        finally:
            events_mod.EventManager._instance = None
            if original_home is None:
                os.environ.pop("AI_DEVOPS_HOME", None)
            else:
                os.environ["AI_DEVOPS_HOME"] = original_home
