from unittest.mock import patch, MagicMock
from pathlib import Path
import pytest
from orchestrator.bin.zoe_tools import retry_task
from orchestrator.bin.errors import PlannerError


def make_task(status="blocked", attempts=1, max_attempts=3, worktree=None, tmux_session="agent-t1"):
    wt = worktree or Path("/tmp/test-worktree")
    return {
        "id": "task-123",
        "status": status,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "worktree": str(wt),
        "tmux_session": tmux_session,
        "model": "gpt-5.3-codex",
        "effort": "high",
        "execution_mode": "tmux",
        "repo": "test-repo",
        "title": "Test Task",
    }


def test_retry_task_not_found():
    with patch("orchestrator.bin.zoe_tools.get_task", return_value=None):
        with pytest.raises(PlannerError, match="not found"):
            retry_task("nonexistent-id")


def test_retry_task_invalid_status():
    task = make_task(status="running")
    with patch("orchestrator.bin.zoe_tools.get_task", return_value=task):
        with pytest.raises(PlannerError, match="status"):
            retry_task("task-123")


def test_retry_task_exceeded_attempts():
    task = make_task(status="blocked", attempts=3, max_attempts=3)
    with patch("orchestrator.bin.zoe_tools.get_task", return_value=task):
        with pytest.raises(PlannerError, match="attempts"):
            retry_task("task-123")


def test_retry_task_success(tmp_path):
    wt = tmp_path / "worktree"
    wt.mkdir()
    (wt / "prompt.txt").write_text("original prompt", encoding="utf-8")
    task = make_task(status="blocked", attempts=1, worktree=wt)

    updated_task = {**task, "attempts": 2, "status": "running"}

    with patch("orchestrator.bin.zoe_tools.get_task", return_value=task), \
         patch("orchestrator.bin.zoe_tools.update_task") as mock_update, \
         patch("orchestrator.bin.zoe_tools.merge_task_metadata") as mock_merge_meta, \
         patch("orchestrator.bin.zoe_tools._restart_agent") as mock_restart:
        mock_update.return_value = None
        result = retry_task("task-123", reason="manual retry test")

    # Retry prompt file created
    retry_file = wt / "prompt.retry2.txt"
    assert retry_file.exists()
    content = retry_file.read_text(encoding="utf-8")
    assert "original prompt" in content
    assert "RERUN DIRECTIVE" in content
    assert "manual retry test" in content

    # update_task called with correct fields
    mock_update.assert_called_once_with("task-123", {
        "attempts": 2,
        "status": "running",
        "note": "retry #2 triggered (manual)",
    })
    mock_merge_meta.assert_called_once()
    mock_restart.assert_called_once()

    assert result["status"] == "running"
    assert result["attempts"] == 2
