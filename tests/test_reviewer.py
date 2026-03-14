import pytest
from unittest.mock import patch, MagicMock, call
from pathlib import Path


def _reload():
    import importlib, sys
    if "orchestrator.bin.reviewer" in sys.modules:
        del sys.modules["orchestrator.bin.reviewer"]
    import orchestrator.bin.reviewer as m
    return m


def test_review_pr_spawns_two_reviewers(tmp_path):
    """review_pr() must run Codex and Claude reviewers and post PR comments."""
    rev = _reload()
    posted = []

    def fake_run(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 0
        m.stdout = f"Review from {cmd[0]}"
        return m

    with patch("subprocess.run", side_effect=fake_run):
        with patch.object(rev, "_get_pr_diff", return_value="diff content"):
            with patch.object(rev, "_post_comment", side_effect=lambda pr, body, d: posted.append(body)):
                rev.review_pr("task-1", 42, tmp_path)
                # Wait for the daemon thread to finish
                import threading
                for t in threading.enumerate():
                    if t.name != "MainThread" and t.daemon:
                        t.join(timeout=5)

    # Both Codex and Claude should have posted a comment
    assert len(posted) >= 2


def test_gemini_reviewer_is_noop(tmp_path, capsys):
    """_run_gemini_review() must log skip and not raise."""
    rev = _reload()
    # Should not raise and should print skip message
    rev._run_gemini_review(42, "some diff", tmp_path)
    captured = capsys.readouterr()
    assert "Gemini" in captured.out or "gemini" in captured.out.lower()


def test_get_pr_diff_calls_gh(tmp_path):
    """_get_pr_diff() must call gh pr diff."""
    rev = _reload()
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "--- a/foo\n+++ b/foo\n+new line"
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        diff = rev._get_pr_diff(42, tmp_path)
    assert "new line" in diff
    call_args = mock_run.call_args[0][0]
    assert "gh" in call_args
    assert "pr" in call_args
    assert "diff" in call_args


def test_review_pr_handles_empty_diff(tmp_path, capsys):
    """review_pr() with empty diff must log and skip gracefully."""
    rev = _reload()
    with patch.object(rev, "_get_pr_diff", return_value=""):
        rev.review_pr("task-1", 42, tmp_path)
    captured = capsys.readouterr()
    assert "empty" in captured.out.lower() or "skip" in captured.out.lower()
