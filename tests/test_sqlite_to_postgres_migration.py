from __future__ import annotations

import sqlite3

from packages.kernel.storage.migration import SQLiteToPostgresMigrator


class RecordingStore:
    def __init__(self) -> None:
        self.work_items: list[dict] = []
        self.audit_events: list[dict] = []

    def save_work_item(self, work_item) -> None:
        self.work_items.append(work_item.to_dict())

    def save_audit_event(self, audit_event) -> None:
        self.audit_events.append(audit_event.to_dict())


def test_sqlite_to_postgres_migrator_backfills_work_items_and_audit_events(tmp_path) -> None:
    sqlite_path = tmp_path / "agent_tasks.db"
    conn = sqlite3.connect(sqlite_path)
    conn.execute(
        """
        CREATE TABLE agent_tasks (
            id TEXT PRIMARY KEY,
            repo TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            metadata TEXT,
            created_at INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO agent_tasks (id, repo, title, status, note, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "task-001",
            "acme/platform",
            "Add context pack bootstrap",
            "running",
            "seeded from sqlite",
            '{"description": "Bootstrap context pack enforcement"}',
            1710000000000,
        ),
    )
    conn.commit()
    conn.close()

    store = RecordingStore()
    migrator = SQLiteToPostgresMigrator(sqlite_path, store)

    summary = migrator.migrate_agent_tasks()

    assert summary["migrated"] == 1
    assert store.work_items[0]["repo"] == "acme/platform"
    assert store.work_items[0]["title"] == "Add context pack bootstrap"
    assert store.audit_events[0]["entityId"] == store.work_items[0]["workItemId"]
