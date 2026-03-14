"""
Obsidian Local REST API client.

Requires the Obsidian Local REST API plugin (https://github.com/coddingtonbear/obsidian-local-rest-api).

Environment:
    OBSIDIAN_API_TOKEN: API token configured in the plugin
    OBSIDIAN_API_PORT: Port (default: 27123)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class ObsidianClient:
    base_url: str
    token: str
    timeout: int = 8

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        Search the vault. Returns list of {path, excerpt}.
        Returns [] on any error (unreachable, auth failure, etc.).
        """
        try:
            resp = requests.post(
                f"{self.base_url}/search/simple/",
                headers=self._headers(),
                params={"query": query, "contextLength": 200},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[WARN] Obsidian API error {resp.status_code}, skipping")
                return []
            data = resp.json()
            results = []
            for item in (data.get("results") or [])[:limit]:
                filename = item.get("filename", "")
                matches = item.get("matches") or []
                excerpt = " … ".join(
                    m.get("context", "") for m in matches[:2]
                )
                results.append({"path": filename, "excerpt": excerpt})
            return results
        except Exception as exc:
            print(f"[INFO] Obsidian unreachable, skipping business context: {exc}")
            return []

    def get_note(self, path: str) -> str:
        """
        Fetch full note content by vault-relative path.
        Returns '' on any error.
        """
        try:
            resp = requests.get(
                f"{self.base_url}/vault/{path}",
                headers=self._headers(),
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                print(f"[WARN] Obsidian get_note {resp.status_code} for {path}")
                return ""
            return resp.text
        except Exception as exc:
            print(f"[INFO] Obsidian unreachable for note {path}: {exc}")
            return ""

    def find_by_tags(self, tags: list[str]) -> list[dict[str, Any]]:
        """
        Find notes by tags. Returns [] on any error.
        Implemented via search (tag: prefix per Obsidian search syntax).
        """
        query = " OR ".join(f"tag:{t}" for t in tags)
        return self.search(query)

    @classmethod
    def from_env(cls) -> "ObsidianClient":
        """Construct from environment variables."""
        token = os.getenv("OBSIDIAN_API_TOKEN", "")
        port = os.getenv("OBSIDIAN_API_PORT", "27123")
        return cls(base_url=f"http://localhost:{port}", token=token)
