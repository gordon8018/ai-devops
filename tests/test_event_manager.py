from __future__ import annotations

import importlib
import os
import tempfile

from orchestrator.api.events import EventManager


def test_event_manager_get_history_supports_limit_slicing() -> None:
    manager = EventManager()
    manager.clear_history()

    manager.publish_task_status("task_001", "running", {})
    manager.publish_task_status("task_002", "ready", {})

    history = manager.get_history(limit=1)

    assert len(history) == 1
    assert history[0]["data"]["task_id"] == "task_002"


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
