"""Notification module for the Zoe orchestrator.

Provides backward-compatible notify(), notify_ready(), and notify_failure() helpers,
plus new alert routing capabilities.

Legacy usage (backward compatible):
    from orchestrator.bin.notify import notify, notify_ready, notify_failure
    notify("Hello from Zoe")
    notify_ready("task-123", "https://github.com/...")

New usage (with alert levels):
    from orchestrator.bin.notify import alert_info, alert_warning, alert_critical
    alert_warning("Task timeout", "Task X has been running for 3 hours")
"""
from __future__ import annotations
import logging
import os
from typing import Optional, List
import requests

# Import new notification framework
from orchestrator.notifiers import (
    Alert,
    AlertLevel,
    Notifier,
    NotificationResult,
    TelegramNotifier,
    DiscordNotifier,
    EmailNotifier,
)
from orchestrator.bin.alert_router import (
    AlertRouter,
    RouterConfig,
    create_default_router,
    get_router,
)

logger = logging.getLogger(__name__)


# Legacy functions (backward compatible)

def notify(msg: str) -> None:
    """Send message to configured Telegram chat. Silent on failure.
    
    This is a legacy function that sends via Telegram only.
    For new code, consider using alert_info() instead.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing)")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10,
        )
    except requests.RequestException:
        return


def notify_ready(task_id: str, pr_url: str) -> None:
    """Human-review-ready notification with PR link.
    
    This sends a notification that a task is ready for human review.
    """
    notify(f"Task ready: {task_id}\nPR: {pr_url}")


def notify_failure(task_id: str, detail: str) -> None:
    """CI failure / agent death notification.
    
    This sends a warning-level alert about a task failure.
    """
    notify(f"Task failed: {task_id}\nDetail: {detail}")


# New API - Alert-based notifications

def send_alert(alert: Alert) -> List[NotificationResult]:
    """Send an alert through the configured router.
    
    Args:
        alert: The alert to send
        
    Returns:
        List of notification results from each channel
    """
    router = get_router()
    return router.route(alert)


def alert_info(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send an info-level alert.
    
    Args:
        title: Alert title
        message: Alert message body
        **kwargs: Additional Alert fields (task_id, plan_id, metadata)
        
    Returns:
        List of notification results
    """
    return get_router().info(title, message, **kwargs)


def alert_warning(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send a warning-level alert.
    
    Args:
        title: Alert title
        message: Alert message body
        **kwargs: Additional Alert fields (task_id, plan_id, metadata)
        
    Returns:
        List of notification results
    """
    return get_router().warning(title, message, **kwargs)


def alert_critical(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send a critical-level alert.
    
    Args:
        title: Alert title
        message: Alert message body
        **kwargs: Additional Alert fields (task_id, plan_id, metadata)
        
    Returns:
        List of notification results
    """
    return get_router().critical(title, message, **kwargs)


# Configuration helpers

def configure_router(
    telegram_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    discord_webhook: Optional[str] = None,
    smtp_host: Optional[str] = None,
    smtp_user: Optional[str] = None,
    smtp_password: Optional[str] = None,
    email_from: Optional[str] = None,
    email_to: Optional[str] = None,
) -> AlertRouter:
    """Configure and return a custom router with specific notifier settings.
    
    This allows programmatic configuration instead of relying solely on
    environment variables.
    """
    router = AlertRouter()
    
    # Add Telegram if configured
    if telegram_token and telegram_chat_id:
        router.add_notifier(TelegramNotifier(
            token=telegram_token,
            chat_id=telegram_chat_id
        ))
    else:
        router.add_notifier(TelegramNotifier())  # Uses env vars
    
    # Add Discord if configured
    if discord_webhook:
        router.add_notifier(DiscordNotifier(webhook_url=discord_webhook))
    else:
        router.add_notifier(DiscordNotifier())  # Uses env vars
    
    # Add Email if fully configured
    if all([smtp_host, smtp_user, smtp_password, email_from, email_to]):
        router.add_notifier(EmailNotifier(
            host=smtp_host,
            user=smtp_user,
            password=smtp_password,
            from_addr=email_from,
            to_addrs=[email_to]
        ))
    else:
        router.add_notifier(EmailNotifier())  # Uses env vars
    
    return router


# Expose key classes for convenience
__all__ = [
    # Legacy API (backward compatible)
    "notify",
    "notify_ready",
    "notify_failure",
    # New alert API
    "send_alert",
    "alert_info",
    "alert_warning",
    "alert_critical",
    # Configuration
    "configure_router",
    # Re-exported from notifiers
    "Alert",
    "AlertLevel",
    "Notifier",
    "NotificationResult",
    "AlertRouter",
    "TelegramNotifier",
    "DiscordNotifier",
    "EmailNotifier",
]
