# Package 0 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成契约修复的前置清理：修复 Release 阶段推进阻塞 bug，补齐 `succeeded` 终态，并为 `dedup_key` / `source_system` 预留稳定 schema，不改变现有总线、mutation 抽象和大状态机。

**Architecture:** 本包严格限制在前置清理范围。Release 推进采用显式方法调用 `advance(work_item_id)`，不引入自动调度；数据库迁移采用现有代码内嵌 `ALTER TABLE ... ADD COLUMN` 方式，不引入 Alembic；Incident 的 `source_system` / `dedup_key` 作为一等字段落库，避免后续从 `payload_json` 再做一次迁移。

**Tech Stack:** Python 3.12, pytest, SQLite, PostgreSQL-compatible control-plane store, existing release/incident workers

---

## 决策冻结

- `D1`: Release 推进触发方式采用 `β`，即显式方法调用，无自动调度。
- `D2`: PostgreSQL 列加法采用 `β`，即 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，不引入 Alembic。
- `D3`: Incident 的 `source_system` / `dedup_key` 采用一等字段和独立列，不放入 `payload_json`。
- `D4`: “异常收敛 / dead-letter” 从包 0 移除，留到包 3 和 `spawn_agent` 路径一起处理。

## 文件边界

### 需要修改

- `apps/release_worker/service.py`
  - 新增显式推进方法 `advance(work_item_id)`
  - 修复 stage 推进逻辑，支持推进到 `full` 后写 `succeeded`
- `packages/release/rollout/service.py`
  - 明确 stage 序列和 `next_stage(current_stage)` 行为
- `packages/shared/domain/models.py`
  - `WorkItem` 新增 `dedup_key`
- `packages/kernel/storage/postgres.py`
  - `work_items` / `incidents` 表加新列
  - `ensure_schema()` 增加增量列迁移
  - `save/get/list` 读写带上 `dedup_key` / `source_system`
- `orchestrator/bin/db.py`
  - SQLite `agent_tasks` 表增量加 `dedup_key`
  - dual-write 到 control plane 时带出 `dedup_key`
- `apps/incident_worker/service.py`
  - `incident` dict 新增顶层键 `sourceSystem` / `dedupKey`
  - 写入和读取都走独立字段

### 需要新增或扩展测试

- `tests/test_release_worker.py`
- `tests/test_release_rollout.py`
- `tests/test_postgres_storage.py`
- `tests/test_db_dual_write.py`
- `tests/test_work_item_service.py`
- `tests/test_incident_worker.py`

### 需要新增验收工件

- `docs/architecture/package-0-acceptance.md`
  - 记录真任务联调步骤、命令、预期结果
- `scripts/package_0_acceptance.py`
  - 最小验收脚本，串起 ready -> release created -> 手动推进 -> succeeded 验证

---

## PR-0.1 Release 推进修复

### Task 1: 为 RolloutController 明确阶段序列

**Files:**
- Modify: `packages/release/rollout/service.py`
- Test: `tests/test_release_rollout.py`

- [ ] **Step 1: 写失败测试，固定阶段推进序列**

```python
from packages.release.rollout.service import RolloutController


def test_next_stage_advances_in_order_until_full() -> None:
    controller = RolloutController()

    assert controller.next_stage("unknown") == "team-only"
    assert controller.next_stage("team-only") == "beta"
    assert controller.next_stage("beta") == "1%"
    assert controller.next_stage("1%") == "5%"
    assert controller.next_stage("5%") == "20%"
    assert controller.next_stage("20%") == "full"
    assert controller.next_stage("full") == "full"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_release_rollout.py::test_next_stage_advances_in_order_until_full -v`

Expected: FAIL，因为当前 `next_stage()` 还没有覆盖完整推进语义或现有测试未锁定这一行为。

- [ ] **Step 3: 最小实现阶段推进**

