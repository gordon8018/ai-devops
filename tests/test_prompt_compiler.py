#!/usr/bin/env python3
"""
Tests for prompt_compiler.py

Covers:
- Prompt compilation with context files
- Task formatting
- Context file discovery
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

# Add orchestrator to path
SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
import sys
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from prompt_compiler import compile_prompt


class TestPromptCompiler(unittest.TestCase):
    """Test prompt compilation logic"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_task(self, **overrides) -> dict:
        """Helper to create task dict"""
        task = {
            "title": "Test Task",
            "description": "Test description",
        }
        task.update(overrides)
        return task

    def test_compile_prompt_basic(self):
        """Test basic prompt compilation"""
        task = self.make_task(
            title="Fix login bug",
            description="Fix the login timeout issue",
        )
        
        prompt = compile_prompt(task, self.repo_root)
        
        self.assertIn("Fix login bug", prompt)
        self.assertIn("Fix the login timeout issue", prompt)
        self.assertIn("TASK TITLE:", prompt)
        self.assertIn("TASK DESCRIPTION:", prompt)
        self.assertIn("DEFINITION OF DONE:", prompt)
        self.assertIn("CONSTRAINTS:", prompt)
        self.assertIn("FIRST STEP:", prompt)

    def test_compile_prompt_with_context_files(self):
        """Test prompt includes existing context files"""
        # Create context files
        (self.repo_root / "README.md").write_text("# Test Repo")
        (self.repo_root / "SPEC.md").write_text("# Specification")
        
        task = self.make_task()
        prompt = compile_prompt(task, self.repo_root)
        
        self.assertIn("Useful context files:", prompt)
        self.assertIn("SPEC.md", prompt)
        self.assertIn("README.md", prompt)

    def test_compile_prompt_no_context_files(self):
        """Test prompt handles missing context files"""
        task = self.make_task()
        prompt = compile_prompt(task, self.repo_root)
        
        # Should still work, just without context hint
        self.assertIn("FIRST STEP:", prompt)

    def test_compile_prompt_only_some_context_files(self):
        """Test prompt includes only existing context files"""
        # Create only README
        (self.repo_root / "README.md").write_text("# Test Repo")
        
        task = self.make_task()
        prompt = compile_prompt(task, self.repo_root)
        
        self.assertIn("README.md", prompt)
        self.assertNotIn("SPEC.md", prompt)
        self.assertNotIn("CONTEXT.md", prompt)

    def test_compile_prompt_includes_engineering_guidance(self):
        """Test prompt includes standard engineering guidance"""
        task = self.make_task()
        prompt = compile_prompt(task, self.repo_root)
        
        # Check for standard engineering practices
        self.assertIn("senior engineer", prompt.lower())
        self.assertIn("Implement the change", prompt)
        self.assertIn("Add/adjust tests", prompt)
        self.assertIn("Run local checks", prompt)
        self.assertIn("Create commits with clear messages", prompt)
        self.assertIn("minimal, safe changes", prompt.lower())
        self.assertIn("search within repo first", prompt.lower())

    def test_compile_prompt_with_special_chars(self):
        """Test prompt handles special characters in title/description"""
        task = self.make_task(
            title="Fix bug: 'timeout' & <null> handling",
            description="Handle edge cases with \"quotes\" and\nnewlines",
        )
        
        prompt = compile_prompt(task, self.repo_root)
        
        # Should not raise, should include content
        self.assertIn("Fix bug:", prompt)
        self.assertIn("Handle edge cases", prompt)


class TestPromptCompilerIntegration(unittest.TestCase):
    """Integration tests for prompt compiler CLI"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.repo_root = self.base / "repo"
        self.repo_root.mkdir()
        (self.repo_root / "README.md").write_text("# Test")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_invocation(self):
        """Test CLI can be invoked directly"""
        import subprocess
        import sys
        
        task_file = self.base / "task.json"
        task = {
            "title": "CLI Test",
            "description": "Test via CLI",
        }
        task_file.write_text(json.dumps(task))
        
        compiler_path = BASE / "orchestrator" / "bin" / "prompt_compiler.py"
        
        result = subprocess.run(
            [sys.executable, str(compiler_path), str(task_file), str(self.repo_root)],
            capture_output=True,
            text=True,
        )
        
        self.assertEqual(result.returncode, 0)
        self.assertIn("CLI Test", result.stdout)


if __name__ == "__main__":
    unittest.main()
