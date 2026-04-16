# Package 1 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成包 1 的事件统一改造：给 `Event` / `AuditEvent` 增加 actor 身份，桥接 `InMemoryEventBus` 与 `EventManager`，并让 Kernel 发出的细粒度领域事件能够被旧 worker 和 Console 路径接收。

**Architecture:** 本包不删除旧 `EventManager`，也不直接废弃 `InMemoryEventBus`。实现策略是先扩展统一事件 envelope 和 actor 字段，再用 bridge 把 Kernel 细粒度事件镜像到 legacy `EventManager`，最后把 `WorkItemService` 的关键发布路径切到标准领域事件。包 1 只解决“事件表达”和“总线打通”，不做 mutation 原子写、不做 outbox、不做状态机补齐。

**Tech Stack:** Python 3.12, pytest, existing EventManager journal, in-memory bridge adapter, control-plane domain models

---

## 决策冻结

- `P1-D1`: 保留两条 bus，先桥接，不直接删除 `InMemoryEventBus`。
- `P1-D2`: `actor_id` / `actor_type` 先采用带默认值的兼容加法：
  - `actor_id="system:legacy"`
  - `actor_type="system"`
- `P1-D3`: 保留 `EventType` 粗粒度分类；新增 `event_name` 承载细粒度领域事件名。
- `P1-D4`: 包 1 不引入 transactional outbox，不做状态写入 + audit + event 的原子化抽象。

## 文件边界

### 需要修改

- `orchestrator/api/events.py`
  - 给 `Event` 增加 `event_name` / `actor_id` / `actor_type`
  - 扩展 `to_dict()` / `to_json()` 输出
  - 补充细粒度事件的兼容发布能力
- `packages/shared/domain/models.py`
  - 给 `AuditEvent` 增加 `actor_id` / `actor_type`
- `packages/kernel/events/bus.py`
  - `EventEnvelope` 增加 actor / source 元数据
  - 引入 bridge hook 或桥接适配能力
- `packages/kernel/services/work_items.py`
  - 统一发标准领域事件 payload
  - 用包含 `old_status` / `new_status` 的状态迁移事件
- `apps/console_api/service.py`
  - 审计写入显式带 actor
- `apps/release_worker/service.py`
  - 审计写入显式带 actor
- `apps/incident_worker/service.py`
  - 审计写入显式带 actor
- `orchestrator/bin/zoe_tools.py`
  - 兼容新增 `AuditEvent` 字段
- `orchestrator/bin/db.py`
  - 兼容新增 `AuditEvent` 字段
- `packages/kernel/storage/migration.py`
  - 兼容新增 `AuditEvent` 字段

### 需要新增测试

- `tests/test_event_manager.py`
- `tests/test_kernel_event_bus.py`
- `tests/test_work_item_service.py`
- `tests/test_runtime_state.py`
- `tests/test_release_worker.py`
- `tests/test_incident_worker.py`
- 如有必要：`tests/test_console_work_items_service.py`

### 需要新增验收工件

- `scripts/package_1_acceptance.py`
- `docs/architecture/package-1-acceptance.md`

---

## PR-1.1 事件模型与 Actor 基础设施

### Task 1: 给 Event 增加细粒度事件名和 actor 字段

**Files:**
- Modify: `orchestrator/api/events.py`
- Test: `tests/test_event_manager.py`

- [ ] **Step 1: 写失败测试，固定 Event 的序列化契约**

```python
from orchestrator.api.events import Event, EventType


def test_event_to_dict_includes_event_name_and_actor_fields() -> None:
    event = Event(
        event_type=EventType.SYSTEM,
        event_name="work_item.created",
        data={"workItemId": "wi_001"},
        source="kernel",
        actor_id="system:kernel",
        actor_type="system",
    )

    payload = event.to_dict()

    assert payload["type"] == "system"
    assert payload["eventName"] == "work_item.created"
    assert payload["actorId"] == "system:kernel"
    assert payload["actorType"] == "system"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_event_manager.py::test_event_to_dict_includes_event_name_and_actor_fields -v`

Expected: FAIL，因为当前 `Event` 还没有 `event_name` / `actor_id` / `actor_type` 字段。

- [ ] **Step 3: 最小实现 Event 新字段和默认值**

