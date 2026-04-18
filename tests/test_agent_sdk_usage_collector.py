from dataclasses import dataclass


def test_collector_extracts_usage():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    @dataclass
    class FakeUsage:
        input_tokens: int = 1000
        output_tokens: int = 500
        total_tokens: int = 1500

    @dataclass
    class FakeResult:
        usage: FakeUsage = None

    usage = TokenUsageCollector.extract(FakeResult(usage=FakeUsage()), model="gpt-5.4", duration=12.5)
    assert usage["input_tokens"] == 1000
    assert usage["model"] == "gpt-5.4"


def test_collector_handles_missing_usage():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector

    @dataclass
    class FakeResult:
        usage: None = None

    usage = TokenUsageCollector.extract(FakeResult(), model="gpt-5.4", duration=5.0)
    assert usage["input_tokens"] == 0


def test_collector_aggregates():
    from packages.agent_sdk.tracing.usage_collector import TokenUsageCollector
    runs = [
        {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150, "model": "gpt-5.4", "duration_seconds": 5.0},
        {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300, "model": "claude-opus-4-6", "duration_seconds": 8.0},
    ]
    agg = TokenUsageCollector.aggregate(runs)
    assert agg["total_tokens"] == 450
    assert agg["run_count"] == 2
