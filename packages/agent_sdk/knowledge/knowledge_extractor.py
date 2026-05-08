"""LLM call to extract structured reusable knowledge from agent output."""

from __future__ import annotations

import json
from dataclasses import dataclass

from agents import Agent, Runner

EXTRACTION_SYSTEM_PROMPT = """\
You are a knowledge distillation assistant. Given an agent's implementation output, extract only:
1. Reusable patterns (things that worked well and should be repeated)
2. Gotchas (traps, non-obvious behaviors, things to avoid)
3. Decisions (architectural or design choices made and why)

Format output as JSON:
{
  "patterns": ["..."],
  "gotchas":  ["..."],
  "decisions": ["..."]
}

Be specific and concrete. Omit generic advice. Each entry <= 150 chars.
Max 5 items per category. Output ONLY the JSON object.
"""


@dataclass(frozen=True)
class ExtractedKnowledge:
    patterns: tuple[str, ...]
    gotchas: tuple[str, ...]
    decisions: tuple[str, ...]

    def is_empty(self) -> bool:
        return not (self.patterns or self.gotchas or self.decisions)


class KnowledgeExtractor:
    """Call an LLM to extract structured knowledge from implementation output."""

    @staticmethod
    async def extract(
        implementation_output: str,
        subtask_title: str,
        extractor_model: str = "claude-sonnet-4-6",
    ) -> ExtractedKnowledge:
        agent = Agent(
            name="knowledge-extractor",
            instructions=EXTRACTION_SYSTEM_PROMPT,
            model=extractor_model,
            tools=[],
        )
        prompt = (
            f"Subtask: {subtask_title}\n\n"
            f"Implementation output:\n{implementation_output[:6000]}"
        )

        try:
            result = await Runner.run(starting_agent=agent, input=prompt, max_turns=3)
            raw = str(result.final_output or "").strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                parts = raw.split("```")
                # parts[1] is content between first pair of fences
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            data = json.loads(raw)
            return ExtractedKnowledge(
                patterns=tuple(str(x)[:150] for x in data.get("patterns", [])[:5]),
                gotchas=tuple(str(x)[:150] for x in data.get("gotchas", [])[:5]),
                decisions=tuple(str(x)[:150] for x in data.get("decisions", [])[:5]),
            )
        except Exception:
            return ExtractedKnowledge(patterns=(), gotchas=(), decisions=())
