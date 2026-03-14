"""
Local PR Review Pipeline.

Spawns Codex and Claude as reviewers for a PR diff.
Posts review comments via gh pr comment.
Gemini reviewer is reserved (no-op).
"""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

REVIEW_PROMPT_TEMPLATE = """\
You are a senior code reviewer. Review the following PR diff for:
- Correctness and logic errors
- Security vulnerabilities (injection, auth bypass, data exposure)
- Edge cases and error handling gaps
- Test coverage gaps

Be concise. Use GitHub-flavoured markdown. Start with a one-line summary.

PR DIFF:
{diff}
"""

CODEX_CMD = os.getenv("CODEX_BIN", "codex")
CLAUDE_CMD = os.getenv("CLAUDE_BIN", "claude")


def _get_pr_diff(pr_number: int, repo_dir: Path) -> str:
    """Fetch PR diff using gh CLI. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number)],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"[WARN] gh pr diff failed for #{pr_number}: {result.stderr[:200]}")
            return ""
        return result.stdout or ""
    except Exception as exc:
        print(f"[WARN] Failed to get PR diff for #{pr_number}: {exc}")
        return ""


def _post_comment(pr_number: int, body: str, repo_dir: Path) -> None:
    """Post a comment on the PR via gh CLI."""
    try:
        subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        print(f"[WARN] Failed to post PR comment: {exc}")


def _run_codex_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Run Codex reviewer (blocking — call from a thread). Posts result as PR comment."""
    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=diff[:8000])
    try:
        result = subprocess.run(
            [CODEX_CMD, "--model", "gpt-5.3-codex", prompt],
            capture_output=True,
            text=True,
            timeout=300,
        )
        review_text = (result.stdout or "").strip()
        if review_text:
            _post_comment(pr_number, f"🤖 **Codex Review:**\n\n{review_text}", repo_dir)
    except FileNotFoundError:
        print(f"[WARN] Codex not found ({CODEX_CMD}), skipping Codex review")
    except Exception as exc:
        print(f"[WARN] Codex review failed: {exc}")


def _run_claude_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Run Claude reviewer (blocking — call from a thread). Posts result as PR comment."""
    prompt = REVIEW_PROMPT_TEMPLATE.format(diff=diff[:8000])
    try:
        result = subprocess.run(
            [CLAUDE_CMD, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=300,
        )
        review_text = (result.stdout or "").strip()
        if review_text:
            _post_comment(pr_number, f"🤖 **Claude Review:**\n\n{review_text}", repo_dir)
    except FileNotFoundError:
        print(f"[WARN] Claude not found ({CLAUDE_CMD}), skipping Claude review")
    except Exception as exc:
        print(f"[WARN] Claude review failed: {exc}")


def _run_gemini_review(pr_number: int, diff: str, repo_dir: Path) -> None:
    """Reserved. Gemini reviewer not yet implemented."""
    print(f"[INFO] Gemini reviewer not yet implemented, skipping PR #{pr_number}")


def review_pr(task_id: str, pr_number: int, repo_dir: Path) -> None:
    """
    Fetch PR diff and run Codex + Claude reviews in a background thread.
    Posts gh pr comment for each review. Non-blocking — returns immediately.
    """
    diff = _get_pr_diff(pr_number, repo_dir)
    if not diff:
        print(f"[INFO] Empty diff for PR #{pr_number}, skipping review")
        return

    print(f"[INFO] Triggering PR review for task {task_id} PR #{pr_number}")

    def _run_all():
        _run_codex_review(pr_number, diff, repo_dir)
        _run_claude_review(pr_number, diff, repo_dir)
        _run_gemini_review(pr_number, diff, repo_dir)

    thread = threading.Thread(target=_run_all, daemon=True)
    thread.start()
