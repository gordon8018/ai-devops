from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

try:
    from .config import agent_scripts_dir, logs_dir
except ImportError:
    from config import agent_scripts_dir, logs_dir


try:
    from .tmux_manager import TmuxManager
except ImportError:
    from tmux_manager import TmuxManager


def runner_codex() -> str:
    return str(Path(os.getenv("CODEX_RUNNER_PATH", str(agent_scripts_dir() / "run-codex-agent.sh"))))


def runner_claude() -> str:
    return str(Path(os.getenv("CLAUDE_RUNNER_PATH", str(agent_scripts_dir() / "run-claude-agent.sh"))))


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
    return logs_dir() / f"{task_id}.exit.json"


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
    log_file = logs_dir() / f"{task_id}.log"
    if not log_file.exists():
        return False
    age_seconds = time.time() - log_file.stat().st_mtime
    return age_seconds > (max_age_minutes * 60)


def task_elapsed_minutes(task: dict) -> float:
    started_at = task.get("startedAt") or task.get("started_at")
    if not started_at:
        return 0
    now_ms = int(time.time() * 1000)
    return (now_ms - started_at) / 60000.0


def pr_info(repo_dir: Path, branch: str) -> Optional[dict]:
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
    mergeable_ok = str(mergeable).lower() in ("true", "mergeable")
    return mergeable_ok and status == "CLEAN"


def analyze_checks(pr: dict) -> Tuple[bool, Optional[str], bool]:
    rollup = pr.get("statusCheckRollup") or []
    if not rollup:
        return (False, None, True)

    pending = False
    failures = []
    for c in rollup:
        name = c.get("name") or c.get("context") or "check"
        status = (c.get("status") or "").upper()
        conc = (c.get("conclusion") or "").upper()
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
    if len(logs) > 2000:
        logs = logs[-2000:]
    return f"CI run failure ({url}) tail:\n{logs}"


def restart_agent(task: dict, worktree: Path, prompt_filename: str) -> None:
    session = task.get("tmuxSession") or task.get("tmux_session")
    agent = task.get("agent", "codex")
    if agent == "claude":
        runner = runner_claude()
        default_model = "claude-sonnet-4"
    else:
        runner = runner_codex()
        default_model = "gpt-5.3-codex"
    if not Path(runner).exists():
        raise RuntimeError(f"Runner not found for agent {agent}: {runner}")
    model = task.get("model", default_model)
    effort = task.get("effort", "high")
    task_id = task["id"]
    execution_mode = task.get("executionMode") or task.get("execution_mode", "tmux")

    if execution_mode == "tmux":
        if session:
            subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True, text=True)
        cmd = (
            f"{shlex.quote(runner)} {shlex.quote(task_id)} {shlex.quote(model)}"
            f" {shlex.quote(effort)} {shlex.quote(str(worktree))} {shlex.quote(prompt_filename)}"
        )
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
        [runner, task_id, model, effort, str(worktree), prompt_filename],
        cwd=str(worktree),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    task["processId"] = process.pid
    task["tmuxSession"] = None


def tmux_session_health_check(session_name: str, worktree: Path) -> dict:
    """使用 TmuxManager 检查会话健康状态"""
    runner = str(worktree / "dummy")  # dummy runner, will be replaced
    manager = TmuxManager(session_name, worktree, runner)
    info = manager.get_session_info()
    if info is None:
        return {"healthy": False, "reason": "tmux unavailable or session not exist"}
    return {"healthy": info["is_healthy"], "session": info}


def tmux_session_rebuild(task: dict, worktree: Path, prompt_filename: str) -> Tuple[bool, str]:
    """使用 TmuxManager 重建 tmux 会话"""
    session_name = task.get("tmuxSession") or task.get("tmux_session")
    agent = task.get("agent", "codex")
    task_id = task.get("id")
    model = task.get("model")
    effort = task.get("effort", "high")
    
    runner = runner_codex() if agent == "codex" else runner_claude()
    manager = TmuxManager(session_name, worktree, runner)
    return manager.safe_rebuild(agent, task_id, model, effort, prompt_filename)


def tmux_list_sessions() -> list[str]:
    """列出所有 tmux 会话"""
    if not tmux_available():
        return []
    try:
        from .tmux_manager import TmuxManager
    except ImportError:
        from tmux_manager import TmuxManager
    # 使用一个假的工作目录创建管理器
    from pathlib import Path
    manager = TmuxManager("_dummy_", Path("."), "dummy")
    return manager.list_sessions()

