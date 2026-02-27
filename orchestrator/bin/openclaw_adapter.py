from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping
from urllib import error, request

from .errors import InvalidPlan, OpenClawDown
from .plan_schema import Plan


def _extract_json_from_text(payload: str) -> dict[str, Any] | None:
    stripped = payload.strip()
    if not stripped:
        return None

    for candidate in (stripped, stripped.strip("`")):
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(decoded, dict):
            return decoded

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        decoded = json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


class OpenClawAdapter:
    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_token: str | None = None,
        timeout_sec: float | None = None,
        cli_bin: str | None = None,
    ) -> None:
        self.webhook_url = webhook_url or os.getenv("OPENCLAW_WEBHOOK_URL")
        self.webhook_token = webhook_token or os.getenv("OPENCLAW_WEBHOOK_TOKEN")
        self.timeout_sec = float(timeout_sec or os.getenv("OPENCLAW_TIMEOUT_SEC", "45"))
        self.cli_bin = cli_bin or os.getenv("OPENCLAW_CLI_BIN")

    def plan(self, task_input: Mapping[str, Any]) -> Plan:
        if self.webhook_url:
            payload = self._call_http(task_input)
            return Plan.from_dict(self._normalize_plan_payload(payload, task_input))

        if self.cli_bin:
            payload = self._call_cli(task_input)
            return Plan.from_dict(self._normalize_plan_payload(payload, task_input))

        raise OpenClawDown("OpenClaw is not configured")

    def rewrite_prompt(self, task_input: Mapping[str, Any]) -> dict[str, Any]:
        """
        Placeholder for Ralph Loop integration.
        The same webhook can later accept failure context and return a revised prompt.
        """
        payload = dict(task_input)
        payload["includeFailureContext"] = True
        if not self.webhook_url and not self.cli_bin:
            raise OpenClawDown("OpenClaw prompt rewrite is not configured")
        return payload

    def _call_http(self, task_input: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(task_input).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.webhook_token:
            headers["Authorization"] = f"Bearer {self.webhook_token}"

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                req = request.Request(self.webhook_url or "", data=body, headers=headers, method="POST")
                with request.urlopen(req, timeout=self.timeout_sec) as response:
                    payload = response.read().decode("utf-8")
                decoded = _extract_json_from_text(payload)
                if decoded is None:
                    raise OpenClawDown("OpenClaw returned non-JSON output")
                return decoded
            except InvalidPlan:
                raise
            except OpenClawDown as exc:
                last_error = exc
            except (error.HTTPError, error.URLError, TimeoutError) as exc:
                last_error = OpenClawDown("OpenClaw webhook request failed")
            if attempt == 0:
                time.sleep(0.5)

        raise last_error or OpenClawDown("OpenClaw webhook request failed")

    def _call_cli(self, task_input: Mapping[str, Any]) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [self.cli_bin or ""],
                input=json.dumps(task_input),
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise OpenClawDown("OpenClaw CLI is unavailable") from exc

        if completed.returncode != 0:
            raise OpenClawDown("OpenClaw CLI returned a non-zero exit code")

        decoded = _extract_json_from_text(completed.stdout)
        if decoded is None:
            raise OpenClawDown("OpenClaw CLI returned non-JSON output")
        return decoded

    def _normalize_plan_payload(
        self, payload: dict[str, Any], task_input: Mapping[str, Any]
    ) -> dict[str, Any]:
        plan_payload = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
        if not isinstance(plan_payload, dict):
            raise InvalidPlan("OpenClaw response did not contain a plan object")

        merged = dict(plan_payload)
        for key in ("planId", "repo", "title", "requestedBy", "requestedAt", "objective", "version"):
            if key not in merged and key in task_input:
                merged[key] = task_input[key]

        merged.setdefault("constraints", task_input.get("constraints", {}))
        merged.setdefault("context", task_input.get("context", {}))
        if "routing" not in merged and "routing" in task_input:
            merged["routing"] = task_input["routing"]
        return merged


def plan_from_file(task_file: Path, adapter: OpenClawAdapter | None = None) -> Plan:
    payload = json.loads(task_file.read_text(encoding="utf-8"))
    planner = adapter or OpenClawAdapter()
    return planner.plan(payload)
