from __future__ import annotations

import io
import json

from orchestrator.api.console import ConsoleAPIHandler, _parse_console_path


class StubConsoleService:
    def get_mission_control(self) -> dict:
        return {"workItems": {"total": 2}, "releases": {"total": 1}, "incidents": {"open": 1}, "recentEvents": []}

    def get_release_console(self) -> dict:
        return {"total": 2, "byStatus": {"rolling_out": 1, "rolled_back": 1}, "items": []}

    def get_incident_console(self) -> dict:
        return {"total": 1, "bySeverity": {"high": 1}, "items": []}

    def get_eval_console(self) -> dict:
        return {
            "taskStatusCounts": {"ready": 1},
            "alertCount": 1,
            "evalRuns": [{"evalRunId": "eval_001"}],
            "auditSummary": {"total": 2, "byAction": {"work_item_created": 1}},
            "governance": {
                "legacyEntrypoints": {
                    "total": 1,
                    "byEntrypoint": {"zoe_tools.build_work_item_session": 1},
                },
                "workItemSources": {"legacy_task_input": 1},
                "cutoverReadiness": {
                    "ready": False,
                    "blockingReasons": ["legacy_entrypoints_active"],
                },
            },
        }

    def get_governance_console(self) -> dict:
        return {
            "legacyEntrypoints": {
                "total": 1,
                "byEntrypoint": {"zoe_tools.build_work_item_session": 1},
            },
            "workItemSources": {"legacy_task_input": 1},
            "cutoverReadiness": {
                "ready": False,
                "blockingReasons": ["legacy_entrypoints_active"],
            },
            "auditSummary": {"total": 2, "byAction": {"legacy_entrypoint_used": 1}},
        }

    def get_task_workspace(self, work_item_id: str) -> dict | None:
        if work_item_id != "wi_stub":
            return None
        return {
            "workItem": {"workItemId": "wi_stub"},
            "contextPack": {"packId": "ctx_stub"},
            "planRequest": {"planId": "plan_stub"},
            "eventTimeline": [],
            "release": {"releaseId": "rel_stub"},
            "incidents": [],
        }


class DummyHandler(ConsoleAPIHandler):
    def __init__(self, path: str = "/api/console/mission-control", service=None) -> None:
        self.path = path
        self.rfile = io.BytesIO(b"")
        self.headers = {"Content-Length": "0"}
        self.console_service = service or StubConsoleService()


def test_parse_console_path_extracts_console_resources() -> None:
    assert _parse_console_path("/api/console/mission-control") == ("mission-control", None)
    assert _parse_console_path("/api/console/releases") == ("release-console", None)
    assert _parse_console_path("/api/console/incidents") == ("incident-console", None)
    assert _parse_console_path("/api/console/evals") == ("eval-console", None)
    assert _parse_console_path("/api/console/governance") == ("governance-console", None)
    assert _parse_console_path("/api/console/work-items/wi_stub/workspace") == ("task-workspace", "wi_stub")


def test_handle_get_mission_control_returns_summary() -> None:
    handler = DummyHandler()

    body, status, content_type = handler.handle_get_mission_control()
    payload = json.loads(body.decode("utf-8"))

    assert status == 200
    assert content_type == "application/json"
    assert payload["data"]["workItems"]["total"] == 2


def test_handle_get_task_workspace_returns_workspace() -> None:
    handler = DummyHandler(service=StubConsoleService())

    body, status, _ = handler.handle_get_task_workspace("wi_stub")
    payload = json.loads(body.decode("utf-8"))

    assert status == 200
    assert payload["data"]["release"]["releaseId"] == "rel_stub"


def test_handle_get_release_and_incident_consoles_return_summaries() -> None:
    handler = DummyHandler(service=StubConsoleService())

    body, status, _ = handler.handle_get_release_console()
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["data"]["total"] == 2

    body, status, _ = handler.handle_get_incident_console()
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["data"]["bySeverity"]["high"] == 1

    body, status, _ = handler.handle_get_eval_console()
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["data"]["alertCount"] == 1
    assert payload["data"]["evalRuns"][0]["evalRunId"] == "eval_001"
    assert payload["data"]["auditSummary"]["total"] == 2
    assert payload["data"]["governance"]["legacyEntrypoints"]["total"] == 1

    body, status, _ = handler.handle_get_governance_console()
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["data"]["legacyEntrypoints"]["total"] == 1
