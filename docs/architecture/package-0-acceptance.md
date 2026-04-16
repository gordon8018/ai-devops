# Package 0 Acceptance

> 用途：在 PR-0.1 + PR-0.2 全部落盘后，验证包 0 的实际行为符合契约 §8.3 声明修复的四个点。不覆盖后续包的工作。

本包共有**三条**独立验收线。第一条走自动化脚本，第二和第三条走手工 DB 查询（因为它们要求真实的存储层状态）。

---

## 前置条件

1. PR-0.1 + PR-0.2 commits 均在 main 上（`git log --oneline -10` 应能看到 `feat: promote incident dedup fields` 位于最新 8 条内）。
2. Python 虚拟环境可用：`source .venv/bin/activate`。
3. 如果要做第二/第三条 DB 验证，确保 `AI_DEVOPS_HOME` 指向仓库根，SQLite 或 Postgres 任一可用。

---

## 验收线 1：Release 推进到 `full + succeeded`（自动化）

**命令**

```bash
source .venv/bin/activate
python3 scripts/package_0_acceptance.py
```

**预期输出**

```
[PASS] release advancement: stage=full status=succeeded ladder=team-only->beta->1%->5%->20%->full

Package 0 acceptance: all checks passed
```

**预期退出码**：`0`

**覆盖的契约点**

- `ReleaseWorker.advance(work_item_id)` 作为显式推进入口（D1: β）是工作的
- stage ladder 按 `team-only → beta → 1% → 5% → 20% → full` 顺序推进、不跳级、不回退
- 到达 `full` 时 status 自动变为 `succeeded`（之前卡死在 `rolling_out` 的 bug 已修）
- Flag adapter 每一步都被调用一次（共 6 次），包括初次 ready 事件触发的 team-only

**失败排查**

- `stage='beta'` 但期望 `'full'`：可能是 `advance()` 被调用次数不够、或推进逻辑回退到旧 `next_stage("unknown")` 固定写法
- `ladder=(..)` 里出现缺项：`_flag_adapter.apply_stage()` 被哪一步漏掉了
- 脚本直接抛 `ModuleNotFoundError`：检查 `.venv` 是否激活、`AI_DEVOPS_HOME` 是否正确

---

## 验收线 2：`dedup_key` 在域模型 + SQLite + 控制平面 Postgres 中作为一等字段持久化

这条走**手工 SQL 检查**，因为它跨 SQLite 和 Postgres 两个持久化层。

### 2A. SQLite `agent_tasks.dedup_key` 列存在且接受写入

**命令**

```bash
source .venv/bin/activate
python3 -c "
import sqlite3
from orchestrator.bin import db
db.init_db()
db.insert_task({
    'id': 'acc-dedup-001',
    'repo': 'acme/platform',
    'title': 'Acceptance: SQLite dedup_key mirror',
    'status': 'queued',
    'metadata': {'dedupKey': 'delivery-acc-001'},
})
conn = sqlite3.connect(str(db.DB_PATH))
row = conn.execute(\"SELECT id, dedup_key FROM agent_tasks WHERE id='acc-dedup-001'\").fetchone()
print(row)
conn.close()
"
```

**预期输出**

```
('acc-dedup-001', 'delivery-acc-001')
```

### 2B. 不带 `dedupKey` 的旧路径保持兼容

**命令**

```bash
python3 -c "
import sqlite3
from orchestrator.bin import db
db.init_db()
db.insert_task({
    'id': 'acc-dedup-002',
    'repo': 'acme/platform',
    'title': 'Acceptance: SQLite no dedup key (legacy path)',
    'status': 'queued',
})
conn = sqlite3.connect(str(db.DB_PATH))
row = conn.execute(\"SELECT id, dedup_key FROM agent_tasks WHERE id='acc-dedup-002'\").fetchone()
print(row)
conn.close()
"
```

**预期输出**

```
('acc-dedup-002', None)
```

`dedup_key` 列为 `None`（未传入时），插入不报错。

### 2C. 控制平面 `work_items.dedup_key` 列存在

仅当控制平面 Postgres 已配置时执行：

```sql
\d work_items
```

**预期输出** 包含：

