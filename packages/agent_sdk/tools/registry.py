"""Tool registry that resolves task type to available FunctionTools."""

from __future__ import annotations

from agents import function_tool

from packages.agent_sdk.tools.builtin.file_tools import read_file_impl, write_file_impl, list_directory_impl
from packages.agent_sdk.tools.builtin.command_tools import run_command_impl


@function_tool
def read_file(file_path: str, workspace: str = ".") -> str:
    """Read the contents of a file within the workspace."""
    return read_file_impl(file_path, workspace)

@function_tool
def write_file(file_path: str, content: str, workspace: str = ".") -> str:
    """Write content to a file within the workspace."""
    return write_file_impl(file_path, content, workspace)

@function_tool
def list_directory(dir_path: str = ".", workspace: str = ".") -> str:
    """List files and directories within the workspace."""
    return list_directory_impl(dir_path, workspace)

@function_tool
def run_command(command: str, workspace: str = ".") -> str:
    """Run a whitelisted shell command in the workspace."""
    return run_command_impl(command, workspace)

@function_tool
def search_code(pattern: str, workspace: str = ".", file_glob: str = "") -> str:
    """Search for a pattern in code files using grep."""
    import shlex
    safe_pattern = shlex.quote(pattern)
    if file_glob:
        safe_glob = shlex.quote(file_glob)
        cmd = f"grep -rn --include={safe_glob} {safe_pattern} ."
    else:
        cmd = f"grep -rn {safe_pattern} ."
    return run_command_impl(cmd, workspace)

@function_tool
def run_tests(test_path: str = "", workspace: str = ".") -> str:
    """Run the test suite using pytest."""
    cmd = f"pytest -q {test_path}" if test_path else "pytest -q"
    return run_command_impl(cmd, workspace)

@function_tool
def lint_check(workspace: str = ".") -> str:
    """Run linting checks."""
    return run_command_impl("ruff check .", workspace)

@function_tool
def type_check(workspace: str = ".") -> str:
    """Run type checking."""
    return run_command_impl("mypy .", workspace)

@function_tool
def git_diff(workspace: str = ".") -> str:
    """Show git diff of current changes."""
    return run_command_impl("git diff", workspace)

@function_tool
def git_log(count: int = 10, workspace: str = ".") -> str:
    """Show recent git log entries."""
    return run_command_impl(f"git log --oneline -n {count}", workspace)

@function_tool
def coverage_report(workspace: str = ".") -> str:
    """Run tests with coverage report."""
    return run_command_impl("pytest --cov --cov-report=term-missing -q", workspace)


_COMMON_TOOLS = [read_file, write_file, list_directory, run_command, search_code]

_TASK_TOOLS: dict[str, list] = {
    "code_generation": [run_tests, lint_check, type_check],
    "code_review":     [git_diff],
    "bug_fix":         [run_tests, git_log],
    "refactor":        [run_tests, type_check],
    "test_generation": [run_tests, coverage_report],
    "documentation":   [],
    "planning":        [],
    "incident_analysis": [git_log],
}


class ToolRegistry:
    @staticmethod
    def resolve(task_type: str) -> list:
        extras = _TASK_TOOLS.get(task_type, [])
        return _COMMON_TOOLS + extras
