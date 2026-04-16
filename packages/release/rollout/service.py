from __future__ import annotations


class RolloutController:
    """Advance a release through explicit rollout stages."""

    STAGES = ("team-only", "beta", "1%", "5%", "20%", "full")

    def next_stage(self, current_stage: str | None) -> str:
        normalized = str(current_stage or "").strip().lower()
        if normalized not in self.STAGES:
            return self.STAGES[0]
        index = self.STAGES.index(normalized)
        if index >= len(self.STAGES) - 1:
            return self.STAGES[-1]
        return self.STAGES[index + 1]
