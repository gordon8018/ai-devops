# SQLite Tracker 迁移总结

## 阶段 1 完成项 ✅

### 1. 新增文件

| 文件 | 说明 |
|------|------|
| `orchestrator/bin/db.py` | SQLite 数据库模块 (新增) |
| `orchestrator/bin/test_db.py` | 数据库测试脚本 |
| `com.ai-devops.monitor.plist` | macOS launchd 配置 |
| `ai-devops-monitor.service` | Linux systemd service |
| `ai-devops-monitor.timer` | Linux systemd timer |

### 2. 修改文件

| 文件 | 修改内容 |
|------|----------|
| `orchestrator/bin/monitor.py` | 重写，支持 SQLite + --once 模式 + 卡死检测 |
| `orchestrator/bin/zoe-daemon.py` | 改用 SQLite insert_task |

### 3. 核心功能

#### SQLite Tracker (db.py)

```python
from orchestrator.bin.db import (
    init_db,              # 初始化数据库
    insert_task,          # 插入/更新任务
    get_task,             # 查询单个任务
    get_running_tasks,    # 获取运行中任务
    update_task,          # 更新任务字段
    update_task_status,   # 更新任务状态
    count_running_tasks,  # 计数运行中任务
    get_all_tasks,        # 获取所有任务 (分页)
    delete_task,          # 删除任务
)
```

#### 数据库 Schema

```sql
CREATE TABLE agent_tasks (
    id TEXT PRIMARY KEY,
    plan_id TEXT,
    repo TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    agent TEXT DEFAULT 'codex',
    model TEXT DEFAULT 'gpt-5.3-codex',
    effort TEXT DEFAULT 'medium',
    worktree TEXT,
    branch TEXT,
    tmux_session TEXT,
    process_id INTEGER,
    started_at INTEGER,
    completed_at INTEGER,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    pr_number INTEGER,
    pr_url TEXT,
    last_failure TEXT,
    last_failure_at INTEGER,
    note TEXT,
    metadata TEXT,
    created_at INTEGER,
    updated_at INTEGER
)
```

#### Monitor 改进

1. **日志活动检测**: 60 分钟无更新 → `log_stale`
2. **硬超时检测**: 180 分钟 → `timeout`
3. **--once 模式**: 支持 launchd/cron 定时触发
4. **SQLite 集成**: 替代 JSON registry

### 4. 测试验证

```bash
# 运行数据库测试
cd ~/ai-devops
python3 orchestrator/bin/test_db.py

# 测试 monitor --once 模式
python3 orchestrator/bin/monitor.py --once

# 验证语法
python3 -m py_compile orchestrator/bin/db.py
python3 -m py_compile orchestrator/bin/monitor.py
python3 -m py_compile orchestrator/bin/zoe-daemon.py
```

### 5. 部署指南

#### macOS (launchd)

```bash
# 编辑 plist 文件，替换路径中的 /Users/gordon 为实际用户名
sed -i '' 's|/Users/gordon|'$HOME'|g' com.ai-devops.monitor.plist

# 注册 launchd
ln -sf ~/ai-devops/com.ai-devops.monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ai-devops.monitor.plist

# 验证
launchctl list | grep ai-devops
```

#### Linux (systemd)

```bash
# 编辑 service 文件，替换路径
sed -i 's|/home/user01|'$HOME'|g' ai-devops-monitor.service
sed -i 's|/home/user01|'$HOME'|g' ai-devops-monitor.timer

# 安装 systemd 服务
sudo cp ai-devops-monitor.service /etc/systemd/system/
sudo cp ai-devops-monitor.timer /etc/systemd/system/

# 启用并启动 timer
sudo systemctl daemon-reload
sudo systemctl enable ai-devops-monitor.timer
sudo systemctl start ai-devops-monitor.timer

# 验证
systemctl list-timers | grep ai-devops
```

### 6. 向后兼容

- JSON registry 文件保留 (不删除)
- `load_registry()` / `save_registry()` 保留 (legacy 兼容)
- 现有 queue/*.json 机制不变

### 7. 数据迁移

```python
from orchestrator.bin.db import migrate_from_json

# 迁移现有 JSON 数据到 SQLite
result = migrate_from_json()
print(f"Migrated: {result['migrated']} tasks")
```

**注意**: 当前 JSON registry 为空 (卡死任务已清理)，无需迁移。

---

## 阶段 1 收益

| 改进 | 收益 |
|------|------|
| SQLite 替代 JSON | 原子操作、并发安全、查询高效 |
| 日志活动检测 | 60 分钟无更新自动告警 |
| 硬超时限制 | 180 分钟强制标记超时 |
| --once 模式 | 支持 launchd/cron，零空闲开销 |

---

## 下一步：阶段 2 - CLI 统一入口

创建 `agent` CLI 工具，提供统一命令接口:

```bash
agent spawn --repo my-repo --title "Fix auth"
agent list --status running
agent status <task-id>
agent kill <task-id>
agent plan --repo my-repo --title "..." --description "..."
agent dispatch --plan <plan-file>
```

预计工时：3-4 小时
