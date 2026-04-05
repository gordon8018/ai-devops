#!/usr/bin/env python3
"""Tests for P0 security fixes: SMTP password encryption + resource leak fixes."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestEmailPasswordEncryption:
    """Test SMTP password encryption support."""
    
    def test_get_password_from_plain_env(self):
        """Plain text password from SMTP_PASSWORD should still work."""
        with patch.dict(os.environ, {"SMTP_PASSWORD": "plain_password"}, clear=False):
            from orchestrator.notifiers.email import _get_password
            pwd = _get_password()
            assert pwd == "plain_password"
    
    def test_get_password_from_encrypted_env(self):
        """Encrypted password from SMTP_PASSWORD_ENC should be decrypted."""
        # Generate a test key and encrypt a password
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        f = Fernet(key)
        encrypted = f.encrypt(b"secret_password").decode()
        
        with patch.dict(os.environ, {
            "SMTP_ENCRYPTION_KEY": key.decode(),
            "SMTP_PASSWORD_ENC": encrypted
        }, clear=False):
            from orchestrator.notifiers.email import _get_password
            pwd = _get_password()
            assert pwd == "secret_password"
    
    def test_get_password_from_file(self):
        """Password from SMTP_PASSWORD_FILE should be read."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write("file_password")
            pwd_file = f.name
        
        try:
            with patch.dict(os.environ, {"SMTP_PASSWORD_FILE": pwd_file}, clear=False):
                from orchestrator.notifiers.email import _get_password
                pwd = _get_password()
                assert pwd == "file_password"
        finally:
            os.unlink(pwd_file)
    
    def test_email_notifier_uses_secure_password_loader(self):
        """EmailNotifier should use _get_password when no password provided."""
        with patch.dict(os.environ, {"SMTP_PASSWORD": "test_pwd"}, clear=False):
            from orchestrator.notifiers.email import EmailNotifier
            notifier = EmailNotifier(
                host="smtp.test.com",
                user="test@test.com",
                from_addr="test@test.com",
                to_addrs=["recipient@test.com"]
            )
            assert notifier._password == "test_pwd"


class TestAlertRouterResourceLeak:
    """Test AlertRouter _results deque with max length."""
    
    def test_results_has_max_length(self):
        """_results should be a deque with maxlen."""
        from orchestrator.bin.alert_router import AlertRouter
        from collections import deque
        
        router = AlertRouter(max_results=10)
        assert isinstance(router._results, deque)
        assert router._results.maxlen == 10
    
    def test_results_automatic_trimming(self):
        """_results should automatically trim when exceeding maxlen."""
        from orchestrator.bin.alert_router import AlertRouter, NotificationResult
        
        router = AlertRouter(max_results=5)
        
        # Add 10 results
        for i in range(10):
            router._results.append(NotificationResult(f"notifier_{i}", True))
        
        # Should only keep last 5
        assert len(router._results) == 5
        assert router._results[0].notifier_name == "notifier_5"
        assert router._results[-1].notifier_name == "notifier_9"
    
    def test_default_max_results_is_1000(self):
        """Default max_results should be 1000."""
        from orchestrator.bin.alert_router import AlertRouter
        
        router = AlertRouter()
        assert router._max_results == 1000
        assert router._results.maxlen == 1000


class TestEventManagerResourceLeak:
    """Test EventManager _event_history deque with max length."""
    
    def test_event_history_is_deque(self):
        """_event_history should be a deque."""
        from orchestrator.api.events import EventManager
        from collections import deque
        
        # Reset singleton to test initialization
        original_instance = EventManager._instance
        EventManager._instance = None
        
        try:
            manager = EventManager()
            assert isinstance(manager._event_history, deque)
            assert manager._event_history.maxlen == 100  # default
        finally:
            EventManager._instance = original_instance
    
    def test_event_history_automatic_trimming(self):
        """_event_history should automatically trim when exceeding maxlen."""
        from orchestrator.api.events import EventManager, Event, EventType
        
        # Reset singleton
        original_instance = EventManager._instance
        from collections import deque
        EventManager._instance = None
        
        try:
            manager = EventManager()
            # Manually set maxlen for testing (since singleton doesn't accept init args)
            manager._event_history = deque(maxlen=5)
            
            # Publish 10 events
            for i in range(10):
                event = Event(
                    event_type=EventType.SYSTEM,
                    data={"index": i}
                )
                manager.publish(event)
            
            # Should only keep last 5
            assert len(manager._event_history) == 5
            assert manager._event_history[0].data["index"] == 5
            assert manager._event_history[-1].data["index"] == 9
        finally:
            EventManager._instance = original_instance
    
    def test_default_max_history_is_100(self):
        """Default max_history should be 100."""
        from orchestrator.api.events import EventManager
        
        # Reset singleton
        original_instance = EventManager._instance
        EventManager._instance = None
        
        try:
            manager = EventManager()
            assert manager._max_history == 100
            assert manager._event_history.maxlen == 100
        finally:
            EventManager._instance = original_instance


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
