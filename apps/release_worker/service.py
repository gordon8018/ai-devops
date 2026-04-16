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
from packages.shared.mutation import MutationService

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
        audit_recorder: Callable[[AuditEvent], None] | None = None,
    ) -> None:
        self._event_manager = event_manager
        self._flag_adapter = flag_adapter or StatsigFlagAdapter()
        self._rollout_controller = rollout_controller or RolloutController()
        self._rollback_controller = rollback_controller or RollbackController()
        self._persistence_store = persistence_store or ensure_control_plane_store()
        self._audit_recorder = audit_recorder or record_audit_event
        self._mutations = MutationService()
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

    def _persist_release(self, work_item_id: str, release: dict[str, Any]) -> None:
        snapshot = dict(release)
        self._releases[work_item_id] = snapshot
        store = self._store()
        if store is not None and hasattr(store, "save_release"):
            store.save_release(snapshot)

    def _rollback_release(self, work_item_id: str, previous_release: dict[str, Any] | None) -> None:
        store = self._store()
        if previous_release is None:
            self._releases.pop(work_item_id, None)
            if store is not None and hasattr(store, "delete_release"):
                store.delete_release(work_item_id)
            return

        restored = dict(previous_release)
        self._releases[work_item_id] = restored
        if store is not None and hasattr(store, "save_release"):
            store.save_release(restored)

    def advance(self, work_item_id: str) -> dict[str, Any] | None:
        release = self.get_release(work_item_id)
        if release is None:
            return None
        if release.get("status") in {"rolled_back", "succeeded"}:
            return release

        previous_release = dict(release)
        updated_release = dict(release)
        current_stage = updated_release.get("stage") or "unknown"
        next_stage = self._rollout_controller.next_stage(current_stage)
        updated_release["stage"] = next_stage
        if next_stage == "full":
            updated_release["status"] = "succeeded"

        action = "release_succeeded" if updated_release["status"] == "succeeded" else "release_stage_advanced"
        self._mutations.apply(
            persist=lambda: self._persist_release(work_item_id, updated_release),
            audit=lambda: self._audit_recorder(
                AuditEvent(
                    audit_event_id=f"ae_{updated_release['releaseId']}_{action}_{int(time.time() * 1000)}",
                    entity_type="release",
                    entity_id=updated_release["releaseId"],
                    action=action,
                    payload={"workItemId": work_item_id, "stage": next_stage},
                    actor_id="system:release_worker",
                    actor_type="system",
                )
            ),
            publish_events=[
                lambda: self._flag_adapter.apply_stage(updated_release["releaseId"], next_stage)
            ],
            rollback=lambda: self._rollback_release(work_item_id, previous_release),
        )
        return updated_release

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
        existing = self.get_release(work_item_id)
        if existing is not None:
            return

        release_id = f"rel_{work_item_id}"
        stage = self._rollout_controller.next_stage("unknown")
        release = {
            "releaseId": release_id,
            "workItemId": work_item_id,
            "stage": stage,
            "status": "rolling_out",
        }
        self._mutations.apply(
            persist=lambda: self._persist_release(work_item_id, release),
            audit=lambda: self._audit_recorder(
                AuditEvent(
                    audit_event_id=f"ae_{release_id}_started_{int(time.time() * 1000)}",
                    entity_type="release",
                    entity_id=release_id,
                    action="release_started",
                    payload={"workItemId": work_item_id, "stage": stage},
                    actor_id="system:release_worker",
                    actor_type="system",
                )
            ),
            publish_events=[lambda: self._flag_adapter.apply_stage(release_id, stage)],
            rollback=lambda: self._rollback_release(work_item_id, None),
        )

    def _handle_system_event(self, payload: dict[str, Any]) -> None:
        if payload.get("type") != "guardrail_breach":
            return
        work_item_id = str(payload.get("work_item_id") or "").strip()
        release = self.get_release(work_item_id)
        if release is None:
            return

        decision = self._rollback_controller.evaluate(
            guardrails=dict(payload.get("guardrails") or {}),
            thresholds=dict(payload.get("thresholds") or {}),
        )
        if not decision.should_rollback:
            return

        previous_release = dict(release)
        updated_release = dict(release)
        updated_release["status"] = "rolled_back"
        updated_release["rollbackReason"] = decision.reason
        self._mutations.apply(
            persist=lambda: self._persist_release(work_item_id, updated_release),
            audit=lambda: self._audit_recorder(
                AuditEvent(
                    audit_event_id=f"ae_{updated_release['releaseId']}_rolled_back_{int(time.time() * 1000)}",
                    entity_type="release",
                    entity_id=updated_release["releaseId"],
                    action="release_rolled_back",
                    payload={"workItemId": work_item_id, "reason": decision.reason},
                    actor_id="system:release_worker",
                    actor_type="system",
                )
            ),
            publish_events=[
                lambda: self._event_manager.publish_alert(
                    "warning",
                    f"Release rolled back for {work_item_id}",
                    {"reason": decision.reason, "releaseId": updated_release["releaseId"]},
                    source="release_worker",
                )
            ],
            rollback=lambda: self._rollback_release(work_item_id, previous_release),
        )


def get_global_release_worker() -> ReleaseWorker | None:
    return _GLOBAL_RELEASE_WORKER
