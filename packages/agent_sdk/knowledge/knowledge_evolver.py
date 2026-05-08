"""Orchestrate knowledge extraction and CLAUDE.md persistence after successful runs."""

from __future__ import annotations

import logging
from typing import Any

from packages.agent_sdk.guardrails.input_guards import PromptInjectionGuard
from packages.agent_sdk.knowledge.claudemd_writer import ClaudeMDWriter
from packages.agent_sdk.knowledge.knowledge_extractor import ExtractedKnowledge, KnowledgeExtractor
from packages.shared.domain.models import AgentRunResult, AgentRunStatus

logger = logging.getLogger(__name__)


class KnowledgeEvolver:
    """
    Post-run hook: extract reusable patterns from successful agent output and
    persist them to CLAUDE.md for cross-WorkItem knowledge accumulation.

    NEVER raises — all exceptions are swallowed so they never block execution.
    """

    def __init__(self, event_bus: Any = None, extractor_model: str = "claude-sonnet-4-6"):
        self._event_bus = event_bus
        self._extractor_model = extractor_model

    async def evolve(
        self,
        result: AgentRunResult,
        implementation_output: str,
        subtask_title: str,
        work_item_id: str,
        workspace_path: str,
    ) -> bool:
        """Returns True if knowledge was written. Always swallows exceptions."""
        if result.agent_run.status != AgentRunStatus.COMPLETED:
            return False
        if not implementation_output.strip():
            return False

        try:
            knowledge = await KnowledgeExtractor.extract(
                implementation_output=implementation_output,
                subtask_title=subtask_title,
                extractor_model=self._extractor_model,
            )

            if knowledge.is_empty():
                return False

            # Fix H8: guard extracted knowledge against prompt injection before persisting
            if not _is_knowledge_safe(knowledge):
                logger.warning(
                    "KnowledgeEvolver: injection detected in extracted knowledge for %s/%s — skipped",
                    work_item_id, result.agent_run.run_id,
                )
                return False

            written = await ClaudeMDWriter.write(
                workspace_path=workspace_path,
                knowledge=knowledge,
                work_item_id=work_item_id,
                subtask_id=result.agent_run.run_id,
            )

            if self._event_bus and written:
                self._event_bus.publish("knowledge.evolved", {
                    "work_item_id": work_item_id,
                    "subtask_id": result.agent_run.run_id,
                    "patterns": len(knowledge.patterns),
                    "gotchas": len(knowledge.gotchas),
                    "decisions": len(knowledge.decisions),
                })

            return written

        except Exception as e:
            logger.warning("KnowledgeEvolver.evolve failed silently: %s", e)
            return False


def _is_knowledge_safe(knowledge: ExtractedKnowledge) -> bool:
    """Return False if any knowledge entry triggers the prompt injection guard."""
    all_entries = list(knowledge.patterns) + list(knowledge.gotchas) + list(knowledge.decisions)
    for entry in all_entries:
        if PromptInjectionGuard.check(entry).tripwire_triggered:
            return False
    return True
