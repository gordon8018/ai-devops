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
            metadata_json TEXT NOT NULL,
            dedup_key TEXT
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
            payload_json TEXT NOT NULL,
            source_system TEXT,
            dedup_key TEXT
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
            # Idempotent column adds for existing DBs that predate these fields.
            cursor.execute(
                "ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dedup_key TEXT"
            )
            cursor.execute(
                "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS source_system TEXT"
            )
            cursor.execute(
                "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dedup_key TEXT"
            )
            conn.commit()

    def save_work_item(self, work_item: WorkItem) -> None:
        dedup_key = getattr(work_item, "dedup_key", None)
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO work_items (
                    work_item_id, type, title, goal, priority, status, repo,
                    constraints_json, acceptance_criteria_json, requested_by,
                    requested_at, source, metadata_json, dedup_key
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (work_item_id) DO UPDATE SET
                    type = EXCLUDED.type,
                    title = EXCLUDED.title,
                    goal = EXCLUDED.goal,
                    priority = EXCLUDED.priority,
                    status = EXCLUDED.status,
                    repo = EXCLUDED.repo,
                    constraints_json = EXCLUDED.constraints_json,
                    acceptance_criteria_json = EXCLUDED.acceptance_criteria_json,
                    requested_by = EXCLUDED.requested_by,
                    requested_at = EXCLUDED.requested_at,
                    source = EXCLUDED.source,
                    metadata_json = EXCLUDED.metadata_json,
                    dedup_key = EXCLUDED.dedup_key
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
                    dedup_key,
                ),
            )
            conn.commit()

    def delete_work_item(self, work_item_id: str) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                "DELETE FROM work_items WHERE work_item_id = %s",
                (work_item_id,),
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
                ON CONFLICT (pack_id) DO UPDATE SET
                    work_item_id = EXCLUDED.work_item_id,
                    repo_scope_json = EXCLUDED.repo_scope_json,
                    docs_json = EXCLUDED.docs_json,
                    recent_changes_json = EXCLUDED.recent_changes_json,
                    constraints_json = EXCLUDED.constraints_json,
                    acceptance_criteria_json = EXCLUDED.acceptance_criteria_json,
                    known_failures_json = EXCLUDED.known_failures_json,
                    risk_profile = EXCLUDED.risk_profile
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

    def delete_context_pack(self, work_item_id: str) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                "DELETE FROM context_packs WHERE work_item_id = %s",
                (work_item_id,),
            )
            conn.commit()

    def save_release(self, release: dict) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO releases (
                    release_id, work_item_id, status, payload_json
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT (release_id) DO UPDATE SET
                    work_item_id = EXCLUDED.work_item_id,
                    status = EXCLUDED.status,
                    payload_json = EXCLUDED.payload_json
                """,
                (
                    release["releaseId"],
                    release["workItemId"],
                    release["status"],
                    json.dumps(release, ensure_ascii=False, sort_keys=True),
                ),
            )
            conn.commit()

    def delete_release(self, work_item_id: str) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                "DELETE FROM releases WHERE work_item_id = %s",
                (work_item_id,),
            )
            conn.commit()

    def save_incident(self, incident: dict) -> None:
        # D3: sourceSystem / dedupKey live only in independent columns.
        payload_body = {
            key: value
            for key, value in incident.items()
            if key not in ("sourceSystem", "dedupKey")
        }
        with self._connection_factory() as conn:
            conn.cursor().execute(
                """
                INSERT INTO incidents (
                    incident_id, work_item_id, severity, status, payload_json,
                    source_system, dedup_key
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (incident_id) DO UPDATE SET
                    work_item_id = EXCLUDED.work_item_id,
                    severity = EXCLUDED.severity,
                    status = EXCLUDED.status,
                    payload_json = EXCLUDED.payload_json,
                    source_system = EXCLUDED.source_system,
                    dedup_key = EXCLUDED.dedup_key
                """,
                (
                    incident["incidentId"],
                    incident.get("workItemId"),
                    incident["severity"],
                    incident["status"],
                    json.dumps(payload_body, ensure_ascii=False, sort_keys=True),
                    incident.get("sourceSystem"),
                    incident.get("dedupKey"),
                ),
            )
            conn.commit()

    def delete_incident(self, incident_id: str) -> None:
        with self._connection_factory() as conn:
            conn.cursor().execute(
                "DELETE FROM incidents WHERE incident_id = %s",
                (incident_id,),
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

    def get_work_item(self, work_item_id: str) -> dict | None:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    work_item_id, type, title, goal, priority, status, repo,
                    constraints_json, acceptance_criteria_json, requested_by,
                    requested_at, source, metadata_json, dedup_key
                FROM work_items
                WHERE work_item_id = %s
                """,
                (work_item_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return self._compose_work_item_record(conn.cursor(), row)

    def list_work_items(self) -> list[dict]:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    work_item_id, type, title, goal, priority, status, repo,
                    constraints_json, acceptance_criteria_json, requested_by,
                    requested_at, source, metadata_json, dedup_key
                FROM work_items
                ORDER BY requested_at DESC, work_item_id DESC
                """
            )
            rows = cursor.fetchall()
            context_cursor = conn.cursor()
            return [self._compose_work_item_record(context_cursor, row) for row in rows]

    def get_context_pack(self, work_item_id: str) -> dict | None:
        with self._connection_factory() as conn:
            return self._fetch_context_pack(conn.cursor(), work_item_id)

    def get_release(self, work_item_id: str) -> dict | None:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload_json
                FROM releases
                WHERE work_item_id = %s
                ORDER BY release_id DESC
                LIMIT 1
                """,
                (work_item_id,),
            )
            return self._decode_payload_row(cursor.fetchone())

    def list_releases(self) -> list[dict]:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload_json
                FROM releases
                ORDER BY release_id DESC
                """
            )
            return [payload for payload in (self._decode_payload_row(row) for row in cursor.fetchall()) if payload]

    def get_incident(self, incident_id: str) -> dict | None:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload_json, source_system, dedup_key
                FROM incidents
                WHERE incident_id = %s
                LIMIT 1
                """,
                (incident_id,),
            )
            return self._decode_incident_row(cursor.fetchone())

    def list_incidents(self) -> list[dict]:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payload_json, source_system, dedup_key
                FROM incidents
                ORDER BY incident_id DESC
                """
            )
            return [payload for payload in (self._decode_incident_row(row) for row in cursor.fetchall()) if payload]

    def list_audit_events(self) -> list[dict]:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT audit_event_id, entity_type, entity_id, action, payload_json, created_at
                FROM audit_events
                ORDER BY created_at ASC, audit_event_id ASC
                """
            )
            return [
                {
                    "auditEventId": row[0],
                    "entityType": row[1],
                    "entityId": row[2],
                    "action": row[3],
                    "payload": json.loads(row[4] or "{}"),
                    "createdAt": row[5],
                }
                for row in cursor.fetchall()
            ]

    def list_eval_runs(self) -> list[dict]:
        with self._connection_factory() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT eval_run_id, work_item_id, status, payload_json
                FROM eval_runs
                ORDER BY eval_run_id ASC
                """
            )
            return [
                {
                    "evalRunId": row[0],
                    "workItemId": row[1],
                    "status": row[2],
                    "summary": json.loads(row[3] or "{}").get("summary", ""),
                    "payload": {
                        key: value
                        for key, value in json.loads(row[3] or "{}").items()
                        if key != "summary"
                    },
                }
                for row in cursor.fetchall()
            ]

    @staticmethod
    def _decode_payload_row(row) -> dict | None:
        if row is None:
            return None
        payload = row[0] if isinstance(row, (list, tuple)) else row
        return json.loads(payload or "{}")

    @staticmethod
    def _decode_incident_row(row) -> dict | None:
        """Decode an incidents row into a dict, promoting source_system /
        dedup_key columns onto the top level. New writes strip these keys from
        payload_json (see save_incident), so the payload-side fallback only
        exists to decode legacy rows written before that contract landed."""
        if row is None:
            return None
        if isinstance(row, (list, tuple)):
            payload_raw = row[0]
            source_system = row[1] if len(row) > 1 else None
            dedup_key = row[2] if len(row) > 2 else None
        else:
            payload_raw = row
            source_system = None
            dedup_key = None
        incident = json.loads(payload_raw or "{}")
        if source_system is not None:
            incident["sourceSystem"] = source_system
        elif "sourceSystem" not in incident:
            incident["sourceSystem"] = None
        if dedup_key is not None:
            incident["dedupKey"] = dedup_key
        elif "dedupKey" not in incident:
            incident["dedupKey"] = None
        return incident

    def _fetch_context_pack(self, cursor, work_item_id: str) -> dict | None:
        cursor.execute(
            """
            SELECT
                pack_id, work_item_id, repo_scope_json, docs_json,
                recent_changes_json, constraints_json, acceptance_criteria_json,
                known_failures_json, risk_profile
            FROM context_packs
            WHERE work_item_id = %s
            ORDER BY pack_id DESC
            LIMIT 1
            """,
            (work_item_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {
            "packId": row[0],
            "workItemId": row[1],
            "repoScope": json.loads(row[2] or "[]"),
            "docs": json.loads(row[3] or "[]"),
            "recentChanges": json.loads(row[4] or "[]"),
            "constraints": json.loads(row[5] or "{}"),
            "acceptanceCriteria": json.loads(row[6] or "[]"),
            "knownFailures": json.loads(row[7] or "[]"),
            "riskProfile": row[8],
        }

    def _compose_work_item_record(self, context_cursor, row) -> dict:
        work_item = {
            "workItemId": row[0],
            "type": row[1],
            "title": row[2],
            "goal": row[3],
            "priority": row[4],
            "status": row[5],
            "repo": row[6],
            "constraints": json.loads(row[7] or "{}"),
            "acceptanceCriteria": json.loads(row[8] or "[]"),
            "requestedBy": row[9],
            "requestedAt": row[10],
            "source": row[11],
            "metadata": json.loads(row[12] or "{}"),
            "dedupKey": row[13] if len(row) > 13 else None,
        }
        context_pack = self._fetch_context_pack(context_cursor, work_item["workItemId"])
        return {
            "workItem": work_item,
            "contextPack": context_pack,
            "planRequest": {
                "workItem": work_item,
                "context": {"contextPack": context_pack},
            },
        }
