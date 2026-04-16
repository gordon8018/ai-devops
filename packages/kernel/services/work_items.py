from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from orchestrator.bin.zoe_tools import build_plan_request
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.shared.domain.models import (
    AgentRun,
    AgentRunStatus,
    ContextPack,
    QualityRun,
    QualityRunStatus,
    WorkItem,
    WorkItemStatus,
)


class MissingContextPackError(ValueError):
    """Raised when an execution path tries to start without a ContextPack."""


class MissingQualityRunError(ValueError):
    """Raised when terminal platform states lack structured quality evidence."""


@dataclass(slots=True, frozen=True)
class LegacyWorkItemSession:
    work_item: WorkItem
    context_pack: ContextPack
    plan_request: dict[str, Any]


class WorkItemService:
    """Compatibility bridge from legacy task inputs to platform-native objects."""

    def __init__(
        self,
        *,
        event_bus: InMemoryEventBus | None = None,
        context_assembler: ContextPackAssembler | None = None,
    ) -> None:
        self._event_bus = event_bus or InMemoryEventBus()
        self._context_assembler = context_assembler or ContextPackAssembler()

    @property
    def event_bus(self) -> InMemoryEventBus:
        return self._event_bus

    def create_legacy_session(
        self,
        task_input: dict[str, Any],
        *,
        base_dir=None,
    ) -> LegacyWorkItemSession:
        work_item = WorkItem.from_legacy_task_input(task_input)
        self._event_bus.publish(
            "work_item.created",
            work_item.to_dict(),
            source="kernel.work_items",
            actor_id="system:kernel",
            actor_type="system",
        )

        context_pack = self._context_assembler.build(
            work_item,
            legacy_task_input=task_input,
        )
        self._event_bus.publish(
            "context_pack.created",
            context_pack.to_dict(),
            source="kernel.work_items",
            actor_id="system:kernel",
            actor_type="system",
        )

        context = {
            **dict(task_input.get("context") or {}),
            "workItem": work_item.to_dict(),
            "contextPack": context_pack.to_dict(),
        }
        synthesized_task_spec = self._synthesize_task_spec(
            work_item=work_item,
            context_pack=context_pack,
            task_input=task_input,
        )
        if synthesized_task_spec and not isinstance(task_input.get("taskSpec"), dict):
            context["taskSpec"] = synthesized_task_spec
        enriched_input = {
            **task_input,
            "context": context,
        }
        if synthesized_task_spec and not isinstance(task_input.get("taskSpec"), dict):
            enriched_input["taskSpec"] = synthesized_task_spec
        if not enriched_input.get("description") and work_item.goal:
            enriched_input["description"] = work_item.goal
        if not enriched_input.get("title") and work_item.title:
            enriched_input["title"] = work_item.title
        if not enriched_input.get("repo") and work_item.repo:
            enriched_input["repo"] = work_item.repo

        plan_request = build_plan_request(enriched_input, base_dir=base_dir)
        self._event_bus.publish(
            "plan.requested",
            {
                "workItemId": work_item.work_item_id,
                "planId": plan_request["planId"],
            },
            source="kernel.work_items",
            actor_id="system:kernel",
            actor_type="system",
        )
        return LegacyWorkItemSession(
            work_item=work_item,
            context_pack=context_pack,
            plan_request=plan_request,
        )

    def prepare_agent_run(
        self,
        *,
        work_item: WorkItem,
        context_pack: ContextPack | None,
        agent: str,
        model: str,
        planned_steps: tuple[str, ...] = (),
    ) -> AgentRun:
        if context_pack is None or not context_pack.pack_id:
            raise MissingContextPackError("AgentRun requires a bound ContextPack before execution")

        run = AgentRun(
            run_id=f"run_{work_item.work_item_id}_{agent}",
            work_item_id=work_item.work_item_id,
            context_pack_id=context_pack.pack_id,
            agent=agent,
            model=model,
            status=AgentRunStatus.PENDING,
            planned_steps=tuple(planned_steps),
        )
        run.validate_for_execution()
        self._event_bus.publish(
            "agent_run.prepared",
            run.to_dict(),
            source="kernel.work_items",
            actor_id="system:kernel",
            actor_type="system",
        )
        return run

    def transition_work_item_status(
        self,
        work_item: WorkItem,
        *,
        target_status: WorkItemStatus,
        quality_run: QualityRun | None,
    ) -> WorkItem:
        if target_status in {WorkItemStatus.RELEASED, WorkItemStatus.CLOSED}:
            if quality_run is None or quality_run.status is not QualityRunStatus.PASSED:
                raise MissingQualityRunError(
                    f"WorkItem {work_item.work_item_id} requires a passed QualityRun before {target_status.value}"
                )

        transitioned = WorkItem(
            work_item_id=work_item.work_item_id,
            type=work_item.type,
            title=work_item.title,
            goal=work_item.goal,
            priority=work_item.priority,
            status=target_status,
            repo=work_item.repo,
            constraints=work_item.constraints,
            acceptance_criteria=work_item.acceptance_criteria,
            requested_by=work_item.requested_by,
            requested_at=work_item.requested_at,
            source=work_item.source,
            metadata=work_item.metadata,
        )
        self._event_bus.publish(
            "work_item.status_changed",
            {
                "workItemId": work_item.work_item_id,
                "oldStatus": work_item.status.value,
                "newStatus": target_status.value,
                "qualityRunId": quality_run.quality_run_id if quality_run else None,
            },
            source="kernel.work_items",
            actor_id="system:kernel",
            actor_type="system",
        )
        return transitioned

    def _synthesize_task_spec(
        self,
        *,
        work_item: WorkItem,
        context_pack: ContextPack,
        task_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        constraints = dict(task_input.get("constraints") or {})
        context = dict(task_input.get("context") or {})
        has_scope_contract = any(
            constraints.get(key)
            for key in ("allowedPaths", "forbiddenPaths", "blockedPaths", "mustTouch", "requiredTouchedPaths")
        )
        if not has_scope_contract:
            return None

        files_hint = tuple(str(item) for item in context.get("filesHint") or () if str(item).strip())
        first_step_requirement = str(
            context.get("firstStepRequirement")
            or "Read the scoped context pack, then inspect the required target files before editing."
        )
        return {
            "repo": work_item.repo,
            "title": work_item.title,
            "goal": work_item.goal,
            "workingRoot": ".",
            "acceptanceCriteria": list(context_pack.acceptance_criteria or work_item.acceptance_criteria),
            "allowedPaths": list(constraints.get("allowedPaths") or ()),
            "forbiddenPaths": list(constraints.get("forbiddenPaths") or constraints.get("blockedPaths") or ()),
            "mustTouch": list(constraints.get("mustTouch") or constraints.get("requiredTouchedPaths") or files_hint),
            "filesHint": list(files_hint),
            "definitionOfDone": list(
                context_pack.acceptance_criteria
                or work_item.acceptance_criteria
                or ("Implement the requested scoped change.",)
            ),
            "validation": list(
                context.get("validation")
                or constraints.get("validation")
                or ("Run the narrowest automated checks that cover the scoped files.",)
            ),
            "firstStepRequirement": first_step_requirement,
            "failureRules": list(
                context.get("failureRules")
                or constraints.get("failureRules")
                or (
                    "Stop and report if the required scope is insufficient.",
                    "Do not edit files outside allowedPaths.",
                )
            ),
        }
