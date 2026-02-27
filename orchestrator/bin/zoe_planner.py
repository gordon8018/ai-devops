#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orchestrator.bin.dispatch import archive_subtasks, default_base_dir, dispatch_plan_file, plan_dir
from orchestrator.bin.errors import InvalidPlan, OpenClawDown, PlannerError, PolicyViolation
from orchestrator.bin.openclaw_adapter import OpenClawAdapter
from orchestrator.bin.plan_schema import Plan, sanitize_identifier

SCHEMA_VERSION = "1.0"
RISK_PATTERNS = {
    "secret_exfiltration": re.compile(
        r"(exfiltrate|dump|print|show|cat).{0,40}(secret|token|env|environment|ssh|credential)",
        re.IGNORECASE,
    ),
    "dangerous_command": re.compile(
        r"(rm\s+-rf|chmod\s+777|curl.+\|\s*sh|wget.+\|\s*sh)",
        re.IGNORECASE,
    ),
}


def generate_plan_id(repo: str, title: str, requested_at_ms: int) -> str:
    timestamp = str(requested_at_ms)
    repo_part = sanitize_identifier(repo.replace("/", "-"))
    slug = sanitize_identifier(title.lower())[:48]
    return sanitize_identifier(f"{timestamp}-{repo_part}-{slug}")


def detect_risk_flags(objective: str) -> list[str]:
    return [name for name, pattern in RISK_PATTERNS.items() if pattern.search(objective)]


def validate_task_policy(task_input: dict[str, Any]) -> list[str]:
    objective = str(task_input.get("objective") or task_input.get("description") or "")
    flags = detect_risk_flags(objective)
    if flags:
        raise PolicyViolation(f"Task blocked by planner policy: {', '.join(flags)}")
    return flags


def build_plan_request(task_input: dict[str, Any]) -> dict[str, Any]:
    requested_at = int(task_input.get("requested_at") or task_input.get("requestedAt") or 0)
    if requested_at <= 0:
        requested_at = int(__import__("time").time() * 1000)

    requested_by = str(task_input.get("requested_by") or task_input.get("requestedBy") or "unknown")
    repo = str(task_input.get("repo") or "").strip()
    title = str(task_input.get("title") or "").strip()
    objective = str(task_input.get("objective") or task_input.get("description") or "").strip()
    if not repo or not title or not objective:
        raise InvalidPlan("Task input must include repo, title, and description/objective")

    plan_id = str(task_input.get("planId") or generate_plan_id(repo, title, requested_at))
    routing = {
        "agent": str(task_input.get("agent") or "codex").strip(),
        "model": str(task_input.get("model") or "gpt-5.3-codex").strip(),
        "effort": str(task_input.get("effort") or "medium").strip(),
    }
    constraints = dict(task_input.get("constraints") or {})
    constraints.setdefault(
        "systemPolicy",
        {
            "secretsAccess": "forbidden",
            "dangerousCommands": "forbidden",
            "networkUsage": "explicitly justify before use",
        },
    )

    risk_flags = validate_task_policy(
        {
            "objective": objective,
        }
    )
    context = dict(task_input.get("context") or {})
    context.setdefault("riskFlags", risk_flags)

    return {
        "planId": plan_id,
        "repo": repo,
        "title": title,
        "requestedBy": requested_by,
        "requestedAt": requested_at,
        "objective": objective,
        "constraints": constraints,
        "context": context,
        "routing": routing,
        "version": SCHEMA_VERSION,
        "systemCapabilities": {
            "agents": [
                {"name": "codex", "models": ["gpt-5.3-codex"]},
                {"name": "claude", "models": ["claude-sonnet-4"]},
            ],
            "worktreeStrategies": ["shared", "isolated"],
        },
        "includeFailureContext": bool(task_input.get("includeFailureContext", False)),
    }


def save_plan(plan: Plan, *, base_dir: Path | None = None) -> Path:
    root = base_dir or default_base_dir()
    target_dir = plan_dir(plan, root)
    target_dir.mkdir(parents=True, exist_ok=True)
    plan_path = target_dir / "plan.json"
    plan.write_json(plan_path)
    archive_subtasks(plan, root)
    return plan_path


def plan_task(
    task_input: dict[str, Any],
    *,
    adapter: OpenClawAdapter | None = None,
    base_dir: Path | None = None,
) -> tuple[Plan, Path]:
    planner = adapter or OpenClawAdapter()
    request_payload = build_plan_request(task_input)
    plan = planner.plan(request_payload)
    plan_path = save_plan(plan, base_dir=base_dir)
    return plan, plan_path


def emit_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InvalidPlan(f"Task file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InvalidPlan(f"Task file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise InvalidPlan("Task file must contain a JSON object")
    return payload


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zoe planner and prompt compiler")
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
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    base_dir = Path(os.getenv("AI_DEVOPS_HOME", str(default_base_dir())))

    try:
        if args.command == "plan":
            task_input = read_json_file(args.task_file)
            plan, plan_path = plan_task(task_input, base_dir=base_dir)
            emit_json({"plan": plan.to_dict(), "planFile": str(plan_path)})
            return 0

        if args.command == "dispatch":
            queued = dispatch_plan_file(
                args.plan_file,
                base_dir=base_dir,
                watch=args.watch,
                poll_interval_sec=args.poll_interval_sec,
            )
            emit_json(
                {
                    "planFile": str(args.plan_file),
                    "queued": [str(path) for path in queued],
                    "queuedCount": len(queued),
                }
            )
            return 0

        if args.command == "plan-and-dispatch":
            task_input = read_json_file(args.task_file)
            plan, plan_path = plan_task(task_input, base_dir=base_dir)
            queued = dispatch_plan_file(
                plan_path,
                base_dir=base_dir,
                watch=args.watch,
                poll_interval_sec=args.poll_interval_sec,
            )
            emit_json(
                {
                    "plan": plan.to_dict(),
                    "planFile": str(plan_path),
                    "queued": [str(path) for path in queued],
                    "queuedCount": len(queued),
                }
            )
            return 0
    except OpenClawDown as exc:
        print(f"OPENCLAW_DOWN: {exc}", file=sys.stderr)
        return 2
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
