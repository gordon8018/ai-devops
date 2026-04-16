# Package 2 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成包 2 的原子写路径收敛：为 Console / Release / Incident 三条真实写路径引入统一 mutation 抽象，消除分散的 `save -> audit -> event` 反模式，并用测试固定失败语义。

**Architecture:** 本包不做 transactional outbox，也不引入数据库事务协调器。实现策略是先引入一个共享 `MutationService`，把“状态写入成功后才能写 audit，audit 成功后才能发事件”这条顺序抽象出来；在需要时用显式 rollback 闭包恢复内存状态和持久化快照，避免出现 audit 已写但状态未写，或状态已改但 event 误发的半成品结果。包 2 只收敛写路径，不改状态机，不改执行入口。

**Tech Stack:** Python 3.12, pytest, existing control-plane store interfaces, runtime_state audit recorder, EventManager bridge

---

## 决策冻结

- `P2-D1`: 不做 transactional outbox；事件发布仍是进程内 publish，但必须在 state + audit 成功后才执行。
- `P2-D2`: 共享抽象放在 `packages/shared/mutation/`，避免仅由 Kernel 独占。
- `P2-D3`: 对需要“失败后回滚状态”的路径，显式传入 `rollback()` 闭包；不做隐式魔法快照。
- `P2-D4`: 本包只改三条真实写路径：
  - `apps/console_api/service.py`
  - `apps/release_worker/service.py`
  - `apps/incident_worker/service.py`
- `P2-D5`: `publish_alert()` 这类外部副作用视为 domain event 之后的附加动作；先不纳入“必须回滚”的范围。

## 文件边界

### 需要新增

- `packages/shared/mutation/__init__.py`
  - 导出 mutation 抽象
- `packages/shared/mutation/service.py`
  - 提供 `MutationService`
  - 定义 `MutationStepResult` / `MutationContext` 等最小对象
- `tests/test_mutation_service.py`
  - 覆盖成功、state 写失败、audit 写失败、event 发布失败、rollback 被调用等语义

### 需要修改

- `apps/console_api/service.py`
  - `create_work_item()` 改走 mutation 抽象
- `apps/release_worker/service.py`
  - `advance()` / `_handle_task_status()` / `_handle_system_event()` 改走 mutation 抽象
- `apps/incident_worker/service.py`
  - `_ingest_alert()` / `_verify_incident()` 改走 mutation 抽象
- `tests/test_console_work_items_service.py`
  - 补 state/audit/event 顺序与失败场景测试
- `tests/test_release_worker.py`
  - 补 mutation 路径失败测试
- `tests/test_incident_worker.py`
  - 补 mutation 路径失败测试
- `docs/architecture/package-2-acceptance.md`
  - 验收步骤与预期
- `scripts/package_2_acceptance.py`
  - 真链路脚本，验证 mutation 抽象已接管真实写路径

---

## PR-2.1 引入共享 Mutation 抽象

### Task 1: 为 MutationService 固定“先状态、后审计、再事件”的成功语义

**Files:**
- Create: `packages/shared/mutation/service.py`
- Create: `packages/shared/mutation/__init__.py`
- Test: `tests/test_mutation_service.py`

- [ ] **Step 1: 写失败测试，固定成功顺序**

```python
from packages.shared.mutation.service import MutationService


def test_mutation_service_runs_state_then_audit_then_events() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()
    service.apply(
        persist=persist,
        audit=audit,
        publish_events=[publish],
    )

    assert calls == ["persist", "audit", "publish"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_mutation_service.py::test_mutation_service_runs_state_then_audit_then_events -v`

Expected: FAIL，因为 `MutationService` 还不存在。

- [ ] **Step 3: 最小实现 MutationService**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class MutationService:
    def apply(
        self,
        *,
        persist: Callable[[], None],
        audit: Callable[[], None],
        publish_events: list[Callable[[], None]] | tuple[Callable[[], None], ...] = (),
        rollback: Callable[[], None] | None = None,
    ) -> None:
        persist()
        try:
            audit()
        except Exception:
            if rollback is not None:
                rollback()
            raise
        for publish in publish_events:
            publish()
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_mutation_service.py::test_mutation_service_runs_state_then_audit_then_events -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/shared/mutation/service.py packages/shared/mutation/__init__.py tests/test_mutation_service.py
git commit -m "feat: add shared mutation service"
```

### Task 2: 固定失败语义，防止出现 audit/event 幽灵写入

**Files:**
- Modify: `packages/shared/mutation/service.py`
- Test: `tests/test_mutation_service.py`

- [ ] **Step 1: 写失败测试，state 写失败时 audit/event 不执行**

```python
import pytest

