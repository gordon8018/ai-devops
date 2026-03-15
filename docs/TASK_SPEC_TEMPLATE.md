# TASK_SPEC_TEMPLATE.md

Use this file as the **only execution contract** for ai-devops / Zoe scoped coding tasks.

Rule: do **not** dispatch from raw free-form text when the repo is large or scope is risky. Fill this template first.

---

## 1) Task Title
Short, specific title.

Example:
`Implement Sonos full-results matching only inside sonos-pure-play skill`

---

## 2) Goal / Desired Outcome
Describe the result you want, not just the area to edit.

Required:
- what should work after completion
- what success looks like for a human reviewer
- what must not happen

Example:
- Improve Sonos result matching and playback flow.
- Keep all work inside `skills/sonos-pure-play/**`.
- Do not edit unrelated browser extension, docs, tests, or root scripts.

---

## 3) Repo
Required.

Example:
`nakamoto_jason/clawd`

---

## 4) Working Root
Required. The narrowest safe working root.

Example:
`/Users/nakamoto_jason/clawd`

---

## 5) Allowed Paths (required)
List the **only** paths the agent may edit.
Use absolute paths when possible.

Example:
```json
[
  "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/**"
]
```

---

## 6) Forbidden Paths (required)
List paths the agent must never edit.
Include common drift areas.

Example:
```json
[
  "/Users/nakamoto_jason/clawd/src/**",
  "/Users/nakamoto_jason/clawd/extensions/**",
  "/Users/nakamoto_jason/clawd/projects/ai-devops/**",
  "/Users/nakamoto_jason/clawd/projects/tests/**",
  "/Users/nakamoto_jason/clawd/docs/**",
  "/Users/nakamoto_jason/clawd/scripts/**"
]
```

---

## 7) Must Touch (required)
List files that must be touched for the task to count as valid.
If none of these are touched, treat the run as failure.

Example:
```json
[
  "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/query-planner.mjs",
  "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/web-flow.mjs"
]
```

---

## 8) Prefer Create / Prefer Edit (optional but recommended)
Use this to guide file creation or bias edits toward the right files.

Example:
```json
{
  "preferCreate": [
    "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/candidate-ranker.mjs",
    "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/playback-memory.mjs"
  ],
  "preferEdit": [
    "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/query-planner.mjs",
    "/Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/web-flow.mjs"
  ]
}
```

---

## 9) Definition of Done (required)
Write human-reviewable completion criteria.

Example:
- Search intent resolves to better candidate matching.
- Playback flow uses the correct Sonos detail/result action.
- No edits outside `skills/sonos-pure-play/**`.
- `query-planner.mjs` and/or `web-flow.mjs` are genuinely updated.
- Relevant tests or smoke checks pass.

---

## 10) Validation / Test Plan (required)
List exact checks the agent should run.

Example:
```text
- Run targeted tests for the modified Sonos files.
- If no formal tests exist, run a local smoke check.
- Report exact commands and results.
```

---

## 11) First-Step File Plan (required)
Before coding, the agent must first state:
- which files it plans to edit
- why each file is in scope
- why every file is inside Allowed Paths

If it cannot produce this cleanly, it must stop.

---

## 12) Failure Rules (required)
The agent must stop and fail if any of these happen:

- planned files fall outside Allowed Paths
- touched files fall outside Allowed Paths
- any Forbidden Path is modified
- none of the Must Touch files are edited
- the agent wants to change unrelated docs/tests/scripts just because they were discovered in the repo

---

# Copy/Paste Task Spec Example

```yaml
title: Implement Sonos full-results matching only inside sonos-pure-play skill

goal: |
  Improve Sonos result matching and playback behavior for the sonos-pure-play skill.
  Keep all work strictly inside the sonos-pure-play skill directory.
  Do not edit unrelated browser-extension, docs, tests, or repo-root script files.

repo: nakamoto_jason/clawd
workingRoot: /Users/nakamoto_jason/clawd

allowedPaths:
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/**

forbiddenPaths:
  - /Users/nakamoto_jason/clawd/src/**
  - /Users/nakamoto_jason/clawd/extensions/**
  - /Users/nakamoto_jason/clawd/projects/ai-devops/**
  - /Users/nakamoto_jason/clawd/projects/tests/**
  - /Users/nakamoto_jason/clawd/docs/**
  - /Users/nakamoto_jason/clawd/scripts/**

mustTouch:
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/query-planner.mjs
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/web-flow.mjs

preferCreate:
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/candidate-ranker.mjs
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/playback-memory.mjs

preferEdit:
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/query-planner.mjs
  - /Users/nakamoto_jason/clawd/skills/sonos-pure-play/scripts/web-flow.mjs

definitionOfDone:
  - Sonos search/result matching is improved.
  - Playback flow is improved.
  - No files outside allowedPaths are edited.
  - At least one mustTouch file is edited.
  - Validation commands and results are reported.

validation:
  - Run targeted tests if available.
  - Otherwise run a smoke check.
  - Report exact commands and output.

firstStepRequirement: |
  Before making changes, list the exact files you plan to edit and explain why each is in scope.
  If the file plan cannot stay inside allowedPaths, stop and fail.

failureRules:
  - Stop if any planned or touched file is outside allowedPaths.
  - Stop if any forbiddenPath is touched.
  - Stop if no mustTouch file is edited.
```

---

# Minimum Usage Instruction

Give the coding agent this file and say:

`Fill this template first. Treat it as the execution contract. Do not dispatch or code until the file plan, allowedPaths, forbiddenPaths, and mustTouch are all explicit and valid.`
