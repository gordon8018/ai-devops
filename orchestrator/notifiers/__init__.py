"""Notification framework for the Zoe orchestrator.

Provides a unified interface for sending notifications through multiple channels:
- Telegram
- Discord
- Email

Usage:
    from orchestrator.notifiers import Alert, AlertLevel, TelegramNotifier
    
    notifier = TelegramNotifier()
    alert = Alert(
        level=AlertLevel.WARNING,
        title="Task Failed",
        message="Task X encountered an error"
    )
    notifier.send(alert)
"""
from .base import (
    Alert,
    AlertLevel,
    Notifier,
    NotificationError,
    NotificationResult,
)
from .telegram import TelegramNotifier
from .discord import DiscordNotifier
from .email import EmailNotifier

__all__ = [
    # Base classes
    "Alert",
    "AlertLevel",
    "Notifier",
    "NotificationError",
    "NotificationResult",
    # Implementations
    "TelegramNotifier",
    "DiscordNotifier",
    "EmailNotifier",
]