```python
class RolloutController:
    STAGES = ("team-only", "beta", "1%", "5%", "20%", "full")

    def next_stage(self, current_stage: str) -> str:
        normalized = str(current_stage or "unknown").strip().lower()
        if normalized not in self.STAGES:
            return self.STAGES[0]
        index = self.STAGES.index(normalized)
        if index >= len(self.STAGES) - 1:
            return self.STAGES[-1]
        return self.STAGES[index + 1]
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_release_rollout.py::test_next_stage_advances_in_order_until_full -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/release/rollout/service.py tests/test_release_rollout.py
git commit -m "fix: correct rollout stage progression"
```

### Task 2: 给 ReleaseWorker 增加显式推进方法

**Files:**
- Modify: `apps/release_worker/service.py`
- Test: `tests/test_release_worker.py`

- [ ] **Step 1: 写失败测试，显式调用 `advance()` 推进 release**

```python
from apps.release_worker.service import ReleaseWorker
from orchestrator.api.events import Event, EventManager, EventType


class RecordingFlagAdapter:
    def __init__(self) -> None:
        self.applied: list[tuple[str, str]] = []

    def apply_stage(self, release_id: str, stage: str) -> None:
        self.applied.append((release_id, stage))


def test_release_worker_advance_moves_stage_to_full_and_marks_succeeded() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={"task_id": "wi_advance", "status": "ready", "details": {"work_item_id": "wi_advance"}},
            source="test",
        )
    )

    for _ in range(5):
        worker.advance("wi_advance")

    release = worker.get_release("wi_advance")

    assert release is not None
    assert release["stage"] == "full"
    assert release["status"] == "succeeded"
    worker.stop()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_release_worker.py::test_release_worker_advance_moves_stage_to_full_and_marks_succeeded -v`

Expected: FAIL，因为当前 `ReleaseWorker` 没有 `advance()`，且 `status` 不会写成 `succeeded`

- [ ] **Step 3: 最小实现 `advance()` 与 `succeeded` 终态**

```python
class ReleaseWorker:
    ...

    def advance(self, work_item_id: str) -> dict[str, Any] | None:
        release = self.get_release(work_item_id)
        if release is None:
            return None
        if release.get("status") in {"rolled_back", "succeeded"}:
            return release

        current_stage = str(release.get("stage") or "unknown")
        next_stage = self._rollout_controller.next_stage(current_stage)
        release["stage"] = next_stage
        if next_stage == "full":
            release["status"] = "succeeded"

        self._releases[work_item_id] = release
        store = self._store()
        if store is not None and hasattr(store, "save_release"):
            store.save_release(release)
        self._flag_adapter.apply_stage(release["releaseId"], next_stage)
        return release
```

- [ ] **Step 4: 把初次创建 release 的逻辑改成只创建起始阶段**

```python
def _handle_task_status(self, payload: dict[str, Any]) -> None:
    ...
    release = {
        "releaseId": release_id,
        "workItemId": work_item_id,
        "stage": self._rollout_controller.next_stage("unknown"),
        "status": "rolling_out",
    }
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `pytest tests/test_release_worker.py -v`

Expected: PASS，且现有 rollback 用例不回归

- [ ] **Step 6: 提交**

```bash
git add apps/release_worker/service.py tests/test_release_worker.py
git commit -m "fix: add explicit release advancement"
```

### Task 3: 为 succeeded 写持久化与事件断言

**Files:**
- Modify: `apps/release_worker/service.py`
- Test: `tests/test_release_worker.py`

- [ ] **Step 1: 写失败测试，要求 `succeeded` 产生可观察记录**

```python
def test_release_worker_records_succeeded_state_when_full_stage_reached() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    flag_adapter = RecordingFlagAdapter()
    worker = ReleaseWorker(event_manager=event_manager, flag_adapter=flag_adapter)
    worker.start()
    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={"task_id": "wi_success", "status": "ready", "details": {"work_item_id": "wi_success"}},
            source="test",
        )
    )

    for _ in range(5):
        worker.advance("wi_success")

    release = worker.get_release("wi_success")
    assert release is not None
    assert release["status"] == "succeeded"
    worker.stop()
