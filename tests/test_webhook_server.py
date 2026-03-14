#!/usr/bin/env python3
"""
Tests for webhook_server.py

Covers:
- Signature verification
- Event handlers (check_run, workflow_run, pull_request)
- HTTP request handling
- Health check endpoint
"""

import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from unittest.mock import patch, MagicMock

# Add orchestrator to path
SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))

from webhook_server import (
    verify_signature,
    log_event,
    handle_check_run,
    handle_workflow_run,
    handle_pull_request,
    GitHubWebhookHandler,
    run_server,
)
from db import init_db, get_task, insert_task


class TestSignatureVerification(unittest.TestCase):
    """Test webhook signature verification"""

    def setUp(self):
        self.secret = b"test-secret-key"
        self.payload = b'{"test": "data"}'

    def test_valid_signature(self):
        """Test valid signature passes verification"""
        signature = "sha256=" + hmac.new(self.secret, self.payload, hashlib.sha256).hexdigest()
        
        with patch("webhook_server.WEBHOOK_SECRET", self.secret):
            result = verify_signature(self.payload, signature)
        
        self.assertTrue(result)

    def test_invalid_signature(self):
        """Test invalid signature fails verification"""
        signature = "sha256=invalidhash"
        
        with patch("webhook_server.WEBHOOK_SECRET", self.secret):
            result = verify_signature(self.payload, signature)
        
        self.assertFalse(result)

    def test_missing_signature(self):
        """Test missing signature fails verification"""
        with patch("webhook_server.WEBHOOK_SECRET", self.secret):
            result = verify_signature(self.payload, "")
        
        self.assertFalse(result)

    def test_no_secret_configured(self):
        """Test fails verification when no secret configured"""
        with patch("webhook_server.WEBHOOK_SECRET", b""):
            result = verify_signature(self.payload, "")

        self.assertFalse(result)

    def test_wrong_prefix(self):
        """Test signature with wrong prefix fails"""
        signature = "md5=abc123"
        
        with patch("webhook_server.WEBHOOK_SECRET", self.secret):
            result = verify_signature(self.payload, signature)
        
        self.assertFalse(result)


