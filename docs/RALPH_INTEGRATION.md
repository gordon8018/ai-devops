# Ralph Integration Documentation

## Overview

This document describes the integration between ai-devops and ralph, an autonomous AI coding loop tool. The integration enables ai-devops to dispatch tasks to ralph for execution, track progress, and synchronize state back to the orchestrator.

## Architecture

```
ai-devops orchestrator
    │
    ├── task_to_prd.py    (TaskSpec → prd.json converter)
    ├── ralph_state.py    (State storage in SQLite)
    └── ralph_runner.py   (ralph.sh wrapper)
         │
         ▼
    ralph.sh (Claude Code / Amp)
         │
         ▼
    prd.json + progress.txt
```

## Components

### 1. TaskSpec → prd.json Converter (`task_to_prd.py`)

Converts ai-devops TaskSpec format to ralph's prd.json format.

**Input (TaskSpec):**
```json
{
  "taskId": "task-20260414-001",
  "task": "Add priority field to database",
  "acceptanceCriteria": [
    "Add priority column to tasks table",
    "Typecheck passes"
  ],
  "repo": "user01/ai-devops",
  "userStories": [
    "Create migration for priority column",
    "Update API to support priority field"
  ]
}
```

**Output (prd.json):**
```json
{
  "project": "ai-devops",
  "branchName": "ralph/task-20260414-001",
  "description": "Add priority field to database",
  "aiDevopsTaskId": "task-20260414-001",
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false
  },
  "userStories": [
    {
      "id": "US-001",
      "title": "Create migration for priority column",
      "description": "Create migration for priority column",
      "acceptanceCriteria": [
        "Add priority column to tasks table",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": "",
      "sourceSubtaskId": "task-20260414-001-0"
    }
  ]
}
```

**Usage:**
```bash
# Convert TaskSpec to prd.json
python3 orchestrator/bin/task_to_prd.py task_spec.json prd.json

# CLI usage
./task_to_prd.py <task_spec.json> [output.json]
```

### 2. Ralph State Storage (`ralph_state.py`)

Manages ralph execution state in SQLite database.

**Database Schema:**
```sql
CREATE TABLE ralph_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    logs TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**API:**
```python
from ralph_state import RalphState

# Initialize
state = RalphState(db_path="agent_tasks.db")

# Create state entry
row_id = state.create(
    task_id="task-001",
    status="queued",
    progress=0,
    metadata={"branch": "ralph/task-001"}
)

# Update state
state.update("task-001", status="running", progress=25)

# Append log
state.append_log("task-001", "Started iteration 1")

# Get state
entry = state.get("task-001")

# List states
entries = state.list(status="running", limit=10)

# Delete state
state.delete("task-001")
```

**CLI:**
```bash
# Create state
./ralph_state.py create <task_id> [status] [progress]

# Get state
./ralph_state.py get <task_id>

# List states
./ralph_state.py list [status]

# Update state
./ralph_state.py update <task_id> [status] [progress]

# Delete state
./ralph_state.py delete <task_id>
```

### 3. Ralph Executor Wrapper (`ralph_runner.py`)

Wraps ralph.sh execution and captures output for state synchronization.

**Usage:**
```python
from ralph_runner import RalphRunner

# Initialize
runner = RalphRunner(
    ralph_dir="/path/to/ralph/dir",
    ralph_sh_path="~/.openclaw/workspace-alpha/ralph/ralph.sh",
    tool="claude"
)

# Save prd.json
runner.save_prd_json(prd)

# Run ralph (foreground)
result = runner.run(max_iterations=10, timeout=7200)

# Run ralph (background)
result = runner.run(max_iterations=10, background=True)

# Get status
status = runner.get_status()

# Parse progress.txt
progress = runner.parse_progress()

# Parse prd.json
prd_info = runner.parse_prd_json()

# Wait for completion
final_status = runner.wait_for_completion(poll_interval=30, timeout=7200)
```

**CLI:**
```bash
# Run ralph
./ralph_runner.py run <ralph_dir> [max_iterations]

