#!/usr/bin/env python3
"""Tests for GbrainIndexer - Phase 3"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from gbrain_indexer import GbrainIndexer, GbrainIndexerError


class TestGbrainIndexer(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.gbrain_dir = os.path.join(self.tmpdir, "gbrain")
        os.makedirs(self.gbrain_dir)
        Path(self.gbrain_dir, "src", "cli.ts").parent.mkdir(parents=True, exist_ok=True)
        Path(self.gbrain_dir, "src", "cli.ts").write_text("// mock")
        self.indexer = GbrainIndexer(gbrain_dir=self.gbrain_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_run_gbrain_cmd_missing_dir(self):
        indexer = GbrainIndexer(gbrain_dir="/nonexistent")
        result = indexer._run_gbrain_cmd(["import", "/tmp"])
        self.assertFalse(result["success"])

    @patch("subprocess.run")
    def test_import_directory(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="imported 5 files", stderr="")
        artifact_dir = Path(self.tmpdir) / "artifacts"
        artifact_dir.mkdir()
        (artifact_dir / "test.md").write_text("content")

        result = self.indexer.import_directory(artifact_dir, tags=["tag1", "tag2"])
        self.assertTrue(result["success"])
        self.assertEqual(result["tags"], ["tag1", "tag2"])

    def test_import_directory_missing(self):
        result = self.indexer.import_directory(Path("/nonexistent"))
        self.assertFalse(result["success"])

    @patch("subprocess.run")
    def test_embed_new(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="embedded 10 docs", stderr="")
        result = self.indexer.embed_new()
        self.assertTrue(result["success"])

    @patch.object(GbrainIndexer, "import_directory")
    @patch.object(GbrainIndexer, "embed_new")
    def test_index_task_artifacts(self, mock_embed, mock_import):
        mock_import.return_value = {"success": True, "imported_dir": "/tmp/test"}
        mock_embed.return_value = {"success": True}

        artifact_dir = Path(self.tmpdir) / "art"
        artifact_dir.mkdir()
        result = self.indexer.index_task_artifacts("TASK-001", artifact_dir, project="test-proj", task_type="bugfix")

        self.assertTrue(result["success"])
        self.assertIn("TASK-001", result["tags"])
        self.assertIn("project:test-proj", result["tags"])
        self.assertIn("type:bugfix", result["tags"])

    @patch.object(GbrainIndexer, "index_task_artifacts")
    def test_index_from_obsidian_vault(self, mock_index):
        # Create vault reports
        vault_dir = Path.home() / "obsidian-vault" / "gordon8018" / "ai-devops" / "reports"
        vault_dir.mkdir(parents=True, exist_ok=True)
        report_file = vault_dir / f"report_TASK-Vault_20260101.md"
        report_file.write_text("# Report")

        mock_index.return_value = {"success": True, "task_id": "TASK-Vault"}
        result = self.indexer.index_from_obsidian_vault("TASK-Vault")

        # Cleanup
        report_file.unlink(missing_ok=True)

        self.assertTrue(result["success"])


class TestPhase3EndToEnd(unittest.TestCase):
    """End-to-end test for complete Phase 3 workflow."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("subprocess.run")
    def test_full_phase3_pipeline(self, mock_run):
        """Test: obsidian_sync → gbrain_indexer pipeline (mocked external commands)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

        # Setup
        vault_dir = os.path.join(self.tmpdir, "vault")
        ralph_dir = Path(self.tmpdir) / "ralph"
        ralph_dir.mkdir()
        (ralph_dir / "progress.txt").write_text("## Done")
        (ralph_dir / "prd.json").write_text(json.dumps({"project": "test"}))

        # Obsidian sync
        from obsidian_sync import ObsidianSync
        sync = ObsidianSync(vault_dir=vault_dir, fns_cli_dir=self.tmpdir)
        sync_result = sync.full_sync(ralph_dir, "E2E-001")
        self.assertTrue(sync_result.get("artifact_sync") is not None)

        # gbrain indexer
        gbrain_dir = Path(self.tmpdir) / "gbrain"
        gbrain_dir.mkdir()
        (gbrain_dir / "src").mkdir()
        (gbrain_dir / "src" / "cli.ts").write_text("")

        from gbrain_indexer import GbrainIndexer
        indexer = GbrainIndexer(gbrain_dir=str(gbrain_dir))
        idx_result = indexer.index_task_artifacts("E2E-001", ralph_dir)
        self.assertTrue(idx_result["success"])


if __name__ == "__main__":
    unittest.main()
