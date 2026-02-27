# Zoe Planner

`zoe_planner.py` upgrades Zoe from a template prompt writer into a task planner plus prompt compiler. It accepts a high-level task, lets Zoe act as the planning agent, validates the generated plan, archives the plan, and dispatches runnable subtasks into the existing queue.

The current planner engine uses a phased splitter. For code changes it usually emits a sequential chain such as implementation foundation -> primary implementation -> validation -> docs, while simpler tasks collapse to fewer subtasks. Pure documentation or analysis requests stay conservative instead of inventing empty code work. Each phase now gets a narrower `filesHint` subset so implementation, tests, and docs do not all point at the same paths.

## Files

- `orchestrator/bin/zoe_planner.py`: CLI entrypoint for planning and dispatch.
- `orchestrator/bin/planner_engine.py`: Zoe's internal planning engine.
- `orchestrator/bin/plan_schema.py`: strict JSON schema validation and DAG checks.
- `orchestrator/bin/dispatch.py`: queue payload builder and dependency-aware dispatcher.
- `orchestrator/bin/errors.py`: planner error types.

## Environment

- `AI_DEVOPS_HOME`: optional override for the base directory. Default: `~/ai-devops`
- `DISCORD_ALLOWED_USERS`: comma-separated Discord user ids or `username#tag` entries allowed to use `/task`
- `DISCORD_ALLOWED_ROLE_IDS`: comma-separated Discord role ids allowed to use `/task`
- `CODEX_RUNNER_PATH`: optional override for the Codex runner script
- `CODEX_BIN`: optional absolute path to the `codex` CLI when it is not already on the service `PATH`
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
  "description": "Plan and ship a prompt compiler backed by Zoe.",
  "agent": "codex",
  "model": "gpt-5.3-codex",
  "effort": "high",
  "requested_by": "alice#1234",
  "requested_at": 1730000000000
}
```

The planner injects system policy and capability metadata before Zoe generates a plan. If the objective looks like secret exfiltration or dangerous command injection, the request is rejected before any plan is produced.

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

## Discord Flow

`/task` now:

1. checks the Discord allowlist
2. calls `zoe_planner.py plan-and-dispatch`
3. replies with `planId` and a short subtask list
4. falls back to a single queue item if the planner itself errors

Fallback queue items are tagged with `metadata.plannedBy = "fallback"`.

## Daemon Integration

`zoe-daemon.py` now prefers `task.json.prompt`. If a queue item has no `prompt`, it falls back to the older template-based `compile_prompt()` behavior.

`metadata.worktreeStrategy = "shared"` makes the daemon reuse a plan-level branch/worktree derived from `planId`. `isolated` keeps the previous one-task-per-branch behavior.

## Troubleshooting

- `POLICY_VIOLATION`: the task description matched the injection/exfiltration filter and was blocked before planning.
- `PLANNER_ERROR`: Zoe generated a plan request or plan payload that failed schema validation.
- Queue files created but nothing starts: check `orchestrator/bin/zoe-daemon.py`, the configured runner path, and whether `CODEX_BIN` or the service `PATH` can resolve `codex`.
- The machine does not have `tmux`: Zoe falls back to a detached background process. `agents/run-codex-agent.sh` still creates a PTY with `script`, so Codex can run without tmux.
- Downstream subtasks are not appearing: run the dispatcher in watch mode or inspect `dispatch-state.json` and `~/.clawdbot/active-tasks.json`.
