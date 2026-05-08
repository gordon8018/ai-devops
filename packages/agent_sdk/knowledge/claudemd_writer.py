"""Async-safe atomic append of extracted knowledge to CLAUDE.md."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from packages.agent_sdk.knowledge.knowledge_extractor import ExtractedKnowledge

MAX_CLAUDEMD_BYTES = 50 * 1024  # 50KB cap before archiving
SECTION_HEADER = "## Patterns (auto-accumulated by AI-DevOps)\n"

_FILE_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lock(path: str) -> asyncio.Lock:
    if path not in _FILE_LOCKS:
        _FILE_LOCKS[path] = asyncio.Lock()
    return _FILE_LOCKS[path]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _atomic_write(path: str, content: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _rotate(path: str, existing_content: str) -> None:
    archive_path = path + ".archive"
    with open(archive_path, "a", encoding="utf-8") as af:
        af.write(f"\n\n# Archived {datetime.now(timezone.utc).isoformat()}\n")
        af.write(existing_content)
    _atomic_write(path, f"# Project Knowledge\n\n{SECTION_HEADER}\n")


def _build_content(existing: str, entry: str, entry_hash: str) -> str:
    if SECTION_HEADER not in existing:
        existing = existing.rstrip() + f"\n\n{SECTION_HEADER}\n"
    return existing.rstrip() + f"\n\n<!-- hash:{entry_hash} -->\n{entry}\n"


class ClaudeMDWriter:
    """Async-safe, atomic append of knowledge entries to CLAUDE.md."""

    @staticmethod
    async def write(
        workspace_path: str,
        knowledge: ExtractedKnowledge,
        work_item_id: str,
        subtask_id: str,
        timestamp: str | None = None,
    ) -> bool:
        """Append knowledge to {workspace_path}/CLAUDE.md atomically. Returns True if written."""
        if knowledge.is_empty():
            return False

        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = ClaudeMDWriter._format_entry(knowledge, work_item_id, subtask_id, ts)
        entry_hash = _content_hash(entry)
        claudemd_path = str(Path(workspace_path) / "CLAUDE.md")

        async with _get_lock(claudemd_path):
            existing = await asyncio.to_thread(_read_file_safe, claudemd_path)

            if entry_hash in existing:
                return False  # dedup

            if len(existing.encode("utf-8")) > MAX_CLAUDEMD_BYTES:
                await asyncio.to_thread(_rotate, claudemd_path, existing)
                existing = ""

            new_content = _build_content(existing, entry, entry_hash)
            await asyncio.to_thread(_atomic_write, claudemd_path, new_content)
            return True

    @staticmethod
    def _format_entry(
        knowledge: ExtractedKnowledge,
        work_item_id: str,
        subtask_id: str,
        ts: str,
    ) -> str:
        lines = [f"### [{ts}] {work_item_id} / {subtask_id}"]
        if knowledge.patterns:
            lines.append("**Patterns:**")
            lines.extend(f"- {p}" for p in knowledge.patterns)
        if knowledge.gotchas:
            lines.append("**Gotchas:**")
            lines.extend(f"- {g}" for g in knowledge.gotchas)
        if knowledge.decisions:
            lines.append("**Decisions:**")
            lines.extend(f"- {d}" for d in knowledge.decisions)
        return "\n".join(lines)
