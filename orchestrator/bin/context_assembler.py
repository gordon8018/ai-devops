#!/usr/bin/env python3
"""
Context Assembler - Phase 4+

Assembles retrieved historical tasks into Ralph-readable context
with clear structure and prioritization.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

try:
    from gbrain_retriever import HistoricalTask
except ImportError:
    from orchestrator.bin.gbrain_retriever import HistoricalTask


class ContextAssemblerError(Exception):
    pass


@dataclass
class ContextConfig:
    """Configuration for context assembly."""
    max_tasks: int = 3
    include_code_patterns: bool = True
    include_decisions: bool = True
    include_review_comments: bool = True
    include_file_structure: bool = False  # Default to False to save space
    prioritize_high_relevance: bool = True
    min_relevance_threshold: float = 0.5


class ContextAssembler:
    """Assembles historical task context for Ralph consumption."""

    def __init__(self, config: Optional[ContextConfig] = None):
        self.config = config or ContextConfig()

    def _format_task_context(self, task: HistoricalTask, index: int) -> str:
        """Format a single historical task into markdown context."""
        lines = [
            f"## 相关任务 {index}: {task.task_id}",
            f"**相关度**: {task.relevance_score:.2%}",
            f"**检索方式**: {task.retrieval_method}",
            "",
        ]

        # Description
        if task.description:
            lines.append(f"**描述**: {task.description}")
            lines.append("")

        # Code pattern (if enabled)
        if self.config.include_code_patterns and task.code_pattern:
            lines.append("**实现模式**:")
            lines.append("```")
            lines.append(task.code_pattern)
            lines.append("```")
            lines.append("")

        # Design decisions (if enabled)
        if self.config.include_decisions and task.decisions:
            lines.append("**设计决策**:")
            for decision in task.decisions.split('\n') if task.decisions else []:
                decision = decision.strip()
                if decision:
                    lines.append(f"- {decision}")
            lines.append("")

        # Code review comments (if enabled)
        if self.config.include_review_comments and task.review_comments:
            lines.append("**Code Review 意见**:")
            for comment in task.review_comments.split('\n') if task.review_comments else []:
                comment = comment.strip()
                if comment:
                    lines.append(f"- {comment}")
            lines.append("")

        # File structure (if enabled)
        if self.config.include_file_structure and task.file_structure:
            lines.append("**文件结构**:")
            lines.append("```")
            lines.append(task.file_structure)
            lines.append("```")
            lines.append("")

        # Tags (useful for filtering)
        if task.tags:
            tags_str = ", ".join([t for t in task.tags if not t.startswith("date:")])
            if tags_str:
                lines.append(f"**标签**: {tags_str}")
                lines.append("")

        return "\n".join(lines)

    def _format_introduction(self, current_task: Dict[str, Any]) -> str:
        """Format the introduction for the context."""
        task_id = current_task.get("taskId", "UNKNOWN")
        task_desc = current_task.get("task", "")

        lines = [
            "# 历史参考上下文",
            "",
            f"**当前任务**: {task_id}",
            f"**任务描述**: {task_desc}",
            "",
            "以下是从历史任务中检索到的相关经验，可供参考：",
            "",
        ]

        return "\n".join(lines)

    def _format_summary(self, tasks: List[HistoricalTask]) -> str:
        """Format a summary of retrieved tasks."""
        if not tasks:
            return ""

        lines = [
            "---",
            "",
            "## 检索摘要",
            "",
            f"- 共检索到 {len(tasks)} 个相关历史任务",
            f"- 平均相关度: {sum(t.relevance_score for t in tasks) / len(tasks):.2%}",
            f"- 相关度范围: {min(t.relevance_score for t in tasks):.2%} - {max(t.relevance_score for t in tasks):.2%}",
            "",
            "**使用建议**:",
            "- 优先参考高相关度任务（> 80%）的实现模式",
            "- 注意 Code Review 意见中的改进建议",
            "- 根据当前任务特点调整设计决策",
            "",
        ]

        return "\n".join(lines)

    def assemble(
        self,
        current_task: Dict[str, Any],
        historical_tasks: List[HistoricalTask],
        config: Optional[ContextConfig] = None,
    ) -> str:
        """
        Assemble historical tasks into Ralph-readable context.

        Args:
            current_task: Current TaskSpec dictionary
            historical_tasks: List of HistoricalTask objects
            config: Optional configuration override

        Returns:
            Formatted markdown context string
        """
        if config:
            self.config = config

        # Filter by relevance threshold
        filtered_tasks = [
            t for t in historical_tasks
            if t.relevance_score >= self.config.min_relevance_threshold
        ]

        # Sort by relevance if prioritization is enabled
        if self.config.prioritize_high_relevance:
            filtered_tasks.sort(key=lambda t: t.relevance_score, reverse=True)

        # Limit to max tasks
        filtered_tasks = filtered_tasks[:self.config.max_tasks]

        # Build context
        context_parts = [
            self._format_introduction(current_task),
        ]

        for idx, task in enumerate(filtered_tasks, 1):
            context_parts.append(self._format_task_context(task, idx))

        if filtered_tasks:
            context_parts.append(self._format_summary(filtered_tasks))
        else:
            context_parts.append("---\n\n*未找到相关历史任务*")

        return "\n".join(context_parts)

    def assemble_compact(
        self,
        current_task: Dict[str, Any],
        historical_tasks: List[HistoricalTask],
    ) -> str:
        """
        Assemble a compact version of context for space-constrained scenarios.

        Args:
            current_task: Current TaskSpec dictionary
            historical_tasks: List of HistoricalTask objects

        Returns:
            Compact formatted markdown context string
        """
        compact_config = ContextConfig(
            max_tasks=2,
            include_code_patterns=True,
            include_decisions=True,
            include_review_comments=False,  # Skip reviews for compact mode
            include_file_structure=False,
            prioritize_high_relevance=True,
            min_relevance_threshold=0.7,  # Higher threshold for compact mode
        )

        return self.assemble(current_task, historical_tasks, compact_config)

    def save_context(
        self,
        context: str,
        output_path: str | Path,
    ) -> None:
        """
        Save assembled context to file.

        Args:
            context: Formatted context string
            output_path: Path to save the context file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output_path.write_text(context, encoding='utf-8')


