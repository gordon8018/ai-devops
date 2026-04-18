"""Input guardrails for agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuardrailResult:
    tripwire_triggered: bool
    message: str = ""
    warnings: tuple[str, ...] = ()


_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub Token", re.compile(r"ghp_[a-zA-Z0-9]{36}")),
    ("GitHub OAuth", re.compile(r"gho_[a-zA-Z0-9]{36}")),
    ("Private Key Header", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("Generic API Key", re.compile(r"(?:api[_-]?key|apikey)\s*[:=]\s*['\"][a-zA-Z0-9]{20,}", re.IGNORECASE)),
    ("Generic Secret", re.compile(r"(?:secret|password|passwd|pwd)\s*[:=]\s*['\"][^\s'\"]{8,}", re.IGNORECASE)),
    ("Slack Token", re.compile(r"xox[baprs]-[a-zA-Z0-9-]+")),
]


class BoundaryGuard:
    @staticmethod
    def check(constraints: dict, definition_of_done: tuple[str, ...]) -> GuardrailResult:
        issues: list[str] = []
        if not constraints:
            issues.append("constraints dict is empty")
        if not constraints.get("allowedPaths"):
            issues.append("allowedPaths is missing or empty")
        if not definition_of_done:
            issues.append("definition_of_done is empty")
        if issues:
            return GuardrailResult(tripwire_triggered=True, message=f"Boundary check failed: {'; '.join(issues)}")
        return GuardrailResult(tripwire_triggered=False)


class SensitiveDataGuard:
    @staticmethod
    def check(text: str) -> GuardrailResult:
        warnings: list[str] = []
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                warnings.append(f"Potential {name} detected in input")
        return GuardrailResult(tripwire_triggered=False, warnings=tuple(warnings))
