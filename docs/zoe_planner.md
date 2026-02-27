# Zoe Planner

`zoe_planner.py` upgrades Zoe from a template prompt writer into a task planner plus prompt compiler. It accepts a high-level task, asks OpenClaw for a structured plan, validates the returned schema, archives the plan, and dispatches runnable subtasks into the existing queue.

## Files

- `orchestrator/bin/zoe_planner.py`: CLI entrypoint for planning and dispatch.
- `orchestrator/bin/openclaw_adapter.py`: OpenClaw HTTP adapter with optional CLI fallback.
- `orchestrator/bin/plan_schema.py`: strict JSON schema validation and DAG checks.
- `orchestrator/bin/dispatch.py`: queue payload builder and dependency-aware dispatcher.
- `orchestrator/bin/errors.py`: planner error types.

## Environment

- `AI_DEVOPS_HOME`: optional override for the base directory. Default: `~/ai-devops`
- `OPENCLAW_WEBHOOK_URL`: local or remote webhook endpoint for planning. Example: `http://127.0.0.1:7777/webhooks/plan`
- `OPENCLAW_WEBHOOK_TOKEN`: optional bearer token. Never logged.
- `OPENCLAW_TIMEOUT_SEC`: webhook timeout in seconds. Default: `45`
- `OPENCLAW_CLI_BIN`: optional executable path for a stdin/stdout JSON CLI fallback. If unset, CLI mode is disabled.
- `DISCORD_ALLOWED_USERS`: comma-separated Discord user ids or `username#tag` entries allowed to use `/task`
- `DISCORD_ALLOWED_ROLE_IDS`: comma-separated Discord role ids allowed to use `/task`
- `CODEX_RUNNER_PATH`: optional override for the Codex runner script
- `CLAUDE_RUNNER_PATH`: optional override for the Claude runner script

## CLI

Plan only:

```bash
python3 orchestrator/bin/zoe_planner.py plan --task-file /tmp/task.json
```

Dispatch an existing plan:

```bash
python3 orchestrator/bin/zoe_planner.py dispatch --plan-file ~/ai-devops/tasks/<planId>/plan.json
```

Plan and dispatch ready subtasks:

```bash
python3 orchestrator/bin/zoe_planner.py plan-and-dispatch --task-file /tmp/task.json
```

Dependency watcher mode:

```bash
python3 orchestrator/bin/zoe_planner.py dispatch --plan-file ~/ai-devops/tasks/<planId>/plan.json --watch
```

## Task Input

Example task input passed to the planner:

```json
{
  "repo": "my-repo",
  "title": "Implement Zoe planner",
  "description": "Plan and ship a prompt compiler backed by OpenClaw.",
  "agent": "codex",
  "model": "gpt-5.3-codex",
  "effort": "high",
  "requested_by": "alice#1234",
  "requested_at": 1730000000000
}
```

The planner injects system policy and capability metadata before calling OpenClaw. If the objective looks like secret exfiltration or dangerous command injection, the request is rejected before any OpenClaw call is made.

## Plan Output

Validated plans are archived under:

- `~/ai-devops/tasks/<planId>/plan.json`
- `~/ai-devops/tasks/<planId>/subtasks/<subtaskId>.json`
- `~/ai-devops/tasks/<planId>/dispatch-state.json`

Each queue item is written to:

- `~/ai-devops/orchestrator/queue/<planId>-<subtaskId>.json`

Queue payloads keep the legacy fields Zoe already needs:

- `id`
- `repo`
- `title`
- `description`
- `agent`
- `model`
- `effort`

Planner metadata is attached under `metadata`:

- `planId`
- `subtaskId`
- `dependsOn`
- `worktreeStrategy`
- `filesHint`
- `plannedBy`

## OpenClaw Webhook Contract

Request body includes:

- `repo`
- `title`
- `objective`
- `constraints`
- `context`
- `routing`
- `systemCapabilities`
- `includeFailureContext`

Preferred response:

```json
{
  "plan": {
    "planId": "1730000000000-my-repo-implement-zoe-planner",
    "repo": "my-repo",
    "title": "Implement Zoe planner",
    "requestedBy": "alice#1234",
    "requestedAt": 1730000000000,
    "objective": "Plan and ship a prompt compiler backed by OpenClaw.",
    "version": "1.0",
    "routing": {
      "agent": "codex",
      "model": "gpt-5.3-codex",
      "effort": "high"
    },
    "subtasks": [
      {
        "id": "S1",
        "title": "Design plan schema",
        "description": "Implement the schema validator and plan archive.",
        "worktreeStrategy": "isolated",
        "dependsOn": [],
        "filesHint": ["orchestrator/bin/plan_schema.py"],
        "prompt": "DoD: implement strict validation and tests. Boundary: do not change monitor.py.",
        "definitionOfDone": ["Validation rejects cycles and oversize prompts."]
      }
    ]
  }
}
```

The adapter will also accept a raw JSON object instead of `{ "plan": ... }`. If the webhook returns plain text, the adapter tries to extract a JSON object. If it still cannot parse JSON, the bot falls back to a single legacy queue item.

## Discord Flow

`/task` now:

1. checks the Discord allowlist
2. calls `zoe_planner.py plan-and-dispatch`
3. replies with `planId` and a short subtask list
4. falls back to a single queue item if OpenClaw is down, times out, or returns non-JSON output

Fallback queue items are tagged with `metadata.plannedBy = "fallback"`.

## Daemon Integration

`zoe-daemon.py` now prefers `task.json.prompt`. If a queue item has no `prompt`, it falls back to the older template-based `compile_prompt()` behavior.

`metadata.worktreeStrategy = "shared"` makes the daemon reuse a plan-level branch/worktree derived from `planId`. `isolated` keeps the previous one-task-per-branch behavior.

## Troubleshooting

- `OPENCLAW_DOWN`: check `OPENCLAW_WEBHOOK_URL`, the local webhook process, and the timeout.
- `POLICY_VIOLATION`: the task description matched the injection/exfiltration filter and was blocked before planning.
- `PLANNER_ERROR`: OpenClaw responded, but the returned plan failed schema validation.
- Queue files created but nothing starts: check `orchestrator/bin/zoe-daemon.py`, tmux availability, and the configured runner path.
- Downstream subtasks are not appearing: run the dispatcher in watch mode or inspect `dispatch-state.json` and `~/.clawdbot/active-tasks.json`.
