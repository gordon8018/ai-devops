from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any


class TaskSpecError(ValueError):
    """Raised when TASK_SPEC is missing, malformed, or invalid."""


_REQUIRED_FIELDS = (
    "title",
    "goal",
    "repo",
    "workingRoot",
    "allowedPaths",
    "forbiddenPaths",
    "mustTouch",
    "definitionOfDone",
    "validation",
    "firstStepRequirement",
    "failureRules",
)


def _strip_code_fence(text: str) -> str:
    lines = text.splitlines()
    if len(lines) >= 2 and lines[0].strip().startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return text


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if text == "":
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    data: dict[str, Any] = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if raw.startswith(" ") or raw.startswith("\t"):
            raise TaskSpecError(f"Unexpected indentation at line {i + 1}: {raw}")
        if ":" not in raw:
            raise TaskSpecError(f"Invalid TASK_SPEC line {i + 1}: {raw}")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "|":
            i += 1
            block: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                if nxt.startswith("  "):
                    block.append(nxt[2:])
                    i += 1
                    continue
                if not nxt.strip():
                    block.append("")
                    i += 1
                    continue
                break
            data[key] = "\n".join(block).strip("\n")
            continue
        if value == "":
            i += 1
            seq: list[Any] = []
            nested: dict[str, Any] = {}
            saw_seq = False
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    i += 1
                    continue
                if not nxt.startswith("  "):
                    break
                item = nxt[2:]
                if item.startswith("- "):
                    saw_seq = True
                    seq.append(_parse_scalar(item[2:]))
                    i += 1
                    continue
                if ":" in item and not saw_seq:
                    child_key, child_value = item.split(":", 1)
                    nested[child_key.strip()] = _parse_scalar(child_value)
                    i += 1
                    continue
                raise TaskSpecError(f"Unsupported nested TASK_SPEC structure at line {i + 1}: {nxt}")
            data[key] = seq if saw_seq else nested
            continue
        data[key] = _parse_scalar(value)
        i += 1
    return data


def parse_task_spec_text(text: str, *, source: str = "<inline>") -> dict[str, Any]:
    content = textwrap.dedent(_strip_code_fence(text.strip()))
    if not content:
        raise TaskSpecError(f"TASK_SPEC is empty: {source}")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = _parse_simple_yaml(content)
    if not isinstance(payload, dict):
        raise TaskSpecError(f"TASK_SPEC must be an object: {source}")
    return payload


def load_task_spec_file(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    if not target.exists():
        raise TaskSpecError(f"TASK_SPEC file not found: {target}")
    return parse_task_spec_text(target.read_text(encoding="utf-8"), source=str(target))


def validate_task_spec(payload: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in _REQUIRED_FIELDS if field not in payload or payload[field] in (None, "", [])]
    if missing:
        raise TaskSpecError(f"TASK_SPEC missing required fields: {', '.join(missing)}")

    for key in ("allowedPaths", "forbiddenPaths", "mustTouch", "definitionOfDone", "validation", "failureRules"):
        if not isinstance(payload.get(key), list) or not payload[key]:
            raise TaskSpecError(f"TASK_SPEC field '{key}' must be a non-empty list")

    if not isinstance(payload.get("firstStepRequirement"), str) or not payload["firstStepRequirement"].strip():
        raise TaskSpecError("TASK_SPEC field 'firstStepRequirement' must be a non-empty string")

    allowed = [str(item).strip() for item in payload.get("allowedPaths", []) if str(item).strip()]
    forbidden = [str(item).strip() for item in payload.get("forbiddenPaths", []) if str(item).strip()]
    must_touch = [str(item).strip() for item in payload.get("mustTouch", []) if str(item).strip()]
    if not allowed or not must_touch:
        raise TaskSpecError("TASK_SPEC must include non-empty allowedPaths and mustTouch")

    if not any(any(target.startswith(root.rstrip("*")) or root.rstrip("*").rstrip("/") in target for root in allowed) for target in must_touch):
        raise TaskSpecError("TASK_SPEC mustTouch must stay inside allowedPaths")

    normalized = dict(payload)
    normalized["allowedPaths"] = allowed
    normalized["forbiddenPaths"] = forbidden
    normalized["mustTouch"] = must_touch
    return normalized


def task_spec_to_task_input(spec: dict[str, Any]) -> dict[str, Any]:
    validated = validate_task_spec(spec)
    context = {
        "taskSpec": validated,
        "filesHint": list(validated.get("mustTouch", [])),
    }
    constraints = {
        "allowedPaths": list(validated.get("allowedPaths", [])),
        "forbiddenPaths": list(validated.get("forbiddenPaths", [])),
        "mustTouch": list(validated.get("mustTouch", [])),
        "definitionOfDone": list(validated.get("definitionOfDone", [])),
        "validation": list(validated.get("validation", [])),
        "failureRules": list(validated.get("failureRules", [])),
        "firstStepRequirement": validated.get("firstStepRequirement", ""),
        "workingRoot": validated.get("workingRoot", ""),
    }
    for key in ("preferCreate", "preferEdit"):
        if isinstance(validated.get(key), list) and validated[key]:
            constraints[key] = list(validated[key])
    return {
        "repo": validated["repo"],
        "title": validated["title"],
        "description": validated["goal"],
        "constraints": constraints,
        "context": context,
    }


def scoped_task_requires_task_spec(task_input: dict[str, Any]) -> bool:
    constraints = task_input.get("constraints")
    if not isinstance(constraints, dict):
        return False
    return any(bool(constraints.get(key)) for key in ("allowedPaths", "forbiddenPaths", "mustTouch", "requiredTouchedPaths"))
