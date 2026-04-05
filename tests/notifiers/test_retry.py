"""Tests for notification retry mechanisms."""

import pytest
from unittest.mock import patch, MagicMock
from tenacity import RetryError

from orchestrator.notifiers.telegram import TelegramNotifier
from orchestrator.notifiers.discord import DiscordNotifier
from orchestrator.notifiers.email import EmailNotifier
from orchestrator.notifiers.base import Alert, AlertLevel


class TestTelegramRetry:
    """Test Telegram notifier retry mechanism."""
    
    def test_success_without_retry(self):
        """Test successful send without retry."""
        notifier = TelegramNotifier(token="test_token", chat_id="12345")
        alert = Alert(level=AlertLevel.INFO, title="Test", message="Test message")
        
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_post.call_count == 1
    
    def test_retry_on_failure(self):
        """Test that retry happens on failure."""
        notifier = TelegramNotifier(token="test_token", chat_id="12345")
        alert = Alert(level=AlertLevel.INFO, title="Test", message="Test message")
        
        with patch('requests.post') as mock_post:
            mock_response_fail = MagicMock()
            mock_response_fail.raise_for_status.side_effect = Exception("Network error")
            mock_response_success = MagicMock()
            mock_response_success.raise_for_status = MagicMock()
            
            mock_post.side_effect = [mock_response_fail, mock_response_fail, mock_response_success]
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_post.call_count == 3
    
    def test_retry_exhausted(self):
        """Test that all retries are exhausted on continuous failure."""
        notifier = TelegramNotifier(token="test_token", chat_id="12345")
        alert = Alert(level=AlertLevel.INFO, title="Test", message="Test message")
        
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("Network error")
            mock_post.return_value = mock_response
            
            # All retries fail - should return False after 3 attempts
            result = notifier.send(alert)
            
            assert result is False
            assert mock_post.call_count == 3


class TestDiscordRetry:
    """Test Discord notifier retry mechanism."""
    
    def test_success_without_retry(self):
        """Test successful send without retry."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/webhook/test")
        alert = Alert(level=AlertLevel.WARNING, title="Test", message="Test message")
        
        with patch('requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_post.call_count == 1
    
    def test_retry_on_failure(self):
        """Test that retry happens on failure."""
        notifier = DiscordNotifier(webhook_url="https://discord.com/webhook/test")
        alert = Alert(level=AlertLevel.CRITICAL, title="Test", message="Test message")
        
        with patch('requests.post') as mock_post:
            mock_response_fail = MagicMock()
            mock_response_fail.raise_for_status.side_effect = Exception("Network error")
            mock_response_success = MagicMock()
            mock_response_success.raise_for_status = MagicMock()
            
            mock_post.side_effect = [mock_response_fail, mock_response_success]
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_post.call_count == 2


class TestEmailRetry:
    """Test Email notifier retry mechanism."""
    
    def test_success_without_retry(self):
        """Test successful send without retry."""
        notifier = EmailNotifier(
            host="smtp.example.com",
            port=587,
            user="test@example.com",
            password="testpass",
            from_addr="test@example.com",
            to_addrs=["user@example.com"]
        )
        alert = Alert(level=AlertLevel.WARNING, title="Test", message="Test message")
        
        with patch('smtplib.SMTP') as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_smtp.call_count == 1
    
    def test_retry_on_failure(self):
        """Test that retry happens on failure."""
        notifier = EmailNotifier(
            host="smtp.example.com",
            port=587,
            user="test@example.com",
            password="testpass",
            from_addr="test@example.com",
            to_addrs=["user@example.com"]
        )
        alert = Alert(level=AlertLevel.CRITICAL, title="Test", message="Test message")
        
        with patch('smtplib.SMTP') as mock_smtp:
            mock_server_fail = MagicMock()
            mock_server_fail.starttls.side_effect = Exception("Connection error")
            mock_server_success = MagicMock()
            mock_server_success.starttls = MagicMock()
            
            mock_smtp.return_value.__enter__.side_effect = [mock_server_fail, mock_server_success]
            mock_smtp.return_value.__exit__ = MagicMock(return_value=False)
            
            result = notifier.send(alert)
            
            assert result is True
            assert mock_smtp.call_count == 2
