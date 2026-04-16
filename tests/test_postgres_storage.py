from __future__ import annotations

from packages.kernel.storage.postgres import ControlPlanePostgresStore, control_plane_schema_sql
from packages.shared.domain.models import AuditEvent, ContextPack, EvalRun, EvalRunStatus, RiskProfile, WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


class RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params or ()))

    def fetchall(self) -> list[tuple]:
        return []


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