def load_task_spec_from_file(path: str | Path) -> Dict[str, Any]:
    """
    Load TaskSpec from JSON file.

    Args:
        path: Path to TaskSpec JSON file

    Returns:
        TaskSpec dictionary

    Raises:
        ContextAssemblerError: If file not found or invalid JSON
    """
    path = Path(path)
    if not path.exists():
        raise ContextAssemblerError(f"TaskSpec file not found: {path}")

    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ContextAssemblerError(f"Invalid JSON in TaskSpec file: {e}")


if __name__ == "--main__":
    import sys

    if len(sys.argv) < 3:
        print("ContextAssembler CLI")
        print("Usage:")
        print("  context_assembler.py assemble <task_spec.json> <historical_tasks.json> [output.md]")
        print("  context_assembler.py compact <task_spec.json> <historical_tasks.json> [output.md]")
        sys.exit(0)

    cmd = sys.argv[1]
    task_spec_path = sys.argv[2]
    historical_tasks_path = sys.argv[3]
    output_path = sys.argv[4] if len(sys.argv) > 4 else "context.md"

    try:
        # Load data
        current_task = load_task_spec_from_file(task_spec_path)

        with open(historical_tasks_path, 'r') as f:
            historical_tasks_data = json.load(f)

        # Convert to HistoricalTask objects
        historical_tasks = [HistoricalTask(**t) for t in historical_tasks_data]

        # Assemble
        assembler = ContextAssembler()

        if cmd == "assemble":
            context = assembler.assemble(current_task, historical_tasks)
        elif cmd == "compact":
            context = assembler.assemble_compact(current_task, historical_tasks)
        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

        # Save
        assembler.save_context(context, output_path)

        print(f"✓ Context assembled and saved to {output_path}")
        print(f"  Tasks included: {len(historical_tasks)}")

    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
