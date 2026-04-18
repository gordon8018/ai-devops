"""Token usage extraction and aggregation."""

from __future__ import annotations

from typing import Any

# Approximate cost per 1M tokens (USD)
_COST_PER_1M: dict[str, tuple[float, float]] = {
    # (input_cost, output_cost) per 1M tokens
    "gpt-5.4": (2.50, 10.00),
    "gpt-5.4-mini": (0.40, 1.60),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}


class TokenUsageCollector:
    @staticmethod
    def extract(result: Any, model: str, duration: float) -> dict[str, Any]:
        usage = getattr(result, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        costs = _COST_PER_1M.get(model, (0.0, 0.0))
        cost_estimate = (input_tokens * costs[0] + output_tokens * costs[1]) / 1_000_000
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": (getattr(usage, "total_tokens", 0) if usage else 0),
            "model": model,
            "duration_seconds": round(duration, 2),
            "cost_estimate": round(cost_estimate, 6),
        }

    @staticmethod
    def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "total_input_tokens": sum(r.get("input_tokens", 0) for r in runs),
            "total_output_tokens": sum(r.get("output_tokens", 0) for r in runs),
            "total_tokens": sum(r.get("total_tokens", 0) for r in runs),
            "total_duration_seconds": round(sum(r.get("duration_seconds", 0) for r in runs), 2),
            "run_count": len(runs),
            "models_used": list({r.get("model", "unknown") for r in runs}),
        }
