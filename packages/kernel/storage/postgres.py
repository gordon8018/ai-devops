from __future__ import annotations

import json
from textwrap import dedent

from packages.shared.domain.models import AuditEvent, ContextPack, EvalRun, WorkItem


def control_plane_schema_sql() -> str:
    return dedent(
        """
        CREATE TABLE IF NOT EXISTS work_items (
            work_item_id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            goal TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            repo TEXT NOT NULL,
            constraints_json TEXT NOT NULL,
            acceptance_criteria_json TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            requested_at BIGINT NOT NULL,
            source TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS context_packs (
            pack_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            repo_scope_json TEXT NOT NULL,
            docs_json TEXT NOT NULL,
            recent_changes_json TEXT NOT NULL,
            constraints_json TEXT NOT NULL,
            acceptance_criteria_json TEXT NOT NULL,
            known_failures_json TEXT NOT NULL,
            risk_profile TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plans (
            plan_id TEXT PRIMARY KEY,
            work_item_id TEXT,
            repo TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS plan_subtasks (
            subtask_id TEXT PRIMARY KEY,
            plan_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            context_pack_id TEXT NOT NULL,
            agent TEXT NOT NULL,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            planned_steps_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS run_steps (
            run_step_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quality_runs (
            quality_run_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            gate_type TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_findings (
            finding_id TEXT PRIMARY KEY,
            quality_run_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS releases (
            release_id TEXT PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            work_item_id TEXT,
            severity TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tickets (
            ticket_id TEXT PRIMARY KEY,
            incident_id TEXT,
            provider TEXT NOT NULL,
            external_id TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS eval_runs (
            eval_run_id TEXT PRIMARY KEY,
            work_item_id TEXT,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            audit_event_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at BIGINT NOT NULL
        );
        """
    ).strip()


class ControlPlanePostgresStore:
    """DB-API compatible store used during PostgreSQL migration."""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def ensure_schema(self) -> None:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            for statement in control_plane_schema_sql().split(";"):
                sql = statement.strip()
                if sql:
                    cursor.execute(sql)
            conn.commit()

    def save_work_item(self, work_item: WorkItem) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO work_items (
                    work_item_id, type, title, goal, priority, status, repo,
                    constraints_json, acceptance_criteria_json, requested_by,
                    requested_at, source, metadata_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    work_item.work_item_id,
                    work_item.type.value,
                    work_item.title,
                    work_item.goal,
                    work_item.priority.value,
                    work_item.status.value,
                    work_item.repo,
                    json.dumps(work_item.constraints, ensure_ascii=False, sort_keys=True),
                    json.dumps(list(work_item.acceptance_criteria), ensure_ascii=False),
                    work_item.requested_by,
                    work_item.requested_at,
                    work_item.source,
                    json.dumps(work_item.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()

    def save_context_pack(self, context_pack: ContextPack) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO context_packs (
                    pack_id, work_item_id, repo_scope_json, docs_json,
                    recent_changes_json, constraints_json, acceptance_criteria_json,
                    known_failures_json, risk_profile
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    context_pack.pack_id,
                    context_pack.work_item_id,
                    json.dumps(list(context_pack.repo_scope), ensure_ascii=False),
                    json.dumps(list(context_pack.docs), ensure_ascii=False),
                    json.dumps(list(context_pack.recent_changes), ensure_ascii=False),
                    json.dumps(context_pack.constraints, ensure_ascii=False, sort_keys=True),
                    json.dumps(list(context_pack.acceptance_criteria), ensure_ascii=False),
                    json.dumps(list(context_pack.known_failures), ensure_ascii=False),
                    context_pack.risk_profile.value,
                ),
            )
            conn.commit()

    def save_audit_event(self, audit_event: AuditEvent) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO audit_events (
                    audit_event_id, entity_type, entity_id, action, payload_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    audit_event.audit_event_id,
                    audit_event.entity_type,
                    audit_event.entity_id,
                    audit_event.action,
                    audit_event.payload_json(),
                    audit_event.created_at,
                ),
            )
            conn.commit()

    def save_eval_run(self, eval_run: EvalRun) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO eval_runs (
                    eval_run_id, work_item_id, status, payload_json
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (eval_run_id) DO UPDATE SET
                    work_item_id = EXCLUDED.work_item_id,
                    status = EXCLUDED.status,
                    payload_json = EXCLUDED.payload_json
                """,
                (
                    eval_run.eval_run_id,
                    eval_run.work_item_id,
                    eval_run.status.value,
                    json.dumps(
                        {"summary": eval_run.summary, **eval_run.payload},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            conn.commit()
