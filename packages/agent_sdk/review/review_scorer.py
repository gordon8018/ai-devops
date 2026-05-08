"""Parse free-text LLM review output into a structured ReviewScore."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from packages.shared.domain.models import ReviewFinding

PASS_THRESHOLD = 85

_SCORE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(\d{1,3})\s*/\s*100\b"),
    re.compile(r"Score:\s*\**(\d{1,3})\**/100"),
    re.compile(r"总分[：:]\s*(\d{1,3})\s*/\s*100"),
    re.compile(r"\b(\d{1,2})\s*/\s*10\b"),
    re.compile(r"评分[：:]\s*(\d{1,3})"),
]

_SENTINEL_PASS = re.compile(r"ADVERSARIAL_RESULT\s*:\s*PASS", re.IGNORECASE)
_SENTINEL_FAIL = re.compile(r"ADVERSARIAL_RESULT\s*:\s*FAIL", re.IGNORECASE)

_SEVERITY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("critical", re.compile(r"\[CRITICAL\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)", re.DOTALL | re.IGNORECASE)),
    ("high",     re.compile(r"\[HIGH\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",     re.DOTALL | re.IGNORECASE)),
    ("medium",   re.compile(r"\[MEDIUM\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",   re.DOTALL | re.IGNORECASE)),
    ("low",      re.compile(r"\[LOW\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",      re.DOTALL | re.IGNORECASE)),
]


@dataclass(frozen=True)
class ReviewScore:
    score: int
    passed: bool
    findings: tuple[ReviewFinding, ...]
    raw_output: str
    sentinel_used: bool = False


class ReviewScorer:
    """Extract numeric score and structured findings from LLM reviewer output."""

    @staticmethod
    def parse(raw_output: str, subtask_id: str) -> ReviewScore:
        tail_lines = [l for l in raw_output.splitlines() if l.strip()][-10:]
        tail = "\n".join(tail_lines)

        sentinel_pass = bool(_SENTINEL_PASS.search(tail))
        sentinel_fail = bool(_SENTINEL_FAIL.search(tail))
        sentinel_used = sentinel_pass or sentinel_fail

        # Always extract numeric score regardless of sentinel presence
        score: int | None = None
        for pattern in _SCORE_PATTERNS:
            m = pattern.search(raw_output)
            if m:
                raw_val = int(m.group(1))
                score = raw_val * 10 if raw_val <= 10 else raw_val
                score = max(0, min(100, score))
                break

        findings = ReviewScorer._extract_findings(raw_output, subtask_id)

        if sentinel_used:
            # Sentinel is authoritative for pass/fail; numeric score is preserved for observability
            effective_score = score if score is not None else (100 if sentinel_pass else 0)
            passed = sentinel_pass and not sentinel_fail
            return ReviewScore(
                score=effective_score, passed=passed,
                findings=tuple(findings), raw_output=raw_output, sentinel_used=True,
            )

        if score is None:
            score = 0

        has_critical = any(f.severity == "critical" for f in findings)
        passed = (score >= PASS_THRESHOLD) and not has_critical

        return ReviewScore(score=score, passed=passed, findings=tuple(findings), raw_output=raw_output)

    @staticmethod
    def _extract_findings(raw_output: str, subtask_id: str) -> list[ReviewFinding]:
        findings: list[ReviewFinding] = []
        for severity, pattern in _SEVERITY_PATTERNS:
            for i, m in enumerate(pattern.finditer(raw_output)):
                findings.append(ReviewFinding(
                    finding_id=f"{subtask_id}-review-{severity}-{i}",
                    category="review",
                    severity=severity,
                    message=m.group(1).strip()[:500],
                    source_guardrail="AdversarialReview",
                ))
        return findings
