"""Telegram notification module for the Zoe orchestrator.

Provides notify(), notify_ready(), and notify_failure() helpers.
All functions are silent on missing credentials or network errors.
"""
from __future__ import annotations
import logging
import os

logger = logging.getLogger(__name__)


def notify(msg: str) -> None:
    """Send message to configured Telegram chat. Silent on failure."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing)")
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
    except Exception as exc:
        logger.warning("Telegram notification failed: %s", exc)


def notify_ready(task_id: str, pr_url: str) -> None:
    """Human-review-ready notification with PR link."""
    notify(f"Task {task_id} ready for review: {pr_url}")


def notify_failure(task_id: str, detail: str) -> None:
    """CI failure / agent death notification."""
    notify(f"Task {task_id} failed: {detail}")
