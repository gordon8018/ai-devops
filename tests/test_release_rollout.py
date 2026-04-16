from __future__ import annotations

from packages.release.rollout.service import RolloutController


def test_rollout_controller_advances_through_expected_stages() -> None:
    controller = RolloutController()

    assert controller.next_stage("team-only") == "beta"
    assert controller.next_stage("beta") == "1%"
    assert controller.next_stage("1%") == "5%"
    assert controller.next_stage("5%") == "20%"
    assert controller.next_stage("20%") == "full"
