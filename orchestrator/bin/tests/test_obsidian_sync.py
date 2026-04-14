#!/usr/bin/env python3
"""Tests for ObsidianSync - Phase 3"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from obsidian_sync import ObsidianSync, ObsidianSyncError


class TestObsidianSync(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.vault_dir = os.path.join(self.tmpdir, "vault")
        self.sync = ObsidianSync(vault_dir=self.vault_dir, fns_cli_dir="/nonexistent")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ensure_vault_dirs(self):
        self.sync.ensure_vault_dirs()
        for d in self.sync.sync_dirs.values():
            self.assertTrue(d.exists())

    def test_sync_agents_md(self):
        source = Path(self.tmpdir) / "AGENTS.md"
        source.write_text("# Test AGENTS\nContent here")
        result = self.sync.sync_agents_md(source)
        self.assertTrue(result["synced"])
        self.assertTrue(Path(result["dest"]).exists())
        content = Path(result["dest"]).read_text()
        self.assertIn("synced_at:", content)
        self.assertIn("# Test AGENTS", content)

    def test_sync_agents_md_missing_source(self):
        result = self.sync.sync_agents_md(Path("/nonexistent/AGENTS.md"))
        self.assertFalse(result["synced"])

    def test_sync_task_report(self):
        result = self.sync.sync_task_report("TASK-001", "Task completed successfully")
        self.assertTrue(result["synced"])
        content = Path(result["dest"]).read_text()
        self.assertIn("TASK-001", content)
        self.assertIn("Task completed successfully", content)

    def test_sync_review_summary(self):
        result = self.sync.sync_review_summary("TASK-002", "LGTM, minor nits")
        self.assertTrue(result["synced"])
        content = Path(result["dest"]).read_text()
        self.assertIn("code-review", content)

    def test_sync_decision_record(self):
        result = self.sync.sync_decision_record("TASK-003", "Use PostgreSQL", "Need ACID compliance")
        self.assertTrue(result["synced"])
        content = Path(result["dest"]).read_text()
        self.assertIn("PostgreSQL", content)
        self.assertIn("ACID", content)

    def test_sync_ralph_artifacts(self):
        ralph_dir = Path(self.tmpdir) / "ralph_task"
        ralph_dir.mkdir()
        (ralph_dir / "progress.txt").write_text("## Iteration 1\nDone")
        (ralph_dir / "prd.json").write_text(json.dumps({"project": "test"}))

        result = self.sync.sync_ralph_artifacts(ralph_dir, "TASK-004")
        self.assertGreater(len(result["synced_files"]), 0)

    def test_trigger_fast_node_sync_missing_dir(self):
        result = self.sync.trigger_fast_node_sync()
        self.assertFalse(result["success"])

    def test_full_sync(self):
        ralph_dir = Path(self.tmpdir) / "ralph_full"
        ralph_dir.mkdir()
        (ralph_dir / "progress.txt").write_text("Done")
        agents_md = Path(self.tmpdir) / "AGENTS.md"
        agents_md.write_text("# Agents")

        result = self.sync.full_sync(ralph_dir, "TASK-005", agents_md)
        self.assertIn("artifact_sync", result)
        self.assertIn("agents_sync", result)

    def test_tags_in_report(self):
        result = self.sync.sync_task_report("T1", "content", metadata={"tags": ["custom-tag"]})
        content = Path(result["dest"]).read_text()
        self.assertIn("custom-tag", content)


if __name__ == "__main__":
    unittest.main()
