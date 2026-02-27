#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orchestrator.bin.errors import PlannerError, PolicyViolation
from orchestrator.bin.zoe_tool_contract import tool_contracts_payload, tool_names
from orchestrator.bin.zoe_tools import (
    dispatch_plan,
    list_plans,
    plan_and_dispatch_task,
    plan_task,
    task_status,
)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _load_json_request(request_file: Path | None) -> dict[str, Any]:
    if request_file is not None:
        raw = request_file.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlannerError("Request payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise PlannerError("Request payload must be a JSON object")
    return payload


def _dispatch_tool_call(payload: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    tool = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(tool, str) or tool not in tool_names():
        raise PlannerError(f"Unsupported tool: {tool}")
    if not isinstance(args, dict):
        raise PlannerError("Tool args must be a JSON object")

    if tool == "plan_task":
        return plan_task(args, base_dir=base_dir).to_dict()
    if tool == "plan_and_dispatch_task":
        return plan_and_dispatch_task(
            args,
            base_dir=base_dir,
            watch=bool(args.get("watch", False)),
            poll_interval_sec=float(args.get("poll_interval_sec", 5.0)),
        ).to_dict()
    if tool == "dispatch_plan":
        plan_file = args.get("planFile")
        if not isinstance(plan_file, str) or not plan_file.strip():
            raise PlannerError("dispatch_plan requires args.planFile")
        return dispatch_plan(
            Path(plan_file),
            base_dir=base_dir,
            watch=bool(args.get("watch", False)),
            poll_interval_sec=float(args.get("poll_interval_sec", 5.0)),
        ).to_dict()
    if tool == "task_status":
        return task_status(
            task_id=args.get("task_id"),
            plan_id=args.get("plan_id"),
            base_dir=base_dir,
        )
    if tool == "list_plans":
        limit = int(args.get("limit", 10))
        return list_plans(base_dir=base_dir, limit=limit)
    raise PlannerError(f"Tool handler not implemented: {tool}")


def _success(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "result": result,
    }


def _failure(tool: str | None, exc: Exception, *, code: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "type": exc.__class__.__name__,
            "message": str(exc),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agent-facing JSON I/O API for Zoe's local tool layer"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    schema_parser = subparsers.add_parser("schema", help="Print the machine-readable Zoe tool contracts")
    schema_parser.add_argument("--pretty", action="store_true")

    invoke_parser = subparsers.add_parser("invoke", help="Invoke a Zoe tool with a JSON request")
    invoke_parser.add_argument("--request-file", type=Path)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    base_dir = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))

    if args.command == "schema":
        payload = tool_contracts_payload()
        if args.pretty:
            _emit(payload)
        else:
            print(json.dumps(payload, ensure_ascii=False))
        return 0

    if args.command == "invoke":
        tool_name: str | None = None
        try:
            request_payload = _load_json_request(args.request_file)
            tool_name = request_payload.get("tool") if isinstance(request_payload.get("tool"), str) else None
            result = _dispatch_tool_call(request_payload, base_dir=base_dir)
            _emit(_success(tool_name or "unknown", result))
            return 0
        except PolicyViolation as exc:
            _emit(_failure(tool_name, exc, code="POLICY_VIOLATION"))
            return 3
        except PlannerError as exc:
            _emit(_failure(tool_name, exc, code="PLANNER_ERROR"))
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
