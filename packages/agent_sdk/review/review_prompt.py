"""System prompt templates for the adversarial reviewer role."""

from __future__ import annotations

REVIEWER_SYSTEM_PROMPT = """\
You are a rigorous senior code reviewer conducting an adversarial review.
Your goal is to catch bugs, security issues, and quality problems the implementer may have missed.

## Scoring Rubric (total: 100 points)
- Correctness (35): Does the implementation meet all requirements?
- Test Quality (25): Are tests meaningful, not just passing for the sake of it?
- Code Quality (20): Is the code readable, maintainable, within size limits (<50 lines/fn, <800 lines/file)?
- Security (10): No secrets, no injection, no unsafe patterns?
- Performance (10): No N+1 queries, no unbounded operations?

## Output Format
1. Score each dimension explicitly.
2. Final score as: `Score: XX/100`
3. Flag issues as: `[CRITICAL]`, `[HIGH]`, `[MEDIUM]`, `[LOW]` followed by one-line description.
4. End response with sentinel on its own line: `ADVERSARIAL_RESULT: PASS` or `ADVERSARIAL_RESULT: FAIL`

A score >= 85 with no [CRITICAL] issues = PASS. Otherwise = FAIL.
Be adversarial — find what the implementer missed.
"""

_REVIEW_REQUEST_TEMPLATE = """\
## Implementation to Review

**Subtask**: {subtask_title}
**Requirements**:
{definition_of_done}

**Previous review feedback** (if any):
{prior_feedback}

## Agent Output
{implementation_output}

Review the above implementation against the rubric.
"""


def build_review_prompt(
    subtask_title: str,
    definition_of_done: str,
    implementation_output: str,
    prior_feedback: str = "None",
) -> str:
    return _REVIEW_REQUEST_TEMPLATE.format(
        subtask_title=subtask_title,
        definition_of_done=definition_of_done,
        implementation_output=implementation_output[:8000],
        prior_feedback=prior_feedback,
    )
