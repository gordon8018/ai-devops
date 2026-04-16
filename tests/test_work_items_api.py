from __future__ import annotations

import io
import json

from orchestrator.api.work_items import WorkItemsAPIHandler, _parse_path


class StubWorkItemsService:
    def __init__(self) -> None:
        self.created: dict[str, dict] = {}

    def create_work_item(self, payload: dict) -> dict:
        result = {
            "workItem": {
                "workItemId": payload.get("workItemId", "wi_stub"),
                "repo": payload["repo"],
                "title": payload["title"],
            },
            "contextPack": {
                "packId": "ctx_stub",
                "workItemId": payload.get("workItemId", "wi_stub"),
            },
            "planRequest": {
                "planId": "plan_stub",
            },
        }
        self.created[result["workItem"]["workItemId"]] = result
        return result

    def get_work_item(self, work_item_id: str) -> dict | None:
        return self.created.get(work_item_id)

    def list_work_items(self) -> list[dict]:
        return list(self.created.values())

    def get_context_pack(self, work_item_id: str) -> dict | None:
        record = self.created.get(work_item_id)
        if record is None:
            return None
        return record["contextPack"]


class DummyHandler(WorkItemsAPIHandler):
    def __init__(self, *, body: bytes = b"", path: str = "/api/work-items", service=None) -> None:
        self.path = path
        self.rfile = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))}
        self.work_items_service = service or StubWorkItemsService()


def test_parse_path_extracts_work_item_id() -> None:
    assert _parse_path("/api/work-items") == ("work-items", None)
    assert _parse_path("/api/work-items/wi_001") == ("work-items", "wi_001")
    assert _parse_path("/api/work-items/wi_001/context-pack") == ("work-item-context-pack", "wi_001")


def test_handle_post_work_items_creates_payload() -> None:
    handler = DummyHandler(
        body=json.dumps(
            {
                "repo": "acme/platform",
                "title": "Create work item API",
            }
        ).encode("utf-8"),
    )

    body, status, content_type = handler.handle_post_work_items()
    payload = json.loads(body.decode("utf-8"))

    assert status == 201
    assert content_type == "application/json"
    assert payload["success"] is True
    assert payload["data"]["workItem"]["repo"] == "acme/platform"


def test_handle_get_work_items_returns_collection_and_single_item() -> None:
    service = StubWorkItemsService()
    service.create_work_item({"repo": "acme/platform", "title": "Create work item API"})
    handler = DummyHandler(service=service)

    body, status, _ = handler.handle_get_work_items()
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["count"] == 1

    body, status, _ = handler.handle_get_work_items("wi_stub")
    payload = json.loads(body.decode("utf-8"))
    assert status == 200
    assert payload["data"]["workItem"]["workItemId"] == "wi_stub"


def test_handle_get_context_pack_returns_context_pack() -> None:
    service = StubWorkItemsService()
    service.create_work_item({"repo": "acme/platform", "title": "Create work item API"})
    handler = DummyHandler(service=service)

    body, status, _ = handler.handle_get_context_pack("wi_stub")
    payload = json.loads(body.decode("utf-8"))

    assert status == 200
    assert payload["data"]["packId"] == "ctx_stub"
