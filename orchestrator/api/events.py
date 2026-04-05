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
import time
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for JSON serialization"""
        return {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }
    
    def to_json(self) -> str:
        """Convert event to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


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
            data={
                "task_id": task_id,
                "status": status,
                "details": details or {},
            },
            source=source,
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
            events = self._event_history.copy()
        
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        
        # Return most recent events
        events = events[-limit:]
        return [e.to_dict() for e in events]
    
    def clear_history(self):
        """Clear event history"""
        with self._lock:
            self._event_history.clear()


# Global event manager instance
_event_manager: Optional[EventManager] = None


def get_event_manager() -> EventManager:
    """Get the global event manager instance"""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager
