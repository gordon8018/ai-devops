from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from packages.context.adapters.git import GitContextAdapter
from packages.context.adapters.obsidian import ObsidianContextAdapter
from packages.context.graph.service import ContextGraphBuilder
from packages.context.indexer.repository import RepositoryIndexer
from packages.shared.domain.models import ContextPack, RiskProfile, WorkItem, WorkItemPriority


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return tuple(ordered)


class ContextPackAssembler:
    """Builds a structured ContextPack from a work item and legacy task hints."""

    def __init__(
        self,
        *,
        repo_indexer: RepositoryIndexer | None = None,
        graph_builder: ContextGraphBuilder | None = None,
        git_adapter: GitContextAdapter | None = None,
        obsidian_adapter: ObsidianContextAdapter | None = None,
        repo_locator=None,
    ) -> None:
        self._repo_indexer = repo_indexer or RepositoryIndexer()
        self._graph_builder = graph_builder or ContextGraphBuilder()
        self._git_adapter = git_adapter or GitContextAdapter()
        self._obsidian_adapter = obsidian_adapter or ObsidianContextAdapter()
        self._repo_locator = repo_locator or self._default_repo_locator

    def _default_repo_locator(self, repo: str) -> Path | None:
        if not repo:
            return None
        base = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
        candidate = base / "repos" / repo
        return candidate if candidate.exists() else None

    def build(self, work_item: WorkItem, *, legacy_task_input: dict[str, Any] | None = None) -> ContextPack:
        task_input = legacy_task_input or {}
        context = dict(task_input.get("context") or {})
        constraints = {**work_item.constraints, **dict(context.get("constraints") or {})}
        task_spec = context.get("taskSpec") if isinstance(context.get("taskSpec"), dict) else {}

        repo_scope_seed = _dedupe(
            list(constraints.get("allowedPaths") or [])
            + list(constraints.get("mustTouch") or [])
            + list(task_spec.get("allowedPaths") or [])
            + list(task_spec.get("mustTouch") or [])
            + list(context.get("filesHint") or [])
        )
        docs = list(context.get("docs") or []) + list(context.get("documentation") or [])
        recent_changes = list(context.get("recentChanges") or [])
        acceptance_criteria = _dedupe(
            list(work_item.acceptance_criteria)
            + list(task_input.get("acceptanceCriteria") or [])
            + list(context.get("acceptanceCriteria") or [])
            + list(task_spec.get("definitionOfDone") or [])
        )
        known_failures = list(context.get("knownFailures") or []) + list(context.get("failureContext") or [])

        repo_scope = list(repo_scope_seed)
        repo_root = self._repo_locator(work_item.repo)
        if repo_root is not None:
            index = self._repo_indexer.index(Path(repo_root))
            graph = self._graph_builder.build(index)
            repo_scope.extend(graph.related_paths(repo_scope_seed))
            docs.extend(index.docs)
            recent_changes.extend(self._git_adapter.recent_changes(Path(repo_root)))

        search_query = " ".join(part for part in (work_item.title, work_item.goal) if part).strip()
        if search_query:
            docs.extend(self._obsidian_adapter.search(search_query))
            known_failures.extend(self._obsidian_adapter.failure_excerpts(search_query))

        known_failures = _dedupe(
            list(context.get("knownFailures") or [])
            + list(context.get("failureContext") or [])
            + known_failures
        )
        docs = _dedupe(docs)
        recent_changes = _dedupe(recent_changes)
        repo_scope = _dedupe(repo_scope)

        risk_profile = {
            WorkItemPriority.LOW: RiskProfile.LOW,
            WorkItemPriority.MEDIUM: RiskProfile.MEDIUM,
            WorkItemPriority.HIGH: RiskProfile.HIGH,
            WorkItemPriority.CRITICAL: RiskProfile.CRITICAL,
        }[work_item.priority]

        return ContextPack(
            pack_id=f"ctx_{work_item.work_item_id}",
            work_item_id=work_item.work_item_id,
            repo_scope=repo_scope,
            docs=docs,
            recent_changes=recent_changes,
            constraints=constraints,
            acceptance_criteria=acceptance_criteria,
            known_failures=known_failures,
            risk_profile=risk_profile,
        )
