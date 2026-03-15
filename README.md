# AI DevOps

Zoe tool layer for planning, dispatching, and running coding agents against local Git worktrees.

[![CI](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml/badge.svg)](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml)

Language: **English** | [简体中文](README.zh-CN.md)


## What This Repo Does

This repository contains the fixed workflow layer behind Zoe:

- **Zoe** (OpenClaw agent) decides which local tool to call
- **This repo** provides deterministic tools for planning, validation, dispatch, execution, and monitoring
- **discord.py bot** (optional) local control adapter for development and fallback operations
- **Dispatcher** archives plans and writes runnable subtasks into the local queue
- **zoe-daemon** consumes queue items, creates Git worktrees, writes prompts, and starts agents
- **monitor** watches active tasks, PR status, and CI; triggers retry loops on failure

### Core Capabilities

- Structured task planning with validation
- Prompt compilation per subtask
- Phased multi-subtask planning (implementation → validation → docs)
- Dependency-aware dispatch
- SQLite-based task tracking
- GitHub webhook integration
- CI failure detection with automatic retry (Ralph Loop v2)
- Obsidian vault context injection into retry prompts
- Success pattern memory (winning prompts saved and injected into future plans)
- Local PR review pipeline (Codex + Claude reviewers post GitHub comments)
- Daily cleanup daemon (stale worktrees + old logs)
- Telegram notifications for task state changes

## Architecture

```mermaid
flowchart TD
    U[Discord User] --> DC[Discord Channel]
    DC --> OC[OpenClaw Runtime]
    OC --> Z[Zoe Agent<br/>AI decision layer]
    CLI[scripts/spawn-agent.sh] --> API

    Z --> API[zoe_tool_api.py]
    API --> T1[plan_task]
    API --> T2[dispatch_plan]
    API --> T3[task_status / list_plans]
    API --> T4[retry_task]

    subgraph ToolLayer["Tool Layer (this repo)"]
        subgraph Planning["Planning"]
            T1 --> ZT[zoe_tools.py]
            ZT --> OBS[(Obsidian<br/>Local REST API)]
            ZT --> TPL[.clawdbot/prompt-templates/]
            OBS -. business context .-> ZT
            TPL -. success patterns .-> ZT
            ZT --> PE[planner_engine.py]
            PE --> PS[plan_schema.py]
            PS --> PJ[tasks/planId/plan.json]
        end

        subgraph Dispatch["Dispatch"]
            T2 --> DP[dispatch.py]
            PJ --> DP
            DP --> Q[orchestrator/queue/]
        end

        subgraph Execution["Execution"]
            Q --> ZD[zoe-daemon.py]
            ZD --> WT[worktrees/]
            ZD --> PT[prompt.txt]
            ZD --> AG[run-codex-agent.sh]
            AG --> X{tmux?}
            X -->|yes| TM[tmux session]
            X -->|no| BG[detached process]
        end

        subgraph Tracking["State & Monitoring"]
            TM --> DB[.clawdbot/agent_tasks.db]
            BG --> DB
            T3 --> DB
            T4 --> M[monitor.py]
            M --> DB
            DB --> M
        end

        subgraph PostMerge["Post-PR Pipeline"]
            M -->|pr_created| RV[reviewer.py<br/>Codex + Claude]
            RV -->|comments| GH[(GitHub PR)]
            M -->|CI fail| FL[failure-logs/]
            M -->|ready| TPL
            FL -. retry context .-> M
        end

        subgraph Maintenance["Daily Cleanup (02:00)"]
            CD[cleanup_daemon.py]
            CD --> WT
            CD --> Q
            CD --> FL
        end
    end

    M -->|状态变更| TG[Telegram notify.py]
    B[discord/bot.py] -. dev only .-> ZT
```

