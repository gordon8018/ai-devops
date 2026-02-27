#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

BASE = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
QUEUE = BASE / "orchestrator" / "queue"
REPOS = BASE / "repos"
WORKTREES = BASE / "worktrees"
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"

AGENT_RUNNER_CODEX = Path(os.getenv("CODEX_RUNNER_PATH", str(BASE / "agents" / "run-codex-agent.sh")))
AGENT_RUNNER_CLAUDE = Path(os.getenv("CLAUDE_RUNNER_PATH", str(BASE / "agents" / "run-claude-agent.sh")))

# Import prompt compiler (template fallback when Zoe did not provide a prompt)
from prompt_compiler import compile_prompt  # type: ignore


def sanitize_branch_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", "/") else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-_/") or "task"


def sh(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> str:
    r = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"CWD: {cwd}\n"
            f"STDOUT:\n{r.stdout}\n"
            f"STDERR:\n{r.stderr}\n"
        )
    return (r.stdout or "").strip()


def load_registry() -> list[dict]:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY.exists():
        REGISTRY.write_text("[]", encoding="utf-8")
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_registry(items: list[dict]) -> None:
    REGISTRY.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_has(session: str) -> bool:
    if not tmux_available():
        return False
    r = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True, text=True)
    return r.returncode == 0


def ensure_repo(repo_name: str) -> Path:
    repo_root = REPOS / repo_name
    if not repo_root.exists():
        raise RuntimeError(
            f"Repo not found: {repo_root}\n"
            f"Clone it under ~/ai-devops/repos/{repo_name} first."
        )
    return repo_root


def create_worktree(repo_root: Path, branch: str) -> Path:
    """
    Create a worktree from origin/main into WORKTREES/<branch-with-dashes>.
    If your default branch isn't main, change origin/main accordingly.
    """
    WORKTREES.mkdir(parents=True, exist_ok=True)

    wt_dir = WORKTREES / branch.replace("/", "-")
    if wt_dir.exists():
        # If directory exists, treat it as already provisioned. Still ensure worktree is attached.
        return wt_dir

    sh(["git", "fetch", "origin"], cwd=repo_root)

    # Create worktree based on origin/main
    sh(["git", "worktree", "add", str(wt_dir), "-b", branch, "origin/main"], cwd=repo_root)
    return wt_dir


def runner_for_agent(agent: str) -> Path:
    if agent == "codex":
        return AGENT_RUNNER_CODEX
    if agent == "claude":
        return AGENT_RUNNER_CLAUDE
    raise RuntimeError(f"Unsupported agent: {agent}")


def resolve_branch(task: dict) -> str:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    worktree_strategy = metadata.get("worktreeStrategy")
    if worktree_strategy == "shared" and metadata.get("planId"):
        return f"plan/{sanitize_branch_component(str(metadata['planId']))}"
    return f"feat/{sanitize_branch_component(task['id'])}"


def launch_agent_process(
    runner: Path,
    task: dict,
    wt_dir: Path,
    prompt_txt: Path,
) -> tuple[str, str | None, int | None]:
    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")
    session = f"agent-{task['id']}"

    if tmux_available():
        if tmux_has(session):
            raise RuntimeError(f"tmux session already exists: {session}")
        cmd = f'"{runner}" "{task["id"]}" "{model}" "{effort}" "{wt_dir}" "{prompt_txt.name}"'
        sh(["tmux", "new-session", "-d", "-s", session, "-c", str(wt_dir), cmd])
        return ("tmux", session, None)

    process = subprocess.Popen(
        [str(runner), task["id"], model, effort, str(wt_dir), prompt_txt.name],
        cwd=str(wt_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return ("process", None, process.pid)


def spawn_agent(task: dict) -> dict:
    repo_name = task["repo"]
    repo_root = ensure_repo(repo_name)
    agent = str(task.get("agent", "codex"))

    # Branch / worktree names
    branch = resolve_branch(task)
    wt_dir = create_worktree(repo_root, branch)

    # Generate prompt
    prompt_txt = wt_dir / "prompt.txt"
    prompt = task.get("prompt") or compile_prompt(task, wt_dir)
    prompt_txt.write_text(prompt, encoding="utf-8")

    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")

    runner = runner_for_agent(agent)
    if not runner.exists():
        raise RuntimeError(f"Runner not found for agent {agent}: {runner}")

    execution_mode, session, process_id = launch_agent_process(runner, task, wt_dir, prompt_txt)

    item = {
        "id": task["id"],
        "repo": repo_name,
        "title": task.get("title", ""),
        "branch": branch,
        "worktree": str(wt_dir),
        "tmuxSession": session,
        "processId": process_id,
        "executionMode": execution_mode,
        "agent": agent,
        "model": model,
        "effort": effort,
        "status": "running",
        "startedAt": int(time.time() * 1000),
        "notifyOnComplete": True,
        "metadata": task.get("metadata", {}),
        "planId": task.get("metadata", {}).get("planId") if isinstance(task.get("metadata"), dict) else None,
        "subtaskId": task.get("metadata", {}).get("subtaskId") if isinstance(task.get("metadata"), dict) else None,
        "worktreeStrategy": task.get("metadata", {}).get("worktreeStrategy") if isinstance(task.get("metadata"), dict) else None,
        "promptSource": "task.prompt" if task.get("prompt") else "prompt_compiler",

        # Ralph Loop controls
        "attempts": 0,
        "maxAttempts": int(task.get("maxAttempts", 3)),
        "promptFile": str(prompt_txt),
        "lastFailure": None,
        "pr": None,
        "prUrl": None,
        "completedAt": None,
        "note": None,
    }
    return item


def main() -> None:
    QUEUE.mkdir(parents=True, exist_ok=True)
    print(f"Zoe daemon started. Watching queue: {QUEUE}")

    while True:
        for p in sorted(QUEUE.glob("*.json")):
            try:
                task = json.loads(p.read_text(encoding="utf-8"))
                if "id" not in task or "repo" not in task:
                    raise RuntimeError(f"Invalid task JSON (missing id/repo): {p}")

                reg = load_registry()
                if any(x.get("id") == task["id"] for x in reg):
                    # already tracked; remove queue item to avoid loops
                    p.unlink(missing_ok=True)
                    continue

                item = spawn_agent(task)
                reg.append(item)
                save_registry(reg)

                p.unlink(missing_ok=True)
                if item["executionMode"] == "tmux":
                    print(f"Spawned task {item['id']} in tmux {item['tmuxSession']}")
                else:
                    print(f"Spawned task {item['id']} as background process {item['processId']}")
            except Exception as e:
                # Do NOT delete the task file; keep it for inspection/retry
                print(f"[ERROR] Failed processing {p}: {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
