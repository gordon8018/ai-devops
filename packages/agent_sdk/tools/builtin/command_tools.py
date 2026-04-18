"""Shell command tools with whitelist enforcement."""

from __future__ import annotations

import subprocess

COMMAND_WHITELIST = frozenset({
    "echo", "cat", "head", "tail", "wc", "sort", "uniq", "diff",
    "ls", "find", "grep", "rg",
    "git", "pytest", "python", "node", "npm", "npx", "make",
    "pip", "pip3", "flake8", "mypy", "ruff", "black",
})

TOOL_TIMEOUT = 120


def run_command_impl(command: str, workspace: str, timeout: int = TOOL_TIMEOUT) -> str:
    first_word = command.strip().split()[0] if command.strip() else ""
    base = first_word.split("/")[-1]
    if base not in COMMAND_WHITELIST:
        raise PermissionError(
            f"Command '{base}' is not whitelisted. Allowed: {', '.join(sorted(COMMAND_WHITELIST))}"
        )
    try:
        result = subprocess.run(
            command, shell=True, cwd=workspace, capture_output=True,
            text=True, timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[stderr]: {result.stderr}" if result.stderr else ""
            output += f"\n[exit code]: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