from packages.shared.mutation.service import MutationService


def test_mutation_service_skips_audit_and_events_when_persist_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")
        raise RuntimeError("persist failed")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()

    with pytest.raises(RuntimeError, match="persist failed"):
        service.apply(persist=persist, audit=audit, publish_events=[publish])

    assert calls == ["persist"]
```

- [ ] **Step 2: 写失败测试，audit 失败时 rollback 被调用且 event 不执行**

```python
def test_mutation_service_rolls_back_when_audit_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")
        raise RuntimeError("audit failed")

    def rollback() -> None:
        calls.append("rollback")

    def publish() -> None:
        calls.append("publish")

    service = MutationService()

    with pytest.raises(RuntimeError, match="audit failed"):
        service.apply(
            persist=persist,
            audit=audit,
            publish_events=[publish],
            rollback=rollback,
        )

    assert calls == ["persist", "audit", "rollback"]
```

- [ ] **Step 3: 写失败测试，event 发布失败时错误向外冒泡**

```python
def test_mutation_service_raises_when_event_publish_fails() -> None:
    calls: list[str] = []

    def persist() -> None:
        calls.append("persist")

    def audit() -> None:
        calls.append("audit")

    def publish() -> None:
        calls.append("publish")
        raise RuntimeError("publish failed")

    service = MutationService()

    with pytest.raises(RuntimeError, match="publish failed"):
        service.apply(
            persist=persist,
            audit=audit,
            publish_events=[publish],
        )

    assert calls == ["persist", "audit", "publish"]
```

- [ ] **Step 4: 运行测试，确认失败**

Run: `pytest tests/test_mutation_service.py -v`

Expected: FAIL，直到失败语义被完整实现。

- [ ] **Step 5: 最小实现失败语义**

```python
class MutationService:
    def apply(...):
        persist()
        try:
            audit()
        except Exception:
            if rollback is not None:
                rollback()
            raise
        for publish in publish_events:
            publish()
```

说明：event 发布失败不触发 rollback，这是本包的冻结决策；event 属于 state+audit 成功后的后置副作用。

- [ ] **Step 6: 运行测试，确认通过**

Run: `pytest tests/test_mutation_service.py -v`

Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add packages/shared/mutation/service.py tests/test_mutation_service.py
git commit -m "test: lock mutation failure semantics"
```

---

## PR-2.2 切换三条真实写路径

### Task 3: Console create_work_item 改走 MutationService

**Files:**
- Modify: `apps/console_api/service.py`
- Test: `tests/test_console_work_items_service.py`

- [ ] **Step 1: 写失败测试，固定 create_work_item 的写入顺序**

```python
from apps.console_api.service import WorkItemsApplicationService


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def save_work_item(self, work_item) -> None:
        self.calls.append("save_work_item")

    def save_context_pack(self, context_pack) -> None:
        self.calls.append("save_context_pack")


def test_console_create_work_item_persists_before_audit() -> None:
    calls: list[str] = []
    store = RecordingStore()
    service = WorkItemsApplicationService(
        persistence_store=store,
        audit_recorder=lambda event: calls.append("audit"),
    )

    service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Mutation ordering",
            "description": "Console writes should be ordered",
        }
    )

    assert store.calls == ["save_work_item", "save_context_pack"]
    assert calls == ["audit"]
```

- [ ] **Step 2: 写失败测试，state 写失败时不写 audit**

```python
import pytest


class FailingStore:
    def save_work_item(self, work_item) -> None:
        raise RuntimeError("store write failed")


def test_console_create_work_item_skips_audit_when_store_write_fails() -> None:
    calls: list[str] = []
    service = WorkItemsApplicationService(
        persistence_store=FailingStore(),
        audit_recorder=lambda event: calls.append("audit"),
    )

    with pytest.raises(RuntimeError, match="store write failed"):
        service.create_work_item(
            {
                "repo": "acme/platform",
                "title": "Mutation ordering",
                "description": "Console writes should be ordered",
            }
        )

    assert calls == []
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `pytest tests/test_console_work_items_service.py::test_console_create_work_item_persists_before_audit tests/test_console_work_items_service.py::test_console_create_work_item_skips_audit_when_store_write_fails -v`

Expected: FAIL，当前代码还没有共享 mutation 抽象。

- [ ] **Step 4: 最小实现 Console mutation 路径**

```python
from packages.shared.mutation.service import MutationService


class WorkItemsApplicationService:
    def __init__(...):
        ...
        self._mutation_service = MutationService()

    def create_work_item(self, payload: dict) -> dict:
        ...
        self._mutation_service.apply(
            persist=lambda: self._persist_created_work_item(session),
            audit=lambda: self._audit_recorder(AuditEvent(...)),
        )
        return record
