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
