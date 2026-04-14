#!/usr/bin/env python3
"""
Unit tests for context_assembler.py
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

from context_assembler import (
    ContextAssembler,
    ContextAssemblerError,
    ContextConfig,
)


class TestContextAssembler:
    """Test suite for ContextAssembler class."""

    @pytest.fixture
    def assembler(self):
        """Create a ContextAssembler instance for testing."""
        return ContextAssembler()

    @pytest.fixture
    def sample_current_task(self):
        """Sample current TaskSpec for testing."""
        return {
            "taskId": "PROJ-123",
            "task": "Implement user authentication",
            "userStories": ["Create login endpoint"],
            "acceptanceCriteria": ["Login returns JWT on success"],
            "repo": "my-org/my-repo",
        }

    @pytest.fixture
    def sample_historical_tasks(self):
        """Sample historical tasks for testing."""
        from gbrain_retriever import HistoricalTask

        return [
            HistoricalTask(
                task_id="AUTH-001",
                description="Previous authentication task",
                code_pattern="def authenticate(username, password):",
                decisions="Use JWT for stateless auth",
                review_comments="Add rate limiting",
                file_structure="auth/\n  login.py\n  jwt.py",
                relevance_score=0.85,
                retrieval_method="vector",
                tags=["AUTH-001", "project:my-repo"],
                metadata={},
            ),
            HistoricalTask(
                task_id="AUTH-002",
                description="Session management task",
                code_pattern="class SessionManager:",
                decisions="Use Redis for session storage",
                review_comments="Good implementation",
                file_structure="session/\n  manager.py",
                relevance_score=0.72,
                retrieval_method="vector",
                tags=["AUTH-002", "project:my-repo"],
                metadata={},
            ),
        ]

    def test_initialization_default_config(self, assembler):
        """Test assembler initialization with default config."""
        assert assembler.config.max_tasks == 3
        assert assembler.config.include_code_patterns == True
        assert assembler.config.include_decisions == True
        assert assembler.config.include_review_comments == True
        assert assembler.config.include_file_structure == False
        assert assembler.config.prioritize_high_relevance == True
        assert assembler.config.min_relevance_threshold == 0.5

    def test_initialization_custom_config(self):
        """Test assembler initialization with custom config."""
        custom_config = ContextConfig(
            max_tasks=5,
            include_code_patterns=False,
            include_file_structure=True,
        )
        assembler = ContextAssembler(config=custom_config)

        assert assembler.config.max_tasks == 5
        assert assembler.config.include_code_patterns == False
        assert assembler.config.include_file_structure == True

    def test_format_task_context(self, assembler, sample_historical_tasks):
        """Test formatting a single task context."""
        task_context = assembler._format_task_context(sample_historical_tasks[0], 1)

        # Check that key elements are present
        assert "## 相关任务 1: AUTH-001" in task_context
        assert "AUTH-001" in task_context
        assert "85%" in task_context  # Relevance score
        assert "Previous authentication task" in task_context
        assert "def authenticate(username, password):" in task_context
        assert "Use JWT for stateless auth" in task_context
        assert "Add rate limiting" in task_context
        # File structure should NOT be included by default
        assert "auth/" not in task_context

    def test_format_task_context_with_file_structure(self):
        """Test formatting task context with file structure enabled."""
        custom_config = ContextConfig(include_file_structure=True)
        assembler = ContextAssembler(config=custom_config)

        from gbrain_retriever import HistoricalTask

        task = HistoricalTask(
            task_id="TEST-001",
            description="Test task",
            code_pattern="def test():",
            decisions="Test decision",
            review_comments="Good",
            file_structure="test/\n  test.py",
            relevance_score=0.85,
            retrieval_method="vector",
            tags=["test"],
            metadata={},
        )

        task_context = assembler._format_task_context(task, 1)

        # File structure should be included
        assert "test/" in task_context
        assert "test.py" in task_context

    def test_format_introduction(self, assembler, sample_current_task):
        """Test formatting the introduction."""
        intro = assembler._format_introduction(sample_current_task)

        assert "# 历史参考上下文" in intro
        assert "PROJ-123" in intro
        assert "Implement user authentication" in intro
        assert "以下是从历史任务中检索到的相关经验" in intro

    def test_format_summary(self, assembler, sample_historical_tasks):
        """Test formatting the summary."""
        summary = assembler._format_summary(sample_historical_tasks)

        assert "## 检索摘要" in summary
        assert "共检索到 2 个相关历史任务" in summary
        assert "平均相关度" in summary
        assert "相关度范围" in summary
        assert "使用建议" in summary

    def test_format_summary_empty_tasks(self, assembler):
        """Test formatting summary with no tasks."""
        summary = assembler._format_summary([])

        assert summary == ""  # Should return empty string

    def test_assemble_full_context(self, assembler, sample_current_task, sample_historical_tasks):
        """Test assembling full context."""
        context = assembler.assemble(sample_current_task, sample_historical_tasks)

        # Check introduction
        assert "# 历史参考上下文" in context
        assert "PROJ-123" in context

        # Check tasks
        assert "## 相关任务 1: AUTH-001" in context
        assert "## 相关任务 2: AUTH-002" in context

        # Check summary
        assert "## 检索摘要" in context
        assert "共检索到 2 个相关历史任务" in context

    def test_assemble_filters_by_min_relevance(self):
        """Test that assemble filters tasks by min_relevance threshold."""
        from gbrain_retriever import HistoricalTask

        custom_config = ContextConfig(min_relevance_threshold=0.8)
        assembler = ContextAssembler(config=custom_config)

        tasks = [
            HistoricalTask(
                task_id="HIGH-001",
                description="High relevance task",
                code_pattern="def high():",
                decisions="High",
                review_comments="Good",
                file_structure="",
                relevance_score=0.85,
                retrieval_method="vector",
                tags=["high"],
                metadata={},
            ),
            HistoricalTask(
                task_id="LOW-001",
                description="Low relevance task",
                code_pattern="def low():",
                decisions="Low",
                review_comments="",
                file_structure="",
                relevance_score=0.4,  # Below threshold
                retrieval_method="vector",
                tags=["low"],
                metadata={},
            ),
        ]

        current_task = {"taskId": "TEST", "task": "Test task"}
        context = assembler.assemble(current_task, tasks)

        # Only high relevance task should be included
        assert "HIGH-001" in context
        assert "LOW-001" not in context

    def test_assemble_limits_max_tasks(self):
        """Test that assemble limits to max_tasks."""
        from gbrain_retriever import HistoricalTask

        custom_config = ContextConfig(max_tasks=2)
        assembler = ContextAssembler(config=custom_config)

        tasks = [
            HistoricalTask(
                task_id=f"TASK-{i:03d}",
                description=f"Task {i}",
                code_pattern=f"def task_{i}():",
                decisions=f"Decision {i}",
                review_comments="",
                file_structure="",
                relevance_score=0.9 - (i * 0.05),
                retrieval_method="vector",
                tags=[f"task{i}"],
                metadata={},
            )
            for i in range(1, 6)  # 5 tasks
        ]

        current_task = {"taskId": "TEST", "task": "Test task"}
        context = assembler.assemble(current_task, tasks)

        # Only top 2 tasks should be included
        assert "TASK-001" in context
        assert "TASK-002" in context
        assert "TASK-003" not in context
        assert "TASK-004" not in context
        assert "TASK-005" not in context

    def test_assemble_prioritizes_high_relevance(self):
        """Test that assemble sorts by relevance when prioritization is enabled."""
        from gbrain_retriever import HistoricalTask

        # Create tasks in random order
        tasks = [
            HistoricalTask(
                task_id="TASK-002",
                description="Task 2",
                code_pattern="def task_2():",
                decisions="Decision 2",
                review_comments="",
                file_structure="",
                relevance_score=0.7,
                retrieval_method="vector",
                tags=["task2"],
                metadata={},
            ),
            HistoricalTask(
                task_id="TASK-001",
                description="Task 1",
                code_pattern="def task_1():",
                decisions="Decision 1",
                review_comments="",
                file_structure="",
                relevance_score=0.9,
                retrieval_method="vector",
                tags=["task1"],
                metadata={},
            ),
            HistoricalTask(
                task_id="TASK-003",
                description="Task 3",
                code_pattern="def task_3():",
                decisions="Decision 3",
                review_comments="",
                file_structure="",
                relevance_score=0.8,
                retrieval_method="vector",
                tags=["task3"],
                metadata={},
            ),
        ]

        current_task = {"taskId": "TEST", "task": "Test task"}
        context = assembler.assemble(current_task, tasks)

        # Tasks should appear in order of relevance
        task_1_pos = context.find("TASK-001")
        task_2_pos = context.find("TASK-002")
        task_3_pos = context.find("TASK-003")

        assert task_1_pos < task_3_pos < task_2_pos

    def test_assemble_no_tasks(self, assembler, sample_current_task):
        """Test assembling context with no historical tasks."""
        context = assembler.assemble(sample_current_task, [])

        # Should still have introduction
        assert "# 历史参考上下文" in context
        assert "PROJ-123" in context

        # Should indicate no tasks found
        assert "未找到相关历史任务" in context

        # Should NOT have summary
        assert "## 检索摘要" not in context

    def test_assemble_compact_mode(self):
        """Test compact assembly mode."""
        from gbrain_retriever import HistoricalTask

        custom_config = ContextConfig(
            max_tasks=2,
            include_code_patterns=True,
            include_decisions=True,
            include_review_comments=False,  # Disabled in compact
            include_file_structure=False,
            prioritize_high_relevance=True,
            min_relevance_threshold=0.7,  # Higher threshold
        )
        assembler = ContextAssembler(config=custom_config)

        tasks = [
            HistoricalTask(
                task_id="TASK-001",
                description="Task 1",
                code_pattern="def task_1():",
                decisions="Decision 1",
                review_comments="Review comments",  # Should NOT be included
                file_structure="file/",  # Should NOT be included
                relevance_score=0.85,
                retrieval_method="vector",
                tags=["task1"],
                metadata={},
            ),
            HistoricalTask(
                task_id="TASK-002",
                description="Task 2",
                code_pattern="def task_2():",
                decisions="Decision 2",
                review_comments="Review comments 2",
                file_structure="file2/",
                relevance_score=0.6,  # Below threshold 0.7
                retrieval_method="vector",
                tags=["task2"],
                metadata={},
            ),
        ]

        current_task = {"taskId": "TEST", "task": "Test task"}
        context = assembler.assemble(current_task, tasks)

        # Check compact mode behavior
        assert "TASK-001" in context
        assert "TASK-002" not in context  # Filtered by threshold
        assert "Review comments" not in context  # Disabled in compact
        assert "file/" not in context  # Disabled in compact

    def test_assemble_compact_method(self, assembler, sample_current_task, sample_historical_tasks):
        """Test the assemble_compact convenience method."""
        context = assembler.assemble_compact(sample_current_task, sample_historical_tasks)

        # Should have introduction and tasks
        assert "# 历史参考上下文" in context
        assert "AUTH-001" in context

        # Should NOT have review comments (compact mode disables them)
        assert "Add rate limiting" not in context

    def test_save_context(self, assembler, tmp_path):
        """Test saving context to file."""
        context_text = "# Test Context\n\nThis is a test context."
        output_path = tmp_path / "test_context.md"

        assembler.save_context(context_text, output_path)

        assert output_path.exists()
        content = output_path.read_text(encoding='utf-8')
        assert content == context_text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
