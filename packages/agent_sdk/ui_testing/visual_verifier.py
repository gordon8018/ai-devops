"""LLM visual verification of screenshots against definition_of_done."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from pathlib import Path

from agents import Agent, Runner

from packages.shared.domain.models import ReviewFinding

VISUAL_VERIFIER_SYSTEM_PROMPT = """\
You are a frontend QA engineer reviewing a screenshot of a web application.
Evaluate whether the screenshot meets the acceptance criteria.

## Output Format
- Score: XX/100
- [CRITICAL] / [HIGH] / [MEDIUM] / [LOW] issue descriptions
- End with: VISUAL_RESULT: PASS or VISUAL_RESULT: FAIL

Score >= 85 with no [CRITICAL] issues = PASS. Otherwise = FAIL.
"""

_SCORE_RE = re.compile(r"\b(\d{1,3})\s*/\s*100\b")
_SENTINEL_PASS = re.compile(r"VISUAL_RESULT\s*:\s*PASS", re.IGNORECASE)
_SENTINEL_FAIL = re.compile(r"VISUAL_RESULT\s*:\s*FAIL", re.IGNORECASE)
_SEVERITY_RE: list[tuple[str, re.Pattern]] = [
    ("critical", re.compile(r"\[CRITICAL\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)", re.DOTALL | re.IGNORECASE)),
    ("high",     re.compile(r"\[HIGH\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",     re.DOTALL | re.IGNORECASE)),
    ("medium",   re.compile(r"\[MEDIUM\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",   re.DOTALL | re.IGNORECASE)),
    ("low",      re.compile(r"\[LOW\](.+?)(?=\[(?:CRITICAL|HIGH|MEDIUM|LOW)\]|$)",      re.DOTALL | re.IGNORECASE)),
]

PASS_THRESHOLD = 85


@dataclass(frozen=True)
class UITestResult:
    passed: bool
    score: int
    findings: tuple[ReviewFinding, ...]
    screenshot_path: str
    raw_output: str


class VisualVerifier:
    @staticmethod
    async def verify(
        screenshot_path: str,
        definition_of_done: str,
        subtask_id: str,
        model: str = "claude-opus-4-6",
    ) -> UITestResult:
        try:
            image_data = base64.standard_b64encode(Path(screenshot_path).read_bytes()).decode()
            agent = Agent(
                name=f"{subtask_id}-visual-verifier",
                instructions=VISUAL_VERIFIER_SYSTEM_PROMPT,
                model=model,
                tools=[],
            )
            input_payload = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data,
                    },
                },
                {
                    "type": "text",
                    "text": (
                        f"## Definition of Done\n{definition_of_done}\n\n"
                        "Does the screenshot meet these criteria?"
                    ),
                },
            ]
            result = await Runner.run(starting_agent=agent, input=input_payload, max_turns=3)
            raw = str(result.final_output or "")
        except Exception as e:
            raw = f"VISUAL_RESULT: FAIL\n[HIGH] Visual verifier failed: {e}"

        return VisualVerifier._parse(raw, screenshot_path, subtask_id)

    @staticmethod
    def _parse(raw: str, screenshot_path: str, subtask_id: str) -> UITestResult:
        # Extract numeric score
        score = 0
        m = _SCORE_RE.search(raw)
        if m:
            score = max(0, min(100, int(m.group(1))))

        # Sentinel determines pass/fail
        sentinel_pass = bool(_SENTINEL_PASS.search(raw))
        sentinel_fail = bool(_SENTINEL_FAIL.search(raw))

        # Extract findings
        findings: list[ReviewFinding] = []
        for severity, pattern in _SEVERITY_RE:
            for i, fm in enumerate(pattern.finditer(raw)):
                findings.append(ReviewFinding(
                    finding_id=f"{subtask_id}-visual-{severity}-{i}",
                    category="ui_test",
                    severity=severity,
                    message=fm.group(1).strip()[:500],
                    source_guardrail="VisualVerifier",
                ))

        has_critical = any(f.severity == "critical" for f in findings)

        if sentinel_pass and not sentinel_fail:
            passed = not has_critical
        elif sentinel_fail:
            passed = False
        else:
            passed = (score >= PASS_THRESHOLD) and not has_critical

        return UITestResult(
            passed=passed,
            score=score,
            findings=tuple(findings),
            screenshot_path=screenshot_path,
            raw_output=raw,
        )
