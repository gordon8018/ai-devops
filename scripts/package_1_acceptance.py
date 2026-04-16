from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.api.events import EventManager
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import WorkItemService
from packages.shared.domain.models import QualityRun, QualityRunStatus, WorkItemStatus


def main() -> int:
    manager = EventManager()
    manager.clear_history()
    bus = InMemoryEventBus(event_manager=manager)
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())

    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Package 1 acceptance",
            "description": "Bridge kernel events into event manager",
            "requested_by": "acceptance",
        }
    )

    quality_run = QualityRun(
        quality_run_id="qr_acceptance_001",
        work_item_id=session.work_item.work_item_id,
        gate_type="acceptance",
        status=QualityRunStatus.PASSED,
        summary="acceptance gate passed",
    )
    service.transition_work_item_status(
        session.work_item,
        target_status=WorkItemStatus.RELEASED,
        quality_run=quality_run,
    )

    history = manager.get_history(limit=10)
    event_names = [item.get("eventName") for item in history]
    status_event = next(
        item for item in history if item.get("eventName") == "work_item.status_changed"
    )

    payload = {
        "work_item_id": session.work_item.work_item_id,
        "event_names": event_names,
        "status_transition": status_event.get("data"),
        "actors": [
            {
                "eventName": item.get("eventName"),
                "actorId": item.get("actorId"),
                "actorType": item.get("actorType"),
                "source": item.get("source"),
            }
            for item in history
            if item.get("eventName") in {
                "work_item.created",
                "context_pack.created",
                "plan.requested",
                "work_item.status_changed",
            }
        ],
    }
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