```

- [ ] **Step 2: 运行测试，确认失败或缺少持久化行为**

Run: `pytest tests/test_release_worker.py::test_release_worker_records_succeeded_state_when_full_stage_reached -v`

Expected: FAIL，若 `advance()` 尚未正确写回或状态未终止

- [ ] **Step 3: 最小补全持久化逻辑**

```python
if store is not None and hasattr(store, "save_release"):
    store.save_release(release)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_release_worker.py::test_release_worker_records_succeeded_state_when_full_stage_reached -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add apps/release_worker/service.py tests/test_release_worker.py
git commit -m "fix: persist succeeded release state"
```

---

## PR-0.2 dedup_key / source_system schema 扩展

### Task 4: 给 WorkItem 增加 `dedup_key`

**Files:**
- Modify: `packages/shared/domain/models.py`
- Test: `tests/test_work_item_service.py`

- [ ] **Step 1: 写失败测试，要求 WorkItem 保留 `dedupKey`**

```python
from packages.shared.domain.models import WorkItem


def test_work_item_from_legacy_task_input_preserves_dedup_key() -> None:
    work_item = WorkItem.from_legacy_task_input(
        {
            "repo": "acme/platform",
            "title": "Add dedup key",
            "description": "Persist dedup key",
            "dedupKey": "delivery-001",
        }
    )

    assert work_item.to_dict()["dedupKey"] == "delivery-001"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_work_item_service.py::test_work_item_from_legacy_task_input_preserves_dedup_key -v`

Expected: FAIL，因为当前 `WorkItem` 没有 `dedup_key`

- [ ] **Step 3: 最小实现 `dedup_key` 字段**

```python
@dataclass(slots=True, frozen=True)
class WorkItem:
    ...
    dedup_key: str | None = None

    @classmethod
    def from_legacy_task_input(cls, task_input: dict[str, Any]) -> "WorkItem":
        ...
        dedup_key = str(task_input.get("dedupKey") or task_input.get("dedup_key") or "").strip() or None
        return cls(..., dedup_key=dedup_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            ...
            "dedupKey": self.dedup_key,
        }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_work_item_service.py::test_work_item_from_legacy_task_input_preserves_dedup_key -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/shared/domain/models.py tests/test_work_item_service.py
git commit -m "feat: add work item dedup key"
```

### Task 5: 给 PostgreSQL `work_items` / `incidents` 增量加列

**Files:**
- Modify: `packages/kernel/storage/postgres.py`
- Test: `tests/test_postgres_storage.py`

- [ ] **Step 1: 写失败测试，要求 schema 包含增量列迁移**

```python
from packages.kernel.storage.postgres import control_plane_schema_sql


def test_control_plane_schema_contains_dedup_and_source_columns() -> None:
    schema = control_plane_schema_sql()

    assert "dedup_key TEXT" in schema
    assert "source_system TEXT" in schema
```

- [ ] **Step 2: 写失败测试，要求 `ensure_schema()` 发出增量 `ALTER TABLE`**

```python
def test_ensure_schema_adds_missing_columns_in_place() -> None:
    conn = RecordingConnection()
    store = ControlPlanePostgresStore(lambda: conn)

    store.ensure_schema()

    statements = [sql for sql, _ in conn.cursor_instance.executed]
    assert any("ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dedup_key TEXT" in sql for sql in statements)
    assert any("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS source_system TEXT" in sql for sql in statements)
    assert any("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dedup_key TEXT" in sql for sql in statements)
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `pytest tests/test_postgres_storage.py -v`

Expected: FAIL，因为当前 schema 没有这些列，也没有增量 `ALTER TABLE`

- [ ] **Step 4: 最小实现列扩展**

```python
CREATE TABLE IF NOT EXISTS work_items (
    ...
    metadata_json TEXT NOT NULL,
    dedup_key TEXT
);

CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    work_item_id TEXT,
    source_system TEXT,
    dedup_key TEXT,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
```

