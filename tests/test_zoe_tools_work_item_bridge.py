from __future__ import annotations

from orchestrator.bin.zoe_tools import build_work_item_session
from packages.shared.domain.runtime_state import clear_runtime_state, list_audit_events


def test_build_work_item_session_enriches_scoped_legacy_task_inputs() -> None:
    session = build_work_item_session(
        {
            "repo": "acme/platform",
            "title": "Protect scoped planner inputs",
            "description": "Ensure scoped legacy tasks get context packs",
            "constraints": {
                "allowedPaths": ["packages/kernel/**"],
                "mustTouch": ["packages/kernel/services/work_items.py"],
            },
            "context": {
                "filesHint": ["packages/kernel/services/work_items.py"],
                "acceptanceCriteria": ["Attach context pack to plan request"],
            },
        }
    )

    assert session.context_pack.pack_id.startswith("ctx_")
    assert session.plan_request["context"]["workItem"]["workItemId"] == session.work_item.work_item_id
    assert session.plan_request["context"]["contextPack"]["packId"] == session.context_pack.pack_id


def test_build_work_item_session_records_legacy_entrypoint_audit() -> None:
    clear_runtime_state()

    session = build_work_item_session(
        {
            "repo": "acme/platform",
            "title": "Track legacy planner usage",
            "description": "Record audit trail when zoe tools are used directly",
        }
    )

    events = list_audit_events()

    assert session.work_item.work_item_id
    assert events[0]["action"] == "legacy_entrypoint_used"
    assert events[0]["payload"]["entrypoint"] == "zoe_tools.build_work_item_session"
