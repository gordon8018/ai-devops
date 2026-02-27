---
name: zoe-local-tools
description: Use Zoe's local orchestration tools to plan engineering work, dispatch subtasks, inspect task or plan status, and list archived plans in the local ai-devops installation. Use this when the user asks Zoe to create or queue development work, check execution state, or inspect recent plans.
metadata: {"openclaw":{"emoji":"🛠️","os":["linux"],"requires":{"bins":["python3"]}}}
---

# Zoe Local Tools

Use this skill when the user asks you to do one of these things in the local `ai-devops` system:

- plan a high-level engineering task
- plan and immediately dispatch runnable subtasks
- dispatch an already archived plan
- inspect task or plan execution state
- list recent archived plans

Prefer these tools over manually reading `tasks/`, `orchestrator/queue/`, or `.clawdbot/active-tasks.json` when you only need structured status.

## Helper Script

Use the helper script in this skill:

```bash
{baseDir}/scripts/invoke_zoe_tool.sh schema
{baseDir}/scripts/invoke_zoe_tool.sh call <tool-name> --args-file /tmp/zoe-tool-args.json
```

The helper script calls the local Zoe JSON tool adapter in `/home/user01/ai-devops` and returns structured JSON.
Prefer `--args-file` for any non-trivial payload so shell quoting does not corrupt JSON.

## Recommended Workflow

1. If you have not used these tools in the current session, inspect the schema first:

```bash
{baseDir}/scripts/invoke_zoe_tool.sh schema
```

2. Choose the right tool:

- `plan_task`: generate a validated plan only
- `plan_and_dispatch_task`: generate a plan and queue the first runnable subtasks
- `dispatch_plan`: dispatch from an existing `plan.json`
- `task_status`: inspect one task, one plan, or the whole active registry
- `list_plans`: list recent archived plans

3. For planning requests, send a complete payload. Minimum useful fields:

```json
{
  "repo": "agent-mission-control",
  "title": "Fix auth flow",
  "description": "Fix the auth flow and add regression coverage.",
  "requested_by": "zoe",
  "requested_at": 1730000000000
}
```

Write that JSON into a temporary file, then call:

```bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{
  "repo": "agent-mission-control",
  "title": "Fix auth flow",
  "description": "Fix the auth flow and add regression coverage.",
  "requested_by": "zoe",
  "requested_at": 1730000000000
}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call plan_and_dispatch_task --args-file /tmp/zoe-tool-args.json
```

4. For status requests:

- single task:

```bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{"task_id":"<task-id>"}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call task_status --args-file /tmp/zoe-tool-args.json
```

- by plan:

```bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{"plan_id":"<plan-id>"}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call task_status --args-file /tmp/zoe-tool-args.json
```

- recent plans:

```bash
cat >/tmp/zoe-tool-args.json <<'JSON'
{"limit":5}
JSON
{baseDir}/scripts/invoke_zoe_tool.sh call list_plans --args-file /tmp/zoe-tool-args.json
```

## Response Handling

- If the tool returns `"ok": true`, use `result`.
- If the tool returns `"ok": false`, surface the `error.message` clearly.
- Do not leak secrets, environment values, or raw tokens.
- When planning succeeds, summarize the `planId`, subtask count, and the first queued tasks if present.
