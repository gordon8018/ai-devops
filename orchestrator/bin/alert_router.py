"""Alert routing and level-based notification dispatch.

Routes alerts to appropriate notifiers based on severity level.
"""
from __future__ import annotations
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from collections import deque

from orchestrator.notifiers import (
    Alert,
    AlertLevel,
    Notifier,
    NotificationResult,
    TelegramNotifier,
    DiscordNotifier,
    EmailNotifier,
)

logger = logging.getLogger(__name__)


# Default routing configuration
DEFAULT_ROUTES: Dict[AlertLevel, List[str]] = {
    AlertLevel.INFO: ["telegram"],
    AlertLevel.WARNING: ["telegram", "discord"],
    AlertLevel.CRITICAL: ["telegram", "discord", "email"],
}


@dataclass
class RouterConfig:
    """Configuration for alert routing."""
    routes: Dict[AlertLevel, List[str]] = field(default_factory=lambda: dict(DEFAULT_ROUTES))
    enabled_notifiers: Optional[Set[str]] = None  # None = all enabled
    
    def get_notifiers_for_level(self, level: AlertLevel) -> List[str]:
        """Get list of notifier names for an alert level."""
        all_notifiers = self.routes.get(level, [])
        if self.enabled_notifiers is None:
            return all_notifiers
        return [n for n in all_notifiers if n in self.enabled_notifiers]


class AlertRouter:
    """Routes alerts to appropriate notifiers based on severity.
    
    Example configuration:
        router = AlertRouter()
        router.add_notifier(TelegramNotifier())
        router.add_notifier(DiscordNotifier())
        router.add_notifier(EmailNotifier())
        
        # Send to all configured channels based on level
        router.route(Alert(
            level=AlertLevel.CRITICAL,
            title="System Down",
            message="Database unreachable"
        ))
    """
    
    def __init__(self, config: Optional[RouterConfig] = None, max_results: int = 1000):
        self._notifiers: Dict[str, Notifier] = {}
        self._config = config or RouterConfig()
        self._results: deque = deque(maxlen=max_results)
        self._max_results = max_results
    
    def add_notifier(self, notifier: Notifier) -> None:
        """Register a notifier."""
        self._notifiers[notifier.name] = notifier
        logger.debug("Registered notifier: %s (enabled=%s)", notifier.name, notifier.enabled)
    
    def remove_notifier(self, name: str) -> None:
        """Remove a notifier by name."""
        self._notifiers.pop(name, None)
    
    def get_notifier(self, name: str) -> Optional[Notifier]:
        """Get a notifier by name."""
        return self._notifiers.get(name)
    
    def list_notifiers(self) -> List[str]:
        """List registered notifier names."""
        return list(self._notifiers.keys())
    
    def route(self, alert: Alert) -> List[NotificationResult]:
        """Route an alert to appropriate notifiers.
        
        Args:
            alert: The alert to route
            
        Returns:
            List of notification results for each attempt
        """
        results = []
        target_names = self._config.get_notifiers_for_level(alert.level)
        
        if not target_names:
            logger.warning("No routes configured for level: %s", alert.level)
            return results
        
        logger.info("Routing alert '%s' (level=%s) to: %s",
                    alert.title, alert.level.value, ", ".join(target_names))
        
        for name in target_names:
            notifier = self._notifiers.get(name)
            if not notifier:
                logger.warning("Notifier not found: %s", name)
                continue
            
            if not notifier.enabled:
                logger.debug("Notifier disabled, skipping: %s", name)
                continue
            
            if not notifier.supports_level(alert.level):
                logger.debug("Notifier %s doesn't support level %s", name, alert.level)
                continue
            
            try:
                success = notifier.send(alert)
                result = NotificationResult(name, success)
            except Exception as exc:
                logger.error("Notifier %s raised exception: %s", name, exc)
                result = NotificationResult(name, False, str(exc))
            
            results.append(result)
        
        self._results.extend(results)
        return results
    
    # Convenience methods for different alert levels
    
    def info(self, title: str, message: str = "", **kwargs) -> List[NotificationResult]:
        """Send an info-level alert."""
        return self.route(Alert(level=AlertLevel.INFO, title=title, message=message, **kwargs))
    
    def warning(self, title: str, message: str = "", **kwargs) -> List[NotificationResult]:
        """Send a warning-level alert."""
        return self.route(Alert(level=AlertLevel.WARNING, title=title, message=message, **kwargs))
    
    def critical(self, title: str, message: str = "", **kwargs) -> List[NotificationResult]:
        """Send a critical-level alert."""
        return self.route(Alert(level=AlertLevel.CRITICAL, title=title, message=message, **kwargs))
    
    def get_results(self) -> List[NotificationResult]:
        """Get all notification results."""
        return list(self._results)
    
    def clear_results(self) -> None:
        """Clear stored results."""
        self._results.clear()


def create_default_router() -> AlertRouter:
    """Create an AlertRouter with all built-in notifiers registered.
    
    Notifiers are enabled based on environment variable configuration.
    """
    router = AlertRouter()
    router.add_notifier(TelegramNotifier())
    router.add_notifier(DiscordNotifier())
    router.add_notifier(EmailNotifier())
    return router


# Singleton instance and lock for thread-safe initialization
_router_instance: Optional[AlertRouter] = None
_router_lock = threading.Lock()


def get_router() -> AlertRouter:
    """Get or create the singleton AlertRouter instance.
    
    Thread-safe implementation using double-checked locking pattern.
    """
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            # Double-check after acquiring lock
            if _router_instance is None:
                _router_instance = create_default_router()
    return _router_instance


def set_router(router: AlertRouter) -> None:
    """Set the global AlertRouter instance.
    
    Thread-safe implementation.
    """
    global _router_instance
    with _router_lock:
        _router_instance = router


# Convenience functions using the global router

def alert_info(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send info-level alert using global router."""
    return get_router().info(title, message, **kwargs)


def alert_warning(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send warning-level alert using global router."""
    return get_router().warning(title, message, **kwargs)


def alert_critical(title: str, message: str = "", **kwargs) -> List[NotificationResult]:
    """Send critical-level alert using global router."""
    return get_router().critical(title, message, **kwargs)
