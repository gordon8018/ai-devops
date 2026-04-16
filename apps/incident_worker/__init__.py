"""Incident worker entrypoint package for ingest, triage, and verification."""

from .service import IncidentWorker

__all__ = ["IncidentWorker"]
