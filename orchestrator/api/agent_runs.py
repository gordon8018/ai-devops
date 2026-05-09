"""GET /api/agent-runs endpoint."""
from __future__ import annotations

import json
from typing import Any

from packages.shared.domain.runtime_state import list_agent_runs


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode("utf-8"), status, "application/json"


class AgentRunsAPIHandler:
    def handle_get_agent_runs(self):
        runs = list_agent_runs()
        return _json_response({"success": True, "data": runs, "count": len(runs)})


def create_agent_runs_handler(base_handler: type) -> type:
    class CombinedHandler(AgentRunsAPIHandler, base_handler):
        def do_GET(self):
            clean = self.path.split("?", 1)[0].strip("/")
            if clean == "api/agent-runs":
                body, status, content_type = self.handle_get_agent_runs()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_OPTIONS(self):
            try:
                super().do_OPTIONS()
            except AttributeError:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.end_headers()

    return CombinedHandler