```
 dedup_key      | text                   |
```

若有实际 work item 已落盘，可进一步：

```sql
SELECT work_item_id, dedup_key
FROM work_items
WHERE dedup_key IS NOT NULL
LIMIT 5;
```

**覆盖的契约点**

- `WorkItem.dedup_key` 作为可选字段加入域模型，默认 `None`（D3）
- SQLite `agent_tasks` 表加 `dedup_key TEXT` 列，用 `PRAGMA table_info` + 条件 `ALTER` 保持幂等（D2）
- `insert_task` dual-write 把 `dedup_key` 从 task dict 或 metadata 里拿出来，落到控制平面 `work_items.dedup_key`
- 旧路径不带 `dedupKey` 时字段为 `NULL`，不报错（向后兼容）

---

## 验收线 3：Incident 的 `sourceSystem` / `dedupKey` 作为顶层字段流过 Worker 和 Postgres

### 3A. Incident Worker 把顶层字段接进 incident dict

**命令**

```bash
source .venv/bin/activate
python3 -c "
from apps.incident_worker.service import IncidentWorker
from orchestrator.api.events import Event, EventManager, EventType

em = EventManager()
em.clear_history()
w = IncidentWorker(event_manager=em)
w.start()

em.publish(Event(
    event_type=EventType.ALERT,
    data={
        'level': 'error',
        'message': 'Checkout timeout in payment service',
        'sourceSystem': 'sentry',
        'dedupKey': 'sentry-event-acc-001',
        'details': {'service': 'payments'},
    },
    source='acceptance',
))

incident = w.list_incidents()[0]
print('sourceSystem=', incident.get('sourceSystem'))
print('dedupKey=', incident.get('dedupKey'))
print('in_details=', 'dedupKey' in incident.get('details', {}))
w.stop()
"
```

**预期输出**

```
sourceSystem= sentry
dedupKey= sentry-event-acc-001
in_details= False
```

关键：`in_details=False` 证明字段是 incident dict 的**顶层键**，没有退化到 `details` 或 `payload`（D3）。

### 3B. 控制平面 `incidents.source_system` / `incidents.dedup_key` 列存在

仅当 Postgres 可用时：

```sql
\d incidents
```

**预期输出** 包含：

```
 source_system  | text                   |
 dedup_key      | text                   |
```

**覆盖的契约点**

- `_ingest_alert` 把 `sourceSystem` / `dedupKey` 放在 incident dict 的顶层，与 `incidentId` / `severity` / `status` 平级
- 同时接受 `source_system` / `dedup_key` 下划线别名
- 空字符串归一化为 `None`
- Postgres `incidents` 表以独立列 `source_system` / `dedup_key` 存储（非 `payload_json`，D3）

---

## 全套回归护栏

在跑完上面三条之前，先跑一遍包 0 相关的测试文件，确保没有静默回归：

```bash
source .venv/bin/activate
pytest tests/test_release_worker.py tests/test_release_rollout.py \
       tests/test_work_item_service.py tests/test_db_dual_write.py \
       tests/test_postgres_storage.py tests/test_incident_worker.py -v
```

**预期**：**38 passed**，0 failed。

> 注意：仓库另有 9 个与包 0 无关的 `tenacity` 依赖失败（`test_monitor.py` / `test_notify.py` / `notifiers/test_retry.py` / `test_p0_security_fixes.py` 的部分），那是预存环境问题、与包 0 无关。要跑全量时请确保 `pip install tenacity`。

---

## 未覆盖的契约点（属于后续包）

这份验收**不包含**以下内容，因为它们明确留给后续包：

- 事件总线统一（→ 包 1）
- 原子 mutation 接口（→ 包 2）
- `spawn_agent` 在 pick-up 时惰性补建 WorkItem + ContextPack（→ 包 3）
- 死信队列 / 异常收敛（→ 包 3）
- AgentRun / Release / Incident 完整状态机（→ 包 4）
- `dedup_key` 的唯一性约束 / 入口幂等校验（→ 后续，非包 0）

这份文档不需要验证它们。

---

## 完工口令

当上述三条线 + 回归测试全部通过后，包 0 可以声明完工。
