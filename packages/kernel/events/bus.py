from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Any, Callable


@dataclass(slots=True, frozen=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))


class InMemoryEventBus:
    """Small event bus for bootstrap migrations before Redis Streams."""

    def __init__(self, *, max_history: int = 200) -> None:
        self._subscribers: list[Callable[[EventEnvelope], None]] = []
        self._history: deque[EventEnvelope] = deque(maxlen=max_history)

    def subscribe(self, callback: Callable[[EventEnvelope], None]) -> Callable[[], None]:
        self._subscribers.append(callback)

        def _unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return _unsubscribe

    def publish(self, event_type: str, payload: dict[str, Any]) -> EventEnvelope:
        envelope = EventEnvelope(event_type=event_type, payload=dict(payload))
        self._history.append(envelope)
        for callback in list(self._subscribers):
            callback(envelope)
        return envelope

    def history(self) -> list[EventEnvelope]:
        return list(self._history)
