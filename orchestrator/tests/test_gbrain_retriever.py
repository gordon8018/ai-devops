#!/usr/bin/env python3
"""
Unit tests for gbrain_retriever.py
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

from gbrain_retriever import (
    GbrainRetriever,
    GbrainRetrieverError,
    SearchStrategy,
    HistoricalTask,
)


class TestGbrainRetriever:
    """Test suite for GbrainRetriever class."""

    @pytest.fixture
    def retriever(self):
        """Create a GbrainRetriever instance for testing."""
        return GbrainRetriever(top_n=3, min_relevance=0.5)

    @pytest.fixture
    def sample_task_spec(self):
        """Sample TaskSpec for testing."""
        return {
            "taskId": "PROJ-123",
            "task": "Implement user authentication",
            "userStories": [
                "Create login endpoint",
                "Add JWT token validation",
            ],
            "acceptanceCriteria": [
                "Login returns JWT on success",
                "Validation checks token format",
            ],
            "repo": "my-org/my-repo",
        }

    @pytest.fixture
    def sample_gbrain_response(self):
        """Sample gbrain search response."""
        return {
            "success": True,
            "returncode": 0,
            "data": {
                "results": [
                    {
                        "content": {
                            "description": "Previous authentication task",
                            "code_pattern": "def authenticate(username, password):",
                            "decisions": "Use JWT for stateless auth",
                            "review_comments": "Add rate limiting",
                            "file_structure": "auth/\n  login.py\n  jwt.py",
                        },
                        "tags": ["AUTH-001", "project:my-repo", "type:feature"],
                        "metadata": {"task_id": "AUTH-001"},
                        "score": 0.85,
                    },
                    {
                        "content": {
                            "description": "Session management task",
                            "code_pattern": "class SessionManager:",
                            "decisions": "Use Redis for session storage",
                            "review_comments": "Good implementation",
                            "file_structure": "session/\n  manager.py",
                        },
                        "tags": ["AUTH-002", "project:my-repo", "type:feature"],
                        "metadata": {"task_id": "AUTH-002"},
                        "score": 0.72,
                    },
                ],
            },
            "stderr": "",
        }

    def test_initialization(self, retriever):
        """Test retriever initialization."""
        assert retriever.top_n == 3
        assert retriever.min_relevance == 0.5
        assert retriever.default_strategy == SearchStrategy.HYBRID

    def test_extract_keywords_from_task_spec(self, retriever, sample_task_spec):
        """Test keyword extraction from TaskSpec."""
        keywords = retriever._extract_keywords_from_task_spec(sample_task_spec)

        # Check that keywords are extracted
        assert len(keywords) > 0
        assert "authentication" in keywords
        assert "jwt" in keywords.lower()

    def test_keyword_search_success(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test successful keyword search."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            results = retriever._keyword_search(sample_task_spec)

            assert len(results) > 0
            assert results[0]["task_id"] == "AUTH-001"
            assert results[0]["relevance_score"] == 0.7  # Default for keyword search
            assert results[0]["retrieval_method"] == "keyword"

    def test_keyword_search_failure(self, retriever, sample_task_spec):
        """Test keyword search failure."""
        error_response = {
            "success": False,
            "error": "Search failed",
        }

        with patch.object(retriever, '_run_gbrain_cmd', return_value=error_response):
            with pytest.raises(GbrainRetrieverError):
                retriever._keyword_search(sample_task_spec)

    def test_vector_search_success(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test successful vector search."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            results = retriever._vector_search(sample_task_spec)

            assert len(results) > 0
            assert results[0]["task_id"] == "AUTH-001"
            assert results[0]["relevance_score"] == 0.85
            assert results[0]["retrieval_method"] == "vector"

    def test_vector_search_fallback(self, retriever, sample_task_spec):
        """Test vector search falls back gracefully when not available."""
        error_response = {
            "success": False,
            "error": "Vector search not available",
        }

        with patch.object(retriever, '_run_gbrain_cmd', return_value=error_response):
            results = retriever._vector_search(sample_task_spec)

            assert len(results) == 0  # Should return empty list, not raise error

    def test_hybrid_search(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test hybrid search combining keyword and vector results."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            results = retriever._hybrid_search(sample_task_spec)

            assert len(results) > 0
            # Hybrid should average scores when both methods find same task
            # Check that retrieval method is marked as hybrid
            assert results[0]["retrieval_method"] == "hybrid"

    def test_retrieve_with_keyword_strategy(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test retrieve with keyword strategy."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            tasks = retriever.retrieve(sample_task_spec, strategy=SearchStrategy.KEYWORD)

            assert len(tasks) > 0
            assert all(isinstance(t, HistoricalTask) for t in tasks)
            assert all(t.retrieval_method == "keyword" for t in tasks)

    def test_retrieve_with_vector_strategy(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test retrieve with vector strategy."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            tasks = retriever.retrieve(sample_task_spec, strategy=SearchStrategy.VECTOR)

            assert len(tasks) > 0
            assert all(isinstance(t, HistoricalTask) for t in tasks)
            assert all(t.retrieval_method == "vector" for t in tasks)

    def test_retrieve_with_hybrid_strategy(self, retriever, sample_task_spec, sample_gbrain_response):
        """Test retrieve with hybrid strategy."""
        with patch.object(retriever, '_run_gbrain_cmd', return_value=sample_gbrain_response):
            tasks = retriever.retrieve(sample_task_spec, strategy=SearchStrategy.HYBRID)

            assert len(tasks) > 0
            assert all(isinstance(t, HistoricalTask) for t in tasks)

    def test_retrieve_filters_by_min_relevance(self, retriever, sample_task_spec):
        """Test that retrieve filters results by min_relevance threshold."""
        low_relevance_response = {
            "success": True,
            "returncode": 0,
            "data": {
                "results": [
                    {
                        "content": {
                            "description": "Low relevance task",
                            "code_pattern": "def low_relevance():",
                            "decisions": "Not relevant",
                            "review_comments": "",
                            "file_structure": "",
                        },
                        "tags": ["LOW-001"],
                        "metadata": {},
                        "score": 0.3,  # Below min_relevance of 0.5
                    },
                ],
            },
            "stderr": "",
        }

        with patch.object(retriever, '_run_gbrain_cmd', return_value=low_relevance_response):
            tasks = retriever.retrieve(sample_task_spec, strategy=SearchStrategy.VECTOR)

            # Should filter out low relevance tasks
            assert len(tasks) == 0

    def test_historical_task_to_dict(self):
        """Test HistoricalTask serialization."""
        task = HistoricalTask(
            task_id="TEST-001",
            description="Test task",
            code_pattern="def test():",
            decisions="Test decision",
            review_comments="Good",
            file_structure="test.py",
            relevance_score=0.85,
            retrieval_method="vector",
            tags=["test"],
            metadata={},
        )

        task_dict = task.to_dict()

        assert task_dict["task_id"] == "TEST-001"
        assert task_dict["relevance_score"] == 0.85
        assert isinstance(task_dict, dict)

    def test_retrieve_by_task_id(self, retriever):
        """Test retrieving a specific task by ID."""
        task_response = {
            "success": True,
            "returncode": 0,
            "data": {
                "content": {
                    "description": "Specific task",
                    "code_pattern": "def specific():",
                    "decisions": "Specific decision",
                    "review_comments": "Good",
                    "file_structure": "specific.py",
                },
                "tags": ["SPEC-001"],
                "metadata": {"task_id": "SPEC-001"},
            },
            "stderr": "",
        }

        with patch.object(retriever, '_run_gbrain_cmd', return_value=task_response):
            task = retriever.retrieve_by_task_id("SPEC-001")

            assert task is not None
            assert task.task_id == "SPEC-001"
            assert isinstance(task, HistoricalTask)

    def test_retrieve_by_task_id_not_found(self, retriever):
        """Test retrieving a non-existent task by ID."""
        not_found_response = {
            "success": True,
            "returncode": 0,
            "data": {},  # No content
            "stderr": "",
        }

        with patch.object(retriever, '_run_gbrain_cmd', return_value=not_found_response):
            task = retriever.retrieve_by_task_id("NONEXISTENT")

            assert task is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
