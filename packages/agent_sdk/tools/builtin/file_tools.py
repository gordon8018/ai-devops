"""File system tools with workspace boundary enforcement."""

from __future__ import annotations

from pathlib import Path


def _validate_path(file_path: str, workspace: str) -> Path:
    resolved = Path(file_path).resolve()
    ws_resolved = Path(workspace).resolve()
    if not str(resolved).startswith(str(ws_resolved)):
        raise PermissionError(f"Path {file_path} is outside workspace {workspace}")
    return resolved


def read_file_impl(file_path: str, workspace: str) -> str:
    resolved = _validate_path(file_path, workspace)
    if not resolved.exists():
        return f"Error: File {file_path} does not exist"
    return resolved.read_text(encoding="utf-8")


def write_file_impl(file_path: str, content: str, workspace: str) -> str:
    resolved = _validate_path(file_path, workspace)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"Successfully wrote {len(content)} bytes to {file_path}"


def list_directory_impl(dir_path: str, workspace: str) -> str:
    resolved = _validate_path(dir_path, workspace)
    if not resolved.is_dir():
        return f"Error: {dir_path} is not a directory"
    entries = sorted(str(p.relative_to(resolved)) for p in resolved.iterdir())
    return "\n".join(entries) if entries else "(empty directory)"
