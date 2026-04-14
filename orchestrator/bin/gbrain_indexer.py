#!/usr/bin/env python3
"""
gbrain Indexer Module - Phase 3

Indexes task artifacts into gbrain knowledge base with automatic
categorization, tagging, and vector embedding.
"""

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class GbrainIndexerError(Exception):
    pass


class GbrainIndexer:
    """Indexes task artifacts into gbrain vector knowledge base."""

    def __init__(
        self,
        gbrain_dir: Optional[str] = None,
        config_path: Optional[str] = None,
    ):
        home = Path.home()
        self.gbrain_dir = Path(gbrain_dir or home / ".openclaw" / "workspace-alpha" / "gbrain")

        self.config: Dict[str, Any] = {}
        if config_path:
            cfg = Path(config_path)
            if cfg.exists():
                self.config = json.loads(cfg.read_text())

    def _run_gbrain_cmd(self, args: List[str], timeout: int = 300) -> Dict[str, Any]:
        """Execute a gbrain CLI command."""
        if not self.gbrain_dir.exists():
            return {"success": False, "error": f"gbrain dir not found: {self.gbrain_dir}"}

        cmd = ["bun", "run", "src/cli.ts"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.gbrain_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[-1000:] if result.stdout else "",
                "stderr": result.stderr[-500:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"gbrain command timed out after {timeout}s"}
        except FileNotFoundError:
            return {"success": False, "error": "bun not found in PATH"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def import_directory(self, directory: Path, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """Import a directory of documents into gbrain."""
        if not directory.exists():
            return {"success": False, "error": f"Directory not found: {directory}"}

        # Create metadata file for tags if provided
        meta_file = None
        if tags:
            meta_file = directory / ".gbrain_meta.json"
            meta_file.write_text(json.dumps({
                "tags": tags,
                "imported_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2))

        result = self._run_gbrain_cmd(["import", str(directory)])

        # Cleanup temp meta file
        if meta_file and meta_file.exists():
            meta_file.unlink()

        if result["success"]:
            result["imported_dir"] = str(directory)
            result["tags"] = tags or []

        return result

    def embed_new(self) -> Dict[str, Any]:
        """Trigger vector embedding for newly imported documents."""
        return self._run_gbrain_cmd(["embed", "--all"])

    def index_task_artifacts(
        self,
        task_id: str,
        artifact_dir: Path,
        project: str = "ai-devops",
        task_type: str = "general",
        execution_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Index task artifacts with categorization and tagging.

        Args:
            task_id: Task identifier
            artifact_dir: Directory containing task artifacts
            project: Project name for categorization
            task_type: Type of task (bugfix, feature, refactor, etc.)
            execution_metadata: Optional execution metadata (iterations, duration, quality_score, etc.)
        """
        ts = datetime.now().strftime("%Y%m%d")
        tags = [
            task_id,
            f"date:{ts}",
            f"project:{project}",
            f"type:{task_type}",
        ]

        # Import artifacts with execution metadata
        meta_file = None
        if execution_metadata:
            meta_file = artifact_dir / ".gbrain_exec_meta.json"
            meta_file.write_text(json.dumps({
                "task_id": task_id,
                "execution_metadata": execution_metadata,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2))

        import_result = self.import_directory(artifact_dir, tags=tags)

        # Cleanup temp meta file
        if meta_file and meta_file.exists():
            meta_file.unlink()

        if not import_result["success"]:
            return {
                "task_id": task_id,
                "import": import_result,
                "embed": None,
                "success": False,
            }

        # Trigger embedding
        embed_result = self.embed_new()

        return {
            "task_id": task_id,
            "tags": tags,
            "import": import_result,
            "embed": embed_result,
            "execution_metadata": execution_metadata,
            "success": import_result["success"] and embed_result.get("success", False),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    def index_from_obsidian_vault(self, task_id: str, project: str = "ai-devops") -> Dict[str, Any]:
        """Index recent Obsidian vault entries for a task into gbrain."""
        home = Path.home()
        vault_reports = home / "obsidian-vault" / "gordon8018" / "ai-devops" / "reports"

        if not vault_reports.exists():
            return {"success": False, "error": "Obsidian vault reports dir not found"}

        # Find files matching task_id
        matching_files = list(vault_reports.glob(f"*{task_id}*"))
        if not matching_files:
            return {"success": False, "error": f"No reports found for task {task_id}"}

        # Create temp staging dir
        staging = Path(f"/tmp/gbrain_staging_{task_id}")
        staging.mkdir(parents=True, exist_ok=True)

        for f in matching_files:
            dest = staging / f.name
            dest.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

        result = self.index_task_artifacts(task_id, staging, project=project)

        # Cleanup staging
        for f in staging.iterdir():
            f.unlink()
        staging.rmdir()

        return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("GbrainIndexer CLI")
        print("Usage:")
        print("  gbrain_indexer.py import <dir> [--tags tag1,tag2]")
        print("  gbrain_indexer.py embed")
        print("  gbrain_indexer.py index-task <task_id> <artifact_dir> [--project name] [--type type]")
        print("  gbrain_indexer.py index-vault <task_id> [--project name]")
        sys.exit(0)

    cmd = sys.argv[1]
    indexer = GbrainIndexer()

    if cmd == "import":
        directory = Path(sys.argv[2])
        tags = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[3] == "--tags" else None
        result = indexer.import_directory(directory, tags=tags)
        print(json.dumps(result, indent=2))

    elif cmd == "embed":
        result = indexer.embed_new()
        print(json.dumps(result, indent=2))

    elif cmd == "index-task":
        task_id = sys.argv[2]
        artifact_dir = Path(sys.argv[3])
        project = "ai-devops"
        task_type = "general"
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == "--project" and i + 1 < len(sys.argv):
                project = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--type" and i + 1 < len(sys.argv):
                task_type = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        result = indexer.index_task_artifacts(task_id, artifact_dir, project=project, task_type=task_type)
        print(json.dumps(result, indent=2))

    elif cmd == "index-vault":
        task_id = sys.argv[2]
        project = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--project" else "ai-devops"
        result = indexer.index_from_obsidian_vault(task_id, project=project)
        print(json.dumps(result, indent=2))
