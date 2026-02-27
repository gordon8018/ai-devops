from __future__ import annotations

from typing import Any


TOOL_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "name": "plan_task",
        "description": (
            "Generate and validate a structured Zoe plan from a high-level engineering task "
            "without dispatching execution subtasks."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["repo", "title", "description", "requested_by", "requested_at"],
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "agent": {"type": "string", "default": "codex"},
                "model": {"type": "string", "default": "gpt-5.3-codex"},
                "effort": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                "requested_by": {"type": "string"},
                "requested_at": {"type": "integer"},
                "constraints": {"type": "object"},
                "context": {"type": "object"},
                "includeFailureContext": {"type": "boolean", "default": False},
            },
            "additionalProperties": True,
        },
        "resultSchema": {
            "type": "object",
            "required": ["plan", "planFile"],
            "properties": {
                "plan": {"type": "object"},
                "planFile": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "plan_and_dispatch_task",
        "description": (
            "Generate a Zoe plan, archive it, and dispatch the first runnable subtasks into "
            "the local execution queue."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["repo", "title", "description", "requested_by", "requested_at"],
            "properties": {
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "agent": {"type": "string", "default": "codex"},
                "model": {"type": "string", "default": "gpt-5.3-codex"},
                "effort": {"type": "string", "enum": ["low", "medium", "high"], "default": "medium"},
                "requested_by": {"type": "string"},
                "requested_at": {"type": "integer"},
                "constraints": {"type": "object"},
                "context": {"type": "object"},
                "includeFailureContext": {"type": "boolean", "default": False},
                "watch": {"type": "boolean", "default": False},
                "poll_interval_sec": {"type": "number", "default": 5.0},
            },
            "additionalProperties": True,
        },
        "resultSchema": {
            "type": "object",
            "required": ["plan", "planFile", "queued", "queuedCount"],
            "properties": {
                "plan": {"type": "object"},
                "planFile": {"type": "string"},
                "queued": {"type": "array", "items": {"type": "string"}},
                "queuedCount": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "dispatch_plan",
        "description": "Dispatch ready subtasks from an archived plan into the local queue.",
        "inputSchema": {
            "type": "object",
            "required": ["planFile"],
            "properties": {
                "planFile": {"type": "string"},
                "watch": {"type": "boolean", "default": False},
                "poll_interval_sec": {"type": "number", "default": 5.0},
            },
            "additionalProperties": False,
        },
        "resultSchema": {
            "type": "object",
            "required": ["planFile", "queued", "queuedCount"],
            "properties": {
                "planFile": {"type": "string"},
                "queued": {"type": "array", "items": {"type": "string"}},
                "queuedCount": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "task_status",
        "description": (
            "Read local execution status for a specific task, all tasks under a plan, or the "
            "entire active registry."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "plan_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "resultSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "object"},
                "tasks": {"type": "array", "items": {"type": "object"}},
                "planId": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_plans",
        "description": "List recent archived Zoe plans from the local tasks directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
            },
            "additionalProperties": False,
        },
        "resultSchema": {
            "type": "object",
            "required": ["plans"],
            "properties": {
                "plans": {"type": "array", "items": {"type": "object"}},
            },
            "additionalProperties": False,
        },
    },
)


def tool_contracts_payload() -> dict[str, Any]:
    return {
        "version": "1.0",
        "tools": list(TOOL_CONTRACTS),
    }


def tool_names() -> set[str]:
    return {tool["name"] for tool in TOOL_CONTRACTS}
