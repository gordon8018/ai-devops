#!/usr/bin/env python3
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys as _sys
import time
from pathlib import Path
from typing import Optional, Tuple

BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))

_sys.path.insert(0, str(BASE / "orchestrator" / "bin"))
from db import init_db, get_running_tasks, update_task

RUNNER_CODEX = str(BASE / "agents" / "run-codex-agent.sh")
LOG_DIR = BASE / "logs"

try:
    from notify import notify
except ImportError:
    def notify(msg: str) -> None:
        print(f"[NOTIFY] {msg}")

try:
    from obsidian_client import ObsidianClient
except ImportError:
    ObsidianClient = None  # type: ignore

try:
    from reviewer import review_pr
except ImportError:
    def review_pr(task_id, pr_number, repo_dir):  # type: ignore[misc]
        print(f"[WARN] reviewer module not available, skipping review for PR #{pr_number}")


def _obsidian_search(query: str) -> list[dict]:
    """Search Obsidian for context. Returns [] if unconfigured or unreachable."""
    token = os.getenv("OBSIDIAN_API_TOKEN", "")
    if not token or ObsidianClient is None:
        return []
    client = ObsidianClient.from_env()
    return client.search(query, limit=2)


def _write_failure_log(repo: str, task_id: str, fail_summary: str, ci_detail: str) -> None:
    """Write a structured failure record to .clawdbot/failure-logs/<repo>/."""
    log_dir = BASE / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    log_file = log_dir / f"{task_id}-{timestamp}.json"
    log_file.write_text(
        json.dumps({
            "taskId": task_id,
            "repo": repo,
            "failSummary": fail_summary,
            "ciDetail": ci_detail[:2000] if ci_detail else "",
            "timestamp": timestamp,
        }, indent=2),
        encoding="utf-8",
    )


def _load_failure_logs(repo: str, limit: int = 2) -> str:
    """Load recent failure log excerpts for a repo."""
    log_dir = BASE / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    if not log_dir.exists():
        return ""
    logs = sorted(log_dir.glob("*.json"), reverse=True)[:limit]
    excerpts = []
    for log in logs:
        try:
            data = json.loads(log.read_text(encoding="utf-8"))
            excerpts.append(f"- [{data.get('taskId','')}] {data.get('failSummary','')} — {data.get('ciDetail','')[:200]}")
        except Exception:
            continue
    return "\n".join(excerpts)


def _save_success_pattern(
    *, repo: str, task_id: str, title: str, worktree: Path, attempts: int
) -> None:
    """Save successful prompt as a template for future planning reference.

    Note: one file per slug (same repo+title overwrites the previous winner),
    so this always stores the most recent winning prompt.
    """
    import re as _re
    prompt_path = worktree / "prompt.txt"
    if not prompt_path.exists():
        return
    content = prompt_path.read_text(encoding="utf-8")

    templates_dir = BASE / ".clawdbot" / "prompt-templates" / repo.replace("/", "_")
    templates_dir.mkdir(parents=True, exist_ok=True)

    slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    if not slug:
        slug = f"task-{task_id}"[:48]
    timestamp = int(time.time() * 1000)
    out_file = templates_dir / f"{slug}.md"
    out_file.write_text(
        f"<!-- attempts={attempts} timestamp={timestamp} repo={repo} -->\n{content}",
        encoding="utf-8",
    )


def _build_retry_prompt(task: dict, retry_n: int, fail_summary: str, ci_detail: str) -> Path:
    """
    Build and write prompt.retryN.txt for a task.
    Injects Obsidian business context and past failure history.
    Returns path to the written file.
    """
    worktree = Path(task.get("worktree", ""))
    base_prompt_path = worktree / "prompt.txt"
    base_prompt = base_prompt_path.read_text(encoding="utf-8") if base_prompt_path.exists() else ""

    # Obsidian context
    query = f"{task.get('title', '')} {task.get('repo', '')}"
    obsidian_results = _obsidian_search(query)
    obsidian_section = ""
    if obsidian_results:
        excerpts = "\n".join(f"- [{r['path']}]: {r['excerpt']}" for r in obsidian_results)
        obsidian_section = f"\nBUSINESS CONTEXT (from Obsidian):\n{excerpts}\n"

    # Past failure history
    past_failures = _load_failure_logs(task.get("repo", ""))
    failures_section = ""
    if past_failures:
        failures_section = f"\nPAST FAILURES FOR THIS REPO:\n{past_failures}\n"

    retry_prompt = (
        base_prompt
        + obsidian_section
        + failures_section
        + "\n\n"
        + f"RERUN DIRECTIVE (Retry #{retry_n}):\n"
        + "CI is failing. Your ONLY priority is to make CI green.\n"
        + f"Failed checks summary: {fail_summary}\n\n"
        + (ci_detail + "\n\n" if ci_detail else "")
        + "Instructions:\n"
        + "- Read failing logs and identify root cause.\n"
        + "- Apply minimal fix.\n"
        + "- Run local equivalent checks/tests if available.\n"
        + "- Push commits to the SAME branch and update the PR.\n"
    )

    retry_prompt_path = worktree / f"prompt.retry{retry_n}.txt"
    retry_prompt_path.write_text(retry_prompt, encoding="utf-8")
    return retry_prompt_path


