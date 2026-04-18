"""Token usage extraction and aggregation."""

from __future__ import annotations

from typing import Any


class TokenUsageCollector:
    @staticmethod
    def extract(result: Any, model: str, duration: float) -> dict[str, Any]:
        usage = getattr(result, "usage", None)
        return {
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
            "model": model,
            "duration_seconds": round(duration, 2),
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
