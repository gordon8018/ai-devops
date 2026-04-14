# Knowledge Base Sync Guide (Phase 3)

## Overview

Phase 3 adds automatic knowledge synchronization after each Ralph task execution. Task artifacts are synced to both an Obsidian vault (with cloud push via FastNodeSync) and a gbrain vector knowledge base.

## Architecture

```
Ralph Task → Quality Gate → [Pass] → ObsidianSync → GbrainIndexer → Complete
                                      ↓                  ↓
                              Obsidian Vault      gbrain Vector DB
                              ~/obsidian-vault/   ~/.openclaw/workspace-alpha/gbrain/
                                      ↓
                              FastNodeSync → Cloud
```

## Configuration

Edit `bin/knowledge_config.json` to customize:
- Vault directory paths
- FastNodeSync timeout and CLI path
- gbrain import/embed commands
- Hook execution order and retry policy
- Tagging and filtering rules

## Synced Content

| Category | Source | Vault Destination |
|----------|--------|-------------------|
| Task Reports | progress.txt | `reports/` |
| Code Reviews | Quality gate output | `reviews/` |
| Decision Records | prd.json, key decisions | `decisions/` |
| AGENTS.md | Workspace AGENTS.md | `agents/` |

## Manual Sync

If automatic sync fails, run manually:

```bash
cd /home/user01/ai-devops/orchestrator/bin

# Sync a task's artifacts to Obsidian + cloud
python3 obsidian_sync.py full /path/to/ralph/workspace TASK-001

# Index into gbrain
python3 gbrain_indexer.py index-task TASK-001 /path/to/artifacts

# Just push to cloud
python3 obsidian_sync.py cloud-push

# Just run embedding
python3 gbrain_indexer.py embed
```

## Troubleshooting

- **Obsidian unreachable**: Ensure Obsidian is running with Local REST API plugin (for API client; file-based sync works without it)
- **FastNodeSync fails**: Check `~/FastNodeSync-CLI` exists and credentials are configured
- **gbrain import fails**: Ensure bun is installed and `~/.openclaw/workspace-alpha/gbrain/` exists
- **Pipeline continues despite sync failure**: This is by design (`continue_on_failure: true` in config); sync failures don't block task completion
