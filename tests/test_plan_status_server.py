# tests/test_plan_status_server.py
import sys
import json
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status_server import PlanStatusServer, plan_view_to_dict
from plan_status import PlanView, SubtaskView


def test_plan_view_to_dict_shape():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready", pr_url="https://gh/1", pr_number=1),
        SubtaskView(id="s2", title="B", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks, objective="Test")
    d = plan_view_to_dict(pv)
    assert d["planId"] == "p1"
    assert d["repo"] == "org/repo"
    assert d["completedCount"] == 1
    assert d["totalCount"] == 2
    assert len(d["subtasks"]) == 2
    s2 = next(s for s in d["subtasks"] if s["id"] == "s2")
    assert s2["dependsOn"] == ["s1"]
    assert s2["prUrl"] is None


def test_server_serves_json_api(tmp_path, monkeypatch):
    plan_id = "test-plan"
    # minimal DB
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT PRIMARY KEY, plan_id TEXT, repo TEXT, title TEXT,
        status TEXT, agent TEXT, model TEXT, pr_number INTEGER,
        pr_url TEXT, attempts INTEGER DEFAULT 0, note TEXT,
        metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    # minimal plan archive
    plan_dir = tmp_path / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({
        "planId": plan_id, "repo": "org/repo", "objective": "Test", "requestedBy": "bot", "requestedAt": 0
    }))
    (plan_dir / "subtasks").mkdir()
    (plan_dir / "subtasks" / "s1.json").write_text(json.dumps(
        {"id": "s1", "title": "Task1", "depends_on": []}
    ))
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    server = PlanStatusServer(plan_id=plan_id, base_dir=tmp_path)
    server.start()
    time.sleep(0.2)

    try:
        url = f"http://localhost:{server.port}/api/plan/{plan_id}"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
        assert data["planId"] == plan_id
        assert "subtasks" in data
    finally:
        server.stop()


def test_server_serves_html_root(tmp_path, monkeypatch):
    plan_id = "test-plan"
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT, plan_id TEXT, repo TEXT, title TEXT, status TEXT,
        agent TEXT, model TEXT, pr_number INTEGER, pr_url TEXT,
        attempts INTEGER, note TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    plan_dir = tmp_path / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({"planId": plan_id, "repo": "r", "objective": "", "requestedBy": "", "requestedAt": 0}))
    (plan_dir / "subtasks").mkdir()
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    server = PlanStatusServer(plan_id=plan_id, base_dir=tmp_path)
    server.start()
    time.sleep(0.2)
    try:
        with urllib.request.urlopen(f"http://localhost:{server.port}/", timeout=3) as resp:
            html = resp.read().decode()
        assert "<!DOCTYPE html>" in html
        assert plan_id in html
    finally:
        server.stop()
