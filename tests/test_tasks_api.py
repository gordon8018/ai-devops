from __future__ import annotations

import io

from orchestrator.api.tasks import create_tasks_handler


def test_tasks_handler_delegates_unmatched_get_routes_to_base_handler() -> None:
    calls: list[str] = []

    class BaseHandler:
        def __init__(self) -> None:
            self.path = "/api/work-items"
            self.rfile = io.BytesIO(b"")
            self.wfile = io.BytesIO()
            self.headers = {"Content-Length": "0"}

        def do_GET(self):
            calls.append("base_get")

        def do_DELETE(self):
            calls.append("base_delete")

        def send_response(self, status: int) -> None:
            calls.append(f"send_response:{status}")

        def send_header(self, key: str, value: str) -> None:
            calls.append(f"header:{key}={value}")

        def end_headers(self) -> None:
            calls.append("end_headers")

    handler_cls = create_tasks_handler(BaseHandler)
    handler = handler_cls()

    handler.do_GET()

    assert calls == ["base_get"]


def test_tasks_parse_path_ignores_query_string() -> None:
    from orchestrator.api.tasks import _parse_path

    assert _parse_path("/api/tasks?limit=5") == ("tasks", None)