```python
@dataclass
class Event:
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=lambda: time.time())
    source: Optional[str] = None
    event_name: str | None = None
    actor_id: str = "system:legacy"
    actor_type: str = "system"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type.value,
            "eventName": self.event_name,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
            "actorId": self.actor_id,
            "actorType": self.actor_type,
        }
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_event_manager.py::test_event_to_dict_includes_event_name_and_actor_fields -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add orchestrator/api/events.py tests/test_event_manager.py
git commit -m "feat: add actor fields to event envelope"
```

### Task 2: 保持 EventManager helper 的 legacy 兼容

**Files:**
- Modify: `orchestrator/api/events.py`
- Test: `tests/test_event_manager.py`

- [ ] **Step 1: 写失败测试，固定 helper 的默认 actor 与兼容事件名**

```python
from orchestrator.api.events import EventManager


def test_publish_task_status_sets_default_actor_and_legacy_event_name() -> None:
    manager = EventManager()
    manager.clear_history()

    manager.publish_task_status("task_001", "ready", {"work_item_id": "wi_001"}, source="test")

    history = manager.get_history(limit=1)

    assert history[0]["type"] == "task_status"
    assert history[0]["eventName"] == "task.status_changed"
    assert history[0]["actorId"] == "system:legacy"
    assert history[0]["actorType"] == "system"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_event_manager.py::test_publish_task_status_sets_default_actor_and_legacy_event_name -v`

Expected: FAIL，因为 helper 目前不会填充这些字段。

- [ ] **Step 3: 最小实现 helper 兼容输出**

```python
def publish_task_status(...):
    event = Event(
        event_type=EventType.TASK_STATUS,
        event_name="task.status_changed",
        data={
            "task_id": task_id,
            "status": status,
            "details": details or {},
        },
        source=source,
        actor_id="system:legacy",
        actor_type="system",
    )
    self.publish(event)
```

- [ ] **Step 4: 运行事件管理相关测试**

Run: `pytest tests/test_event_manager.py -v`

Expected: PASS，现有 history / journal 测试不回归。

- [ ] **Step 5: 提交**

```bash
git add orchestrator/api/events.py tests/test_event_manager.py
git commit -m "fix: keep legacy event helpers compatible with actor fields"
```

### Task 3: 给 AuditEvent 增加 actor 字段并兼容现有调用点

**Files:**
- Modify: `packages/shared/domain/models.py`
- Modify: `apps/console_api/service.py`
- Modify: `apps/release_worker/service.py`
- Modify: `apps/incident_worker/service.py`
- Modify: `orchestrator/bin/zoe_tools.py`
- Modify: `orchestrator/bin/db.py`
- Modify: `packages/kernel/storage/migration.py`
- Test: `tests/test_runtime_state.py`

- [ ] **Step 1: 写失败测试，固定 AuditEvent 的序列化契约**

```python
from packages.shared.domain.models import AuditEvent


def test_audit_event_to_dict_includes_actor_fields() -> None:
    event = AuditEvent(
        audit_event_id="audit_001",
        entity_type="work_item",
        entity_id="wi_001",
        action="created",
        actor_id="human:alice",
        actor_type="human",
        payload={"status": "queued"},
    )

    payload = event.to_dict()

    assert payload["actorId"] == "human:alice"
    assert payload["actorType"] == "human"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_runtime_state.py::test_audit_event_to_dict_includes_actor_fields -v`

Expected: FAIL，因为当前 `AuditEvent` 没有 actor 字段。

- [ ] **Step 3: 最小实现 AuditEvent actor 字段和默认值**

```python
@dataclass(slots=True, frozen=True)
class AuditEvent:
    audit_event_id: str
    entity_type: str
    entity_id: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    actor_id: str = "system:legacy"
    actor_type: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "auditEventId": self.audit_event_id,
            "entityType": self.entity_type,
            "entityId": self.entity_id,
            "action": self.action,
            "payload": self.payload,
            "createdAt": self.created_at,
            "actorId": self.actor_id,
            "actorType": self.actor_type,
        }
```

- [ ] **Step 4: 显式补齐核心写路径的 actor**

```python
AuditEvent(
    audit_event_id="...",
    entity_type="work_item",
    entity_id=work_item_id,
    action="created",
    payload={"status": "queued"},
    actor_id="human:console",
    actor_type="human",
)
```

