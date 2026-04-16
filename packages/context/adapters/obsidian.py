from __future__ import annotations

from typing import Any

from orchestrator.bin.obsidian_client import ObsidianClient


class ObsidianContextAdapter:
    """Fetch note hits and failure excerpts from Obsidian."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _get_client(self) -> Any | None:
        if self._client is not None:
            return self._client
        try:
            client = ObsidianClient.from_env()
        except Exception:
            return None
        if not client.token:
            return None
        self._client = client
        return client

    def _search_items(self, query: str, limit: int = 3) -> tuple[dict[str, Any], ...]:
        client = self._get_client()
        if client is None:
            return ()
        try:
            results = client.search(query, limit=limit)
        except Exception:
            return ()
        if not isinstance(results, list):
            return ()
        return tuple(item for item in results if isinstance(item, dict))

    def search(self, query: str, limit: int = 3) -> tuple[str, ...]:
        return tuple(str(item.get("path") or "") for item in self._search_items(query, limit) if item.get("path"))

    def failure_excerpts(self, query: str, limit: int = 3) -> tuple[str, ...]:
        return tuple(
            str(item.get("excerpt") or "")
            for item in self._search_items(query, limit)
            if str(item.get("excerpt") or "").strip()
        )
