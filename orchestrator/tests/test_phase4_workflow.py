#!/usr/bin/env python3
"""
End-to-end tests for Phase 4+ workflow
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

from gbrain_retriever import GbrainRetriever, HistoricalTask, SearchStrategy
from context_assembler import ContextAssembler
from retrieval_feedback import RetrievalFeedback


class TestPhase4Workflow:
    """Test suite for complete Phase 4+ workflow."""

    @pytest.fixture
    def sample_task_spec(self):
        """Sample TaskSpec for testing."""
        return {
            "taskId": "PROJ-123",
            "task": "Implement user authentication with JWT",
            "userStories": [
                "Create login endpoint",
                "Implement JWT token generation",
                "Add token validation middleware",
            ],
            "acceptanceCriteria": [
                "Login returns JWT on successful authentication",
                "JWT tokens expire after 1 hour",
                "Validation rejects invalid or expired tokens",
            ],
            "repo": "my-org/my-repo",
        }

    @pytest.fixture
    def sample_historical_tasks(self):
        """Sample historical tasks for testing."""
        return [
            HistoricalTask(
                task_id="AUTH-001",
                description="Implemented JWT-based authentication",
                code_pattern="def authenticate(username, password):\n    user = db.find_user(username)\n    if verify_password(password, user.password_hash):\n        return jwt.encode(...)",
                decisions="Use JWT for stateless authentication. Store secrets in environment variables.",
                review_comments="Good implementation. Consider adding refresh tokens. Add rate limiting to prevent brute force attacks.",
                file_structure="auth/\n  login.py\n  jwt.py\n  middleware.py",
                relevance_score=0.92,
                retrieval_method="hybrid",
                tags=["AUTH-001", "project:my-repo", "type:feature", "jwt", "authentication"],
                metadata={"executed_at": "2024-03-15", "duration_seconds": 7200},
            ),
            HistoricalTask(
                task_id="AUTH-002",
                description="Session management with Redis",
                code_pattern="class SessionManager:\n    def __init__(self, redis_client):\n        self.redis = redis_client",
                decisions="Use Redis for session storage with TTL. Implement session cleanup.",
                review_comments="Good structure. Consider using Redis transactions for atomic operations.",
                file_structure="session/\n  manager.py\n  store.py",
                relevance_score=0.78,
                retrieval_method="hybrid",
                tags=["AUTH-002", "project:my-repo", "type:feature", "session"],
                metadata={"executed_at": "2024-03-20", "duration_seconds": 5400},
            ),
            HistoricalTask(
                task_id="SEC-001",
                description="Password hashing and verification",
                code_pattern="def hash_password(password):\n    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())",
                decisions="Use bcrypt for password hashing. Store only hashed passwords.",
                review_comments="Correct use of bcrypt. Good practice.",
                file_structure="security/\n  password.py",
                relevance_score=0.85,
                retrieval_method="keyword",
                tags=["SEC-001", "project:my-repo", "type:security"],
                metadata={"executed_at": "2024-03-10", "duration_seconds": 3600},
            ),
        ]

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir)

    def test_complete_retrieval_and_assembly_workflow(
        self, sample_task_spec, sample_historical_tasks, temp_dir
    ):
        """Test complete workflow from retrieval to context assembly."""
        # Step 1: Setup retriever
        gbrain_dir = temp_dir / "gbrain"
        gbrain_dir.mkdir()

        retriever = GbrainRetriever(gbrain_dir=str(gbrain_dir), top_n=3, min_relevance=0.5)

        # Mock the gbrain command to return sample data
        gbrain_response = {
            "success": True,
            "returncode": 0,
            "data": {
                "results": [
                    {
                        "content": {
                            "description": t.description,
                            "code_pattern": t.code_pattern,
                            "decisions": t.decisions,
                            "review_comments": t.review_comments,
                            "file_structure": t.file_structure,
                        },
                        "tags": t.tags,
                        "metadata": {"task_id": t.task_id},
                        "score": t.relevance_score,
                    }
                    for t in sample_historical_tasks
                ],
            },
            "stderr": "",
        }

        # Step 2: Retrieve historical tasks
        with patch.object(retriever, '_run_gbrain_cmd', return_value=gbrain_response):
            retrieved_tasks = retriever.retrieve(sample_task_spec)

        # Verify retrieval
        assert len(retrieved_tasks) == 3
        assert all(isinstance(t, HistoricalTask) for t in retrieved_tasks)
        assert retrieved_tasks[0].task_id == "AUTH-001"
        assert retrieved_tasks[0].relevance_score == 0.92

        # Step 3: Assemble context
        assembler = ContextAssembler()
        context = assembler.assemble(sample_task_spec, retrieved_tasks)

        # Verify context structure
        assert "# 历史参考上下文" in context
        assert "PROJ-123" in context
        assert "Implement user authentication with JWT" in context

        # Verify all tasks are included
        for task in sample_historical_tasks:
            assert task.task_id in context
            assert task.description in context

        # Verify implementation patterns are included
        assert "def authenticate(username, password):" in context
        assert "class SessionManager:" in context
        assert "def hash_password(password):" in context

        # Verify design decisions are included
        assert "Use JWT for stateless authentication" in context
        assert "Use Redis for session storage" in context
        assert "Use bcrypt for password hashing" in context

        # Verify review comments are included
        assert "Consider adding refresh tokens" in context
        assert "Add rate limiting" in context
        assert "Consider using Redis transactions" in context

        # Verify summary is present
        assert "## 检索摘要" in context
        assert "共检索到 3 个相关历史任务" in context

    def test_feedback_recording_workflow(
        self, sample_task_spec, sample_historical_tasks, temp_dir
    ):
        """Test feedback recording and quality assessment workflow."""
        # Setup feedback system
        feedback_dir = temp_dir / "feedback"
        feedback_dir.mkdir()
        feedback = RetrievalFeedback(feedback_dir=str(feedback_dir))

        # Step 1: Record retrieval
        retrieved_tasks_dict = [t.to_dict() for t in sample_historical_tasks]
        record_result = feedback.record_retrieval(
            task_id=sample_task_spec["taskId"],
            retrieved_tasks=retrieved_tasks_dict,
            context_injected=True,
            execution_metrics={
                "iterations": 5,
                "duration_seconds": 3600,
                "quality_score": 8.5,
            },
        )

        # Verify recording
        assert record_result["success"] == True
        assert record_result["task_id"] == "PROJ-123"
        assert record_result["num_retrieved_tasks"] == 3
        assert (feedback_dir / "PROJ-123_feedback.json").exists()

        # Step 2: Update usage feedback
        update_result = feedback.update_usage_feedback(
            task_id=sample_task_spec["taskId"],
            ralph_used_context=True,
            user_rating=4,
            feedback_notes="Historical context was very helpful for JWT implementation",
        )

        # Verify update
        assert update_result["success"] == True

        # Step 3: Evaluate retrieval quality
        quality_assessment = feedback.evaluate_retrieval_quality(sample_task_spec["taskId"])

        # Verify quality assessment
        assert quality_assessment["task_id"] == "PROJ-123"
        assert quality_assessment["num_retrieved_tasks"] == 3
        assert quality_assessment["context_injected"] == True
        assert quality_assessment["ralph_used_context"] == True
        assert quality_assessment["user_rating"] == 4
        assert quality_assessment["feedback_notes"] == "Historical context was very helpful for JWT implementation"
        assert "avg_relevance_score" in quality_assessment
        assert "quality_tier" in quality_assessment
        assert "overall_quality_score" in quality_assessment

        # Verify quality tier calculation
        avg_relevance = sum(t.relevance_score for t in sample_historical_tasks) / len(sample_historical_tasks)
        assert abs(quality_assessment["avg_relevance_score"] - avg_relevance) < 0.01

        # High tier (avg relevance > 0.8)
        assert quality_assessment["quality_tier"] == "high"

        # Overall quality score should be high
        assert quality_assessment["overall_quality_score"] > 0.7

    def test_compact_mode_workflow(
        self, sample_task_spec, sample_historical_tasks, temp_dir
    ):
        """Test compact mode workflow for space-constrained scenarios."""
        # Use compact assembly
        assembler = ContextAssembler()
        compact_context = assembler.assemble_compact(sample_task_spec, sample_historical_tasks)

        # Verify compact context structure
        assert "# 历史参考上下文" in compact_context
        assert "PROJ-123" in compact_context

        # Should have fewer tasks (compact mode limits to 2)
        # And filters by higher relevance threshold (0.7)
        high_relevance_tasks = [t for t in sample_historical_tasks if t.relevance_score >= 0.7]
        assert len(high_relevance_tasks) >= 2

        # Should NOT include review comments (compact mode disables them)
        assert "Consider adding refresh tokens" not in compact_context

        # Should include code patterns and decisions
        assert "def authenticate(username, password):" in compact_context
        assert "Use JWT for stateless authentication" in compact_context

    def test_retrieval_with_different_strategies(
        self, sample_task_spec, sample_historical_tasks, temp_dir
    ):
        """Test retrieval with different search strategies."""
        gbrain_dir = temp_dir / "gbrain"
        gbrain_dir.mkdir()

        # Create gbrain response for keyword search
        keyword_response = {
            "success": True,
            "returncode": 0,
            "data": {
                "results": [
                    {
                        "content": {
                            "description": t.description,
                            "code_pattern": t.code_pattern,
                            "decisions": t.decisions,
                            "review_comments": t.review_comments,
                            "file_structure": t.file_structure,
                        },
                        "tags": t.tags,
                        "metadata": {"task_id": t.task_id},
                    }
                    for t in sample_historical_tasks[:2]  # Fewer results for keyword
                ],
            },
            "stderr": "",
        }

        # Test keyword strategy
        retriever = GbrainRetriever(gbrain_dir=str(gbrain_dir), top_n=5, min_relevance=0.0)
        with patch.object(retriever, '_run_gbrain_cmd', return_value=keyword_response):
            keyword_results = retriever.retrieve(sample_task_spec, strategy=SearchStrategy.KEYWORD)

        # Verify keyword results
        assert len(keyword_results) >= 2
        assert all(t.retrieval_method == "keyword" for t in keyword_results)

        # Test that different strategies can be used
        # (In a real scenario, vector and hybrid would return different results)

    def test_quality_report_generation(self, sample_task_spec, sample_historical_tasks, temp_dir):
        """Test generation of quality report across multiple feedback records."""
        feedback_dir = temp_dir / "feedback"
        feedback_dir.mkdir()
        feedback = RetrievalFeedback(feedback_dir=str(feedback_dir))

        # Record multiple retrieval events
        tasks = [sample_task_spec]
        for i, historical_tasks in enumerate([sample_historical_tasks, sample_historical_tasks[:2]]):
            task_spec = {"taskId": f"PROJ-{i+100}", "task": f"Task {i+100}"}
            retrieved_tasks_dict = [t.to_dict() for t in historical_tasks]
            feedback.record_retrieval(
                task_id=task_spec["taskId"],
                retrieved_tasks=retrieved_tasks_dict,
                context_injected=True,
                execution_metrics={"iterations": 5, "duration_seconds": 3600},
            )

        # Generate quality report
        report = feedback.generate_quality_report()

        # Verify report structure
        assert "total_retrievals" in report
        assert report["total_retrievals"] == 2
        assert "avg_relevance_score" in report
        assert "quality_distribution" in report
        assert "recommendations" in report

        # Verify quality distribution
        assert "high" in report["quality_distribution"]
        assert "medium" in report["quality_distribution"]
        assert "low" in report["quality_distribution"]

    def test_context_file_persistence(self, sample_task_spec, sample_historical_tasks, temp_dir):
        """Test saving context to file and reusing it."""
        # Assemble context
        assembler = ContextAssembler()
        context = assembler.assemble(sample_task_spec, sample_historical_tasks)

        # Save to file
        context_file = temp_dir / "context.md"
        assembler.save_context(context, context_file)

        # Verify file exists and has correct content
        assert context_file.exists()
        file_content = context_file.read_text(encoding='utf-8')
        assert file_content == context
        assert "# 历史参考上下文" in file_content

        # Verify it can be reused
        assert "PROJ-123" in file_content
        assert "AUTH-001" in file_content

    def test_integration_with_task_to_prd(self, sample_task_spec, sample_historical_tasks, temp_dir):
        """Test integration with task_to_prd.py (context field in prd.json)."""
        # Assemble context
        assembler = ContextAssembler()
        context = assembler.assemble(sample_task_spec, sample_historical_tasks)

        # Import task_to_prd function
        from task_to_prd import task_spec_to_prd_json

        # Convert task spec to PRD with context
        prd = task_spec_to_prd_json(sample_task_spec, historical_context=context)

        # Verify PRD structure
        assert "context" in prd
        assert prd["context"] == context
        assert "# 历史参考上下文" in prd["context"]
        assert "PROJ-123" in prd["context"]

        # Verify other PRD fields are intact
        assert prd["project"] == "my-repo"
        assert prd["aiDevopsTaskId"] == "PROJ-123"
        assert len(prd["userStories"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
