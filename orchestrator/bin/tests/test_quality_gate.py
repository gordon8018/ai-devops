#!/usr/bin/env python3
"""Unit tests for quality_gate.py"""

import sys
import os
import tempfile
import json
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from quality_gate import QualityGate, CodeReviewResult, QualityGateError
    from ralph_state import RalphState
except ImportError:
    from orchestrator.bin.quality_gate import QualityGate, CodeReviewResult, QualityGateError
    from orchestrator.bin.ralph_state import RalphState


def test_code_review_result():
    """Test CodeReviewResult class"""
    result = CodeReviewResult(score=8.5, passed=True, feedback=["Good code"], pr_number=123)
    assert result.score == 8.5
    assert result.passed is True
    assert len(result.feedback) == 1
    assert result.pr_number == 123
    
    data = result.to_dict()
    assert data["score"] == 8.5
    assert data["passed"] is True
    print("✓ test_code_review_result passed")


def test_quality_gate_init():
    """Test QualityGate initialization"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        gate = QualityGate(db_path)
        assert gate.state is not None
        assert gate.default_threshold == 8.0
        assert gate.max_review_attempts == 3
        print("✓ test_quality_gate_init passed")


def test_quality_gate_run_code_review():
    """Test running code review"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        db_path = tmpdir / "test.db"
        repo_dir = tmpdir / "repo"
        repo_dir.mkdir()
        
        # Create a dummy Python file
        (repo_dir / "test.py").write_text("print('hello')")
        
        gate = QualityGate(db_path)
        gate.state.create("test_task")
        
        result = gate.run_code_review("test_task", repo_dir)
        assert isinstance(result, CodeReviewResult)
        assert 0 <= result.score <= 10
        print("✓ test_quality_gate_run_code_review passed")


def test_quality_gate_feedback_generation():
    """Test feedback generation based on score"""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        gate = QualityGate(db_path)
        
        # High score feedback
        feedback = gate._generate_feedback(9.0, 8.0)
        assert "✓ Code review passed" in feedback[0]
        
        # Low score feedback
        feedback = gate._generate_feedback(6.0, 8.0)
        assert "✗ Code review score" in feedback[0]
        assert "refactoring" in feedback[1]
        
        print("✓ test_quality_gate_feedback_generation passed")


def run_all_tests():
    """Run all tests"""
    print("Running quality_gate tests...")
    print()
    
    test_code_review_result()
    test_quality_gate_init()
    test_quality_gate_run_code_review()
    test_quality_gate_feedback_generation()
    
    print()
    print("All quality_gate tests passed!")


if __name__ == "__main__":
    run_all_tests()
