from __future__ import annotations


class VerifyEngine:
    """Minimal verification engine for incident closure decisions."""

    def should_close(self, *, resolved: bool) -> bool:
        return bool(resolved)
