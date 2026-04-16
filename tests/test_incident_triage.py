from __future__ import annotations

from packages.incident.triage.service import TriageEngine


def test_triage_engine_clusters_similar_messages_and_scores_severity() -> None:
    engine = TriageEngine()

    key = engine.fingerprint("Database timeout in checkout service")
    severity = engine.score(level="critical", message="Database timeout in checkout service")

    assert key.startswith("inc_")
    assert severity == "critical"
