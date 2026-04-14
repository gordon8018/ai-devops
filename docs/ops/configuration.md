# 配置参考

## 概述

本文档提供 Ralph 集成系统的完整配置参考，包括所有配置项的说明和示例。

---

## 目录

- [环境变量](#环境变量)
- [配置文件](#配置文件)
- [数据库配置](#数据库配置)
- [API 配置](#api-配置)
- [质量检查配置](#质量检查配置)
- [知识同步配置](#知识同步配置)
- [监控配置](#监控配置)

---

## 环境变量

### 必需变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | `ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| `RALPH_DB_PATH` | SQLite 数据库路径 | `~/.ralph/agent_tasks.db` |

### 可选变量

| 变量 | 说明 | 默认值 | 示例 |
|------|------|--------|------|
| `RALPH_DIR` | Ralph 工作目录 | `/tmp/ralph` | `/opt/ralph` |
| `RALPH_SH_PATH` | ralph.sh 脚本路径 | `~/.openclaw/workspace-alpha/ralph/ralph.sh` | `/usr/local/bin/ralph.sh` |
| `RALPH_TOOL` | AI 工具（claude 或 amp） | `claude` | `amp` |
| `RALPH_LOG_LEVEL` | 日志级别 | `INFO` | `DEBUG` |
| `RALPH_LOG_FILE` | 日志文件路径 | `/var/log/ralph/ralph.log` | `/tmp/ralph.log` |
| `RALPH_API_HOST` | API 服务器地址 | `0.0.0.0` | `127.0.0.1` |
| `RALPH_API_PORT` | API 服务器端口 | `8000` | `9000` |
| `RALPH_MAX_ITERATIONS` | 最大迭代次数 | `10` | `15` |
| `RALPH_TIMEOUT` | 执行超时（秒） | `7200` | `10800` |
| `RALPH_WORKERS` | 工作进程数 | `4` | `8` |
| `OBSIDIAN_VAULT_PATH` | Obsidian Vault 路径 | - | `~/Documents/ObsidianVault` |
| `GBRAIN_API_URL` | gbrain API URL | - | `https://api.gbrain.example.com` |
| `GBRAIN_API_KEY` | gbrain API Key | - | `gb-api-key-123` |

### .env 文件示例

```bash
# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 数据库
RALPH_DB_PATH=~/.ralph/agent_tasks.db

# Ralph
RALPH_DIR=/opt/ralph
RALPH_SH_PATH=~/.openclaw/workspace-alpha/ralph/ralph.sh
RALPH_TOOL=claude
RALPH_MAX_ITERATIONS=10
RALPH_TIMEOUT=7200

# API
RALPH_API_HOST=0.0.0.0
RALPH_API_PORT=8000

# 日志
RALPH_LOG_LEVEL=INFO
RALPH_LOG_FILE=/var/log/ralph/ralph.log

# 知识库
OBSIDIAN_VAULT_PATH=~/Documents/ObsidianVault
GBRAIN_API_URL=https://api.gbrain.example.com
GBRAIN_API_KEY=gb-api-key-123
```

---

## 配置文件

### 主配置文件位置

按优先级（从高到低）：

1. `./.ralphconfig.json`
2. `~/.ralphconfig.json`
3. `/etc/ralph/config.json`

### 配置文件示例

```json
{
  "ralph_state": {
    "db_path": "~/.ralph/agent_tasks.db",
    "default_limit": 50,
    "cache_ttl": 3600
  },
  "ralph_runner": {
    "default_timeout": 7200,
    "default_iterations": 10,
    "default_tool": "claude",
    "max_workers": 4
  },
  "api": {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 4,
    "cors_origins": ["http://localhost:3000"],
    "rate_limit": {
      "enabled": true,
      "requests_per_minute": 100
    }
  },
  "quality_gate": {
    "github_token": "${GITHUB_TOKEN}",
    "default_repo": "user01/ai-devops",
    "policy": "strict",
    "checks": {
      "typecheck": "bun run typecheck",
      "lint": "bun run lint",
      "test": "bun run test",
      "browserVerification": false
    }
  },
  "context_enhancement": {
    "obsidian_path": "~/Documents/ObsidianVault",
    "gbrain_url": "https://api.gbrain.example.com",
    "gbrain_key": "${GBRAIN_API_KEY}",
    "max_context_length": 5000,
    "cache_enabled": true,
    "cache_ttl": 3600
  },
  "feedback_loop": {
    "insights_db": "~/.ralph/insights.db",
    "auto_optimization": false,
    "optimization_interval": 86400
  },
  "monitoring": {
    "enabled": true,
    "prometheus": {
      "enabled": false,
      "port": 9090
    },
    "alerting": {
      "enabled": true,
      "slack_webhook": "${SLACK_WEBHOOK}",
      "telegram_bot_token": "${TELEGRAM_BOT_TOKEN}",
      "telegram_chat_id": "${TELEGRAM_CHAT_ID}"
    }
  }
}
```

---

## 数据库配置

### SQLite 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `db_path` | 数据库文件路径 | `~/.ralph/agent_tasks.db` |
| `journal_mode` | 日志模式 | `WAL` |
| `synchronous` | 同步模式 | `NORMAL` |
| `cache_size` | 缓存大小（KB） | `-2000` |
| `page_size` | 页面大小 | `4096` |

### SQLite 优化配置

```python
import sqlite3

conn = sqlite3.connect('agent_tasks.db')
cursor = conn.cursor()

# 启用 WAL 模式（提高并发性能）
cursor.execute("PRAGMA journal_mode=WAL")

# 设置同步模式
cursor.execute("PRAGMA synchronous=NORMAL")

# 设置缓存大小（2MB）
cursor.execute("PRAGMA cache_size=-2000")

# 设置页面大小（4KB）
cursor.execute("PRAGMA page_size=4096")

conn.commit()
```

### 数据库索引

```sql
-- 状态索引
CREATE INDEX idx_status ON ralph_state(status);

-- 更新时间索引
CREATE INDEX idx_updated_at ON ralph_state(updated_at);

-- 复合索引
CREATE INDEX idx_status_updated ON ralph_state(status, updated_at);
```

---

## API 配置

### FastAPI 配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `host` | 服务器地址 | `0.0.0.0` |
| `port` | 服务器端口 | `8000` |
| `workers` | 工作进程数 | `4` |
| `reload` | 自动重载 | `false` |
| `log_level` | 日志级别 | `info` |
| `access_log` | 访问日志 | `true` |

### CORS 配置

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://ralph.example.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 速率限制配置

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# 全局限流
@limiter.limit("100/minute")
@app.get("/api/v1/tasks")
async def list_tasks():
    ...

# 路由限流
@app.post("/api/v1/tasks")
@limiter.limit("10/minute")
async def create_task():
    ...
```

---

## 质量检查配置

### prd.json 质量检查

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false,
    "securityScan": {
      "enabled": true,
      "tools": ["snyk", "trivy"],
      "blocking": true
    },
    "codeReview": {
      "required": true,
      "minReviewers": 1,
      "autoAssign": ["@gordon", "@alice"]
    }
  }
}
```

### 质量门禁策略

**Strict Policy:**

```python
{
  "blocking_checks": ["typecheck", "lint", "test", "security"],
  "min_reviewers": 2,
  "ci_timeout": 3600
}
```

**Lenient Policy:**

```python
{
  "blocking_checks": ["typecheck", "test"],
  "warning_checks": ["lint", "security"],
  "min_reviewers": 1,
  "ci_timeout": 7200
}
```

### CI 检查配置

```yaml
# .github/workflows/ralph-quality.yml
name: Ralph Quality Gate

on:
  pull_request:
    branches: [main]

env:
  NODE_VERSION: "18"

jobs:
  quality-check:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: ${{ env.NODE_VERSION }}

      - name: Setup Bun
        uses: oven-sh/setup-bun@v1

      - name: Install dependencies
        run: bun install

      - name: Typecheck
        run: bun run typecheck

      - name: Lint
        run: bun run lint

      - name: Test
        run: bun run test --coverage

      - name: Security scan
        run: npx snyk test

      - name: Build
        run: bun run build
```

---

## 知识同步配置

### Obsidian 配置

```json
{
  "obsidian": {
    "vault_path": "~/Documents/ObsidianVault",
    "ignore_patterns": [
      "node_modules",
      ".git",
      ".obsidian",
      "dist"
    ],
    "file_extensions": [".md"],
    "max_results": 10,
    "min_score": 1.0
  }
}
```

### gbrain 配置

```json
{
  "gbrain": {
    "api_url": "https://api.gbrain.example.com",
    "api_key": "${GBRAIN_API_KEY}",
    "max_entities": 5,
    "include_relations": true,
    "timeout": 30
  }
}
```

### 上下文增强配置

```json
{
  "context_enhancement": {
    "max_length": 5000,
    "prioritize_by": ["tags", "title", "content"],
    "include_static": true,
    "include_dynamic": true,
    "include_runtime": true,
    "cache_enabled": true,
    "cache_ttl": 3600
  }
}
```

---

## 监控配置

### Prometheus 配置

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'ralph'
    static_configs:
      - targets: ['localhost:9090']
```

### 告警配置

```yaml
# alertmanager.yml
route:
  receiver: 'default'
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 12h

receivers:
  - name: 'default'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK}'
        channel: '#alerts'
    telegram_configs:
      - bot_token: '${TELEGRAM_BOT_TOKEN}'
        chat_id: '${TELEGRAM_CHAT_ID}'
```

### 告警规则

```yaml
# alerts.yml
groups:
  - name: ralph_alerts
    rules:
      - alert: TaskTimeout
        expr: ralph_task_duration_seconds > 7200
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Task {{ $labels.task_id }} has timed out"

      - alert: HighFailureRate
        expr: rate(ralph_tasks_failed_total[1h]) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High task failure rate detected"
```

---

## 日志配置

### 日志级别

| 级别 | 说明 | 使用场景 |
|------|------|----------|
| `DEBUG` | 详细调试信息 | 开发环境 |
| `INFO` | 一般信息 | 生产环境 |
| `WARNING` | 警告信息 | 所有环境 |
| `ERROR` | 错误信息 | 所有环境 |
| `CRITICAL` | 严重错误 | 所有环境 |

### 日志格式

```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/ralph/ralph.log'),
        logging.StreamHandler()
    ]
)
```

### 日志轮转

```python
from logging.handlers import RotatingFileHandler

# 日志文件轮转（10MB，保留 5 个备份）
handler = RotatingFileHandler(
    '/var/log/ralph/ralph.log',
    maxBytes=10*1024*1024,
    backupCount=5
)
```

---

## 最佳实践

1. **使用环境变量**：敏感信息（如 API Key）使用环境变量
2. **配置验证**：启动时验证所有配置项
3. **默认值**：为所有配置项提供合理的默认值
4. **文档化**：在代码中注释配置项的用途
5. **版本控制**：不将敏感配置提交到版本控制
6. **配置分离**：开发、测试、生产环境使用不同配置
7. **热重载**：支持配置热重载（使用信号）

---

## 参考文档

- [部署指南](./deployment.md)
- [监控指南](./monitoring.md)
- [故障排查](./troubleshooting.md)