对于 worker 和 legacy 路径，先使用系统 actor，例如：

```python
actor_id="system:release_worker"
actor_type="system"
```

- [ ] **Step 5: 运行审计相关测试**

Run: `pytest tests/test_runtime_state.py tests/test_release_worker.py tests/test_incident_worker.py -v`

Expected: PASS，现有写审计路径不回归。

- [ ] **Step 6: 提交**

```bash
git add packages/shared/domain/models.py apps/console_api/service.py apps/release_worker/service.py apps/incident_worker/service.py orchestrator/bin/zoe_tools.py orchestrator/bin/db.py packages/kernel/storage/migration.py tests/test_runtime_state.py tests/test_release_worker.py tests/test_incident_worker.py
git commit -m "feat: add actor fields to audit events"
```

---

## PR-1.2 两条 Event Bus 的桥接层

### Task 4: 扩展 EventEnvelope，给 Kernel 事件带上元数据

**Files:**
- Modify: `packages/kernel/events/bus.py`
- Test: `tests/test_kernel_event_bus.py`

- [ ] **Step 1: 写失败测试，固定 EventEnvelope 的 actor/source 字段**

```python
from packages.kernel.events.bus import InMemoryEventBus


def test_in_memory_event_bus_keeps_actor_and_source_metadata() -> None:
    bus = InMemoryEventBus()

    envelope = bus.publish(
        "work_item.created",
        {"workItemId": "wi_001"},
        source="kernel",
        actor_id="system:kernel",
        actor_type="system",
    )

    assert envelope.source == "kernel"
    assert envelope.actor_id == "system:kernel"
    assert envelope.actor_type == "system"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_kernel_event_bus.py::test_in_memory_event_bus_keeps_actor_and_source_metadata -v`

Expected: FAIL，因为当前 `EventEnvelope` 和 `publish()` 还不接受这些参数。

- [ ] **Step 3: 最小实现 EventEnvelope 元数据**

```python
@dataclass(slots=True, frozen=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    source: str | None = None
    actor_id: str = "system:legacy"
    actor_type: str = "system"


def publish(
    self,
    event_type: str,
    payload: dict[str, Any],
    *,
    source: str | None = None,
    actor_id: str = "system:legacy",
    actor_type: str = "system",
) -> EventEnvelope:
    envelope = EventEnvelope(
        event_type=event_type,
        payload=dict(payload),
        source=source,
        actor_id=actor_id,
        actor_type=actor_type,
    )
```

- [ ] **Step 4: 运行 kernel event bus 测试**

Run: `pytest tests/test_kernel_event_bus.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/kernel/events/bus.py tests/test_kernel_event_bus.py
git commit -m "feat: add metadata to kernel event envelopes"
```

### Task 5: 实现 InMemoryEventBus 到 EventManager 的 bridge

**Files:**
- Modify: `packages/kernel/events/bus.py`
- Modify: `orchestrator/api/events.py`
- Test: `tests/test_kernel_event_bus.py`
- Test: `tests/test_event_manager.py`

- [ ] **Step 1: 写失败测试，固定 bridge 发布行为**

```python
from orchestrator.api.events import EventManager
from packages.kernel.events.bus import InMemoryEventBus


def test_kernel_bus_bridge_publishes_domain_events_to_event_manager() -> None:
    manager = EventManager()
    manager.clear_history()
    bus = InMemoryEventBus(event_manager=manager)

    bus.publish(
        "work_item.created",
        {"workItemId": "wi_001"},
        source="kernel",
        actor_id="system:kernel",
        actor_type="system",
    )

    history = manager.get_history(limit=1)

    assert history[0]["eventName"] == "work_item.created"
    assert history[0]["data"]["workItemId"] == "wi_001"
    assert history[0]["actorId"] == "system:kernel"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_kernel_event_bus.py::test_kernel_bus_bridge_publishes_domain_events_to_event_manager -v`

Expected: FAIL，因为当前 bus 不会桥接到 `EventManager`。

- [ ] **Step 3: 最小实现 bridge**

```python
class InMemoryEventBus:
    def __init__(self, *, max_history: int = 200, event_manager=None) -> None:
        self._subscribers = []
        self._history = deque(maxlen=max_history)
        self._event_manager = event_manager

    def publish(...):
        ...
        if self._event_manager is not None:
            self._event_manager.publish(
                Event(
                    event_type=EventType.SYSTEM,
                    event_name=event_type,
                    data=dict(payload),
                    source=source,
                    actor_id=actor_id,
                    actor_type=actor_type,
                )
            )
```