```

- [ ] **Step 5: 运行 Console 相关回归**

Run: `pytest tests/test_console_work_items_service.py -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/console_api/service.py tests/test_console_work_items_service.py
git commit -m "refactor: route console work item writes through mutation service"
```

### Task 4: ReleaseWorker 三条写路径改走 MutationService

**Files:**
- Modify: `apps/release_worker/service.py`
- Test: `tests/test_release_worker.py`

- [ ] **Step 1: 写失败测试，固定 release_started 的 state/audit 顺序**

```python
from apps.release_worker.service import ReleaseWorker
from orchestrator.api.events import Event, EventManager, EventType


class RecordingStore:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_release(self, release: dict) -> None:
        self.saved.append(dict(release))


def test_release_worker_writes_state_before_audit_on_start() -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    store = RecordingStore()
    worker = ReleaseWorker(
        event_manager=event_manager,
        persistence_store=store,
    )
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.TASK_STATUS,
            data={"task_id": "wi_001", "status": "ready", "details": {"work_item_id": "wi_001"}},
            source="test",
        )
    )

    assert len(store.saved) == 1
    assert store.saved[0]["workItemId"] == "wi_001"
    worker.stop()
```

- [ ] **Step 2: 写失败测试，audit 失败时 release 状态回滚**

```python
import pytest


