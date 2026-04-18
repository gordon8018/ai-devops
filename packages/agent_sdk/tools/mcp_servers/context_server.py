"""MCP Server wrapper around ContextPack for on-demand context queries."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from packages.shared.domain.models import ContextPack


class ContextPackServer:
    def __init__(self, context_pack: ContextPack):
        self._pack = context_pack

    def list_resources(self) -> list[dict[str, str]]:
        return [
            {"name": "code-graph", "uri": "context://code-graph"},
            {"name": "recent-changes", "uri": "context://recent-changes"},
            {"name": "documentation", "uri": "context://documentation"},
            {"name": "known-failures", "uri": "context://known-failures"},
            {"name": "success-patterns", "uri": "context://success-patterns"},
        ]

    def get_resource(self, name: str) -> str:
        handlers = {
            "code-graph": lambda: ("Files in scope:\n" + "\n".join(f"- {f}" for f in self._pack.repo_scope)) if self._pack.repo_scope else "(no code graph available)",
            "recent-changes": lambda: ("Recent changes:\n" + "\n".join(f"- {c}" for c in self._pack.recent_changes)) if self._pack.recent_changes else "(no recent changes)",
            "documentation": lambda: "\n\n".join(self._pack.docs) if self._pack.docs else "(no documentation available)",
            "known-failures": lambda: ("Known failures:\n" + "\n".join(f"- {f}" for f in self._pack.known_failures)) if self._pack.known_failures else "(no known failures)",
            "success-patterns": lambda: "(success patterns not yet migrated)",
        }
        handler = handlers.get(name)
        return handler() if handler else f"Unknown resource: {name}"
