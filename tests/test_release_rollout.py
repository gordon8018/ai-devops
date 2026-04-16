from __future__ import annotations

from packages.release.rollout.service import RolloutController


def test_rollout_controller_advances_through_expected_stages() -> None:
    controller = RolloutController()

    assert controller.next_stage("team-only") == "beta"
    assert controller.next_stage("beta") == "1%"
    assert controller.next_stage("1%") == "5%"
    assert controller.next_stage("5%") == "20%"
    assert controller.next_stage("20%") == "full"


def test_next_stage_advances_in_order_until_full() -> None:
    controller = RolloutController()

    assert controller.next_stage("unknown") == "team-only"
    assert controller.next_stage("team-only") == "beta"
    assert controller.next_stage("beta") == "1%"
    assert controller.next_stage("1%") == "5%"
    assert controller.next_stage("5%") == "20%"
    assert controller.next_stage("20%") == "full"
    assert controller.next_stage("full") == "full"


def test_next_stage_normalizes_input() -> None:
    controller = RolloutController()

    assert controller.next_stage(" Team-Only ") == "beta"
    assert controller.next_stage("FULL") == "full"
    assert controller.next_stage(None) == "team-only"
    assert controller.next_stage("") == "team-only"
