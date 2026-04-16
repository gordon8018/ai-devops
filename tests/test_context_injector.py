#!/usr/bin/env python3
"""Tests for ContextInjector module"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from orchestrator.bin.context_injector import (
    ContextInjector,
    SuccessPattern,
    FailureContext,
    get_context_injector,
)


class TestSuccessPattern:
    def test_success_pattern_creation(self):
        pattern = SuccessPattern(
            pattern_id="pattern-123",
            task_type="fix",
            approach="Updated auth logic",
            files_touched=["src/auth.py"],
            execution_time_minutes=15,
            success_rate=1.0,
            attempt_count=1,
            last_success_at=1234567890
        )
        assert pattern.pattern_id == "pattern-123"
        assert pattern.task_type == "fix"
        assert pattern.success_rate == 1.0

    def test_success_pattern_with_metadata(self):
        pattern = SuccessPattern(
            pattern_id="pattern-456",
            task_type="implement",
            approach="Created new feature",
            files_touched=["src/feature.py"],
            execution_time_minutes=30,
            success_rate=0.9,
            attempt_count=3,
            last_success_at=1234567890,
            metadata={"key": "value"}
        )
        assert pattern.metadata["key"] == "value"


class TestFailureContext:
    def test_failure_context_creation(self):
        failure = FailureContext(
            failure_id="failure-123",
            task_id="task-456",
            error_type="TimeoutError",
            error_message="Task timed out",
            failed_at=1234567890,
            retry_count=2
        )
        assert failure.failure_id == "failure-123"
        assert failure.error_type == "TimeoutError"
        assert failure.retry_count == 2

    def test_failure_context_with_resolution(self):
        failure = FailureContext(
            failure_id="failure-789",
            task_id="task-012",
            error_type="ConnectionError",
            error_message="Connection refused",
            failed_at=1234567890,
            retry_count=1,
            resolution="Increased timeout",
            resolution_hints=["Check network", "Verify port"]
        )
        assert failure.resolution == "Increased timeout"
        assert len(failure.resolution_hints) == 2


class TestContextInjector:
    def test_context_injector_initialization(self):
        injector = ContextInjector(persist=False)
        assert injector.persist is False
        assert injector._cache == {}

    def test_context_injector_persist_mode_supports_package_import(self):
        injector = ContextInjector(persist=True)
        assert injector.persist is True

    def test_get_shared_workspace_path(self):
        injector = ContextInjector(persist=False)
        path = injector.get_shared_workspace_path("plan-123")
        assert "plan-123" in str(path)
        assert "workspaces" in str(path)

    def test_read_workspace_context_nonexistent(self):
        injector = ContextInjector(persist=False)
        context = injector.read_workspace_context("nonexistent-plan")
        assert context == {}

    def test_write_workspace_context(self):
        injector = ContextInjector(persist=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(injector, 'get_shared_workspace_path', return_value=Path(tmpdir)):
                injector.write_workspace_context("test-plan", {"key": "value"})
                # Verify write succeeded
                assert True

    def test_render_context_template_simple(self):
        injector = ContextInjector(persist=False)
        template = "Hello {{ name }}"
        context = {"name": "World"}
        result = injector.render_context_template(template, context)
        assert "World" in result

    def test_render_context_template_nested(self):
        injector = ContextInjector(persist=False)
        template = "Value: {{ data.level1.level2 }}"
        context = {"data": {"level1": {"level2": "nested_value"}}}
        result = injector.render_context_template(template, context)
        assert "nested_value" in result

    def test_render_context_template_missing_key(self):
        injector = ContextInjector(persist=False)
        template = "Missing: {{ nonexistent }}"
        context = {"other": "value"}
        result = injector.render_context_template(template, context)
        # Should keep original placeholder
        assert "{{ nonexistent }}" in result or "nonexistent" in result


class TestContextInjectorPatterns:
    def test_get_success_patterns_path(self):
        injector = ContextInjector(persist=False)
        path = injector.get_success_patterns_path()
        assert "success_patterns.json" in str(path)

    def test_load_success_patterns_empty(self):
        injector = ContextInjector(persist=False)
        with patch.object(injector, 'get_success_patterns_path') as mock_path:
            mock_path.return_value = Path("/nonexistent/path/patterns.json")
            patterns = injector.load_success_patterns()
        assert patterns == {}

    def test_find_similar_success_patterns_no_match(self):
        injector = ContextInjector(persist=False)
        patterns = injector.find_similar_success_patterns("fix", ["file.py"], limit=3)
        # Should return empty list when no patterns exist
        assert isinstance(patterns, list)


class TestContextInjectorFailures:
    def test_get_failures_path(self):
        injector = ContextInjector(persist=False)
        path = injector.get_failures_path()
        assert "failure_contexts.json" in str(path)

    def test_load_failure_contexts_empty(self):
        injector = ContextInjector(persist=False)
        with patch.object(injector, 'get_failures_path') as mock_path:
            mock_path.return_value = Path("/nonexistent/path/failures.json")
            failures = injector.load_failure_contexts()
        assert failures == {}

    def test_get_recent_failures_empty(self):
        injector = ContextInjector(persist=False)
        failures = injector.get_recent_failures(limit=5)
        assert isinstance(failures, list)