```python
def ensure_schema(self) -> None:
    ...
    cursor.execute("ALTER TABLE work_items ADD COLUMN IF NOT EXISTS dedup_key TEXT")
    cursor.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS source_system TEXT")
    cursor.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dedup_key TEXT")
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `pytest tests/test_postgres_storage.py -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add packages/kernel/storage/postgres.py tests/test_postgres_storage.py
git commit -m "feat: add control plane dedup schema"
```

### Task 6: SQLite 和 dual-write 也带上 `dedup_key`

**Files:**
- Modify: `orchestrator/bin/db.py`
- Test: `tests/test_db_dual_write.py`

- [ ] **Step 1: 写失败测试，要求 dual-write 带出 `dedupKey`**

```python
def test_insert_task_mirrors_dedup_key_to_control_plane() -> None:
    store = RecordingStore()
    db_mod.enable_control_plane_dual_write(store)
    db_mod.init_db()

    db_mod.insert_task(
        {
            "id": "task-004",
            "repo": "acme/platform",
            "title": "Mirror dedup key",
            "status": "queued",
            "metadata": {"dedupKey": "delivery-004"},
        }
    )

    assert store.work_items[0]["dedupKey"] == "delivery-004"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_db_dual_write.py::test_insert_task_mirrors_dedup_key_to_control_plane -v`

Expected: FAIL，因为当前 `db.py` 不会把该字段映射到 `WorkItem`

- [ ] **Step 3: 最小实现 SQLite 迁移和映射**

```python
new_columns = [
    ...,
    ("dedup_key", "TEXT"),
]
```

```python
def _build_work_item_from_task(task: dict[str, Any]) -> WorkItem:
    metadata = _parse_metadata(task.get("metadata"))
    dedup_key = str(task.get("dedup_key") or metadata.get("dedupKey") or metadata.get("dedup_key") or "").strip() or None
    return WorkItem(..., dedup_key=dedup_key)
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_db_dual_write.py::test_insert_task_mirrors_dedup_key_to_control_plane -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add orchestrator/bin/db.py tests/test_db_dual_write.py
git commit -m "feat: mirror dedup key through sqlite dual write"
```

### Task 7: Incident 的 `sourceSystem` / `dedupKey` 升为顶层字段

**Files:**
- Modify: `apps/incident_worker/service.py`
- Modify: `packages/kernel/storage/postgres.py`
- Test: `tests/test_incident_worker.py`

- [ ] **Step 1: 写失败测试，要求 Incident 保留顶层 `sourceSystem` / `dedupKey`**

```python
from apps.incident_worker.service import IncidentWorker
from orchestrator.api.events import Event, EventManager, EventType


def test_incident_worker_preserves_source_system_and_dedup_key() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={
                "level": "error",
                "message": "Checkout timeout in payment service",
                "sourceSystem": "sentry",
                "dedupKey": "event-001",
                "details": {"service": "payments"},
            },
            source="test",
        )
    )

    incident = worker.list_incidents()[0]

    assert incident["sourceSystem"] == "sentry"
    assert incident["dedupKey"] == "event-001"
    worker.stop()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_incident_worker.py::test_incident_worker_preserves_source_system_and_dedup_key -v`

Expected: FAIL，因为当前 incident 顶层没有这两个键

- [ ] **Step 3: 最小实现 Incident 顶层字段**

```python
incident = {
    "incidentId": incident_id,
    "message": message,
    "sourceSystem": str(payload.get("sourceSystem") or payload.get("source_system") or "").strip() or None,
    "dedupKey": str(payload.get("dedupKey") or payload.get("dedup_key") or "").strip() or None,
    "severity": ...,
    "status": "open",
    "occurrenceCount": 0,
    "details": payload.get("details") or {},
}
```

- [ ] **Step 4: PostgreSQL Incident 存储带上这两个独立列**

```python
def save_incident(self, incident: dict) -> None:
    ...
    (
        incident["incidentId"],
        incident.get("workItemId"),
        incident.get("sourceSystem"),
        incident.get("dedupKey"),
        incident["severity"],
        incident["status"],
        json.dumps(incident, ensure_ascii=False, sort_keys=True),
    )
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `pytest tests/test_incident_worker.py -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/incident_worker/service.py packages/kernel/storage/postgres.py tests/test_incident_worker.py
git commit -m "feat: promote incident dedup fields"
```