# Get status
./ralph_runner.py status <ralph_dir>

# Wait for completion
./ralph_runner.py wait <ralph_dir> [poll_interval] [timeout]
```

## Workflow

### Complete Task Execution Flow

1. **Task Creation**
   ```python
   # User creates task via ai-devops
   task_spec = {
       "taskId": "task-20260414-001",
       "task": "Add priority field",
       "acceptanceCriteria": [...],
       "repo": "user01/ai-devops",
       "userStories": [...]
   }
   ```

2. **Convert to PRD**
   ```python
   from task_to_prd import task_spec_to_prd_json
   prd = task_spec_to_prd_json(task_spec)
   ```

3. **Initialize State**
   ```python
   from ralph_state import RalphState
   state = RalphState()
   state.create(task_spec["taskId"], status="queued", progress=0)
   ```

4. **Save PRD and Execute**
   ```python
   from ralph_runner import RalphRunner
   runner = RalphRunner(ralph_dir="/path/to/ralph")
   runner.save_prd_json(prd)
   state.update(task_spec["taskId"], status="running")
   result = runner.run(max_iterations=10, background=True)
   ```

5. **Monitor Progress**
   ```python
   while True:
       status = runner.get_status()
       progress = runner.parse_progress()
       
       # Sync to ai-devops
       state.update(
           task_spec["taskId"],
           progress=prd_info["progress_percent"]
       )
       state.append_log(task_spec["taskId"], f"Iteration {progress['iterations']}")
       
       if status["status"] in ("completed", "failed"):
           break
       
       time.sleep(30)
   ```

6. **Completion**
   ```python
   final_status = runner.get_status()
   state.update(task_spec["taskId"], status=final_status["status"])
   ```

## Status Values

| Status | Description |
|--------|-------------|
| `queued` | Task queued for execution |
| `running` | ralph is executing |
| `completed` | All stories completed |
| `failed` | Execution failed |
| `pr_created` | Pull request created |
| `ci_pending` | Waiting for CI |
| `ci_failed` | CI check failed |
| `review_pending` | Waiting for code review |
| `merged` | Code merged to main |

## Quality Checks

Default quality checks configured in prd.json:

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false
  }
}
```

## Testing

Run unit tests:
```bash
cd /home/user01/ai-devops/orchestrator/bin
python3 tests/test_ralph_integration.py
```

## Dependencies

- Python 3.8+
- SQLite3 (built-in)
- ralph.sh (from workspace-alpha/ralph/)
- Claude Code CLI or Amp

## Troubleshooting

### Issue: ralph.sh not found

**Solution:**
```bash
# Specify ralph.sh path explicitly
runner = RalphRunner(
    ralph_dir="/path/to/ralph",
    ralph_sh_path="~/.openclaw/workspace-alpha/ralph/ralph.sh"
)
```

### Issue: State not updating

**Solution:**
```bash
# Check database
sqlite3 agent_tasks.db "SELECT * FROM ralph_state WHERE task_id = 'task-001'"

# Check logs
./ralph_state.py get task-001
```

### Issue: Conversion fails

**Solution:**
```bash
# Validate TaskSpec
python3 -c "
import json
from task_to_prd import load_task_spec_from_file, task_spec_to_prd_json, validate_prd_json
spec = load_task_spec_from_file('task_spec.json')
prd = task_spec_to_prd_json(spec)
validate_prd_json(prd)
"
```

## Future Enhancements

- [ ] WebSocket real-time status updates
- [ ] Code Review integration
- [ ] CI status monitoring
- [ ] Multi-ralph instance support
- [ ] Automatic retry on failure
- [ ] Knowledge base integration (Obsidian, gbrain)

## References

- [Ralph Integration Analysis](../.openclaw/workspace-research/ralph-integration-analysis.md)
- [ai-devops README](../README.md)
- [TaskSpec Template](TASK_SPEC_TEMPLATE.md)
