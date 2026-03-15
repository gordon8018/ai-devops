# orchestrator/bin/plan_status.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Statuses considered "completed" for progress tracking
_COMPLETED_STATUSES = frozenset({"ready", "merged"})


@dataclass
class SubtaskView:
    id: str
    title: str
    status: str                         # from DB or dispatch archive
    agent: str | None = None
    model: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    attempts: int = 0
    note: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass
class PlanView:
    plan_id: str
    repo: str
    subtasks: list[SubtaskView]
    objective: str = ""
    requested_by: str = ""
    requested_at: int | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status in _COMPLETED_STATUSES)

    @property
    def total_count(self) -> int:
        return len(self.subtasks)


def _load_archive_subtasks(plan_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {subtask_id: archive_dict} from tasks/<plan-id>/subtasks/*.json."""
    result: dict[str, dict[str, Any]] = {}
    subtasks_dir = plan_dir / "subtasks"
    if not subtasks_dir.exists():
        return result
    for path in subtasks_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = data.get("id")
            if sid:
                result[sid] = data
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _load_plan_meta(plan_dir: Path) -> dict[str, Any]:
    plan_file = plan_dir / "plan.json"
    if not plan_file.exists():
        return {}
    try:
        return json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_plan_view(plan_id: str, base_dir: Path | None = None) -> PlanView:
    """Build a PlanView by merging the DB task records with the archived plan structure."""
    import sqlite3 as _sqlite3
    from config import ai_devops_home
    root = base_dir or ai_devops_home()
    plan_dir = root / "tasks" / plan_id

    # --- archive ---
    archive_subtasks = _load_archive_subtasks(plan_dir)
    plan_meta = _load_plan_meta(plan_dir)

    # --- DB ---
    db_path = root / ".clawdbot" / "agent_tasks.db"
    db_tasks: dict[str, dict[str, Any]] = {}
    if db_path.exists():
        conn = _sqlite3.connect(str(db_path))
        conn.row_factory = _sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE plan_id = ? ORDER BY id",
            (plan_id,),
        )
        for row in cursor.fetchall():
            row_dict = dict(row)
            # DB id format: "<plan_id>-<subtask_id>" — extract subtask_id suffix
            raw_id = row_dict["id"]
            prefix = f"{plan_id}-"
            subtask_id = raw_id[len(prefix):] if raw_id.startswith(prefix) else raw_id
            db_tasks[subtask_id] = row_dict
        conn.close()

    # --- merge: archive defines structure, DB provides live status ---
    subtask_views: list[SubtaskView] = []
    for sid, arc in archive_subtasks.items():
        db = db_tasks.get(sid, {})
        depends_on = tuple(arc.get("depends_on") or arc.get("dependsOn") or [])
        status = db.get("status") or arc.get("dispatch", {}).get("state") or "planned"
        subtask_views.append(SubtaskView(
            id=sid,
            title=arc.get("title") or db.get("title") or sid,
            status=status,
            agent=db.get("agent") or arc.get("agent"),
            model=db.get("model") or arc.get("model"),
            pr_number=db.get("pr_number"),
            pr_url=db.get("pr_url"),
            attempts=int(db.get("attempts") or 0),
            note=db.get("note"),
            depends_on=depends_on,
        ))

    return PlanView(
        plan_id=plan_id,
        repo=plan_meta.get("repo") or "",
        subtasks=subtask_views,
        objective=plan_meta.get("objective") or "",
        requested_by=plan_meta.get("requestedBy") or "",
        requested_at=plan_meta.get("requestedAt"),
    )


def list_plan_views(base_dir: Path | None = None, limit: int = 10) -> list[PlanView]:
    """Return recent PlanViews sorted by most recently modified dispatch-state."""
    import sqlite3 as _sqlite3
    from config import ai_devops_home
    root = base_dir or ai_devops_home()
    tasks_dir = root / "tasks"
    if not tasks_dir.exists():
        return []

    plan_dirs = sorted(
        [d for d in tasks_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    views = []
    for d in plan_dirs:
        try:
            views.append(load_plan_view(d.name, base_dir=root))
        except Exception:
            pass
    return views