---

## PR-0.3 真任务联调与验收工件

### Task 8: 编写包 0 验收脚本

**Files:**
- Create: `scripts/package_0_acceptance.py`
- Test: 手工执行

- [ ] **Step 1: 编写最小验收脚本**

```python
#!/usr/bin/env python3
from __future__ import annotations

from orchestrator.api.events import Event, EventManager, EventType
from apps.release_worker.service import ReleaseWorker


def main() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = ReleaseWorker(event_manager=event_manager)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={"task_id": "wi_pkg0", "status": "ready", "details": {"work_item_id": "wi_pkg0"}},
            source="package_0_acceptance",
        )
    )

    for _ in range(5):
        worker.advance("wi_pkg0")

    release = worker.get_release("wi_pkg0")
    if release is None:
        raise SystemExit("release not created")
    print(release)
    worker.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行脚本**

Run: `python3 scripts/package_0_acceptance.py`

Expected: 输出 `{"stage": "full", "status": "succeeded", ...}`

- [ ] **Step 3: 提交**

```bash
git add scripts/package_0_acceptance.py
git commit -m "test: add package 0 acceptance script"
```

### Task 9: 编写包 0 验收文档

**Files:**
- Create: `docs/architecture/package-0-acceptance.md`

- [ ] **Step 1: 写验收步骤**

```markdown
# Package 0 Acceptance

## Release advancement

1. 起任务，直到 work item 进入 `ready`
2. 确认 release 创建后 `stage=team-only`、`status=rolling_out`
3. 手动调用 `release_worker.advance(work_item_id)` 五次
4. 每次查询 `releases` 表，确认阶段依次推进：`beta -> 1% -> 5% -> 20% -> full`
5. 最后一次推进后确认 `status=succeeded`
6. 检查 audit journal 中存在对应记录

## dedup key persistence

1. 从 legacy 入口提交带 `dedupKey` 的任务
2. 查询 `work_items.dedup_key`
3. 提交不带 `dedupKey` 的任务，确认字段为 `NULL`

## incident dedup fields

1. 提交带 `sourceSystem` / `dedupKey` 的 alert
2. 查询 `incidents.source_system` / `incidents.dedup_key`
```

- [ ] **Step 2: 保存并检查内容**

Run: `sed -n '1,220p' docs/architecture/package-0-acceptance.md`

Expected: 文档完整，无 TODO / TBD

- [ ] **Step 3: 提交**

```bash
git add docs/architecture/package-0-acceptance.md
git commit -m "docs: add package 0 acceptance checklist"
```

### Task 10: 执行包 0 最终验收

**Files:**
- Run-only task

- [ ] **Step 1: 跑包 0 相关测试**

Run: `pytest tests/test_release_rollout.py tests/test_release_worker.py tests/test_postgres_storage.py tests/test_db_dual_write.py tests/test_work_item_service.py tests/test_incident_worker.py -v`

Expected: 全部 PASS

- [ ] **Step 2: 跑验收脚本**

Run: `python3 scripts/package_0_acceptance.py`

Expected: 打印 `stage=full` 且 `status=succeeded`

- [ ] **Step 3: 用真实任务链路复核一次**

Run:

```bash
python3 scripts/package_0_acceptance.py
```

Expected:
- release 创建后初始为 `team-only`
- 手动推进 5 次后到 `full`
- 最终状态为 `succeeded`
- 不带 `dedupKey` 的旧路径不报错

- [ ] **Step 4: 汇总结果并提交**

```bash
git add .
git commit -m "chore: complete package 0 acceptance"
```

---

## 自检

- 本计划只覆盖包 0：未引入 event bus 统一、mutation 抽象、Protocol 注入、状态机大改。
- 已显式固定四个 kickoff 决策：`D1-D4`。
- `包 2` 对 `包 1` 的依赖没有提前施工。
- 没有包含 `dead-letter`、`outbox`、`PolicyDecision` 治理链。

---

Plan complete and saved to `docs/architecture/package-0-execution-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. Inline Execution - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
