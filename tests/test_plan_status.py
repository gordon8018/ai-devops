# tests/test_plan_status.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status import SubtaskView, PlanView

def test_subtask_view_defaults():
    sv = SubtaskView(id="s1", title="Fix auth", status="queued")
    assert sv.id == "s1"
    assert sv.agent is None
    assert sv.pr_url is None
    assert sv.depends_on == ()

def test_plan_view_progress():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready"),
        SubtaskView(id="s2", title="B", status="running"),
        SubtaskView(id="s3", title="C", status="queued"),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    assert pv.completed_count == 1
    assert pv.total_count == 3


import json
import sqlite3
import tempfile
import os

def _make_db(tmp: Path, tasks: list[dict]) -> Path:
    db_path = tmp / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE agent_tasks (
            id TEXT PRIMARY KEY, plan_id TEXT, repo TEXT, title TEXT,
            status TEXT, agent TEXT, model TEXT, pr_number INTEGER,
            pr_url TEXT, attempts INTEGER DEFAULT 0, note TEXT,
            metadata TEXT, created_at INTEGER, updated_at INTEGER
        )
    """)
    for t in tasks:
        conn.execute(
            "INSERT INTO agent_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t["id"], t.get("plan_id"), t["repo"], t["title"], t["status"],
             t.get("agent"), t.get("model"), t.get("pr_number"), t.get("pr_url"),
             t.get("attempts", 0), t.get("note"), None, 0, 0)
        )
    conn.commit()
    conn.close()
    return db_path


def _make_plan_archive(tmp: Path, plan_id: str, subtasks: list[dict], plan_meta: dict) -> None:
    plan_dir = tmp / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps(plan_meta))
    subtasks_dir = plan_dir / "subtasks"
    subtasks_dir.mkdir()
    for s in subtasks:
        (subtasks_dir / f"{s['id']}.json").write_text(json.dumps(s))


def test_load_plan_view_merges_db_and_archive(tmp_path, monkeypatch):
    plan_id = "feat-auth"
    _make_db(tmp_path, [
        {"id": "feat-auth-s1", "plan_id": plan_id, "repo": "org/repo",
         "title": "Schema", "status": "ready", "attempts": 0},
        {"id": "feat-auth-s2", "plan_id": plan_id, "repo": "org/repo",
         "title": "API", "status": "running", "attempts": 1},
    ])
    _make_plan_archive(tmp_path, plan_id, [
        {"id": "s1", "title": "Schema", "depends_on": []},
        {"id": "s2", "title": "API", "depends_on": ["s1"]},
    ], {"planId": plan_id, "repo": "org/repo", "objective": "Add auth",
        "requestedBy": "gordon", "requestedAt": 0})

    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    from plan_status import load_plan_view
    pv = load_plan_view(plan_id, base_dir=tmp_path)

    assert pv.plan_id == plan_id
    assert pv.repo == "org/repo"
    assert pv.objective == "Add auth"
    assert len(pv.subtasks) == 2

    s1 = next(s for s in pv.subtasks if s.id == "s1")
    s2 = next(s for s in pv.subtasks if s.id == "s2")
    assert s1.status == "ready"
    assert s2.status == "running"
    assert s2.depends_on == ("s1",)
    assert pv.completed_count == 1
