from __future__ import annotations

from packages.kernel.storage.postgres import ControlPlanePostgresStore, control_plane_schema_sql
from packages.shared.domain.models import AuditEvent, ContextPack, EvalRun, EvalRunStatus, RiskProfile, WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


class RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.fetchone_result: tuple | None = None
        self.fetchall_result: list[tuple] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params or ()))

    def fetchall(self) -> list[tuple]:
        return list(self.fetchall_result)

    def fetchone(self) -> tuple | None:
        return self.fetchone_result


class RecordingConnection:
    def __init__(self) -> None:
        self.cursor_instance = RecordingCursor()
        self.committed = False

    def cursor(self) -> RecordingCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.committed = False

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_control_plane_schema_contains_required_tables() -> None:
    schema = control_plane_schema_sql()
    for table_name in (
        "work_items",
        "context_packs",
        "plans",
        "plan_subtasks",
        "agent_runs",
        "run_steps",
        "quality_runs",
        "review_findings",
        "releases",
        "incidents",
        "tickets",
        "eval_runs",
        "audit_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema


def test_store_writes_work_item_context_pack_and_audit_event() -> None:
    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)

    work_item = WorkItem(
        work_item_id="wi_001",
        type=WorkItemType.FEATURE,
        title="Add work item API",
        goal="Expose a first-class work item endpoint",
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.PLANNING,
        repo="acme/platform",
        constraints={"allowedPaths": ["apps/console_api/**"]},
        acceptance_criteria=("Create endpoint",),
    )
    context_pack = ContextPack(
        pack_id="ctx_001",
        work_item_id="wi_001",
        repo_scope=("apps/console_api/**",),
        docs=("docs/api/work-items.md",),
        recent_changes=("commit:123",),
        constraints={"allowedPaths": ["apps/console_api/**"]},
        acceptance_criteria=("Create endpoint",),
        known_failures=("missing context pack",),
        risk_profile=RiskProfile.MEDIUM,
    )
    audit_event = AuditEvent(
        audit_event_id="ae_001",
        entity_type="work_item",
        entity_id="wi_001",
        action="created",
        payload={"source": "test"},
    )
    eval_run = EvalRun(
        eval_run_id="eval_001",
        work_item_id="wi_001",
        status=EvalRunStatus.PASSED,
        summary="healthy",
        payload={"successRate": 1.0},
    )

    store.save_work_item(work_item)
    store.save_context_pack(context_pack)
    store.save_audit_event(audit_event)
    store.save_eval_run(eval_run)

    statements = [sql for sql, _ in conn.cursor_instance.executed]
    assert any("INSERT INTO work_items" in sql for sql in statements)
    assert any("INSERT INTO context_packs" in sql for sql in statements)
    assert any("INSERT INTO audit_events" in sql for sql in statements)
    assert any("INSERT INTO eval_runs" in sql for sql in statements)
    assert any("ON CONFLICT (eval_run_id)" in sql for sql in statements if "INSERT INTO eval_runs" in sql)
    assert conn.committed is True


def test_control_plane_schema_declares_dedup_and_source_system_columns() -> None:
    schema = control_plane_schema_sql()
    work_items_block = schema.split("CREATE TABLE IF NOT EXISTS work_items", 1)[1].split(");", 1)[0]
    incidents_block = schema.split("CREATE TABLE IF NOT EXISTS incidents", 1)[1].split(");", 1)[0]
    assert "dedup_key TEXT" in work_items_block
    assert "dedup_key TEXT" in incidents_block
    assert "source_system TEXT" in incidents_block


def test_ensure_schema_emits_idempotent_alter_table_add_column_statements() -> None:
    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)
    store.ensure_schema()

    statements = [sql for sql, _ in conn.cursor_instance.executed]

    assert any(
        "ALTER TABLE work_items" in sql
        and "ADD COLUMN IF NOT EXISTS dedup_key TEXT" in sql
        for sql in statements
    )
    assert any(
        "ALTER TABLE incidents" in sql
        and "ADD COLUMN IF NOT EXISTS source_system TEXT" in sql
        for sql in statements
    )
    assert any(
        "ALTER TABLE incidents" in sql
        and "ADD COLUMN IF NOT EXISTS dedup_key TEXT" in sql
        for sql in statements
    )


def test_save_work_item_writes_dedup_key_as_independent_column() -> None:
    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)

    # WorkItem.dedup_key is being added by a parallel task; until it lands,
    # the storage layer must still accept a work item without the attribute
    # and must read it via getattr when it exists. Here we simulate the
    # post-migration world by attaching dedup_key dynamically.
    work_item = WorkItem(
        work_item_id="wi_dedup",
        type=WorkItemType.FEATURE,
        title="T",
        goal="G",
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.PLANNING,
        repo="acme/platform",
        constraints={},
        acceptance_criteria=(),
    )
    # Use object.__setattr__ to bypass frozen dataclass; this mirrors the
    # attribute shape Agent A's change will produce.
    try:
        object.__setattr__(work_item, "dedup_key", "wi-dedup-key-001")
    except (AttributeError, TypeError):
        # Slots-based frozen dataclass without dedup_key slot — skip until
        # the domain model is updated in parallel work.
        import pytest

        pytest.skip("WorkItem.dedup_key not yet added to domain model")

    store.save_work_item(work_item)

    insert_statements = [
        (sql, params)
        for sql, params in conn.cursor_instance.executed
        if "INSERT INTO work_items" in sql
    ]
    assert insert_statements, "expected INSERT INTO work_items statement"
    sql, params = insert_statements[0]
    assert "dedup_key" in sql
    assert "wi-dedup-key-001" in params