def sh(cmd: list[str], cwd: Optional[Path] = None, check: bool = False) -> str:
    r = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"CWD: {cwd}\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}\n"
        )
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_alive(session: str) -> bool:
    if not tmux_available():
        return False
    r = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True, text=True)
    return r.returncode == 0


def process_alive(process_id: int | None) -> bool:
    if not isinstance(process_id, int) or process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def exit_status_path(task_id: str) -> Path:
    return LOG_DIR / f"{task_id}.exit.json"


def load_exit_status(task_id: str) -> Optional[dict]:
    path = exit_status_path(task_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def log_file_stale(task_id: str, max_age_minutes: float = 30.0) -> bool:
    """Return True if the task's log file hasn't been updated within max_age_minutes."""
    log_file = LOG_DIR / f"{task_id}.log"
    if not log_file.exists():
        return False
    age_seconds = time.time() - log_file.stat().st_mtime
    return age_seconds > (max_age_minutes * 60)


def task_elapsed_minutes(task: dict) -> float:
    """Return elapsed time in minutes since task started, or 0 if no startedAt."""
    started_at = task.get("startedAt") or task.get("started_at")
    if not started_at:
        return 0
    now_ms = int(time.time() * 1000)
    return (now_ms - started_at) / 60000.0


def pr_info(repo_dir: Path, branch: str) -> Optional[dict]:
    """
    Use gh to view PR by head ref / branch.
    NOTE: gh pr view <branch> works when branch is a PR headRefName in this repo.
    """
    out = sh(
        [
            "gh",
            "pr",
            "view",
            branch,
            "--json",
            "number,state,url,headRefName,baseRefName,mergeable,mergeStateStatus,statusCheckRollup",
        ],
        cwd=repo_dir,
    )
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


def merge_clean(pr: dict) -> bool:
    mergeable = pr.get("mergeable")
    status = (pr.get("mergeStateStatus") or "").upper()

    # Some gh/graphql shapes:
    # - mergeable may be True/False (bool) or "MERGEABLE"/"CONFLICTING"/"UNKNOWN"
    # We require explicit "mergeable" + CLEAN
    mergeable_ok = str(mergeable).lower() in ("true", "mergeable")
    return mergeable_ok and status == "CLEAN"


def analyze_checks(pr: dict) -> Tuple[bool, Optional[str], bool]:
    """
    Returns: (passed, failure_summary, pending)
    - pending=True means checks still running/queued; do not retry.
    - failure_summary != None means checks completed with failures; eligible for retry.
    """
    rollup = pr.get("statusCheckRollup") or []
    if not rollup:
        # No checks yet -> pending
        return (False, None, True)

    pending = False
    failures = []

    for c in rollup:
        name = c.get("name") or c.get("context") or "check"
        status = (c.get("status") or "").upper()       # QUEUED / IN_PROGRESS / COMPLETED
        conc = (c.get("conclusion") or "").upper()     # SUCCESS / FAILURE / CANCELLED / ...

        # Not completed and no conclusion -> pending
        if status != "COMPLETED" and conc == "":
            pending = True
            continue

        if conc in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"):
            failures.append(f"{name}:{conc}")

    if pending:
        return (False, None, True)

    if failures:
        return (False, "; ".join(failures), False)

    return (True, None, False)


def latest_run_failure(repo_dir: Path, branch: str) -> Optional[str]:
    """
    Pull latest workflow run for the branch and return --log-failed tail (truncated).
    """
    out = sh(
        ["gh", "run", "list", "--branch", branch, "--limit", "1", "--json", "databaseId,status,conclusion,htmlUrl"],
        cwd=repo_dir,
    )
    if not out:
        return None

    try:
        runs = json.loads(out)
    except Exception:
        return None

    if not runs:
        return None

    run = runs[0]
    conc = (run.get("conclusion") or "").upper()
    run_id = run.get("databaseId")
    url = run.get("htmlUrl") or ""

    if conc != "FAILURE" or not run_id:
        return None

    logs = sh(["gh", "run", "view", str(run_id), "--log-failed"], cwd=repo_dir)
    if not logs:
        return f"CI run failure: {url}"

    # Truncate to last 2000 chars (usually most relevant)
    if len(logs) > 2000:
        logs = logs[-2000:]
    return f"CI run failure ({url}) tail:\n{logs}"


def restart_codex_agent(task: dict, worktree: Path, prompt_filename: str) -> None:
    session = task.get("tmuxSession") or task.get("tmux_session")
    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")
    task_id = task["id"]
    execution_mode = task.get("executionMode") or task.get("execution_mode", "tmux")

    if execution_mode == "tmux":
        # Kill old session (ignore errors)
        if session:
            subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True, text=True)
        cmd = f'"{RUNNER_CODEX}" "{task_id}" "{model}" "{effort}" "{worktree}" "{prompt_filename}"'
        sh(["tmux", "new-session", "-d", "-s", session, "-c", str(worktree), cmd], check=True)
        task["processId"] = None
        return

    old_pid = task.get("processId") or task.get("process_id")
    if isinstance(old_pid, int) and old_pid > 0:
        try:
            os.kill(old_pid, signal.SIGTERM)
        except OSError:
            pass
    process = subprocess.Popen(
        [RUNNER_CODEX, task_id, model, effort, str(worktree), prompt_filename],
        cwd=str(worktree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    task["processId"] = process.pid
    task["tmuxSession"] = None


def _process_task(t: dict, notified_ready: set) -> None:
    """Process a single task in one monitoring cycle."""
    status = t.get("status")
    if status not in ("running", "pr_created", "retrying"):
        return

    # Basic fields — db uses snake_case
    session = t.get("tmuxSession") or t.get("tmux_session")
    process_id = t.get("processId") or t.get("process_id")
    execution_mode = t.get("executionMode") or t.get("execution_mode", "tmux")
    worktree = Path(t.get("worktree", ""))
    branch = t.get("branch", "")
    task_id = t.get("id")

    if not task_id or not worktree.exists() or not branch:
        update_task(task_id, {"status": "blocked", "note": "invalid task record (missing id/worktree/branch)"})
        t["status"] = "blocked"
        return

    if execution_mode == "process":
        alive = process_alive(process_id)
    else:
        alive = bool(session) and tmux_alive(session)

    # 1) PR info
    pr = pr_info(worktree, branch)

    if pr and t.get("status") == "running":
        update_task(task_id, {
            "status": "pr_created",
            "pr_number": pr.get("number"),
            "pr_url": pr.get("url"),
        })
        t["status"] = "pr_created"
        t["pr"] = pr.get("number")
        t["prUrl"] = pr.get("url")

        # Trigger async PR review (non-blocking — processes fire-and-forget)
        worktree_path = Path(t.get("worktree", ""))
        if worktree_path.exists() and pr.get("number"):
            review_pr(task_id, pr["number"], worktree_path)

    if not pr:
        # Runtime only matters before a PR exists.
        if not alive and t.get("status") == "running":
            exit_info = load_exit_status(task_id)
            if exit_info:
                exit_code = exit_info.get("exitCode")
                completed_at = exit_info.get("finishedAt")
                if exit_code == 0:
                    update_task(task_id, {
                        "status": "agent_exited",
                        "completed_at": completed_at,
                        "note": "agent process exited cleanly before opening a PR",
                    })
                    t["status"] = "agent_exited"
                else:
                    update_task(task_id, {
                        "status": "agent_failed",
                        "completed_at": completed_at,
                        "note": f"agent exited with code {exit_code}",
                    })
                    t["status"] = "agent_failed"
                    notify(
                        f"\u26a0\ufe0f Agent exited: `{task_id}` with code {exit_code}. Check logs."
                    )
            else:
                note = (
                    "background process not found"
                    if execution_mode == "process"
                    else "tmux session not found"
                )
                update_task(task_id, {"status": "agent_dead", "note": note})
                t["status"] = "agent_dead"
                runtime_ref = (
                    f"pid={process_id}" if execution_mode == "process" else session
                )
                notify(
                    f"\u26a0\ufe0f Agent session dead: `{task_id}` ({runtime_ref}). Check logs."
                )
        return

    # 3) Only handle OPEN PRs for checks/retry
    if (pr.get("state") or "").upper() != "OPEN":
        return

    passed, fail_summary, pending = analyze_checks(pr)

    # pending: do nothing
    if pending:
        return

    # Ready criteria: checks passed + merge clean
    if passed and merge_clean(pr):
        if task_id not in notified_ready:
            notified_ready.add(task_id)
            update_task(task_id, {
                "status": "ready",
                "completed_at": int(time.time() * 1000),
                "note": "checks passed and mergeable clean",
            })
            t["status"] = "ready"
            _save_success_pattern(
                repo=t.get("repo", ""),
                task_id=task_id,
                title=t.get("title", task_id),
                worktree=worktree,
                attempts=int(t.get("attempts", 0)),
            )
            notify(f"\u2705 PR ready: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')} (checks\u2705 + merge\u2705)")
        return

    # checks passed but merge not clean -> notify human (merge conflicts)
    if passed and not merge_clean(pr):
        # Avoid spamming: only notify once by status change
        if t.get("status") != "needs_rebase":
            note = f"merge not clean: mergeable={pr.get('mergeable')} state={pr.get('mergeStateStatus')}"
            update_task(task_id, {"status": "needs_rebase", "note": note})
            t["status"] = "needs_rebase"
            notify(
                f"\u26a0\ufe0f PR checks passed but merge not clean: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
                f"mergeable={pr.get('mergeable')} mergeStateStatus={pr.get('mergeStateStatus')}"
            )
        return

    # 4) checks failed -> Ralph Loop v2 retry
    if fail_summary:
        attempts = int(t.get("attempts", 0))
        max_attempts = int(t.get("maxAttempts") or t.get("max_attempts", 3))

        update_task(task_id, {"last_failure": fail_summary})

        if attempts >= max_attempts:
            if t.get("status") != "blocked":
                update_task(task_id, {"status": "blocked", "note": "max retries reached"})
                t["status"] = "blocked"
                notify(
                    f"\U0001f6d1 CI failed and max retries reached: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
                    f"Fail: {fail_summary}"
                )
            return

        retry_n = attempts + 1

        # Pull more CI details if possible
        ci_detail = latest_run_failure(worktree, branch) or ""

        # Write failure log
        _write_failure_log(t.get("repo", ""), task_id, fail_summary, ci_detail)

        # Build retry prompt with Obsidian context
        retry_prompt_path = _build_retry_prompt(t, retry_n, fail_summary, ci_detail)

        # Restart agent with retry prompt
        try:
            restart_codex_agent(t, worktree, retry_prompt_path.name)
        except Exception as e:
            update_task(task_id, {"status": "blocked", "note": f"failed to restart agent: {e}"})
            t["status"] = "blocked"
            notify(f"\U0001f6d1 Failed to restart agent for `{task_id}`: {e}")
            return

        update_task(task_id, {
            "attempts": retry_n,
            "status": "running",
            "note": f"retry #{retry_n} triggered",
        })
        t["attempts"] = retry_n
        t["status"] = "running"

        notify(
            f"\U0001f501 Retry #{retry_n} triggered: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
            f"Fail: {fail_summary}"
        )


def check_all_tasks(notified_ready: set) -> Tuple[bool, set]:
    """
    Run one monitoring cycle. Returns (changed, notified_ready).
    'changed' is always False now (updates are immediate), kept for API compat.
    """
    items = get_running_tasks()
    for t in items:
        try:
            _process_task(t, notified_ready)
        except Exception as exc:
            task_id = t.get("id", "<unknown>")
            update_task(task_id, {"status": "blocked", "note": f"monitor error: {exc}"})
            print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
    return (False, notified_ready)


def run_once(notified_ready: set) -> None:
    """Run one monitoring cycle over all active tasks."""
    try:
        items = get_running_tasks()
        for t in items:
            try:
                _process_task(t, notified_ready)
            except Exception as exc:
                task_id = t.get("id", "<unknown>")
                update_task(task_id, {"status": "blocked", "note": f"monitor error: {exc}"})
                print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
    except Exception as exc:
        print(f"[ERROR] Monitor loop failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zoe task monitor")
    parser.add_argument("--once", action="store_true",
                        help="Run one monitoring cycle and exit")
    args = parser.parse_args()

    init_db()
    notified_ready: set = set()

    if args.once:
        run_once(notified_ready)
        return

    print("Monitor started.")
    while True:
        run_once(notified_ready)
        time.sleep(30)


if __name__ == "__main__":
    main()
