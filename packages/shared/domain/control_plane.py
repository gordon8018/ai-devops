from __future__ import annotations

from typing import Any
import os


_CONTROL_PLANE_STORE: Any | None = None


def _build_control_plane_store_from_dsn(dsn: str) -> Any:
    from packages.kernel.storage.postgres import ControlPlanePostgresStore

    try:
        import psycopg  # type: ignore

        return ControlPlanePostgresStore(lambda: psycopg.connect(dsn))
    except ImportError:
        try:
            import psycopg2  # type: ignore

            return ControlPlanePostgresStore(lambda: psycopg2.connect(dsn))
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL control-plane store requested but neither psycopg nor psycopg2 is installed"
            ) from exc


def set_control_plane_store(store: Any | None) -> Any | None:
    global _CONTROL_PLANE_STORE
    _CONTROL_PLANE_STORE = store
    return _CONTROL_PLANE_STORE


def clear_control_plane_store() -> None:
    set_control_plane_store(None)


def ensure_control_plane_store(*, dsn: str | None = None) -> Any | None:
    global _CONTROL_PLANE_STORE
    if _CONTROL_PLANE_STORE is not None:
        return _CONTROL_PLANE_STORE

    resolved_dsn = (dsn or os.getenv("AI_DEVOPS_CONTROL_PLANE_DSN") or "").strip()
    if not resolved_dsn:
        return None

    _CONTROL_PLANE_STORE = _build_control_plane_store_from_dsn(resolved_dsn)
    return _CONTROL_PLANE_STORE


def get_control_plane_store() -> Any | None:
    return _CONTROL_PLANE_STORE or ensure_control_plane_store()
