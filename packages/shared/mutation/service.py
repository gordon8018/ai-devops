from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class MutationService:
    def apply(
        self,
        *,
        persist: Callable[[], None],
        audit: Callable[[], None],
        publish_events: list[Callable[[], None]] | tuple[Callable[[], None], ...] = (),
        rollback: Callable[[], None] | None = None,
    ) -> None:
        persist()
        try:
            audit()
        except Exception:
            if rollback is not None:
                rollback()
            raise

        for publish in publish_events:
            publish()
