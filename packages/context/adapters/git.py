from __future__ import annotations

import subprocess
from pathlib import Path


class GitContextAdapter:
    """Read recent repository changes for context packing."""

    def _run_git(self, repo_root: str | Path, args: list[str]) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()

    def recent_changes(self, repo_root: str | Path, limit: int = 5) -> tuple[str, ...]:
        output = self._run_git(repo_root, ["log", f"-n{limit}", "--pretty=format:%h %s"])
        if not output:
            return ()
        changes: list[str] = []
        for line in output.splitlines():
            text = line.strip()
            if not text:
                continue
            changes.append(f"commit:{text}")
        return tuple(changes)
