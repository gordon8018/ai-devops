from __future__ import annotations

import hashlib


class TriageEngine:
    """Fingerprint and severity-score incoming incident signals."""

    def fingerprint(self, message: str) -> str:
        normalized = " ".join(message.lower().split())
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
        return f"inc_{digest}"

    def score(self, *, level: str, message: str) -> str:
        normalized = level.lower().strip()
        if normalized in {"critical", "error", "fatal"}:
            return "critical" if normalized == "critical" else "high"
        if "timeout" in message.lower():
            return "high"
        if normalized == "warning":
            return "medium"
        return "low"
