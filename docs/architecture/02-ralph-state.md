# 状态存储设计 (ralph_state.py)

## 概述

`ralph_state.py` 提供 SQLite 数据库持久化层，用于跟踪 Ralph 任务的生命周期、执行进度和日志。这是任务状态管理的核心组件。

---

## 1. 数据库 Schema

### 1.1 主表：ralph_state

```sql
CREATE TABLE ralph_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    logs TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 索引优化查询性能
CREATE INDEX idx_status ON ralph_state(status);
CREATE INDEX idx_updated_at ON ralph_state(updated_at);
```

### 1.2 字段说明

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INTEGER | PRIMARY KEY | 内部自增 ID |
| `task_id` | TEXT | NOT NULL, UNIQUE | 任务唯一标识符（外部引用） |
| `status` | TEXT | NOT NULL | 当前状态（见状态枚举） |
| `progress` | INTEGER | NOT NULL | 进度百分比（0-100） |
| `logs` | TEXT | NOT NULL | 累积日志（JSON 字符串或纯文本） |
| `metadata` | TEXT | NOT NULL | 额外元数据（JSON 字符串） |
| `updated_at` | TEXT | NOT NULL | 最后更新时间（ISO 8601） |
| `created_at` | TEXT | NOT NULL | 创建时间（ISO 8601） |

---

## 2. 状态枚举

### 2.1 完整状态列表

| 状态 | 说明 | 触发条件 |
|------|------|----------|
| `queued` | 任务已排队等待执行 | 创建任务时 |
| `running` | Ralph 正在执行 | Ralph 启动时 |
| `paused` | 任务已暂停 | 用户手动暂停 |
| `completed` | 所有故事已完成 | Ralph 报告完成 |
| `failed` | 执行失败 | Ralph 报告失败或超时 |
| `pr_created` | PR 已创建 | PR 创建成功后 |
| `ci_pending` | 等待 CI 检查 | PR 创建后 |
| `ci_failed` | CI 检查失败 | CI 报告失败 |
| `ci_passed` | CI 检查通过 | CI 报告通过 |
| `review_pending` | 等待 Code Review | CI 通过后 |
| `review_approved` | Review 已通过 | Reviewer 批准 |
| `review_rejected` | Review 被拒绝 | Reviewer 请求修改 |
| `merged` | 代码已合并 | PR 合并后 |
| `cancelled` | 任务被取消 | 用户手动取消 |

### 2.2 状态转换图

```
queued ──────▶ running ──────▶ completed
  │              │                │
  │              │                ▼
  │              │            pr_created ──────▶ ci_pending
  │              │                                   │
  │              │                           ┌──────┴──────┐
  │              ▼                           ▼             ▼
  └────────── cancelled                    ci_passed    ci_failed
  │              ▲                           │             │
  │              │                           ▼             │
  │              │                       review_pending   │
  │              │                           │             │
  │              │                      ┌────┴────┐        │
  │              │                      ▼         ▼        │
  │              │               review_approved  review_rejected
  │              │                      │             │
  │              │                      ▼             │
  │              │                    merged ◀────────┘
  │              │
  └────────── failed ◀──────────────────────────────┘
```

---

## 3. Python API

### 3.1 初始化

```python
from ralph_state import RalphState

# 使用默认路径
state = RalphState()

# 指定数据库路径
state = RalphState(db_path="/path/to/agent_tasks.db")

# 内存数据库（用于测试）
state = RalphState(db_path=":memory:")
```

### 3.2 CRUD 操作

#### 创建状态

```python
row_id = state.create(
    task_id="task-20260414-001",
    status="queued",
    progress=0,
    metadata={"branch": "ralph/task-001"}
)
```

#### 读取状态

```python
# 获取单个任务
entry = state.get("task-20260414-001")
# Returns: {
#     "id": 1,
#     "task_id": "task-20260414-001",
#     "status": "running",
#     "progress": 25,
#     "logs": "Started iteration 1\nIteration 2 completed\n",
#     "metadata": {"branch": "ralph/task-001"},
#     "updated_at": "2026-04-14T15:30:00",
#     "created_at": "2026-04-14T15:00:00"
# }

# 解析 metadata
import json
metadata = json.loads(entry["metadata"])
```

