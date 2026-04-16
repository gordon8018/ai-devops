from __future__ import annotations


class RolloutController:
    """Advance a release through explicit rollout stages."""

    STAGES = ("team-only", "beta", "1%", "5%", "20%", "full")

    def next_stage(self, current_stage: str) -> str:
        try:
            index = self.STAGES.index(current_stage)
        except ValueError:
            return self.STAGES[0]
        if index >= len(self.STAGES) - 1:
            return self.STAGES[-1]
        return self.STAGES[index + 1]
