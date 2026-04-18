from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Any


def _make_id(prefix: str, *parts: str) -> str:
    raw = "|".join(part for part in parts if part)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


class WorkItemType(str, Enum):
    FEATURE = "feature"
    BUGFIX = "bugfix"
    INCIDENT = "incident"
    RELEASE_NOTE = "release_note"
    EXPERIMENT = "experiment"
    OPS = "ops"


class WorkItemPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkItemStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    BLOCKED = "blocked"
    READY = "ready"
    RELEASED = "released"
    CLOSED = "closed"


class RiskProfile(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class QualityRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class EvalRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    DEGRADED = "degraded"


@dataclass(slots=True, frozen=True)
class WorkItem:
    work_item_id: str
    type: WorkItemType
    title: str
    goal: str
    priority: WorkItemPriority = WorkItemPriority.MEDIUM
    status: WorkItemStatus = WorkItemStatus.QUEUED
    repo: str = ""
    constraints: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    requested_by: str = "unknown"
    requested_at: int = 0
    source: str = "platform"
    metadata: dict[str, Any] = field(default_factory=dict)
    dedup_key: str | None = None

    @classmethod
    def from_legacy_task_input(cls, task_input: dict[str, Any]) -> "WorkItem":
        repo = str(task_input.get("repo") or "").strip()
        title = str(task_input.get("title") or task_input.get("task") or "").strip()
        goal = str(task_input.get("description") or task_input.get("objective") or title).strip()
        requested_by = str(task_input.get("requested_by") or task_input.get("requestedBy") or "legacy")
        requested_at = int(task_input.get("requested_at") or task_input.get("requestedAt") or int(time.time() * 1000))
        constraints = dict(task_input.get("constraints") or {})
        context = dict(task_input.get("context") or {})

        explicit_type = str(task_input.get("type") or context.get("type") or "").strip().lower()
        work_item_type = {
            "feature": WorkItemType.FEATURE,
            "bugfix": WorkItemType.BUGFIX,
            "incident": WorkItemType.INCIDENT,
            "release_note": WorkItemType.RELEASE_NOTE,
            "experiment": WorkItemType.EXPERIMENT,
            "ops": WorkItemType.OPS,
        }.get(explicit_type, WorkItemType.FEATURE)

        priority_text = str(task_input.get("priority") or context.get("priority") or "medium").strip().lower()
        priority = {
            "low": WorkItemPriority.LOW,
            "medium": WorkItemPriority.MEDIUM,
            "high": WorkItemPriority.HIGH,
            "critical": WorkItemPriority.CRITICAL,
        }.get(priority_text, WorkItemPriority.MEDIUM)

        acceptance = task_input.get("acceptanceCriteria") or context.get("acceptanceCriteria") or ()
        if not isinstance(acceptance, (list, tuple)):
            acceptance = ()

        raw_dedup = task_input.get("dedupKey") or task_input.get("dedup_key")
        dedup_key = str(raw_dedup).strip() if raw_dedup is not None else ""
        dedup_key = dedup_key or None

        return cls(
            work_item_id=str(task_input.get("workItemId") or _make_id("wi", repo, title, str(requested_at))),
            type=work_item_type,
            title=title,
            goal=goal,
            priority=priority,
            status=WorkItemStatus.PLANNING,
            repo=repo,
            constraints=constraints,
            acceptance_criteria=tuple(str(item) for item in acceptance if str(item).strip()),
            requested_by=requested_by,
            requested_at=requested_at,
            source="legacy_task_input",
            metadata={
                "legacyTaskInput": {
                    key: value
                    for key, value in task_input.items()
                    if key not in {"contextPack", "workItem"}
                }
            },
            dedup_key=dedup_key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workItemId": self.work_item_id,
            "type": self.type.value,
            "title": self.title,
            "goal": self.goal,
            "priority": self.priority.value,
            "status": self.status.value,
            "repo": self.repo,
            "constraints": self.constraints,
            "acceptanceCriteria": list(self.acceptance_criteria),
            "requestedBy": self.requested_by,
            "requestedAt": self.requested_at,
            "source": self.source,
            "metadata": self.metadata,
            "dedupKey": self.dedup_key,
        }


@dataclass(slots=True, frozen=True)
class ContextPack:
    pack_id: str
    work_item_id: str
    repo_scope: tuple[str, ...] = field(default_factory=tuple)
    docs: tuple[str, ...] = field(default_factory=tuple)
    recent_changes: tuple[str, ...] = field(default_factory=tuple)
    constraints: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = field(default_factory=tuple)
    known_failures: tuple[str, ...] = field(default_factory=tuple)
    risk_profile: RiskProfile = RiskProfile.MEDIUM

    def to_dict(self) -> dict[str, Any]:
        return {
            "packId": self.pack_id,
            "workItemId": self.work_item_id,
            "repoScope": list(self.repo_scope),
            "docs": list(self.docs),
            "recentChanges": list(self.recent_changes),
            "constraints": self.constraints,
            "acceptanceCriteria": list(self.acceptance_criteria),
            "knownFailures": list(self.known_failures),
            "riskProfile": self.risk_profile.value,
        }


@dataclass(slots=True, frozen=True)
class AgentRun:
    run_id: str
    work_item_id: str
    context_pack_id: str
    agent: str
    model: str
    status: AgentRunStatus = AgentRunStatus.PENDING
    planned_steps: tuple[str, ...] = field(default_factory=tuple)

    def validate_for_execution(self) -> None:
        if not self.context_pack_id:
            raise ValueError("AgentRun requires a context_pack_id before execution")

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "workItemId": self.work_item_id,
            "contextPackId": self.context_pack_id,
            "agent": self.agent,
            "model": self.model,
            "status": self.status.value,
            "plannedSteps": list(self.planned_steps),
        }


@dataclass(slots=True, frozen=True)
class ReviewFinding:
    """A finding from a guardrail or code review check."""
    finding_id: str
    category: str
    severity: str
    message: str
    source_guardrail: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class AuditEvent:
    audit_event_id: str
    entity_type: str
    entity_id: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    actor_id: str = "system:legacy"
    actor_type: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "auditEventId": self.audit_event_id,
            "entityType": self.entity_type,
            "entityId": self.entity_id,
            "action": self.action,
            "payload": self.payload,
            "createdAt": self.created_at,
            "actorId": self.actor_id,
            "actorType": self.actor_type,
        }

    def payload_json(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False, sort_keys=True)


@dataclass(slots=True, frozen=True)
class QualityRun:
    quality_run_id: str
    work_item_id: str
    gate_type: str
    status: QualityRunStatus
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualityRunId": self.quality_run_id,
            "workItemId": self.work_item_id,
            "gateType": self.gate_type,
            "status": self.status.value,
            "summary": self.summary,
            "payload": self.payload,
        }


@dataclass(slots=True, frozen=True)
class EvalRun:
    eval_run_id: str
    work_item_id: str
    status: EvalRunStatus
    summary: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evalRunId": self.eval_run_id,
            "workItemId": self.work_item_id,
            "status": self.status.value,
            "summary": self.summary,
            "payload": self.payload,
        }