避免递归桥接：bridge 只做 `Kernel -> EventManager` 单向镜像，不做反向订阅。

- [ ] **Step 4: 运行 bridge 相关测试**

Run: `pytest tests/test_kernel_event_bus.py tests/test_event_manager.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/kernel/events/bus.py orchestrator/api/events.py tests/test_kernel_event_bus.py tests/test_event_manager.py
git commit -m "feat: bridge kernel event bus into event manager"
```

---

## PR-1.3 Kernel 发布路径切到标准领域事件

### Task 6: WorkItemService 创建路径发标准领域事件

**Files:**
- Modify: `packages/kernel/services/work_items.py`
- Test: `tests/test_work_item_service.py`

- [ ] **Step 1: 写失败测试，固定 create_legacy_session 的桥接事件**

```python
from orchestrator.api.events import EventManager
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import WorkItemService


def test_create_legacy_session_bridges_domain_events_to_event_manager() -> None:
    manager = EventManager()
    manager.clear_history()
    bus = InMemoryEventBus(event_manager=manager)
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())

    service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Bridge work item events",
            "description": "Ensure domain events leave kernel bus",
        }
    )

    history = manager.get_history(limit=3)

    assert [event["eventName"] for event in history] == [
        "work_item.created",
        "context_pack.created",
        "plan.requested",
    ]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_work_item_service.py::test_create_legacy_session_bridges_domain_events_to_event_manager -v`

Expected: FAIL，当前 `WorkItemService` 虽然发布到 `InMemoryEventBus`，但未固定桥接语义。

- [ ] **Step 3: 最小实现标准发布元数据**

```python
self._event_bus.publish(
    "work_item.created",
    work_item.to_dict(),
    source="kernel.work_items",
    actor_id="system:kernel",
    actor_type="system",
)
```

对 `context_pack.created`、`plan.requested`、`agent_run.prepared` 采用同样模式。

- [ ] **Step 4: 运行 WorkItemService 测试**

Run: `pytest tests/test_work_item_service.py -v`

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/kernel/services/work_items.py tests/test_work_item_service.py
git commit -m "feat: publish standard domain events from work item service"
```

### Task 7: WorkItem 状态变更事件补齐 old/new status

**Files:**
- Modify: `packages/kernel/services/work_items.py`
- Test: `tests/test_work_item_service.py`

- [ ] **Step 1: 写失败测试，固定状态迁移 payload**

```python
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import WorkItemService
from packages.shared.domain.models import QualityRun, QualityRunStatus, WorkItemStatus


def test_transition_work_item_status_publishes_old_and_new_status() -> None:
    bus = InMemoryEventBus()
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())
    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Promote to released",
            "description": "Need structured status transition event",
        }
    )
    quality_run = QualityRun(
        quality_run_id="qr_001",
        work_item_id=session.work_item.work_item_id,
        gate_type="test",
        status=QualityRunStatus.PASSED,
    )

    service.transition_work_item_status(
        session.work_item,
        target_status=WorkItemStatus.RELEASED,
        quality_run=quality_run,
    )

    last_event = bus.history()[-1]
    assert last_event.event_type == "work_item.status_changed"
    assert last_event.payload["workItemId"] == session.work_item.work_item_id
    assert last_event.payload["oldStatus"] == session.work_item.status.value
    assert last_event.payload["newStatus"] == "released"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_work_item_service.py::test_transition_work_item_status_publishes_old_and_new_status -v`

Expected: FAIL，因为当前 payload 只有新状态，没有 old/new 成对字段。

- [ ] **Step 3: 最小实现状态迁移事件**

```python
self._event_bus.publish(
    "work_item.status_changed",
    {
        "workItemId": work_item.work_item_id,
        "oldStatus": work_item.status.value,
        "newStatus": target_status.value,
        "qualityRunId": quality_run.quality_run_id if quality_run else None,
    },
    source="kernel.work_items",
    actor_id="system:kernel",
    actor_type="system",
)
```

- [ ] **Step 4: 运行 WorkItemService 与 Console 相关回归测试**

Run: `pytest tests/test_work_item_service.py tests/test_console_work_items_service.py -v`

Expected: PASS，如果 Console 对历史事件的读取过于依赖旧字段，在这里一并修补兼容层。

- [ ] **Step 5: 提交**

```bash
git add packages/kernel/services/work_items.py tests/test_work_item_service.py tests/test_console_work_items_service.py
git commit -m "feat: include status transition details in work item events"
```

---

## PR-1.4 包 1 真链路验收与文档

### Task 8: 增加包 1 验收脚本

**Files:**
- Create: `scripts/package_1_acceptance.py`
- Test: manual acceptance run

- [ ] **Step 1: 编写最小验收脚本**

```python
from orchestrator.api.events import EventManager
from packages.context.packer.service import ContextPackAssembler
from packages.kernel.events.bus import InMemoryEventBus
from packages.kernel.services.work_items import WorkItemService