**逻辑功能流程：**
```mermaid
sequenceDiagram
    participant Z as Zoe / CLI
    participant ZT as zoe_tools.py
    participant OBS as Obsidian
    participant TPL as prompt-templates/
    participant PE as planner_engine
    participant DP as dispatch.py
    participant ZD as zoe-daemon
    participant AG as Agent (tmux)
    participant DB as agent_tasks.db
    participant GH as GitHub
    participant M as monitor.py
    participant RV as reviewer.py
    participant TG as Telegram

    Z->>ZT: plan_and_dispatch_task(repo, title, ...)
    ZT->>OBS: search(title) → business context
    ZT->>TPL: load_success_patterns(repo)
    ZT->>PE: build_prompt + success patterns
    PE-->>ZT: plan.json + subtasks
    ZT->>DP: dispatch runnable subtasks
    DP->>ZD: queue/*.json (dependency-gated)

    ZD->>AG: create worktree + write prompt.txt + start agent
    AG->>DB: status = running
    AG->>GH: git push + open PR
    AG->>DB: status = pr_created

    M->>DB: poll active tasks
    M->>GH: check CI status
    M->>RV: review_pr(pr_number) async
    RV->>GH: post Codex + Claude review comments

    alt CI passes
        M->>DB: status = ready
        M->>TPL: save_success_pattern(prompt.txt)
        M->>TG: notify "ready"
    else CI fails
        M->>DB: write failure-log
        M->>ZD: retry with enriched prompt
        M->>TG: notify "retry N"
    end
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js (for OpenClaw)
- tmux (optional, for agent sessions)
- GitHub CLI (optional, for PR monitoring)

### Installation

```bash
# Clone and setup
git clone https://github.com/gordon8018/ai-devops.git
cd ai-devops
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install -e .
pip install pytest pytest-cov python-dotenv
```

### Local Path / Base Directory

All task state, queue files, worktrees, and SQLite data resolve relative to `AI_DEVOPS_HOME`.
If you want the repo to run from its current checkout path, export it explicitly:

```bash
export AI_DEVOPS_HOME="$(pwd)"
```

If unset, the default base directory remains `~/ai-devops`.

### Using the bundled OpenClaw skill

This repository includes an OpenClaw skill at `openclaw-skills/zoe-local-tools/`, but that repo-local copy is **not** automatically active just because the repository was cloned.
For a real OpenClaw installation, copy or install the skill into one of these discovery paths:

- `<workspace>/skills/zoe-local-tools/`
- `~/.openclaw/skills/zoe-local-tools/`

If you keep using the repo-local helper script directly, set `AI_DEVOPS_HOME` first so the script resolves the correct checkout path on that machine.
Do not assume a fixed path like `/home/user01/ai-devops` exists everywhere.

### Environment Setup

```bash
# Copy example env file
cp discord/.env.example discord/.env

# Edit with your credentials
# Required: DISCORD_TOKEN, DISCORD_GUILD_ID, DISCORD_CHANNEL
```

### Run Tests

```bash
# Quick test
./scripts/test.sh

# With coverage
./scripts/test.sh --coverage

