"""
Events Management - Event-driven pub/sub system for real-time updates

Provides:
- EventManager: Central event bus
- Event types: task_status, plan_status, alert
- Pub/sub pattern for loose coupling
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from collections import deque
from collections import defaultdict
import threading


class EventType(Enum):
    """Event types supported by the system"""
    TASK_STATUS = "task_status"
    PLAN_STATUS = "plan_status"
    ALERT = "alert"
    SYSTEM = "system"


@dataclass
class Event:
    """Event data structure"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=lambda: time.time())
    source: Optional[str] = None
    event_name: Optional[str] = None
    actor_id: str = "system:legacy"
    actor_type: str = "system"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for JSON serialization"""
        return {
            "type": self.event_type.value,
            "eventName": self.event_name,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "actorId": self.actor_id,
            "actorType": self.actor_type,
        }
    
    def to_json(self) -> str:
        """Convert event to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _resolve_event_journal_path() -> Path:
    base = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
    return base / ".clawdbot" / "event_history.jsonl"


class EventManager:
    """
    Central event management system with pub/sub pattern
    
    Features:
    - Subscribe to specific event types
    - Publish events to all subscribers
    - Thread-safe operations
    - Async and sync subscriber support
    """
    
    _instance: Optional['EventManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> 'EventManager':
        """Singleton pattern for global event manager"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, max_history: int = 100):
        """Initialize event manager"""
        if self._initialized:
            return
        
        self._initialized = True
        self._subscribers: Dict[EventType, Set[Callable]] = defaultdict(set)
        self._global_subscribers: Set[Callable] = set()
        self._max_history = max_history
        self._event_history: deque = deque(maxlen=max_history)
        self._lock = threading.RLock()
    
    def subscribe(
        self,
        callback: Callable[[Event], None],
        event_types: Optional[List[EventType]] = None
    ) -> Callable[[], None]:
        """
        Subscribe to events
        
        Args:
            callback: Function to call when event is published
            event_types: List of event types to subscribe to (None = all events)
        
        Returns:
            Unsubscribe function
        """
        with self._lock:
            if event_types is None:
                # Subscribe to all events
                self._global_subscribers.add(callback)
            else:
                # Subscribe to specific event types
                for event_type in event_types:
                    self._subscribers[event_type].add(callback)
        
        # Return unsubscribe function
        def unsubscribe():
            with self._lock:
                if event_types is None:
                    self._global_subscribers.discard(callback)
                else:
                    for event_type in event_types:
                        self._subscribers[event_type].discard(callback)
        
        return unsubscribe
    
    def unsubscribe_all(self, callback: Callable[[Event], None]):
        """Remove callback from all subscriptions"""
        with self._lock:
            self._global_subscribers.discard(callback)
            for event_type in self._subscribers:
                self._subscribers[event_type].discard(callback)
    
    def publish(self, event: Event):
        """
        Publish an event to all relevant subscribers
        
        Args:
            event: Event to publish
        """
        # Store in history
        with self._lock:
            self._event_history.append(event)
            self._append_to_journal(event)
            type_subscribers = self._subscribers.get(event.event_type, set()).copy()
            global_subscribers = self._global_subscribers.copy()
        
        # Notify subscribers (outside lock to prevent deadlocks)
        all_callbacks = type_subscribers | global_subscribers
        for callback in all_callbacks:
            try:
                # Support both sync and async callbacks
                result = callback(event)
                if asyncio.iscoroutine(result):
                    # Schedule async callback
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(result)
                    except RuntimeError:
                        # No event loop, skip async callback
                        pass
            except Exception as e:
                print(f"[EventManager] Error in subscriber callback: {e}")

    def _append_to_journal(self, event: Event) -> None:
        journal_path = _resolve_event_journal_path()
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        with journal_path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")

    def _read_journal_history(self) -> List[Dict[str, Any]]:
        journal_path = _resolve_event_journal_path()
        if not journal_path.exists():
            return []

        events: List[Dict[str, Any]] = []
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                events.append(parsed)
        return events
    
    def publish_task_status(
        self,
        task_id: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ):
        """Helper to publish task status events"""
        event = Event(
            event_type=EventType.TASK_STATUS,
            event_name="task.status_changed",
            data={
                "task_id": task_id,
                "status": status,
                "details": details or {},
            },
            source=source,
            actor_id="system:legacy",
            actor_type="system",
        )
        self.publish(event)
    
    def publish_plan_status(
        self,
        plan_id: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ):
        """Helper to publish plan status events"""
        event = Event(
            event_type=EventType.PLAN_STATUS,
            data={
                "plan_id": plan_id,
                "status": status,
                "details": details or {},
            },
            source=source,
        )
        self.publish(event)
    
    def publish_alert(
        self,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None
    ):
        """Helper to publish alert events"""
        event = Event(
            event_type=EventType.ALERT,
            data={
                "level": level,  # info, warning, error, critical
                "message": message,
                "details": details or {},
            },
            source=source,
        )
        self.publish(event)
    
    def get_history(
        self,
        event_types: Optional[List[EventType]] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent event history"""
        with self._lock:
            in_memory_events = [event.to_dict() for event in self._event_history]

        events = self._read_journal_history() or in_memory_events
        
        if event_types:
            allowed_types = {event_type.value for event_type in event_types}
            events = [event for event in events if event.get("type") in allowed_types]
        
        # Return most recent events
        events = events[-limit:]
        return events
    
    def clear_history(self):
        """Clear event history"""
        with self._lock:
            self._event_history.clear()
        journal_path = _resolve_event_journal_path()
        if journal_path.exists():
            journal_path.unlink()


# Global event manager instance
_event_manager: Optional[EventManager] = None


def get_event_manager() -> EventManager:
    """Get the global event manager instance"""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager
