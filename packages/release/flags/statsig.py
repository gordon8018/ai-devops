from __future__ import annotations


class StatsigFlagAdapter:
    """Minimal in-process flag adapter used during release worker bootstrap."""

    def __init__(self) -> None:
        self._applied: dict[str, list[str]] = {}

    def apply_stage(self, release_id: str, stage: str) -> None:
        self._applied.setdefault(release_id, []).append(stage)

    def applied_stages(self, release_id: str) -> tuple[str, ...]:
        return tuple(self._applied.get(release_id, ()))
