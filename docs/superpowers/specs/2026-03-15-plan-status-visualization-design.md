# Plan Status Visualization — Design Spec

**Date:** 2026-03-15
**Status:** Approved
**Author:** Brainstorming session with gordon

---

## Problem

When multiple subtasks are dispatched in parallel, there is no way to see:
- Overall plan progress (X of N subtasks complete)
- Dependency graph execution flow
- Live status updates across all subtasks simultaneously

The underlying data already exists (SQLite `agent_tasks`, `dispatch-state.json`, `subtasks/*.json`). The gap is a presentation layer.

---

## Solution Overview

Add a `agent plan-status <plan-id>` command that provides two synchronized views:

1. **Terminal TUI** — `rich`-based table + ASCII DAG, `--watch` auto-refresh
2. **Browser Dashboard** — static HTML served by a background mini HTTP server, polls a local JSON API every 5 seconds

---

## Architecture

```
agent plan-status <plan-id> [--watch] [--interval N] [--html] [--no-tui]
         │
         ├─ Terminal mode (default)
         │    └── PlanStatusRenderer (rich)
         │         ├── reads SQLite → aggregates subtask statuses
         │         ├── reads dispatch-state.json → dependency graph
         │         └── --watch: in-place refresh every N seconds (default 5s)
         │
         └─ --html mode
              ├── PlanStatusServer (stdlib http.server, no pip deps)
              │    ├── GET /api/plan/<id>  → JSON data
              │    └── GET /               → HTML dashboard
              ├── listens on random localhost port
              ├── runs in background thread; main thread runs rich TUI
              └── webbrowser.open(url) on startup
```

### Data Sources (no schema changes)

| Source | Used for |
|--------|----------|
| `agent_tasks` table (`plan_id` column) | Subtask runtime status, PR info, attempts, notes |
| `tasks/<plan-id>/dispatch-state.json` | Which subtasks are dispatched and when |
| `tasks/<plan-id>/subtasks/*.json` | Dependency graph (`depends_on`), definition of done |
| `tasks/<plan-id>/plan.json` | Plan metadata: objective, repo, requested_by, requested_at |

---

## New Files

| File | Responsibility |
|------|---------------|
| `orchestrator/bin/plan_status.py` | Data aggregation: merges plan archive + DB rows into a unified `PlanView` dataclass |
| `orchestrator/bin/plan_status_renderer.py` | Rich TUI rendering: header panel, ASCII DAG, status table, watch loop |
| `orchestrator/bin/plan_status_server.py` | Mini HTTP server + embedded HTML template (single file, <300 lines) |

Existing files modified:
- `orchestrator/bin/agent.py` — add `cmd_plan_status` and `cmd_plans` subcommands

---

## Section 1: Terminal TUI

### Layout

```
┌─ Plan: feat-user-auth  [repo: myorg/myrepo]  Progress: 3/5 ──────────┐
│ Objective: Add OAuth2 login flow                                       │
│ Requested by: gordon  Started: 2026-03-15 10:23                       │
└────────────────────────────────────────────────────────────────────────┘

Dependency Graph:
  [✅ auth-schema] ──→ [✅ auth-api] ──→ [🔄 auth-tests]
                   ╲──→ [⏳ auth-ui]
  [auth-docs 📋]  (no deps, waiting)

┌──────────────────┬──────────┬──────────┬─────────┬──────────────────┐
│ Subtask          │ Status   │ Agent    │ PR      │ Note             │
├──────────────────┼──────────┼──────────┼─────────┼──────────────────┤
│ auth-schema      │ ✅ ready  │ codex    │ #42     │                  │
│ auth-api         │ ✅ ready  │ codex    │ #43     │                  │
│ auth-tests       │ 🔄 running│ claude   │ —       │ retry #1         │
│ auth-ui          │ ⏳ queued │ codex    │ —       │ waiting: api     │
│ auth-docs        │ 📋 planned│ —        │ —       │ not dispatched   │
└──────────────────┴──────────┴──────────┴─────────┴──────────────────┘

[Auto-refresh in 3s | Ctrl+C to exit | --html to open browser dashboard]
```

### Status Icon Mapping

| Status | Icon | Color |
|--------|------|-------|
| planned | 📋 | dim |
| queued | ⏳ | yellow |
| running / retrying | 🔄 | cyan |
| pr_created | 🔀 | blue |
| ready | ✅ | green |
| merged | 🎉 | green bold |
| blocked / agent_failed / agent_dead | ❌ | red |
| needs_rebase | ⚠️ | yellow |

### DAG Rendering Rules

- ASCII arrows show dependency chains; siblings on the same depth rendered side-by-side
- Nodes > 6: collapse to table-only mode (add a `Depends On` column instead of drawing graph)

---

## Section 2: Browser Dashboard

### Layout

```
┌─────────────────────────────────────────────────────────┐
│  🤖 Plan: feat-user-auth        Progress: ████░░ 3/5    │
│  repo: myorg/myrepo  |  by: gordon  |  🔄 refresh in 5s │
├─────────────────────────────────────────────────────────┤
│  DAG (SVG, auto-layout)                                  │
│  [auth-schema ✅] → [auth-api ✅] → [auth-tests 🔄]      │
│                  ↘ [auth-ui ⏳]                           │
│  [auth-docs 📋]                                          │
├─────────────────────────────────────────────────────────┤
│  Subtask table (PR links clickable → GitHub)             │
└─────────────────────────────────────────────────────────┘
```

### Technical Details

- HTML template embedded as a string in `plan_status_server.py` (no external files)
- DAG rendered as pure SVG + vanilla JS with topological layering (zero frontend frameworks)
- Polling: `setInterval(() => fetch('/api/plan/<id>').then(render), 5000)`
- PR links are clickable anchors pointing to GitHub
- Total HTML template: < 300 lines

### Server Lifecycle

- Starts in a daemon thread when `--html` is passed
- Port: random available port on localhost (retries up to 10 times on conflict)
- Shutdown: `Ctrl+C` in the terminal kills both TUI and server cleanly
- `--no-tui` flag: skips rich TUI, only serves browser (useful for headless use)

---

## Section 3: CLI Integration

### New Subcommands

```bash
# Single snapshot
agent plan-status <plan-id>

# Live TUI, refresh every 5s
agent plan-status <plan-id> --watch

# Custom refresh interval (seconds)
agent plan-status <plan-id> --watch --interval 10

# TUI + browser dashboard
agent plan-status <plan-id> --html

# Browser only (no TUI)
agent plan-status <plan-id> --html --no-tui

# List all plans with progress summary
agent plans [--limit 10]
```

### `agent plans` Output

```
PLAN-ID              PROGRESS   STATUS     REPO               STARTED
feat-user-auth       3/5        running    myorg/myrepo       2026-03-15 10:23
fix-db-migration     5/5        done       myorg/backend      2026-03-14 09:00
```

---

## Constraints

- No new `pip` dependencies: `rich` is already used; `http.server`, `threading`, `webbrowser` are stdlib
- No modifications to `dispatch.py`, `monitor.py`, or `db.py`
- `plan_status.py` reads data only — no writes

---

## Out of Scope

- WebSocket push updates (polling is sufficient)
- Multi-plan comparison view
- Historical plan archives browser
