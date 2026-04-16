#!/usr/bin/env python3
"""Package 0 acceptance script.

Exercises the Release advancement path that PR-0.1 introduced, asserting that
a work item taken to `ready` and then advanced five times ends up in
`stage=full, status=succeeded` with every intermediate stage flagged through
the adapter.

Usage:
    python3 scripts/package_0_acceptance.py

Exits 0 on pass, 1 on any assertion failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.release_worker.service import ReleaseWorker  # noqa: E402
from orchestrator.api.events import Event, EventManager, EventType  # noqa: E402
from packages.release.flags.statsig import StatsigFlagAdapter  # noqa: E402


EXPECTED_LADDER = ("team-only", "beta", "1%", "5%", "20%", "full")


def run_release_advancement_check() -> tuple[bool, str]:
    work_item_id = "wi_pkg0_acceptance"
    release_id = f"rel_{work_item_id}"

    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = StatsigFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    try:
        event_manager.publish(
            Event(
                event_type=EventType.TASK_STATUS,
                data={
                    "task_id": work_item_id,
                    "status": "ready",
                    "details": {"work_item_id": work_item_id},
                },
                source="package_0_acceptance",
            )
        )

        for _ in range(len(EXPECTED_LADDER) - 1):
            worker.advance(work_item_id)

        release = worker.get_release(work_item_id)
        if release is None:
            return False, "release was not created on ready event"

        problems: list[str] = []
        if release.get("stage") != "full":
            problems.append(f"stage={release.get('stage')!r}, expected 'full'")
        if release.get("status") != "succeeded":
            problems.append(f"status={release.get('status')!r}, expected 'succeeded'")

        applied = flag_adapter.applied_stages(release_id)
        if applied != EXPECTED_LADDER:
            problems.append(f"flag adapter ladder={applied!r}, expected {EXPECTED_LADDER!r}")

        if problems:
            return False, "; ".join(problems)

        return True, (
            f"stage={release['stage']} status={release['status']} "
            f"ladder={'->'.join(applied)}"
        )
    finally:
        worker.stop()


def main() -> int:
    checks = [("release advancement", run_release_advancement_check)]

    failures = 0
    for name, check in checks:
        ok, detail = check()
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}: {detail}")
        if not ok:
            failures += 1

    if failures:
        print(f"\n{failures} check(s) failed")
        return 1

    print("\nPackage 0 acceptance: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
