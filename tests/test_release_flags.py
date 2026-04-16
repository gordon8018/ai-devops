from __future__ import annotations

from packages.release.flags.statsig import StatsigFlagAdapter


def test_statsig_flag_adapter_records_applied_stages() -> None:
    adapter = StatsigFlagAdapter()

    adapter.apply_stage("rel_wi_001", "team-only")
    adapter.apply_stage("rel_wi_001", "beta")

    assert adapter.applied_stages("rel_wi_001") == ("team-only", "beta")
