#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path
from typing import Optional

BASE = Path.home() / "ai-devops"
QUEUE = BASE / "orchestrator" / "queue"
REPOS = BASE / "repos"
WORKTREES = BASE / "worktrees"
REGISTRY = BASE / ".clawdbot" / "active-tasks.json"

AGENT_RUNNER_CODEX = BASE / "agents" / "run-codex-agent.sh"

# Import prompt compiler (template now; later replace with OpenClaw-backed compiler)
from prompt_compiler import compile_prompt  # type: ignore


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


def tmux_has(session: str) -> bool:
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


def spawn_codex_agent(task: dict) -> dict:
    repo_name = task["repo"]
    repo_root = ensure_repo(repo_name)

    # Branch / worktree names
    branch = f"feat/{task['id']}"
    wt_dir = create_worktree(repo_root, branch)

    # Generate prompt
    prompt_txt = wt_dir / "prompt.txt"
    prompt = compile_prompt(task, wt_dir)
    prompt_txt.write_text(prompt, encoding="utf-8")

    # tmux session
    session = f"agent-{task['id']}"
    if tmux_has(session):
        raise RuntimeError(f"tmux session already exists: {session}")

    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")

    if not AGENT_RUNNER_CODEX.exists():
        raise RuntimeError(f"Codex runner not found: {AGENT_RUNNER_CODEX}")

    # IMPORTANT: runner supports optional PROMPT_FILE argument (5th arg)
    cmd = f'"{AGENT_RUNNER_CODEX}" "{task["id"]}" "{model}" "{effort}" "{wt_dir}" "{prompt_txt.name}"'
    sh(["tmux", "new-session", "-d", "-s", session, "-c", str(wt_dir), cmd])

    item = {
        "id": task["id"],
        "repo": repo_name,
        "title": task.get("title", ""),
        "branch": branch,
        "worktree": str(wt_dir),
        "tmuxSession": session,
        "agent": "codex",
        "model": model,
        "effort": effort,
        "status": "running",
        "startedAt": int(time.time() * 1000),
        "notifyOnComplete": True,

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

                item = spawn_codex_agent(task)
                reg.append(item)
                save_registry(reg)

                p.unlink(missing_ok=True)
                print(f"Spawned task {item['id']} in tmux {item['tmuxSession']}")
            except Exception as e:
                # Do NOT delete the task file; keep it for inspection/retry
                print(f"[ERROR] Failed processing {p}: {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
