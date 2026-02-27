#!/usr/bin/env python3
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple
from urllib import error, request

from dotenv import load_dotenv

BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"

# Read webhook from ~/ai-devops/discord/.env (recommended single source)
load_dotenv(BASE / "discord" / ".env", override=True)
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

RUNNER_CODEX = str(BASE / "agents" / "run-codex-agent.sh")
LOG_DIR = BASE / "logs"


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
    try:
        data = json.dumps({"content": msg}).encode("utf-8")
        req = request.Request(WEBHOOK, data=data, headers={"Content-Type": "application/json"})
        request.urlopen(req, timeout=10).read()
    except (error.URLError, error.HTTPError, TimeoutError, OSError) as exc:
        print(f"[WARN] Failed to send Discord webhook notification: {exc}")


def load_registry() -> list[dict]:
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(items: list[dict]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


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
    execution_mode = task.get("executionMode", "tmux")

    if execution_mode == "tmux":
        # Kill old session (ignore errors)
        if session:
            subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True, text=True)
        cmd = f'"{RUNNER_CODEX}" "{task_id}" "{model}" "{effort}" "{worktree}" "{prompt_filename}"'
        sh(["tmux", "new-session", "-d", "-s", session, "-c", str(worktree), cmd], check=True)
        task["processId"] = None
        return

    old_pid = task.get("processId")
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


def main() -> None:
    print("Monitor started.")
    notified_ready = set()  # in-memory; persists only for process lifetime

    while True:
        try:
            items = load_registry()
            changed = False

            for t in items:
                try:
                    status = t.get("status")
                    if status not in ("running", "pr_created"):
                        continue

                    # Basic fields
                    session = t.get("tmuxSession")
                    process_id = t.get("processId")
                    execution_mode = t.get("executionMode", "tmux")
                    worktree = Path(t.get("worktree", ""))
                    branch = t.get("branch", "")
                    task_id = t.get("id")

                    if not task_id or not worktree.exists() or not branch:
                        t["status"] = "blocked"
                        t["note"] = "invalid task record (missing id/worktree/branch)"
                        changed = True
                        continue

                    if execution_mode == "process":
                        alive = process_alive(process_id)
                    else:
                        alive = bool(session) and tmux_alive(session)

                    # 1) PR info
                    pr = pr_info(worktree, branch)

                    if pr and t.get("status") == "running":
                        t["status"] = "pr_created"
                        t["pr"] = pr.get("number")
                        t["prUrl"] = pr.get("url")
                        changed = True

                    if not pr:
                        # Runtime only matters before a PR exists.
                        if not alive and t.get("status") == "running":
                            exit_info = load_exit_status(task_id)
                            if exit_info:
                                exit_code = exit_info.get("exitCode")
                                t["completedAt"] = exit_info.get("finishedAt")
                                if exit_code == 0:
                                    t["status"] = "agent_exited"
                                    t["note"] = "agent process exited cleanly before opening a PR"
                                else:
                                    t["status"] = "agent_failed"
                                    t["note"] = f"agent exited with code {exit_code}"
                                    notify(
                                        f"⚠️ Agent exited: `{task_id}` with code {exit_code}. Check logs."
                                    )
                            else:
                                t["status"] = "agent_dead"
                                t["note"] = (
                                    "background process not found"
                                    if execution_mode == "process"
                                    else "tmux session not found"
                                )
                                runtime_ref = (
                                    f"pid={process_id}" if execution_mode == "process" else session
                                )
                                notify(
                                    f"⚠️ Agent session dead: `{task_id}` ({runtime_ref}). Check logs."
                                )
                            changed = True
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
                except Exception as exc:
                    task_id = t.get("id", "<unknown>")
                    t["status"] = "blocked"
                    t["note"] = f"monitor error: {exc}"
                    changed = True
                    print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
                    continue

            if changed:
                save_registry(items)
        except Exception as exc:
            print(f"[ERROR] Monitor loop failed: {exc}")

        time.sleep(30)


if __name__ == "__main__":
    main()
