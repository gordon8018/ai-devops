"""Shell command tools with whitelist enforcement and injection prevention."""

from __future__ import annotations

import shlex
import subprocess

COMMAND_WHITELIST = frozenset({
    "echo", "cat", "head", "tail", "wc", "sort", "uniq", "diff",
    "ls", "find", "grep", "rg",
    "git", "pytest", "python", "node", "npm", "npx", "make",
    "pip", "pip3", "flake8", "mypy", "ruff", "black",
})

# Characters that indicate shell metacharacter abuse
_SHELL_METACHAR = frozenset(";|&$`\\")

TOOL_TIMEOUT = 120


def _validate_command(command: str) -> list[str]:
    """Parse command into args list, validate executable against whitelist.

    Rejects commands containing shell metacharacters to prevent injection.
    Returns the parsed argument list for use with subprocess (no shell=True).
    """
    if not command.strip():
        raise PermissionError("Empty command")

    if any(ch in command for ch in _SHELL_METACHAR):
        raise PermissionError(
            f"Command contains shell metacharacters. "
            f"Only simple commands are allowed (no ;, |, &, $, `)."
        )

    args = shlex.split(command)
    base = args[0].split("/")[-1]
    if base not in COMMAND_WHITELIST:
        raise PermissionError(
            f"Command '{base}' is not whitelisted. Allowed: {', '.join(sorted(COMMAND_WHITELIST))}"
        )
    return args


def run_command_impl(command: str, workspace: str, timeout: int = TOOL_TIMEOUT) -> str:
    args = _validate_command(command)
    try:
        result = subprocess.run(
            args, cwd=workspace, capture_output=True,
            text=True, timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[stderr]: {result.stderr}" if result.stderr else ""
            output += f"\n[exit code]: {result.returncode}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
