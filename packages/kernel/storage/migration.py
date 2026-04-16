from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from packages.shared.domain.models import AuditEvent, WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


def _map_status(status: str) -> WorkItemStatus:
    mapping = {
        "queued": WorkItemStatus.QUEUED,
        "running": WorkItemStatus.RUNNING,
        "blocked": WorkItemStatus.BLOCKED,
        "ready": WorkItemStatus.READY,
        "merged": WorkItemStatus.RELEASED,
        "completed": WorkItemStatus.CLOSED,
    }
    return mapping.get(str(status).strip().lower(), WorkItemStatus.QUEUED)


class SQLiteToPostgresMigrator:
    """Backfills legacy SQLite task state into the new control-plane store."""

    def __init__(self, sqlite_path: str | Path, control_plane_store: Any) -> None:
        self.sqlite_path = Path(sqlite_path)
        self.control_plane_store = control_plane_store

    def migrate_agent_tasks(self) -> dict[str, int]:
        migrated = 0
        with sqlite3.connect(self.sqlite_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, repo, title, status, note, metadata, created_at FROM agent_tasks"
            ).fetchall()

        for row in rows:
            metadata = self._parse_json(row["metadata"])
            description = str(metadata.get("description") or row["title"])
            work_item = WorkItem(
                work_item_id=f"wi_{row['id']}",
                type=WorkItemType.FEATURE,
                title=str(row["title"]),
                goal=description,
                priority=WorkItemPriority.MEDIUM,
                status=_map_status(str(row["status"])),
                repo=str(row["repo"]),
                requested_by="sqlite-migration",
                requested_at=int(row["created_at"] or 0),
                source="sqlite-migration",
                metadata={"legacyTaskId": row["id"], "legacyMetadata": metadata},
            )
            self.control_plane_store.save_work_item(work_item)
            self.control_plane_store.save_audit_event(
                AuditEvent(
                    audit_event_id=f"ae_{row['id']}",
                    entity_type="work_item",
                    entity_id=work_item.work_item_id,
                    action="migrated_from_sqlite",
                    payload={
                        "legacyTaskId": row["id"],
                        "legacyStatus": row["status"],
                        "note": row["note"] or "",
                    },
                    created_at=int(row["created_at"] or 0),
                )
            )
            migrated += 1

        return {"migrated": migrated}

    @staticmethod
    def _parse_json(raw: Any) -> dict[str, Any]:
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
