#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orchestrator.bin.errors import PlannerError, PolicyViolation
from orchestrator.bin.zoe_tools import (
    dispatch_plan,
    list_plans,
    plan_and_dispatch_task,
    plan_task,
    read_json_file,
    task_status,
)


def emit_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compatibility CLI for Zoe planner. Prefer zoe_tools as the tool layer."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="Generate a validated plan")
    plan_parser.add_argument("--task-file", required=True, type=Path)

    dispatch_parser = subparsers.add_parser("dispatch", help="Dispatch a plan to the queue")
    dispatch_parser.add_argument("--plan-file", required=True, type=Path)
    dispatch_parser.add_argument("--watch", action="store_true")
    dispatch_parser.add_argument("--poll-interval-sec", type=float, default=5.0)

    plan_dispatch_parser = subparsers.add_parser(
        "plan-and-dispatch", help="Generate a plan and dispatch ready subtasks"
    )
    plan_dispatch_parser.add_argument("--task-file", required=True, type=Path)
    plan_dispatch_parser.add_argument("--watch", action="store_true")
    plan_dispatch_parser.add_argument("--poll-interval-sec", type=float, default=5.0)

    status_parser = subparsers.add_parser("status", help="Read task or plan status from the registry")
    status_parser.add_argument("--task-id")
    status_parser.add_argument("--plan-id")

    list_parser = subparsers.add_parser("list-plans", help="List recent archived plans")
    list_parser.add_argument("--limit", type=int, default=10)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    base_dir = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))

    try:
        if args.command == "plan":
            task_input = read_json_file(args.task_file)
            emit_json(plan_task(task_input, base_dir=base_dir).to_dict())
            return 0

        if args.command == "dispatch":
            emit_json(
                dispatch_plan(
                    args.plan_file,
                    base_dir=base_dir,
                    watch=args.watch,
                    poll_interval_sec=args.poll_interval_sec,
                ).to_dict()
            )
            return 0

        if args.command == "plan-and-dispatch":
            task_input = read_json_file(args.task_file)
            emit_json(
                plan_and_dispatch_task(
                    task_input,
                    base_dir=base_dir,
                    watch=args.watch,
                    poll_interval_sec=args.poll_interval_sec,
                ).to_dict()
            )
            return 0

        if args.command == "status":
            emit_json(task_status(task_id=args.task_id, plan_id=args.plan_id, base_dir=base_dir))
            return 0

        if args.command == "list-plans":
            emit_json(list_plans(base_dir=base_dir, limit=args.limit))
            return 0
    except PolicyViolation as exc:
        print(f"POLICY_VIOLATION: {exc}", file=sys.stderr)
        return 3
    except PlannerError as exc:
        print(f"PLANNER_ERROR: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
