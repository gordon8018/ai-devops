import json, time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


def _reload(tmp_path, monkeypatch):
    import importlib, sys, orchestrator.bin.db as db_mod
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    importlib.reload(db_mod)
    db_mod.init_db()
    if "orchestrator.bin.cleanup_daemon" in sys.modules:
        del sys.modules["orchestrator.bin.cleanup_daemon"]
    import orchestrator.bin.cleanup_daemon as m
    importlib.reload(m)
    return m, db_mod


def test_cleanup_stale_worktrees_marks_cleaned_up(tmp_path, monkeypatch):
    """cleanup_stale_worktrees() must remove worktrees and mark cleaned_up=1."""
    m, db = _reload(tmp_path, monkeypatch)

    # Create a fake worktree dir
    wt = tmp_path / "worktrees" / "feat-t1"
    wt.mkdir(parents=True)

    db.insert_task({
        "id": "t1", "repo": "r", "title": "T",
        "status": "merged", "worktree": str(wt),
        "branch": "feat/t1",
    })

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        m.cleanup_stale_worktrees()

    task = db.get_task("t1")
    assert task["cleaned_up"] == 1
    # git worktree remove must have been called
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("worktree" in c and "remove" in c for c in calls)


def test_cleanup_stale_worktrees_skips_running(tmp_path, monkeypatch):
    """cleanup_stale_worktrees() must NOT clean up running tasks."""
    m, db = _reload(tmp_path, monkeypatch)

    wt = tmp_path / "worktrees" / "feat-t2"
    wt.mkdir(parents=True)
    db.insert_task({
        "id": "t2", "repo": "r", "title": "T",
        "status": "running", "worktree": str(wt),
    })

    with patch("subprocess.run") as mock_run:
        m.cleanup_stale_worktrees()

    task = db.get_task("t2")
    assert task["cleaned_up"] == 0


def test_cleanup_old_queue_files(tmp_path, monkeypatch):
    """cleanup_old_queue_files() must delete queue files older than 7 days."""
    m, db = _reload(tmp_path, monkeypatch)

    queue_dir = tmp_path / "orchestrator" / "queue"
    queue_dir.mkdir(parents=True)

    old_file = queue_dir / "old-task.json"
    old_file.write_text("{}")
    # Backdate mtime by 8 days
    import os
    old_mtime = time.time() - 8 * 86400
    os.utime(old_file, (old_mtime, old_mtime))

    recent_file = queue_dir / "recent-task.json"
    recent_file.write_text("{}")

    m.cleanup_old_queue_files()

    assert not old_file.exists(), "Old queue file must be deleted"
    assert recent_file.exists(), "Recent queue file must be kept"


def test_cleanup_failure_logs(tmp_path, monkeypatch):
    """cleanup_failure_logs() must delete failure logs older than 30 days."""
    m, db = _reload(tmp_path, monkeypatch)

    log_dir = tmp_path / ".clawdbot" / "failure-logs" / "my-repo"
    log_dir.mkdir(parents=True)

    old_log = log_dir / "t1-old.json"
    old_log.write_text("{}")
    import os
    old_mtime = time.time() - 31 * 86400
    os.utime(old_log, (old_mtime, old_mtime))

    recent_log = log_dir / "t2-recent.json"
    recent_log.write_text("{}")

    m.cleanup_failure_logs()

    assert not old_log.exists()
    assert recent_log.exists()
