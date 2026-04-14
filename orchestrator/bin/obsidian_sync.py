#!/usr/bin/env python3
"""
Obsidian Auto-Sync Module - Phase 3

Syncs ralph task artifacts (AGENTS.md updates, completion reports, code review summaries,
decision records) to the Obsidian vault and triggers FastNodeSync for cloud push.
"""

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ObsidianSyncError(Exception):
    pass


class ObsidianSync:
    """Syncs task artifacts to Obsidian vault and triggers cloud sync via FastNodeSync."""

    def __init__(
        self,
        vault_dir: Optional[str] = None,
        fns_cli_dir: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        # Resolve paths
        home = Path.home()
        self.vault_dir = Path(vault_dir or home / "obsidian-vault" / "gordon8018" / "ai-devops")
        self.fns_cli_dir = Path(fns_cli_dir or home / "FastNodeSync-CLI")

        # Load config if provided
        self.config: Dict[str, Any] = {}
        if config_path:
            cfg = Path(config_path)
            if cfg.exists():
                self.config = json.loads(cfg.read_text())

        # Sync targets within vault
        self.sync_dirs = {
            "reports": self.vault_dir / "reports",
            "reviews": self.vault_dir / "reviews",
            "decisions": self.vault_dir / "decisions",
            "agents": self.vault_dir / "agents",
        }

    def ensure_vault_dirs(self) -> None:
        """Create vault subdirectories if they don't exist."""
        for d in self.sync_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    def sync_agents_md(self, source_agents_path: Path) -> Dict[str, Any]:
        """Copy AGENTS.md to Obsidian vault with timestamp header."""
        if not source_agents_path.exists():
            return {"synced": False, "error": f"Source not found: {source_agents_path}"}

        dest = self.sync_dirs["agents"] / f"AGENTS_{datetime.now().strftime('%Y%m%d')}.md"
        self.ensure_vault_dirs()

        content = source_agents_path.read_text(encoding="utf-8")
        header = (
            f"---\n"
            f"synced_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"source: {source_agents_path}\n"
            f"tags: [agents-md, auto-sync]\n"
            f"---\n\n"
        )
        dest.write_text(header + content, encoding="utf-8")

        return {"synced": True, "dest": str(dest), "size": len(content)}

    def sync_task_report(self, task_id: str, report_content: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """Write a task completion report to Obsidian vault."""
        self.ensure_vault_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"report_{task_id}_{ts}.md"
        dest = self.sync_dirs["reports"] / filename

        meta = metadata or {}
        tags = meta.get("tags", ["task-report", task_id])
        if isinstance(tags, list):
            tags_str = ", ".join(tags)
        else:
            tags_str = tags

        header = (
            f"---\n"
            f"task_id: {task_id}\n"
            f"created_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"tags: [{tags_str}]\n"
            f"---\n\n"
            f"# Task Report: {task_id}\n\n"
        )
        dest.write_text(header + report_content, encoding="utf-8")

        return {"synced": True, "dest": str(dest)}

    def sync_review_summary(self, task_id: str, review_content: str) -> Dict[str, Any]:
        """Write a code review summary to Obsidian vault."""
        self.ensure_vault_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.sync_dirs["reviews"] / f"review_{task_id}_{ts}.md"

        header = (
            f"---\n"
            f"task_id: {task_id}\n"
            f"type: code-review\n"
            f"created_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"tags: [code-review, {task_id}]\n"
            f"---\n\n"
            f"# Code Review: {task_id}\n\n"
        )
        dest.write_text(header + review_content, encoding="utf-8")

        return {"synced": True, "dest": str(dest)}

    def sync_decision_record(self, task_id: str, decision: str, context: str = "") -> Dict[str, Any]:
        """Write an important decision record to Obsidian vault."""
        self.ensure_vault_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = self.sync_dirs["decisions"] / f"decision_{task_id}_{ts}.md"

        header = (
            f"---\n"
            f"task_id: {task_id}\n"
            f"type: decision-record\n"
            f"created_at: {datetime.now(timezone.utc).isoformat()}\n"
            f"tags: [decision, {task_id}]\n"
            f"---\n\n"
            f"# Decision Record: {task_id}\n\n"
        )
        body = f"## Decision\n{decision}\n\n"
        if context:
            body += f"## Context\n{context}\n"

        dest.write_text(header + body, encoding="utf-8")

        return {"synced": True, "dest": str(dest)}

    def sync_ralph_artifacts(self, ralph_dir: Path, task_id: str) -> Dict[str, Any]:
        """Sync all ralph task artifacts to Obsidian vault.

        Scans ralph_dir for standard artifacts and syncs them.
        """
        results = {"synced_files": [], "errors": []}
        self.ensure_vault_dirs()

        # Sync progress.txt as task report
        progress_file = ralph_dir / "progress.txt"
        if progress_file.exists():
            r = self.sync_task_report(task_id, progress_file.read_text(encoding="utf-8"))
            if r["synced"]:
                results["synced_files"].append(r["dest"])

        # Sync prd.json summary as decision record
        prd_file = ralph_dir / "prd.json"
        if prd_file.exists():
            try:
                prd = json.loads(prd_file.read_text(encoding="utf-8"))
                summary = json.dumps(prd, indent=2, ensure_ascii=False)[:2000]
                r = self.sync_decision_record(task_id, f"PRD for {prd.get('project', task_id)}", summary)
                if r["synced"]:
                    results["synced_files"].append(r["dest"])
            except Exception as e:
                results["errors"].append(f"prd.json parse error: {e}")

        return results

    def trigger_fast_node_sync(self) -> Dict[str, Any]:
        """Trigger FastNodeSync-CLI to push changes to cloud."""
        if not self.fns_cli_dir.exists():
            return {"success": False, "error": f"FastNodeSync-CLI not found at {self.fns_cli_dir}"}

        try:
            result = subprocess.run(
                ["python3", "-m", "fns_cli.main", "run"],
                cwd=str(self.fns_cli_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[-500:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "FastNodeSync timed out after 120s"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def full_sync(self, ralph_dir: Path, task_id: str, agents_md_path: Optional[Path] = None) -> Dict[str, Any]:
        """Run complete sync: artifacts → Obsidian vault → FastNodeSync cloud push."""
        result = {
            "task_id": task_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "artifact_sync": None,
            "agents_sync": None,
            "cloud_sync": None,
        }

        # 1. Sync ralph artifacts
        result["artifact_sync"] = self.sync_ralph_artifacts(ralph_dir, task_id)

        # 2. Sync AGENTS.md if provided
        if agents_md_path:
            result["agents_sync"] = self.sync_agents_md(agents_md_path)

        # 3. Trigger cloud sync
        result["cloud_sync"] = self.trigger_fast_node_sync()

        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        result["success"] = (
            result["artifact_sync"] is not None
            and result["cloud_sync"].get("success", False)
        )

        return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("ObsidianSync CLI")
        print("Usage:")
        print("  obsidian_sync.py full <ralph_dir> <task_id> [agents_md_path]")
        print("  obsidian_sync.py sync-artifacts <ralph_dir> <task_id>")
        print("  obsidian_sync.py cloud-push")
        sys.exit(0)

    cmd = sys.argv[1]
    sync = ObsidianSync()

    if cmd == "full":
        ralph_dir = Path(sys.argv[2])
        task_id = sys.argv[3]
        agents_md = Path(sys.argv[4]) if len(sys.argv) > 4 else None
        result = sync.full_sync(ralph_dir, task_id, agents_md)
        print(json.dumps(result, indent=2))

    elif cmd == "sync-artifacts":
        ralph_dir = Path(sys.argv[2])
        task_id = sys.argv[3]
        result = sync.sync_ralph_artifacts(ralph_dir, task_id)
        print(json.dumps(result, indent=2))

    elif cmd == "cloud-push":
        result = sync.trigger_fast_node_sync()
        print(json.dumps(result, indent=2))
