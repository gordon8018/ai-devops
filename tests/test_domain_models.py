import pytest

from packages.shared.domain.models import ReviewFinding


def test_review_finding_creation():
    """ReviewFinding should be a frozen dataclass with required fields."""
    finding = ReviewFinding(
        finding_id="rf-001",
        category="security",
        severity="high",
        message="Detected hardcoded API key",
        source_guardrail="SecretLeakGuard",
    )
    assert finding.finding_id == "rf-001"
    assert finding.category == "security"
    assert finding.severity == "high"
    assert finding.message == "Detected hardcoded API key"
    assert finding.source_guardrail == "SecretLeakGuard"
    assert finding.metadata == {}


def test_review_finding_is_frozen():
    """ReviewFinding should be immutable."""
    finding = ReviewFinding(
        finding_id="rf-001", category="security", severity="high",
        message="test", source_guardrail="TestGuard",
    )
    with pytest.raises(AttributeError):
        finding.severity = "low"


def test_review_finding_with_metadata():
    """ReviewFinding should accept optional metadata."""
    finding = ReviewFinding(
        finding_id="rf-002", category="safety", severity="medium",
        message="eval() detected", source_guardrail="CodeSafetyGuard",
        metadata={"line": 42, "file": "main.py"},
    )
    assert finding.metadata == {"line": 42, "file": "main.py"}
