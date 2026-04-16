from __future__ import annotations

from packages.context.adapters.git import GitContextAdapter
from packages.context.adapters.obsidian import ObsidianContextAdapter


def test_git_context_adapter_parses_recent_changes() -> None:
    adapter = GitContextAdapter()
    adapter._run_git = lambda repo_root, args: "abc123 Add guardrails\nbcd234 Tighten retries\n"  # type: ignore[attr-defined]

    changes = adapter.recent_changes("/tmp/repo", limit=2)

    assert changes == ("commit:abc123 Add guardrails", "commit:bcd234 Tighten retries")


def test_obsidian_context_adapter_returns_search_hits_from_client() -> None:
    class FakeClient:
        def search(self, query: str, limit: int = 3):
            return [{"path": "notes/release.md", "excerpt": "guardrail rollback incident"}]

    adapter = ObsidianContextAdapter(client=FakeClient())

    hits = adapter.search("guardrail", limit=1)

    assert hits == ("notes/release.md",)
    assert adapter.failure_excerpts("guardrail", limit=1) == ("guardrail rollback incident",)