# Run specific test
./scripts/test.sh --test tests/test_db.py::TestTaskCRUD
```

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `discord/` | Optional local control adapter and bot env |
| `orchestrator/bin/` | Tool layer, schema, daemon, monitor, dispatch |
| `orchestrator/queue/` | Pending execution tasks |
| `tasks/` | Archived plans (`tasks/<planId>/plan.json`) |
| `worktrees/` | Per-task Git worktrees |
| `repos/` | Source repositories |
| `agents/` | Runner scripts for coding agents |
| `scripts/` | Helper shell scripts (spawn-agent, cleanup, babysit) |
| `.clawdbot/` | SQLite database, failure logs, prompt templates |
| `.clawdbot/failure-logs/` | Per-repo JSON failure logs (cleaned after 30 days) |
| `.clawdbot/prompt-templates/` | Winning prompt templates for success pattern memory |
| `docs/` | Operational documentation |
| `tests/` | Pytest test suite |

## Important Files

| File | Purpose |
|------|---------|
| `orchestrator/bin/zoe_tools.py` | Unified tool layer for planning/dispatch |
| `orchestrator/bin/zoe_tool_api.py` | JSON I/O adapter for agent tool calls |
| `orchestrator/bin/planner_engine.py` | Zoe's internal planning engine |
| `orchestrator/bin/plan_schema.py` | Plan validation (DAG checks, prompt limits) |
| `orchestrator/bin/dispatch.py` | Queue generation, dependency-gated dispatch |
| `orchestrator/bin/zoe-daemon.py` | Queue consumer, worktree manager, agent spawner |
| `orchestrator/bin/monitor.py` | PR/CI watcher, Ralph Loop v2 retry logic |
| `orchestrator/bin/reviewer.py` | Local PR review pipeline (Codex + Claude) |
| `orchestrator/bin/obsidian_client.py` | Obsidian Local REST API client |
| `orchestrator/bin/cleanup_daemon.py` | Daily worktree + log maintenance daemon |
| `orchestrator/bin/notify.py` | Telegram notification module |
| `orchestrator/bin/db.py` | SQLite task tracker |
| `orchestrator/bin/webhook_server.py` | GitHub webhook receiver |
| `orchestrator/bin/agent.py` | Agent CLI (spawn/list/status/kill) |

## Tool Contracts

Zoe exposes these tools via `zoe_tool_api.py`:

| Tool | Description |
|------|-------------|
| `plan_task` | Create a plan without dispatching |
| `plan_and_dispatch_task` | Create plan and dispatch immediately |
| `dispatch_plan` | Dispatch an existing plan |
| `task_status` | Get status of a specific task |
| `list_plans` | List recent plans |
| `retry_task` | Manually trigger a retry for a failed task |

### Query Tool Schema

```bash
./.venv/bin/python orchestrator/bin/zoe_tool_api.py schema --pretty
```

### Invoke Tool

```bash
printf '%s\n' '{"tool":"list_plans","args":{"limit":3}}' | \
  ./.venv/bin/python orchestrator/bin/zoe_tool_api.py invoke
