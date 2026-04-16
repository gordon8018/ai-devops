from __future__ import annotations

import json
from typing import Any, Optional

from apps.console_api.service import get_global_work_items_service


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode("utf-8"), status, "application/json"


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    return _json_response({"error": message, "success": False}, status)


def _parse_path(path: str) -> tuple[str, Optional[str]]:
    parts = path.split("?", 1)[0].strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "api" and parts[1] == "work-items":
        if len(parts) >= 4 and parts[3] == "context-pack":
            return "work-item-context-pack", parts[2]
        return "work-items", parts[2] if len(parts) >= 3 else None
    return "", None


_SERVICE = get_global_work_items_service()


class WorkItemsAPIHandler:
    work_items_service = _SERVICE

    def handle_get_work_items(self, work_item_id: Optional[str] = None):
        if work_item_id:
            record = self.work_items_service.get_work_item(work_item_id)
            if record is None:
                return _error_response(f"Work item not found: {work_item_id}", 404)
            return _json_response({"success": True, "data": record})

        records = self.work_items_service.list_work_items()
        return _json_response({"success": True, "data": records, "count": len(records)})

    def handle_get_context_pack(self, work_item_id: str):
        record = self.work_items_service.get_context_pack(work_item_id)
        if record is None:
            return _error_response(f"Context pack not found for work item: {work_item_id}", 404)
        return _json_response({"success": True, "data": record})

    def handle_post_work_items(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                return _error_response("Request body is required", 400)
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except json.JSONDecodeError:
            return _error_response("Invalid JSON", 400)

        if not isinstance(payload, dict):
            return _error_response("Request body must be a JSON object", 400)
        if not str(payload.get("repo") or "").strip():
            return _error_response("Field 'repo' is required", 400)
        if not str(payload.get("title") or "").strip():
            return _error_response("Field 'title' is required", 400)

        record = self.work_items_service.create_work_item(payload)
        return _json_response({"success": True, "data": record}, 201)


def create_work_items_handler(base_handler: type) -> type:
    class CombinedHandler(WorkItemsAPIHandler, base_handler):
        def do_GET(self):
            resource, resource_id = _parse_path(self.path)
            if resource == "work-item-context-pack" and resource_id:
                body, status, content_type = self.handle_get_context_pack(resource_id)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            if resource == "work-items":
                body, status, content_type = self.handle_get_work_items(resource_id)
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()

        def do_POST(self):
            resource, resource_id = _parse_path(self.path)
            if resource == "work-items" and resource_id is None:
                body, status, content_type = self.handle_post_work_items()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_POST()

    return CombinedHandler
