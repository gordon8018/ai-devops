"""Telegram notifier implementation.

Sends notifications via Telegram Bot API.
"""
from __future__ import annotations
import logging
import os
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential
from .base import Notifier, Alert, NotificationError

logger = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Send notifications via Telegram Bot API.
    
    Configuration via environment variables:
    - TELEGRAM_BOT_TOKEN: Bot API token
    - TELEGRAM_CHAT_ID: Target chat/channel ID
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: int = 10
    ):
        self._token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self._chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self._timeout = timeout
    
    @property
    def name(self) -> str:
        return "telegram"
    
    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat_id)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, exp_base=2, min=4, max=16),
        reraise=True
    )
    def _send_request(self, alert: Alert) -> bool:
        """Internal send method with retry decorator."""
        import requests
        
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        text = alert.format_message()
        
        response = requests.post(
            url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML"
            },
            timeout=self._timeout
        )
        response.raise_for_status()
        logger.info("Telegram notification sent: %s", alert.title)
        return True
    
    def send(self, alert: Alert) -> bool:
        """Send alert to Telegram with retry mechanism."""
        if not self.enabled:
            logger.warning("Telegram not configured (missing token/chat_id)")
            return False
        
        try:
            return self._send_request(alert)
        except ImportError:
            logger.error("requests library not installed")
            return False
        except Exception as exc:
            logger.warning("Telegram notification failed after retries: %s", exc)
            return False
