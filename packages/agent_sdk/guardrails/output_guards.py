"""Output guardrails for agent execution results."""

from __future__ import annotations

import re
from dataclasses import dataclass

from packages.agent_sdk.guardrails.input_guards import _SECRET_PATTERNS


@dataclass(frozen=True)
class SecretLeakResult:
    tripwire_triggered: bool
    message: str = ""


@dataclass(frozen=True)
class CodeSafetyResult:
    tripwire_triggered: bool = False
    risks: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForbiddenPathResult:
    tripwire_triggered: bool
    message: str = ""
    violations: tuple[str, ...] = ()


_DANGEROUS_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("eval() usage", re.compile(r"\beval\s*\(")),
    ("exec() usage", re.compile(r"\bexec\s*\(")),
    ("shell=True in subprocess", re.compile(r"shell\s*=\s*True")),
    ("rm -rf command", re.compile(r"rm\s+-rf\s")),
    ("chmod 777", re.compile(r"chmod\s+777")),
]


class SecretLeakGuard:
    @staticmethod
    def check(text: str) -> SecretLeakResult:
        for name, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                return SecretLeakResult(tripwire_triggered=True, message=f"Secret leak detected: {name}")
        return SecretLeakResult(tripwire_triggered=False)


class CodeSafetyGuard:
    @staticmethod
    def check(text: str) -> CodeSafetyResult:
        risks = tuple(name for name, pattern in _DANGEROUS_PATTERNS if pattern.search(text))
        return CodeSafetyResult(risks=risks)


class ForbiddenPathGuard:
    @staticmethod
    def check(written_paths: list[str], forbidden_paths: list[str]) -> ForbiddenPathResult:
        violations = tuple(
            f"{w} violates {f}" for w in written_paths for f in forbidden_paths
            if w.startswith(f) or w == f
        )
        if violations:
            return ForbiddenPathResult(tripwire_triggered=True, message=f"{len(violations)} violations", violations=violations)
        return ForbiddenPathResult(tripwire_triggered=False)