def test_save_incident_writes_source_system_and_dedup_key_as_independent_columns() -> None:
    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)

    incident = {
        "incidentId": "inc_001",
        "workItemId": None,
        "severity": "high",
        "status": "open",
        "sourceSystem": "pagerduty",
        "dedupKey": "pd-alert-42",
        "message": "boom",
    }

    store.save_incident(incident)

    insert_statements = [
        (sql, params)
        for sql, params in conn.cursor_instance.executed
        if "INSERT INTO incidents" in sql
    ]
    assert insert_statements, "expected INSERT INTO incidents statement"
    sql, params = insert_statements[0]
    assert "source_system" in sql
    assert "dedup_key" in sql
    assert "pagerduty" in params
    assert "pd-alert-42" in params


def test_save_incident_excludes_source_system_and_dedup_key_from_payload_json() -> None:
    import json

    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)

    incident = {
        "incidentId": "inc_002",
        "workItemId": None,
        "severity": "high",
        "status": "open",
        "sourceSystem": "pagerduty",
        "dedupKey": "pd-alert-42",
        "message": "boom",
    }

    store.save_incident(incident)

    insert_statements = [
        (sql, params)
        for sql, params in conn.cursor_instance.executed
        if "INSERT INTO incidents" in sql
    ]
    assert insert_statements, "expected INSERT INTO incidents statement"
    _, params = insert_statements[0]
    # Per D3: payload_json must not duplicate the independent columns.
    payload_json = params[4]
    decoded = json.loads(payload_json)
    assert "sourceSystem" not in decoded
    assert "dedupKey" not in decoded
    # Other incident fields still land in payload_json.
    assert decoded["incidentId"] == "inc_002"
    assert decoded["message"] == "boom"


def test_get_incident_returns_top_level_source_system_and_dedup_key() -> None:
    import json

    conn = RecordingConnection()
    payload_json = json.dumps(
        {
            "incidentId": "inc_001",
            "severity": "high",
            "status": "open",
            "sourceSystem": "pagerduty",
            "dedupKey": "pd-alert-42",
        },
        sort_keys=True,
    )
    conn.cursor_instance.fetchone_result = (payload_json, "pagerduty", "pd-alert-42")

    store = ControlPlanePostgresStore(lambda: conn)
    incident = store.get_incident("inc_001")

    assert incident is not None
    assert incident["sourceSystem"] == "pagerduty"
    assert incident["dedupKey"] == "pd-alert-42"

    select_sql = [sql for sql, _ in conn.cursor_instance.executed if "FROM incidents" in sql]
    assert select_sql, "expected SELECT FROM incidents"
    assert "source_system" in select_sql[0]
    assert "dedup_key" in select_sql[0]


def test_list_incidents_returns_top_level_source_system_and_dedup_key() -> None:
    import json

    conn = RecordingConnection()
    payload_json = json.dumps(
        {
            "incidentId": "inc_001",
            "severity": "high",
            "status": "open",
            "sourceSystem": "pagerduty",
            "dedupKey": "pd-alert-42",
        },
        sort_keys=True,
    )
    conn.cursor_instance.fetchall_result = [(payload_json, "pagerduty", "pd-alert-42")]

    store = ControlPlanePostgresStore(lambda: conn)
    incidents = store.list_incidents()

    assert len(incidents) == 1
    assert incidents[0]["sourceSystem"] == "pagerduty"
    assert incidents[0]["dedupKey"] == "pd-alert-42"


def test_get_work_item_returns_dedup_key_top_level() -> None:
    import json

    conn = RecordingConnection()
    # cursor() on RecordingConnection always returns the same instance, so both
    # the work_items SELECT and the follow-up context_pack lookup share state.
    # Use fetchone that returns work_item row first, then None for context pack.
    rows = [
        (
            "wi_dedup",
            "feature",
            "T",
            "G",
            "high",
            "planning",
            "acme/platform",
            "{}",
            "[]",
            "qa",
            0,
            "manual",
            "{}",
            "wi-dedup-key-001",
        ),
        None,
    ]

    def _fetchone() -> tuple | None:
        return rows.pop(0) if rows else None

    conn.cursor_instance.fetchone = _fetchone  # type: ignore[assignment]

    store = ControlPlanePostgresStore(lambda: conn)
    record = store.get_work_item("wi_dedup")

    assert record is not None
    assert record["workItem"]["dedupKey"] == "wi-dedup-key-001"

    select_sql = [sql for sql, _ in conn.cursor_instance.executed if "FROM work_items" in sql]
    assert select_sql, "expected SELECT FROM work_items"
    assert "dedup_key" in select_sql[0]
