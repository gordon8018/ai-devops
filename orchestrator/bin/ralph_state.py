#!/usr/bin/env python3
"""
Ralph Execution State Storage Module
"""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


class RalphStateError(Exception):
    pass


class RalphState:
    def __init__(self, db_path: str | Path = None):
        if db_path is None:
            db_path = Path(__file__).parent.parent / "agent_tasks.db"
        self.db_path = Path(db_path)
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ralph_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    logs TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ralph_task_id 
                ON ralph_state(task_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_ralph_status 
                ON ralph_state(status)
            """)
            conn.commit()
        finally:
            conn.close()
    
    def create(self, task_id: str, status: str = "queued",
               progress: int = 0, logs: str = "",
               metadata: Dict[str, Any] = None) -> int:
        if metadata is None:
            metadata = {}
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "INSERT INTO ralph_state (task_id, status, progress, logs, metadata, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
                (task_id, status, progress, logs, json.dumps(metadata))
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            raise RalphStateError(f"Task ID already exists: {task_id}")
        finally:
            conn.close()
    
    def update(self, task_id: str, status: Optional[str] = None,
               progress: Optional[int] = None, logs: Optional[str] = None,
               metadata: Optional[Dict[str, Any]] = None) -> bool:
        updates = []
        values = []
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if progress is not None:
            updates.append("progress = ?")
            values.append(progress)
        if logs is not None:
            updates.append("logs = ?")
            values.append(logs)
        if metadata is not None:
            updates.append("metadata = ?")
            values.append(json.dumps(metadata))
        if not updates:
            return False
        values.append(task_id)
        
        query = f"UPDATE ralph_state SET {', '.join(updates)}, updated_at = datetime('now') WHERE task_id = ?"
        conn = self._get_connection()
        try:
            cursor = conn.execute(query, values)
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def append_log(self, task_id: str, log_entry: str) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT logs FROM ralph_state WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return False
            existing_logs = row["logs"] or ""
            timestamp = "datetime('now')"  # SQLite function
            new_logs = f"{existing_logs}\n[{timestamp}] {log_entry}".lstrip()
            conn.execute("UPDATE ralph_state SET logs = ?, updated_at = datetime('now') WHERE task_id = ?", (new_logs, task_id))
            conn.commit()
            return True
        finally:
            conn.close()
    
    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT * FROM ralph_state WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "task_id": row["task_id"],
                "status": row["status"],
                "progress": row["progress"],
                "logs": row["logs"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                "updated_at": row["updated_at"],
                "created_at": row["created_at"]
            }
        finally:
            conn.close()
    
    def list(self, status: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM ralph_state"
        params = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        conn = self._get_connection()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "task_id": row["task_id"],
                    "status": row["status"],
                    "progress": row["progress"],
                    "logs": row["logs"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                    "updated_at": row["updated_at"],
                    "created_at": row["created_at"]
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    def delete(self, task_id: str) -> bool:
        conn = self._get_connection()
        try:
            cursor = conn.execute("DELETE FROM ralph_state WHERE task_id = ?", (task_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def get_all_statuses(self) -> List[str]:
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT DISTINCT status FROM ralph_state ORDER BY status")
            return [row["status"] for row in cursor.fetchall()]
        finally:
            conn.close()


if __name__ == "__main__":
    import sys
    state = RalphState()
    if len(sys.argv) < 2:
        print("RalphState CLI")
        print("Usage: ralph_state.py <create|get|list|update|delete> [args...]")
        sys.exit(0)
    command = sys.argv[1]
    try:
        if command == "create":
            task_id = sys.argv[2]
            status = sys.argv[3] if len(sys.argv) > 3 else "queued"
            progress = int(sys.argv[4]) if len(sys.argv) > 4 else 0
            row_id = state.create(task_id, status, progress)
            print(f"Created state for task {task_id} (ID: {row_id})")
        elif command == "get":
            task_id = sys.argv[2]
            entry = state.get(task_id)
            if entry:
                print(json.dumps(entry, indent=2))
            else:
                print(f"Task {task_id} not found")
        elif command == "list":
            status = sys.argv[2] if len(sys.argv) > 2 else None
            entries = state.list(status=status)
            print(f"Found {len(entries)} entries:")
            for entry in entries:
                print(f"  {entry['task_id']}: {entry['status']} ({entry['progress']}%)")
        elif command == "update":
            task_id = sys.argv[2]
            status = sys.argv[3] if len(sys.argv) > 3 else None
            progress = int(sys.argv[4]) if len(sys.argv) > 4 else None
            if state.update(task_id, status=status, progress=progress):
                print(f"Updated state for task {task_id}")
            else:
                print(f"Task {task_id} not found")
        elif command == "delete":
            task_id = sys.argv[2]
            if state.delete(task_id):
                print(f"Deleted state for task {task_id}")
            else:
                print(f"Task {task_id} not found")
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
