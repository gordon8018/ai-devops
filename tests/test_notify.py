"""Tests for orchestrator/bin/notify.py — Telegram notification module."""
import os
from unittest.mock import patch, MagicMock
import pytest

from orchestrator.bin.notify import notify, notify_ready, notify_failure


def test_notify_sends_telegram_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        notify("hello world")
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "test-token" in call_args[0][0]  # URL contains token
        assert call_args[1]["json"]["text"] == "hello world"
        assert call_args[1]["json"]["chat_id"] == "12345"


def test_notify_silent_when_no_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    # Should not raise
    notify("hello")


def test_notify_silent_on_http_error(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    import requests
    with patch("requests.post", side_effect=requests.RequestException("timeout")):
        # Should not raise
        notify("hello")


def test_notify_ready_sends_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    with patch("orchestrator.bin.notify.notify") as mock_notify:
        notify_ready("task-123", "https://github.com/org/repo/pull/42")
        mock_notify.assert_called_once()
        msg = mock_notify.call_args[0][0]
        assert "task-123" in msg
        assert "https://github.com/org/repo/pull/42" in msg


def test_notify_failure_sends_message(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    with patch("orchestrator.bin.notify.notify") as mock_notify:
        notify_failure("task-456", "CI timeout after 30 minutes")
        mock_notify.assert_called_once()
        msg = mock_notify.call_args[0][0]
        assert "task-456" in msg
        assert "CI timeout after 30 minutes" in msg
