# tests/test_plan_status_renderer.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status import PlanView, SubtaskView
from plan_status_renderer import status_icon, build_dag_lines, render_plan_view, watch_plan

def test_status_icon_known():
    assert "✅" in status_icon("ready")
    assert "🔄" in status_icon("running")
    assert "❌" in status_icon("blocked")
    assert "⏳" in status_icon("queued")

def test_status_icon_unknown_does_not_crash():
    result = status_icon("some_future_status")
    assert isinstance(result, str)

def test_build_dag_lines_no_deps():
    subtasks = [SubtaskView(id="s1", title="A", status="ready")]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    lines = build_dag_lines(pv)
    assert isinstance(lines, list)
    # single node with no deps — should produce at least one line
    assert len(lines) >= 1

def test_build_dag_lines_with_chain():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready"),
        SubtaskView(id="s2", title="B", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    lines = build_dag_lines(pv)
    combined = " ".join(lines)
    assert "s1" in combined or "A" in combined
    assert "s2" in combined or "B" in combined
    assert "──→" in combined or "-->" in combined

def test_render_plan_view_returns_string():
    subtasks = [
        SubtaskView(id="s1", title="Schema", status="ready"),
        SubtaskView(id="s2", title="API", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="feat-auth", repo="org/repo", subtasks=subtasks,
                  objective="Add auth")
    result = render_plan_view(pv)
    assert isinstance(result, str)
    assert "feat-auth" in result
    assert "org/repo" in result

def test_watch_plan_once_does_not_crash(tmp_path, monkeypatch):
    """Smoke test: watch_plan with once=True completes without error."""
    import json, sqlite3
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT, plan_id TEXT, repo TEXT, title TEXT, status TEXT,
        agent TEXT, model TEXT, pr_number INTEGER, pr_url TEXT,
        attempts INTEGER, note TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    plan_dir = tmp_path / "tasks" / "smoke-plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps(
        {"planId": "smoke-plan", "repo": "org/r", "objective": "", "requestedBy": "", "requestedAt": 0}
    ))
    (plan_dir / "subtasks").mkdir()
    (plan_dir / "subtasks" / "s1.json").write_text(json.dumps(
        {"id": "s1", "title": "T", "depends_on": []}
    ))
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    watch_plan("smoke-plan", once=True, base_dir=tmp_path)
