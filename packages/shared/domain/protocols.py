from __future__ import annotations

from typing import Any, Protocol

from .models import ContextPack, WorkItem


class ContextPackProvider(Protocol):
    def build(
        self,
        work_item: WorkItem,
        *,
        legacy_task_input: dict[str, Any] | None = None,
    ) -> ContextPack: ...