def test_release_worker_rolls_back_state_when_audit_write_fails(monkeypatch) -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    store = RecordingStore()
    worker = ReleaseWorker(event_manager=event_manager, persistence_store=store)

    monkeypatch.setattr(
        "apps.release_worker.service.record_audit_event",
        lambda event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    worker.start()
    with pytest.raises(RuntimeError, match="audit failed"):
        event_manager.publish(
            Event(
                event_type=EventType.TASK_STATUS,
                data={"task_id": "wi_001", "status": "ready", "details": {"work_item_id": "wi_001"}},
                source="test",
            )
        )

    assert worker.get_release("wi_001") is None
    worker.stop()
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `pytest tests/test_release_worker.py::test_release_worker_writes_state_before_audit_on_start tests/test_release_worker.py::test_release_worker_rolls_back_state_when_audit_write_fails -v`

Expected: FAIL

- [ ] **Step 4: 最小实现 Release mutation 路径**

```python
from packages.shared.mutation.service import MutationService

self._mutation_service = MutationService()

self._mutation_service.apply(
    persist=lambda: store.save_release(release),
    audit=lambda: record_audit_event(AuditEvent(...)),
    rollback=lambda: self._rollback_release_state(work_item_id, previous_release),
)
```

说明：`publish_alert()` 保持在 mutation 之后，不纳入 rollback。

- [ ] **Step 5: 运行 Release 回归**

Run: `pytest tests/test_release_worker.py -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/release_worker/service.py tests/test_release_worker.py
git commit -m "refactor: route release writes through mutation service"
```

### Task 5: IncidentWorker 两条写路径改走 MutationService

**Files:**
- Modify: `apps/incident_worker/service.py`
- Test: `tests/test_incident_worker.py`

- [ ] **Step 1: 写失败测试，audit 失败时新 incident 不保留**

```python
import pytest

from apps.incident_worker.service import IncidentWorker
from orchestrator.api.events import Event, EventManager, EventType


def test_incident_worker_rolls_back_new_incident_when_audit_fails(monkeypatch) -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)

    monkeypatch.setattr(
        "apps.incident_worker.service.record_audit_event",
        lambda event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    worker.start()
    with pytest.raises(RuntimeError, match="audit failed"):
        event_manager.publish(
            Event(
                event_type=EventType.ALERT,
                data={"level": "error", "message": "Checkout timeout in payment service"},
                source="test",
            )
        )

    assert worker.list_incidents() == []
    worker.stop()
```

- [ ] **Step 2: 写失败测试，verify 路径 audit 失败时 closed 回滚回原状态**

```python
def test_incident_worker_rolls_back_verify_status_when_audit_fails(monkeypatch) -> None:
    event_manager = EventManager()
    event_manager.clear_history()
    worker = IncidentWorker(event_manager=event_manager)
    worker.start()

    event_manager.publish(
        Event(
            event_type=EventType.ALERT,
            data={"level": "error", "message": "Checkout timeout in payment service"},
            source="test",
        )
    )
    incident_id = worker.list_incidents()[0]["incidentId"]

    monkeypatch.setattr(
        "apps.incident_worker.service.record_audit_event",
        lambda event: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        event_manager.publish(
            Event(
                event_type=EventType.SYSTEM,
                data={"type": "incident_verify", "incident_id": incident_id, "resolved": True},
                source="test",
            )
        )

    assert worker.get_incident(incident_id)["status"] == "open"
    worker.stop()
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `pytest tests/test_incident_worker.py::test_incident_worker_rolls_back_new_incident_when_audit_fails tests/test_incident_worker.py::test_incident_worker_rolls_back_verify_status_when_audit_fails -v`

Expected: FAIL

- [ ] **Step 4: 最小实现 Incident mutation 路径**

```python
from packages.shared.mutation.service import MutationService

self._mutation_service = MutationService()

self._mutation_service.apply(
    persist=lambda: store.save_incident(incident),
    audit=lambda: record_audit_event(AuditEvent(...)),
    rollback=lambda: self._restore_incident_state(incident_id, previous_incident),
)
```

- [ ] **Step 5: 运行 Incident 回归**

Run: `pytest tests/test_incident_worker.py -v`

Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add apps/incident_worker/service.py tests/test_incident_worker.py
git commit -m "refactor: route incident writes through mutation service"
```

---

## PR-2.3 包 2 真链路验收与文档

### Task 6: 增加包 2 验收脚本

**Files:**
- Create: `scripts/package_2_acceptance.py`

- [ ] **Step 1: 编写验收脚本**

```python
from apps.console_api.service import WorkItemsApplicationService
from packages.shared.domain.runtime_state import clear_runtime_state, list_audit_events


def main() -> int:
    clear_runtime_state()
    service = WorkItemsApplicationService()
    record = service.create_work_item(
        {
            "repo": "acme/platform",
            "title": "Package 2 acceptance",
            "description": "Verify mutation service owns real write paths",
        }
    )
    audits = list_audit_events()
    print(
        {
            "work_item_id": record["workItem"]["workItemId"],
            "audit_actions": [item["action"] for item in audits],
            "audit_actors": [item["actorId"] for item in audits],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 运行脚本**

Run: `python3 scripts/package_2_acceptance.py`

Expected: 输出包含 `work_item_created` 与对应 actor。

- [ ] **Step 3: 提交**

```bash
git add scripts/package_2_acceptance.py
git commit -m "test: add package 2 acceptance script"
```

### Task 7: 增加包 2 验收文档

**Files:**
- Create: `docs/architecture/package-2-acceptance.md`

- [ ] **Step 1: 写验收文档**

文档必须包含：

```markdown
# Package 2 Acceptance

## Scope
- Shared mutation service
- Console / Release / Incident write-path migration
- Failure semantics for persist / audit / publish

## Commands
```bash
pytest tests/test_mutation_service.py tests/test_console_work_items_service.py tests/test_release_worker.py tests/test_incident_worker.py -v
python3 scripts/package_2_acceptance.py
```

## Expected
- persist 失败时不写 audit/event
- audit 失败时 rollback 执行
- event publish 失败时错误向外冒泡
- 真实写路径都通过 MutationService
```
```

- [ ] **Step 2: 提交**

```bash
git add docs/architecture/package-2-acceptance.md
git commit -m "docs: add package 2 acceptance checklist"
```

### Task 8: 跑包 2 最终回归

**Files:**
- No code changes required unless regressions appear

- [ ] **Step 1: 跑包 2 相关测试**

Run:

```bash
pytest tests/test_mutation_service.py tests/test_console_work_items_service.py tests/test_release_worker.py tests/test_incident_worker.py tests/test_runtime_state.py -v
```

Expected: PASS

- [ ] **Step 2: 跑验收脚本**

Run:

```bash
python3 scripts/package_2_acceptance.py
```

Expected: 输出 mutation 相关审计结果，无异常。

- [ ] **Step 3: 检查工作区**

Run:

```bash
git status --short
```

Expected: 仅剩本包相关变更。

---

## 包 2 完成定义

包 2 完成时，必须同时满足下面五条：

1. 共享 `MutationService` 已存在，并有独立测试固定成功/失败语义。
2. Console `create_work_item()` 已通过 `MutationService` 落状态和审计。
3. ReleaseWorker 的 `start / advance / rollback` 相关写路径已通过 `MutationService` 收敛。
4. IncidentWorker 的 `ingest / verify` 写路径已通过 `MutationService` 收敛。
5. 有独立验收脚本和验收文档，能证明 mutation 抽象已经接管真实写路径。

## 明确不在本包内

- 不做 transactional outbox
- 不做 PolicyDecision 持久化治理链
- 不改 `spawn_agent` 入口
- 不补完整状态机
- 不引入数据库连接池