def main() -> int:
    manager = EventManager()
    manager.clear_history()
    bus = InMemoryEventBus(event_manager=manager)
    service = WorkItemService(event_bus=bus, context_assembler=ContextPackAssembler())

    session = service.create_legacy_session(
        {
            "repo": "acme/platform",
            "title": "Package 1 acceptance",
            "description": "Bridge kernel events into event manager",
            "requested_by": "acceptance",
        }
    )

    history = manager.get_history(limit=10)
    names = [item.get("eventName") for item in history]
    print({"work_item_id": session.work_item.work_item_id, "event_names": names})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 运行脚本，确认跨 bus 事件存在**

Run: `python scripts/package_1_acceptance.py`

Expected: 输出包含 `work_item.created`、`context_pack.created`、`plan.requested`。

- [ ] **Step 3: 提交**

```bash
git add scripts/package_1_acceptance.py
git commit -m "test: add package 1 acceptance script"
```

### Task 9: 增加包 1 验收文档

**Files:**
- Create: `docs/architecture/package-1-acceptance.md`

- [ ] **Step 1: 写验收文档**

文档必须包含：

```markdown
# Package 1 Acceptance

## Scope
- Event actor fields
- Kernel bus to EventManager bridge
- WorkItemService standard domain event publication

## Commands
```bash
pytest tests/test_event_manager.py tests/test_kernel_event_bus.py tests/test_work_item_service.py -v
python scripts/package_1_acceptance.py
```

## Expected
- Event JSON contains actorId / actorType
- EventManager history contains work_item.created / context_pack.created / plan.requested
- Work item status change includes oldStatus / newStatus
```
```

- [ ] **Step 2: 提交**

```bash
git add docs/architecture/package-1-acceptance.md
git commit -m "docs: add package 1 acceptance checklist"
```

### Task 10: 跑包 1 的最终回归集

**Files:**
- No code changes required unless regressions appear

- [ ] **Step 1: 跑测试**

Run:

```bash
pytest tests/test_event_manager.py tests/test_kernel_event_bus.py tests/test_work_item_service.py tests/test_runtime_state.py tests/test_release_worker.py tests/test_incident_worker.py -v
```

Expected: PASS

- [ ] **Step 2: 跑验收脚本**

Run:

```bash
python scripts/package_1_acceptance.py
```

Expected: 输出中包含细粒度事件名、actor 字段，并确认 bridge 生效。

- [ ] **Step 3: 若全部通过，整理提交**

```bash
git status --short
```

Expected: 工作区干净，仅保留本包文档和测试相关变更。

---

## 包 1 完成定义

包 1 完成时，必须同时满足下面四条：

1. `Event` 和 `AuditEvent` 都已支持 `actor_id` / `actor_type`，且旧调用点不崩。
2. `InMemoryEventBus` 发布的细粒度事件，能够出现在 `EventManager` 的 history / journal 中。
3. `WorkItemService` 的关键事件已经使用标准领域事件名和结构化 payload。
4. 有独立的包 1 验收脚本和验收文档，能够证明跨 bus 桥接不是纸面设计。

## 明确不在本包内

- 不做 transactional outbox
- 不做 mutation 原子写抽象
- 不做 `spawn_agent` 入口修正
- 不补 `AgentRun` / `Release` / `Incident` 完整状态机
- 不强制全链路必须显式传 actor；本包只做“默认兼容 + 核心路径显式带 actor”