#### 更新状态

```python
# 更新单个字段
state.update("task-20260414-001", status="running")
state.update("task-20260414-001", progress=50)

# 更新多个字段
state.update("task-20260414-001", status="running", progress=75)
```

#### 追加日志

```python
# 追加纯文本日志
state.append_log("task-20260414-001", "Iteration 3 completed")

# 追加 JSON 结构化日志
state.append_log("task-20260414-001", json.dumps({
    "event": "iteration_completed",
    "iteration": 3,
    "timestamp": "2026-04-14T15:45:00"
}))
```

#### 列出状态

```python
# 列出所有任务
all_tasks = state.list()

# 按状态筛选
running_tasks = state.list(status="running")

# 按时间范围筛选
recent_tasks = state.list(
    start_date="2026-04-01",
    end_date="2026-04-30"
)

# 组合筛选
running_recent = state.list(
    status="running",
    limit=10
)

# 按更新时间排序
tasks = state.list(order_by="updated_at", order="desc")
```

#### 删除状态

```python
# 删除单个任务
state.delete("task-20260414-001")

# 批量删除
state.delete_many(status="completed", days_old=30)

# 清空所有数据（谨慎使用）
state.delete_all()
```

---

## 4. 高级功能

### 4.1 事务支持

```python
# 自动提交
state.create(task_id="task-001", status="queued")
state.update("task-001", progress=10)

# 手动事务
with state.transaction():
    state.create(task_id="task-001", status="queued")
    state.create(task_id="task-002", status="queued")
    # 出错时自动回滚
```

### 4.2 元数据操作

```python
# 设置元数据
state.set_metadata("task-001", {"branch": "ralph/task-001", "repo": "user01/ai-devops"})

# 获取元数据
metadata = state.get_metadata("task-001")

# 更新特定元数据字段
state.update_metadata("task-001", {"ci_status": "pending"})
```

### 4.3 统计查询

```python
# 按状态统计
stats = state.get_stats_by_status()
# Returns: {"queued": 5, "running": 2, "completed": 15, "failed": 1}

# 任务完成率
completion_rate = state.get_completion_rate()
# Returns: 0.789 (78.9%)

# 平均执行时间
avg_time = state.get_average_execution_time()
# Returns: 3600 (seconds)
```

### 4.4 批量操作

```python
# 批量创建
tasks = [
    {"task_id": "task-001", "status": "queued"},
    {"task_id": "task-002", "status": "queued"}
]
state.create_many(tasks)

# 批量更新
state.update_many(
    task_ids=["task-001", "task-002"],
    status="running"
)
```

---

## 5. CLI 工具

### 5.1 命令行接口

```bash
# 创建状态
./ralph_state.py create <task_id> [status] [progress]
./ralph_state.py create task-001 queued 0

# 获取状态
./ralph_state.py get <task_id>
./ralph_state.py get task-001

# 列出状态
./ralph_state.py list [status]
./ralph_state.py list running
./ralph_state.py list --status completed --limit 10

# 更新状态
./ralph_state.py update <task_id> [status] [progress]
./ralph_state.py update task-001 running 25

# 追加日志
./ralph_state.py log <task_id> <message>
./ralph_state.py log task-001 "Iteration 3 completed"

# 删除状态
./ralph_state.py delete <task_id>
./ralph_state.py delete task-001

# 统计信息
./ralph_state.py stats
```

### 5.2 输出格式

```bash
# JSON 输出
./ralph_state.py get task-001 --format json

# 表格输出
./ralph_state.py list --format table

# 详细输出
./ralph_state.py get task-001 --format pretty
```

---

## 6. 数据库维护

### 6.1 备份

```bash
# 导出数据库
sqlite3 agent_tasks.db .dump > backup.sql

# 压缩备份
gzip backup.sql
```

### 6.2 恢复

```bash
# 从备份恢复
sqlite3 agent_tasks.db < backup.sql

# 从压缩备份恢复
gunzip -c backup.sql.gz | sqlite3 agent_tasks.db
```

### 6.3 迁移

```bash
# SQLite 数据迁移
python3 scripts/migrate_db.py --from old.db --to new.db

# 跨数据库迁移（PostgreSQL, MySQL）
python3 scripts/export_to_postgres.py
```

