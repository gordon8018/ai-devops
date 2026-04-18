from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_run_codex_agent_requires_task_spec_when_flagged(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    prompt = worktree / "prompt.txt"
    prompt.write_text("hello", encoding="utf-8")
    runner = Path(__file__).resolve().parents[1] / "agent_scripts" / "run-codex-agent.sh"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["TASK_SPEC_REQUIRED"] = "1"
    env.pop("TASK_SPEC_FILE", None)
    env["CODEX_BIN"] = "/usr/bin/true"

    result = subprocess.run(
        [str(runner), "task-1", "gpt-5.3-codex", "high", str(worktree), "prompt.txt"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 66
    assert "TASK_SPEC_FILE is required" in result.stderr


def test_run_codex_agent_requires_scope_manifest_if_declared(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    prompt = worktree / "prompt.txt"
    prompt.write_text("hello", encoding="utf-8")
    task_spec = worktree / "task-spec.json"
    task_spec.write_text('{"allowedPaths": ["skills/**"]}', encoding="utf-8")
    runner = Path(__file__).resolve().parents[1] / "agent_scripts" / "run-codex-agent.sh"

    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    env["TASK_SPEC_REQUIRED"] = "1"
    env["TASK_SPEC_FILE"] = str(task_spec)
    env["SCOPE_MANIFEST_FILE"] = str(worktree / ".task-contract" / "scope-manifest.json")
    env["CODEX_BIN"] = "/usr/bin/true"

    result = subprocess.run(
        [str(runner), "task-2", "gpt-5.3-codex", "high", str(worktree), "prompt.txt"],
        cwd=str(worktree),
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 67
    assert "SCOPE_MANIFEST_FILE was provided but missing" in result.stderr
