"""Discord notifier implementation.

Sends notifications via Discord Webhook.
"""
from __future__ import annotations
import logging
import os
from typing import Optional, Dict, Any

from tenacity import retry, stop_after_attempt, wait_exponential
from .base import Notifier, Alert, AlertLevel

logger = logging.getLogger(__name__)


# Discord embed colors for different alert levels
LEVEL_COLORS = {
    AlertLevel.INFO: 0x3498db,      # Blue
    AlertLevel.WARNING: 0xf39c12,   # Orange
    AlertLevel.CRITICAL: 0xe74c3c,  # Red
}


class DiscordNotifier(Notifier):
    """Send notifications via Discord Webhook.
    
    Configuration via environment variables:
    - DISCORD_WEBHOOK_URL: Discord webhook URL
    """
    
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        timeout: int = 10,
        username: Optional[str] = None,
        avatar_url: Optional[str] = None
    ):
        self._webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
        self._timeout = timeout
        self._username = username or os.getenv("DISCORD_USERNAME", "Zoe Bot")
        self._avatar_url = avatar_url or os.getenv("DISCORD_AVATAR_URL")
    
    @property
    def name(self) -> str:
        return "discord"
    
    @property
    def enabled(self) -> bool:
        return bool(self._webhook_url)
    
    def _build_embed(self, alert: Alert) -> Dict[str, Any]:
        """Build Discord embed for the alert."""
        embed = {
            "title": alert.title,
            "description": alert.message,
            "color": LEVEL_COLORS.get(alert.level, 0x95a5a6),
            "fields": [],
        }
        
        if alert.task_id:
            embed["fields"].append({
                "name": "Task ID",
                "value": alert.task_id,
                "inline": True
            })
        
        if alert.plan_id:
            embed["fields"].append({
                "name": "Plan ID",
                "value": alert.plan_id,
                "inline": True
            })
        
        if alert.metadata:
            for key, value in list(alert.metadata.items())[:3]:  # Max 3 additional fields
                embed["fields"].append({
                    "name": key,
                    "value": str(value),
                    "inline": True
                })
        
        return embed
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, exp_base=2, min=4, max=16),
        reraise=True
    )
    def _send_request(self, alert: Alert) -> bool:
        """Internal send method with retry decorator."""
        import requests
        
        payload = {
            "username": self._username,
            "embeds": [self._build_embed(alert)]
        }
        
        if self._avatar_url:
            payload["avatar_url"] = self._avatar_url
        
        response = requests.post(
            self._webhook_url,
            json=payload,
            timeout=self._timeout
        )
        response.raise_for_status()
        logger.info("Discord notification sent: %s", alert.title)
        return True
    
    def send(self, alert: Alert) -> bool:
        """Send alert to Discord via webhook with retry mechanism."""
        if not self.enabled:
            logger.warning("Discord not configured (missing webhook URL)")
            return False
        
        try:
            return self._send_request(alert)
        except ImportError:
            logger.error("requests library not installed")
            return False
        except Exception as exc:
            logger.warning("Discord notification failed after retries: %s", exc)
            return False