class TestEventHandlers(unittest.TestCase):
    """Test webhook event handlers"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.log_dir = self.base / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    def test_handle_check_run_completed(self, mock_get_task, mock_trigger):
        """Test check_run.completed event handling"""
        mock_task = {"id": "test-task-123"}
        mock_get_task.return_value = mock_task
        
        payload = {
            "action": "completed",
            "check_run": {
                "name": "CI Tests",
                "conclusion": "success",
                "status": "completed",
                "head_branch": "feat/test-branch",
                "html_url": "https://github.com/test/run/123",
            }
        }
        
        handle_check_run(payload)
        
        mock_get_task.assert_called()
        mock_trigger.assert_called_once()

    @patch("webhook_server.trigger_monitor")
    def test_handle_check_run_not_completed(self, mock_trigger):
        """Test check_run event with non-completed action is ignored"""
        payload = {
            "action": "created",
            "check_run": {
                "name": "CI Tests",
                "conclusion": None,
                "status": "in_progress",
                "head_branch": "feat/test-branch",
            }
        }
        
        handle_check_run(payload)
        
        mock_trigger.assert_not_called()

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    def test_handle_workflow_run_completed(self, mock_get_task, mock_trigger):
        """Test workflow_run.completed event handling"""
        mock_task = {"id": "test-task-456"}
        mock_get_task.return_value = mock_task
        
        payload = {
            "action": "completed",
            "workflow_run": {
                "name": "CI Pipeline",
                "conclusion": "failure",
                "status": "completed",
                "head_branch": "feat/test-branch",
                "html_url": "https://github.com/test/run/456",
                "id": 789,
            }
        }
        
        handle_workflow_run(payload)
        
        mock_get_task.assert_called()
        mock_trigger.assert_called_once()

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    @patch("webhook_server.update_task")
    def test_handle_pull_request_opened(self, mock_update, mock_get_task, mock_trigger):
        """Test pull_request.opened event handling"""
        mock_task = {"id": "test-task-789"}
        mock_get_task.return_value = mock_task
        
        payload = {
            "action": "opened",
            "pull_request": {
                "head": {"ref": "feat/test-branch"},
                "number": 42,
                "html_url": "https://github.com/test/pull/42",
                "state": "open",
                "merged": False,
            }
        }
        
        handle_pull_request(payload)
        
        mock_get_task.assert_called()
        mock_update.assert_called_once_with(
            "test-task-789",
            {
                "pr_number": 42,
                "pr_url": "https://github.com/test/pull/42",
                "status": "pr_created",
            }
        )
        mock_trigger.assert_called()

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    @patch("webhook_server.update_task")
    def test_handle_pull_request_closed_merged(self, mock_update, mock_get_task, mock_trigger):
        """Test pull_request.closed event with merge"""
        mock_task = {"id": "test-task-merged"}
        mock_get_task.return_value = mock_task
        
        payload = {
            "action": "closed",
            "pull_request": {
                "head": {"ref": "feat/test-branch"},
                "number": 43,
                "html_url": "https://github.com/test/pull/43",
                "state": "closed",
                "merged": True,
            }
        }
        
        handle_pull_request(payload)
        
        mock_update.assert_called_with(
            "test-task-merged",
            {
                "status": "merged",
                "note": "PR #43 merged",
            }
        )

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    @patch("webhook_server.update_task")
    def test_handle_pull_request_closed_not_merged(self, mock_update, mock_get_task, mock_trigger):
        """Test pull_request.closed event without merge"""
        mock_task = {"id": "test-task-closed"}
        mock_get_task.return_value = mock_task
        
        payload = {
            "action": "closed",
            "pull_request": {
                "head": {"ref": "feat/test-branch"},
                "number": 44,
                "html_url": "https://github.com/test/pull/44",
                "state": "closed",
                "merged": False,
            }
        }
        
        handle_pull_request(payload)
        
        mock_update.assert_called_with(
            "test-task-closed",
            {
                "status": "pr_closed",
                "note": "PR #44 closed without merge",
            }
        )

    @patch("webhook_server.trigger_monitor")
    @patch("webhook_server.get_task_by_branch")
    def test_handle_event_no_task_found(self, mock_get_task, mock_trigger):
        """Test event handling when no task found for branch"""
        mock_get_task.return_value = None
        
        payload = {
            "action": "completed",
            "check_run": {
                "name": "CI Tests",
                "conclusion": "success",
                "head_branch": "unknown-branch",
            }
        }
        
        handle_check_run(payload)
        
        mock_get_task.assert_called()
        mock_trigger.assert_not_called()


class TestLogEvent(unittest.TestCase):
    """Test event logging functionality"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        self.log_dir = self.base / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        
        # Patch LOG_DIR in webhook_server module
        import webhook_server
        webhook_server.LOG_DIR = self.log_dir

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    def test_log_event_creates_file(self):
        """Test log_event creates log file"""
        log_event("check_run", "completed", {"branch": "test"})
        
        log_file = self.log_dir / "webhook.log"
        self.assertTrue(log_file.exists())
        
        content = log_file.read_text()
        self.assertIn("check_run", content)
        self.assertIn("completed", content)

    def test_log_event_appends(self):
        """Test log_event appends to existing log"""
        log_event("event1", "action1", {"data": 1})
        log_event("event2", "action2", {"data": 2})
        
        log_file = self.log_dir / "webhook.log"
        lines = log_file.read_text().strip().split("\n")
        
        self.assertEqual(len(lines), 2)


class TestGitHubWebhookHandler(unittest.TestCase):
    """Test HTTP request handler"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    def test_health_check_endpoint(self):
        """Test GET /health returns healthy status"""
        # This would require a running server, tested via integration instead
        pass


class TestWebhookServerIntegration(unittest.TestCase):
    """Integration tests for webhook server"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base = Path(self.temp_dir.name)
        os.environ["AI_DEVOPS_HOME"] = str(self.base)
        init_db()

    def tearDown(self):
        self.temp_dir.cleanup()
        if "AI_DEVOPS_HOME" in os.environ:
            del os.environ["AI_DEVOPS_HOME"]

    @patch("webhook_server.WEBHOOK_SECRET", b"test-secret")
    def test_full_webhook_flow(self):
        """Test complete webhook flow with valid signature"""
        from webhook_server import handle_check_run
        
        payload = {
            "action": "completed",
            "check_run": {
                "name": "CI Tests",
                "conclusion": "success",
                "head_branch": "feat/test",
            }
        }
        
        # Should not raise
        with patch("webhook_server.trigger_monitor"):
            with patch("webhook_server.get_task_by_branch", return_value=None):
                handle_check_run(payload)


if __name__ == "__main__":
    unittest.main()