### 6.4 清理

```python
# 清理旧日志
state.cleanup_old_logs(days=30)

# 清理已完成任务
state.cleanup_completed_tasks(days=7)

# 压缩数据库
state.vacuum()
```

---

## 7. 性能优化

### 7.1 索引优化

```sql
-- 添加复合索引
CREATE INDEX idx_status_updated ON ralph_state(status, updated_at);

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT * FROM ralph_state WHERE status = 'running';
```

### 7.2 查询优化

```python
# 使用 limit 分页
state.list(status="running", limit=100, offset=0)

# 避免全表扫描
state.get("task-001")  # 使用主键，O(1)
state.list(status="running")  # 使用索引，O(log n)

# 批量查询代替循环
task_ids = ["task-001", "task-002", "task-003"]
entries = state.get_many(task_ids)
```

### 7.3 连接池

```python
# 使用连接池减少连接开销
from sqlite3 import connect

pool = RalphState(
    db_path="agent_tasks.db",
    pool_size=5,
    timeout=30
)
```

---

## 8. 测试

### 8.1 单元测试

```python
def test_create_and_get():
    state = RalphState(db_path=":memory:")

    row_id = state.create(
        task_id="task-001",
        status="queued"
    )

    entry = state.get("task-001")

    assert entry["task_id"] == "task-001"
    assert entry["status"] == "queued"
    assert entry["progress"] == 0

def test_status_transitions():
    state = RalphState(db_path=":memory:")
    state.create(task_id="task-001", status="queued")

    state.update("task-001", status="running")
    assert state.get("task-001")["status"] == "running"

    state.update("task-001", status="completed")
    assert state.get("task-001")["status"] == "completed"
```

### 8.2 集成测试

```bash
# 运行测试
python3 -m pytest tests/test_ralph_state.py

# 压力测试
python3 tests/stress_test.py --tasks 1000 --operations 10000
```

---

## 9. 错误处理

### 9.1 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `UNIQUE constraint failed: ralph_state.task_id` | task_id 已存在 | 检查是否重复创建 |
| `database is locked` | 多进程并发访问 | 使用连接池或加锁 |
| `no such table: ralph_state` | 数据库未初始化 | 调用 `state.initialize()` |
| `disk I/O error` | 磁盘空间不足或权限问题 | 检查磁盘空间和权限 |

### 9.2 异常处理

```python
try:
    state.create(task_id="task-001", status="queued")
except sqlite3.IntegrityError as e:
    if "UNIQUE constraint" in str(e):
        print(f"Task {task_id} already exists")
    else:
        raise
except sqlite3.Error as e:
    print(f"Database error: {e}")
```

---

## 10. 最佳实践

1. **使用唯一 task_id**: 确保全局唯一，建议格式：`task-YYYYMMDD-NNN`
2. **定期清理日志**: 使用 `cleanup_old_logs()` 避免日志无限增长
3. **批量操作**: 使用 `create_many()`, `update_many()` 提高效率
4. **索引优化**: 为常用查询添加索引
5. **备份策略**: 定期备份，使用 WAL 模式提高并发性能
6. **事务处理**: 对关键操作使用事务保证一致性
7. **监控数据库大小**: 定期检查数据库文件大小，及时清理

---

## 11. 扩展性

### 11.1 自定义表

```python
# 添加自定义表
state.execute("""
    CREATE TABLE IF NOT EXISTS custom_metrics (
        id INTEGER PRIMARY KEY,
        task_id TEXT,
        metric_name TEXT,
        metric_value REAL,
        FOREIGN KEY (task_id) REFERENCES ralph_state(task_id)
    )
""")
```

### 11.2 多数据库支持

```python
# PostgreSQL 支持
from ralph_state_postgres import RalphStatePostgres

state = RalphStatePostgres(
    host="localhost",
    database="ai_devops",
    user="postgres",
    password="secret"
)
```

---

## 12. 参考文档

- [SQLite 官方文档](https://www.sqlite.org/docs.html)
- [完整集成文档](../RALPH_INTEGRATION.md)
- [备份和恢复](../ops/backup-restore.md)
