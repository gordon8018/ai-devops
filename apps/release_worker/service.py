from __future__ import annotations

from typing import Any, Callable
import time

from orchestrator.api.events import Event, EventManager, EventType
from packages.release.flags.statsig import StatsigFlagAdapter
from packages.release.rollback.service import RollbackController
from packages.release.rollout.service import RolloutController
from packages.shared.domain.control_plane import ensure_control_plane_store
from packages.shared.domain.models import AuditEvent
from packages.shared.domain.runtime_state import record_audit_event

_GLOBAL_RELEASE_WORKER: "ReleaseWorker | None" = None


class ReleaseWorker:
    """Consume platform events and drive release rollout / rollback decisions."""

    def __init__(
        self,
        *,
        event_manager: EventManager,
        flag_adapter: Any | None = None,
        rollout_controller: RolloutController | None = None,
        rollback_controller: RollbackController | None = None,
        persistence_store: Any | None = None,
    ) -> None:
        self._event_manager = event_manager
        self._flag_adapter = flag_adapter or StatsigFlagAdapter()
        self._rollout_controller = rollout_controller or RolloutController()
        self._rollback_controller = rollback_controller or RollbackController()
        self._persistence_store = persistence_store or ensure_control_plane_store()
        self._releases: dict[str, dict[str, Any]] = {}
        self._unsubscribe: Callable[[], None] | None = None

    def _store(self) -> Any | None:
        return self._persistence_store or ensure_control_plane_store()

    def start(self) -> None:
        global _GLOBAL_RELEASE_WORKER
        if self._unsubscribe is None:
            self._unsubscribe = self._event_manager.subscribe(
                self._handle_event,
                event_types=[EventType.TASK_STATUS, EventType.SYSTEM],
            )
            _GLOBAL_RELEASE_WORKER = self

    def stop(self) -> None:
        global _GLOBAL_RELEASE_WORKER
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
            if _GLOBAL_RELEASE_WORKER is self:
                _GLOBAL_RELEASE_WORKER = None

    def get_release(self, work_item_id: str) -> dict[str, Any] | None:
        store = self._store()
        if store is not None and hasattr(store, "get_release"):
            release = store.get_release(work_item_id)
            if release is not None:
                return release
        return self._releases.get(work_item_id)

    def list_releases(self) -> list[dict[str, Any]]:
        store = self._store()
        if store is not None and hasattr(store, "list_releases"):
            releases = list(store.list_releases())
            if releases:
                return releases
        return list(self._releases.values())

    def _handle_event(self, event: Event) -> None:
        if event.event_type is EventType.TASK_STATUS:
            self._handle_task_status(event.data)
            return
        if event.event_type is EventType.SYSTEM:
            self._handle_system_event(event.data)

    def _handle_task_status(self, payload: dict[str, Any]) -> None:
        if payload.get("status") != "ready":
            return
        work_item_id = str(payload.get("details", {}).get("work_item_id") or payload.get("task_id") or "").strip()
        if not work_item_id:
            return

        release_id = f"rel_{work_item_id}"
        stage = self._rollout_controller.next_stage("unknown")
        release = {
            "releaseId": release_id,
            "workItemId": work_item_id,
            "stage": stage,
            "status": "rolling_out",
        }
        self._releases[work_item_id] = release
        store = self._store()
        if store is not None and hasattr(store, "save_release"):
            store.save_release(release)
        self._flag_adapter.apply_stage(release_id, stage)
        record_audit_event(
            AuditEvent(
                audit_event_id=f"ae_{release_id}_started_{int(time.time() * 1000)}",
                entity_type="release",
                entity_id=release_id,
                action="release_started",
                payload={"workItemId": work_item_id, "stage": stage},
            )
        )

    def _handle_system_event(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "guardrail_breach":
            return
        work_item_id = str(payload.get("work_item_id") or "").strip()
        release = self._releases.get(work_item_id)
        if release is None:
            return

        decision = self._rollback_controller.evaluate(
            guardrails=dict(payload.get("guardrails") or {}),
            thresholds=dict(payload.get("thresholds") or {}),
        )
        if not decision.should_rollback:
            return

        release["status"] = "rolled_back"
        release["rollbackReason"] = decision.reason
        store = self._store()
        if store is not None and hasattr(store, "save_release"):
            store.save_release(release)
        record_audit_event(
            AuditEvent(
                audit_event_id=f"ae_{release['releaseId']}_rolled_back_{int(time.time() * 1000)}",
                entity_type="release",
                entity_id=release["releaseId"],
                action="release_rolled_back",
                payload={"workItemId": work_item_id, "reason": decision.reason},
            )
        )
        self._event_manager.publish_alert(
            "warning",
            f"Release rolled back for {work_item_id}",
            {"reason": decision.reason, "releaseId": release["releaseId"]},
            source="release_worker",
        )


def get_global_release_worker() -> ReleaseWorker | None:
    return _GLOBAL_RELEASE_WORKER
