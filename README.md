# AI DevOps

Zoe orchestration for planning, dispatching, and running coding agents against local Git worktrees.

## What This Repo Does

This repository contains a minimal multi-agent control plane centered on Zoe:

- Discord users submit high-level engineering tasks with `/task`
- Zoe receives the task and acts as the planning agent, producing a validated execution plan
- The dispatcher archives the plan and writes runnable subtasks into the local queue
- `zoe-daemon` consumes queue items, creates Git worktrees, writes prompts, and starts agents with `tmux` when available or a detached local process otherwise
- `monitor` watches active tasks, PR status, and CI, and can trigger retry loops when CI fails

The current implementation focuses on:

- structured task planning
- prompt compilation per subtask
- dependency-aware dispatch
- compatibility with the existing queue/daemon/monitor flow

## Architecture

```text
Discord /task
  -> discord/bot.py
  -> orchestrator/bin/zoe_planner.py
  -> orchestrator/bin/planner_engine.py
  -> orchestrator/bin/plan_schema.py
  -> orchestrator/bin/dispatch.py
  -> orchestrator/queue/*.json
  -> orchestrator/bin/zoe-daemon.py
  -> agents/run-codex-agent.sh
  -> .clawdbot/active-tasks.json
  -> orchestrator/bin/monitor.py
```

## Key Directories

- `discord/`: Discord bot entrypoint and local bot env file
- `orchestrator/bin/`: planner, adapter, schema validation, daemon, monitor, and dispatch logic
- `orchestrator/queue/`: pending execution tasks consumed by `zoe-daemon`
- `tasks/`: archived plans and subtask snapshots under `tasks/<planId>/`
- `worktrees/`: per-task or shared plan worktrees
- `repos/`: source repositories from which worktrees are created
- `agents/`: runner scripts for coding agents
- `.clawdbot/`: runtime registry for active tasks
- `docs/`: focused operational docs
- `tests/`: pytest coverage for plan schema and dispatch behavior

## Important Files

- `discord/bot.py`: Slash commands, allowlist enforcement, planner invocation, fallback queue behavior
- `orchestrator/bin/zoe_planner.py`: CLI entrypoint for `plan`, `dispatch`, and `plan-and-dispatch`
- `orchestrator/bin/planner_engine.py`: Zoe's internal planning engine
- `orchestrator/bin/plan_schema.py`: strict validation for plan JSON, subtask inheritance, DAG checks, and prompt limits
- `orchestrator/bin/dispatch.py`: queue payload generation and dependency-gated dispatch
- `orchestrator/bin/zoe-daemon.py`: queue consumer, worktree manager, prompt writer, and agent spawner
- `orchestrator/bin/monitor.py`: PR/CI watcher and Ralph Loop retry logic
- `orchestrator/bin/prompt_compiler.py`: legacy prompt fallback when a task has no precomputed prompt
- `docs/zoe_planner.md`: planner-specific usage and troubleshooting

## Planner Flow

When a user runs `/task`, the system now does this:

1. validates the Discord user against the allowlist
2. builds a normalized planning request
3. lets Zoe plan the work inside the orchestrator
4. validates the returned plan before accepting it
5. writes:
   - `tasks/<planId>/plan.json`
   - `tasks/<planId>/subtasks/<subtaskId>.json`
6. dispatches the first runnable subtasks into `orchestrator/queue/`
7. replies in Discord with the `planId` and subtask summary

If planning fails, the bot falls back to a single queue task and marks it with `metadata.plannedBy = "fallback"`.

## Queue and Execution Model

Each dispatched queue item includes the legacy fields already expected by `zoe-daemon`:

- `id`
- `repo`
- `title`
- `description`
- `agent`
- `model`
- `effort`

Planner metadata is attached under `metadata`, including:

- `planId`
- `subtaskId`
- `dependsOn`
- `worktreeStrategy`
- `filesHint`
- `plannedBy`

`zoe-daemon.py` now prefers `task["prompt"]` when present. If a queue item does not carry a prompt, it falls back to the older template prompt compiler.

## Environment

Core environment variables:

- `DISCORD_TOKEN`
- `DISCORD_GUILD_ID`
- `DISCORD_CHANNEL`
- `DISCORD_ALLOWED_USERS`
- `DISCORD_ALLOWED_ROLE_IDS`
- `AI_DEVOPS_HOME`
- `CODEX_RUNNER_PATH`
- `CLAUDE_RUNNER_PATH`
- `CODEX_BIN`

## Local Usage

Run the planner directly:

```bash
./.venv/bin/python orchestrator/bin/zoe_planner.py plan --task-file /tmp/task.json
./.venv/bin/python orchestrator/bin/zoe_planner.py dispatch --plan-file ~/ai-devops/tasks/<planId>/plan.json
./.venv/bin/python orchestrator/bin/zoe_planner.py plan-and-dispatch --task-file /tmp/task.json
```

Run tests:

```bash
./.venv/bin/python -m pytest -q
```

## Testing

Current test coverage includes:

- valid plan acceptance
- missing dependency rejection
- dependency cycle rejection
- prompt length guardrails
- queue file generation
- topological dispatch order

## Notes

- `monitor.py` is still responsible for CI-triggered retry handling
- Zoe currently plans internally inside the orchestrator instead of calling an external planner service
- `pydantic` is not currently used in this repo; validation is implemented in typed Python code in `plan_schema.py`
- `agents/run-codex-agent.sh` now provisions its own PTY via `script`, so Codex can run under `tmux` or without it

## Further Reading

- `docs/zoe_planner.md`
