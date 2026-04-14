# Phase 2 Quick Start Guide

## Quality Gate Usage

### Run Code Review

    python3 orchestrator/bin/quality_gate.py review task_id repo_dir --threshold 8.0

### Enforce Quality Gate

    python3 orchestrator/bin/quality_gate.py enforce task_id repo_dir

### Check CI Status

    python3 orchestrator/bin/ci_monitor.py check branch-name

## Dashboard API

### List Tasks

    python3 orchestrator/bin/ralph_dashboard.py tasks --status completed

### Get Statistics

    python3 orchestrator/bin/ralph_dashboard.py stats

## Running Tests

    cd orchestrator/bin/tests
    python3 test_quality_gate.py
    python3 test_ci_monitor.py
    python3 test_ralph_ws.py

## Configuration

- Quality threshold: 8.0
- Max retry attempts: 3
- CI poll interval: 30 seconds
- CI timeout: 3600 seconds
- WebSocket port: 8766

## Alert Integration

Alerts are triggered for:
- Task failures (CRITICAL)
- Retry limit exceeded (WARNING)
- Code review failures (WARNING)
- CI failures (WARNING)
