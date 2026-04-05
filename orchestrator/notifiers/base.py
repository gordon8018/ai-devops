"""Abstract base class for notification channels.

Provides a unified interface for all notifiers (Telegram, Discord, Email, etc.)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Represents an alert/notification to be sent."""
    level: AlertLevel
    title: str
    message: str
    task_id: Optional[str] = None
    plan_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def format_message(self) -> str:
        """Format the alert as a readable message."""
        parts = [f"[{self.level.value.upper()}] {self.title}"]
        if self.message:
            parts.append(self.message)
        if self.task_id:
            parts.append(f"Task: {self.task_id}")
        if self.plan_id:
            parts.append(f"Plan: {self.plan_id}")
        return "\n".join(parts)


class Notifier(ABC):
    """Abstract base class for notification channels.
    
    All notifiers must implement send() and optionally supports_level().
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this notifier (e.g., 'telegram', 'discord')."""
        pass
    
    @property
    def enabled(self) -> bool:
        """Check if this notifier is properly configured and enabled."""
        return True
    
    def supports_level(self, level: AlertLevel) -> bool:
        """Check if this notifier handles the given alert level.
        
        Default: handle all levels.
        Override to restrict (e.g., email only for critical).
        """
        return True
    
    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Send an alert through this channel.
        
        Args:
            alert: The alert to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        pass
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} enabled={self.enabled}>"


class NotificationError(Exception):
    """Base exception for notification failures."""
    pass


class NotificationResult:
    """Result of a notification attempt."""
    
    def __init__(self, notifier_name: str, success: bool, error: Optional[str] = None):
        self.notifier_name = notifier_name
        self.success = success
        self.error = error
    
    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"<NotificationResult {self.notifier_name} {status}>"
