#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib import request

from dotenv import load_dotenv

BASE = Path.home() / "ai-devops"
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"

# Read webhook from ~/ai-devops/discord/.env (recommended single source)
load_dotenv(BASE / "discord" / ".env")
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

RUNNER_CODEX = str(BASE / "agents" / "run-codex-agent.sh")


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


def notify(msg: str) -> None:
    if not WEBHOOK:
        print("[WARN] DISCORD_WEBHOOK_URL not set; skip notify:", msg)
        return
    data = json.dumps({"content": msg}).encode("utf-8")
    req = request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
    request.urlopen(req, timeout=10).read()


def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(items: list[dict]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def tmux_alive(session: str) -> bool:
    r = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True, text=True)
    return r.returncode == 0


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
    session = task["tmuxSession"]
    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")
    task_id = task["id"]

    # Kill old session (ignore errors)
    subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True, text=True)

    cmd = f'"{RUNNER_CODEX}" "{task_id}" "{model}" "{effort}" "{worktree}" "{prompt_filename}"'
    # new session
    sh(["tmux", "new-session", "-d", "-s", session, "-c", str(worktree), cmd], check=True)


def main() -> None:
    print("Monitor started.")
    notified_ready = set()  # in-memory; persists only for process lifetime

    while True:
        items = load_registry()
        changed = False

        for t in items:
            status = t.get("status")
            if status not in ("running", "pr_created"):
                continue

            # Basic fields
            session = t.get("tmuxSession")
            worktree = Path(t.get("worktree", ""))
            branch = t.get("branch", "")
            task_id = t.get("id")

            if not task_id or not session or not worktree.exists() or not branch:
                t["status"] = "blocked"
                t["note"] = "invalid task record (missing id/session/worktree/branch)"
                changed = True
                continue

            # 1) tmux must be alive for running tasks
            if not tmux_alive(session):
                if t.get("status") == "running":
                    t["status"] = "agent_dead"
                    t["note"] = "tmux session not found"
                    changed = True
                    notify(f"⚠️ Agent session dead: `{task_id}` ({session}). Check logs.")
                continue

            # 2) PR info
            pr = pr_info(worktree, branch)

            if pr and t.get("status") == "running":
                t["status"] = "pr_created"
                t["pr"] = pr.get("number")
                t["prUrl"] = pr.get("url")
                changed = True

            if not pr:
                # PR not created yet; continue waiting
                continue

            # 3) Only handle OPEN PRs for checks/retry
            if (pr.get("state") or "").upper() != "OPEN":
                continue

            passed, fail_summary, pending = analyze_checks(pr)

            # pending: do nothing
            if pending:
                continue

            # Ready criteria: checks passed + merge clean
            if passed and merge_clean(pr):
                if task_id not in notified_ready:
                    notified_ready.add(task_id)
                    t["status"] = "ready"
                    t["completedAt"] = int(time.time() * 1000)
                    t["note"] = "checks passed and mergeable clean"
                    changed = True
                    notify(f"✅ PR ready: `{task_id}` {t.get('prUrl','')} (checks✅ + merge✅)")
                continue

            # checks passed but merge not clean -> notify human (merge conflicts)
            if passed and not merge_clean(pr):
                # Avoid spamming: only notify once by status change
                if t.get("status") != "needs_rebase":
                    t["status"] = "needs_rebase"
                    t["note"] = f"merge not clean: mergeable={pr.get('mergeable')} state={pr.get('mergeStateStatus')}"
                    changed = True
                    notify(
                        f"⚠️ PR checks passed but merge not clean: `{task_id}` {t.get('prUrl','')}\n"
                        f"mergeable={pr.get('mergeable')} mergeStateStatus={pr.get('mergeStateStatus')}"
                    )
                continue

            # 4) checks failed -> Ralph Loop v2 retry
            if fail_summary:
                attempts = int(t.get("attempts", 0))
                max_attempts = int(t.get("maxAttempts", 3))

                t["lastFailure"] = fail_summary

                if attempts >= max_attempts:
                    if t.get("status") != "blocked":
                        t["status"] = "blocked"
                        t["note"] = "max retries reached"
                        changed = True
                        notify(
                            f"🛑 CI failed and max retries reached: `{task_id}` {t.get('prUrl','')}\n"
                            f"Fail: {fail_summary}"
                        )
                    continue

                retry_n = attempts + 1

                # Pull more CI details if possible
                ci_detail = latest_run_failure(worktree, branch) or ""

                # Base prompt
                base_prompt_path = worktree / "prompt.txt"
                base_prompt = base_prompt_path.read_text(encoding="utf-8") if base_prompt_path.exists() else ""

                retry_prompt_path = worktree / f"prompt.retry{retry_n}.txt"

                retry_prompt = (
                    base_prompt
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
                retry_prompt_path.write_text(retry_prompt, encoding="utf-8")

                # Restart agent with retry prompt
                try:
                    restart_codex_agent(t, worktree, retry_prompt_path.name)
                except Exception as e:
                    t["status"] = "blocked"
                    t["note"] = f"failed to restart agent: {e}"
                    changed = True
                    notify(f"🛑 Failed to restart agent for `{task_id}`: {e}")
                    continue

                t["attempts"] = retry_n
                t["status"] = "running"
                t["note"] = f"retry #{retry_n} triggered"
                changed = True

                notify(
                    f"🔁 Retry #{retry_n} triggered: `{task_id}` {t.get('prUrl','')}\n"
                    f"Fail: {fail_summary}"
                )

        if changed:
            save_registry(items)

        time.sleep(30)


if __name__ == "__main__":
    main()
