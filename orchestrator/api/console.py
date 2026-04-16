from __future__ import annotations

import json
from typing import Any, Optional

from apps.console_api.service import get_global_console_service


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode("utf-8"), status, "application/json"


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    return _json_response({"error": message, "success": False}, status)


def _parse_console_path(path: str) -> tuple[str, Optional[str]]:
    parts = path.split("?", 1)[0].strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "console":
        if parts[2] == "mission-control":
            return "mission-control", None
        if parts[2] == "releases":
            return "release-console", None
        if parts[2] == "incidents":
            return "incident-console", None
        if parts[2] == "evals":
            return "eval-console", None
        if parts[2] == "governance":
            return "governance-console", None
        if len(parts) >= 5 and parts[2] == "work-items" and parts[4] == "workspace":
            return "task-workspace", parts[3]
    return "", None


_SERVICE = get_global_console_service()


class ConsoleAPIHandler:
    console_service = _SERVICE

    def handle_get_mission_control(self):
        return _json_response({"success": True, "data": self.console_service.get_mission_control()})

    def handle_get_release_console(self):
        return _json_response({"success": True, "data": self.console_service.get_release_console()})

    def handle_get_incident_console(self):
        return _json_response({"success": True, "data": self.console_service.get_incident_console()})

    def handle_get_eval_console(self):
        return _json_response({"success": True, "data": self.console_service.get_eval_console()})

    def handle_get_governance_console(self):
        return _json_response({"success": True, "data": self.console_service.get_governance_console()})

    def handle_get_task_workspace(self, work_item_id: str):
        record = self.console_service.get_task_workspace(work_item_id)
        if record is None:
            return _error_response(f"Task workspace not found: {work_item_id}", 404)
        return _json_response({"success": True, "data": record})


def create_console_handler(base_handler: type) -> type:
    class CombinedHandler(ConsoleAPIHandler, base_handler):
        def do_GET(self):
            resource, resource_id = _parse_console_path(self.path)
            if resource == "mission-control":
                body, status, content_type = self.handle_get_mission_control()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "release-console":
                body, status, content_type = self.handle_get_release_console()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "incident-console":
                body, status, content_type = self.handle_get_incident_console()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "eval-console":
                body, status, content_type = self.handle_get_eval_console()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "governance-console":
                body, status, content_type = self.handle_get_governance_console()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "task-workspace" and resource_id:
                body, status, content_type = self.handle_get_task_workspace(resource_id)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

    return CombinedHandler
