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


def test_insert_task_mirrors_dedup_key_to_control_plane() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_mod = _reload_db_module(tmpdir)
        db_mod.init_db()

        # Verify idempotent dedup_key migration added the column
        import sqlite3 as _sqlite3

        with _sqlite3.connect(os.fspath(db_mod.DB_PATH)) as _conn:
            cols = {row[1] for row in _conn.execute("PRAGMA table_info(agent_tasks)").fetchall()}
        assert "dedup_key" in cols

        store = RecordingStore()
        db_mod.enable_control_plane_dual_write(store)

        # Case 1: dedup_key provided directly on the task dict
        db_mod.insert_task(
            {
                "id": "task-dedup-direct",
                "repo": "acme/platform",
                "title": "Direct dedup key",
                "status": "queued",
                "dedup_key": "incident-direct-1",
            }
        )
        assert store.work_items[-1]["dedupKey"] == "incident-direct-1"

        # Case 2: dedupKey in metadata (camelCase preferred)
        db_mod.insert_task(
            {
                "id": "task-dedup-metacamel",
                "repo": "acme/platform",
                "title": "Metadata camelCase dedup",
                "status": "queued",
                "metadata": {"dedupKey": "incident-meta-cc"},
            }
        )
        assert store.work_items[-1]["dedupKey"] == "incident-meta-cc"

        # Case 3: dedup_key in metadata (snake_case fallback)
        db_mod.insert_task(
            {
                "id": "task-dedup-metasnake",
                "repo": "acme/platform",
                "title": "Metadata snake_case dedup",
                "status": "queued",
                "metadata": {"dedup_key": "incident-meta-sc"},
            }
        )
        assert store.work_items[-1]["dedupKey"] == "incident-meta-sc"

        # Case 4: no dedup key anywhere -> None
        db_mod.insert_task(
            {
                "id": "task-dedup-absent",
                "repo": "acme/platform",
                "title": "No dedup key",
                "status": "queued",
            }
        )
        assert store.work_items[-1]["dedupKey"] is None

        # Case 5: top-level camelCase dedupKey (PR-0.4: legacy entrypoint compat)
        db_mod.insert_task(
            {
                "id": "task-dedup-topcamel",
                "repo": "acme/platform",
                "title": "Top-level camelCase dedup",
                "status": "queued",
                "dedupKey": "incident-top-cc",
            }
        )
        assert store.work_items[-1]["dedupKey"] == "incident-top-cc"


def test_insert_task_prefers_snake_case_when_both_top_level_aliases_present() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_mod = _reload_db_module(tmpdir)
        db_mod.init_db()
        store = RecordingStore()
        db_mod.enable_control_plane_dual_write(store)

        # Both aliases present: snake_case wins (matches file convention)
        db_mod.insert_task(
            {
                "id": "task-dedup-both",
                "repo": "acme/platform",
                "title": "Both aliases present",
                "status": "queued",
                "dedup_key": "snake-wins",
                "dedupKey": "camel-loses",
            }
        )
        assert store.work_items[-1]["dedupKey"] == "snake-wins"
