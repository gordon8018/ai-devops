from __future__ import annotations

import importlib
import os
import sys
import tempfile


class RecordingStore:
    def __init__(self) -> None:
        self.work_items: list[dict] = []
        self.audit_events: list[dict] = []

    def save_work_item(self, work_item) -> None:
        self.work_items.append(work_item.to_dict())

    def save_audit_event(self, audit_event) -> None:
        self.audit_events.append(audit_event.to_dict())


def _reload_db_module(tmpdir: str):
    os.environ["AI_DEVOPS_HOME"] = tmpdir
    if "orchestrator.bin.db" in sys.modules:
        del sys.modules["orchestrator.bin.db"]
    import orchestrator.bin.db as db_mod
    importlib.reload(db_mod)
    return db_mod


def test_insert_task_dual_writes_to_control_plane_store() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_mod = _reload_db_module(tmpdir)
        db_mod.init_db()
        store = RecordingStore()
        db_mod.enable_control_plane_dual_write(store)

        db_mod.insert_task(
            {
                "id": "task-001",
                "repo": "acme/platform",
                "title": "Mirror task inserts",
                "status": "running",
            }
        )

        assert store.work_items[0]["repo"] == "acme/platform"
        assert store.audit_events[0]["action"] == "sqlite_task_inserted"


def test_update_task_dual_writes_latest_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_mod = _reload_db_module(tmpdir)
        db_mod.init_db()
        store = RecordingStore()
        db_mod.enable_control_plane_dual_write(store)

        db_mod.insert_task(
            {
                "id": "task-002",
                "repo": "acme/platform",
                "title": "Mirror task updates",
                "status": "queued",
            }
        )
        store.work_items.clear()
        store.audit_events.clear()

        db_mod.update_task("task-002", {"status": "running", "note": "started"})

        assert store.work_items[0]["status"] == "running"
        assert store.audit_events[0]["action"] == "sqlite_task_updated"


def test_configure_control_plane_dual_write_uses_store_builder() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_mod = _reload_db_module(tmpdir)
        db_mod.init_db()
        store = RecordingStore()
        db_mod._build_control_plane_store_from_dsn = lambda dsn: store

        db_mod.configure_control_plane_dual_write(dsn="postgresql://control-plane")
        db_mod.insert_task(
            {
                "id": "task-003",
                "repo": "acme/platform",
                "title": "Configured mirror",
                "status": "queued",
            }
        )

        assert store.work_items[0]["workItemId"] == "task-003"