```

## Planner Flow

1. **Accept** normalized planning request from Zoe or local adapter
2. **Build** planning request with repo, title, objective, constraints
3. **Plan** using `planner_engine.py` (generates subtasks with dependencies)
4. **Validate** plan (DAG checks, prompt limits, schema validation)
5. **Write** `tasks/<planId>/plan.json` + `subtasks/*.json`
6. **Dispatch** runnable subtasks to `orchestrator/queue/`
7. **Return** structured data for Zoe's response

## Queue and Execution Model

### Queue Item Structure

```json
{
  "id": "1773448846631-test-repo-fix-auth-S1",
  "repo": "test/repo",
  "title": "Land the primary implementation",
  "description": "Fix auth flow",
  "agent": "codex",
  "model": "gpt-5.3-codex",
  "effort": "high",
  "prompt": "DoD: fix auth.\nBoundary: stay scoped.",
  "metadata": {
    "planId": "1773448846631-test-repo-fix-auth",
    "subtaskId": "S1",
    "dependsOn": [],
    "worktreeStrategy": "isolated",
    "filesHint": ["src/auth/session.ts"],
    "plannedBy": "zoe"
  }
}
```

### Execution Lifecycle

```
queued → running → pr_created → ready → merged
                          ↓
                    needs_rebase / blocked / timeout
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Discord bot token |
| `DISCORD_GUILD_ID` | Discord server ID |
| `DISCORD_CHANNEL` | Default channel ID |
| `DISCORD_ALLOWED_USERS` | Comma-separated user IDs |
| `AI_DEVOPS_HOME` | AI DevOps home directory (default: `~/ai-devops`) |
| `CODEX_RUNNER_PATH` | Path to Codex runner script |
| `GITHUB_WEBHOOK_SECRET` | Webhook signature secret |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | Telegram chat/group ID for notifications |
| `OBSIDIAN_API_TOKEN` | Obsidian Local REST API token (optional) |
| `OBSIDIAN_API_PORT` | Obsidian API port (default: `27123`) |

## Testing

### Test Suite

- **137 test cases** across 13 test files
- Runs on every push/PR via GitHub Actions

### Run Tests

```bash
# All tests
./scripts/test.sh

# With coverage report
./scripts/test.sh --coverage

# Specific test file
python -m pytest tests/test_monitor.py -v

# Specific test
python -m pytest tests/test_db.py::TestTaskCRUD::test_insert_task -v
```

## CI/CD

Automated on GitHub Actions:

- **Test**: Python 3.12, pytest with coverage
- **Lint**: flake8, black, isort
- **Coverage**: Uploads to Codecov

Triggered on:
- Push to `main`/`master`
- Pull requests to `main`/`master`

See `.github/workflows/ci.yml` for configuration.

## Shell Scripts

| Script | Purpose |
|--------|---------|
| `scripts/spawn-agent.sh` | CLI shortcut: `plan_and_dispatch_task` via `zoe_tool_api.py` |
| `scripts/cleanup-worktrees.sh` | Run `cleanup_daemon.py --once` to remove stale worktrees |
| `scripts/babysit.sh` | Read-only view: active tmux agent sessions + SQLite task states |
| `scripts/test.sh` | Run pytest (with optional `--coverage` flag) |

```bash
# Spawn a task from the command line
./scripts/spawn-agent.sh my-org/my-repo "Fix login bug" "Auth token not invalidated on logout"

# Check what's running
./scripts/babysit.sh

# Clean up finished worktrees
./scripts/cleanup-worktrees.sh
```

## Notes

- **monitor.py** handles CI-triggered retry (Ralph Loop v2) — injects Obsidian business context and structured failure logs into retry prompts
- **reviewer.py** posts Codex + Claude code review comments on newly created PRs (runs in background thread)
- **cleanup_daemon.py** runs daily at 02:00 to remove worktrees for terminal-state tasks and delete old queue/log files
- **Success pattern memory** — when a task reaches `ready` state, the winning prompt is saved to `.clawdbot/prompt-templates/`; future plans for the same repo inject the top 3 templates as "PAST SUCCESSES"
- **Zoe** is the AI decision layer; this repo is the deterministic tool layer
- **No pydantic** - validation uses typed Python in `plan_schema.py`
- **run-codex-agent.sh** provisions PTY via `script` for tmux compatibility

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Queue files not consumed | Check `zoe-daemon.py` is running |
| Task stuck in `running` | Check `monitor.py` logs, verify tmux session (`./scripts/babysit.sh`) |
| CI retry not triggering | Check `monitor.py` is running; verify `GITHUB_WEBHOOK_SECRET` |
| Telegram notifications silent | Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in env |
| Obsidian context missing | Verify `OBSIDIAN_API_TOKEN` and that the Local REST API plugin is enabled |
| Stale worktrees accumulating | Run `./scripts/cleanup-worktrees.sh` or start `cleanup_daemon.py` |
| Plan validation fails | Check `docs/zoe_planner.md` for schema |

### Logs

```bash
# Daemon logs
tail -f logs/zoe-daemon.log

# Monitor logs
tail -f logs/monitor.log

# Webhook logs
tail -f logs/webhook.log
```

## Further Reading

- [docs/zoe_planner.md](docs/zoe_planner.md) - Planner usage and troubleshooting
- [docs/TEST_COVERAGE.md](docs/TEST_COVERAGE.md) - Detailed test coverage report
- [docs/agent-cli.md](docs/agent-cli.md) - Agent CLI reference
- [docs/sqlite-migration-summary.md](docs/sqlite-migration-summary.md) - Database migration notes
- [docs/webhook-setup.md](docs/webhook-setup.md) - GitHub webhook configuration

---

**License:** MIT | **Maintainer:** Gordon Yang
