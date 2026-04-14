# 实时监控设计

## 概述

实时监控系统提供 Ralph 任务执行的实时可见性，通过 WebSocket 推送和 Dashboard API 让用户随时了解任务状态、进度和日志。

---

## 1. 监控架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Real-time Monitoring Layer                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  WebSocket  │  │  Dashboard  │  │   Alerting  │         │
│  │   Server    │  │    API      │  │   System    │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │  Client  │      │  Client  │      │  Alert   │
    │  (Web)   │      │  (CLI)   │      │ Channel  │
    └──────────┘      └──────────┘      └──────────┘
          │                 │
          │                 │
          └────────┬────────┘
                   │
                   ▼
            ┌──────────────┐
            │  Ralph      │
            │  State      │
            └──────────────┘
```

### 1.2 数据流

```
Ralph State Store (状态变更)
        │
        │ Event Bus
        ▼
WebSocket Server (广播事件)
        │
        ├─────────────────┬─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
  Web Dashboard     CLI Client     Mobile App
  (实时更新)       (状态显示)     (推送通知)
```

---

## 2. WebSocket Server

### 2.1 服务器实现

```python
import asyncio
import json
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
from typing import Set

app = FastAPI()

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """接受新连接"""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        """断开连接"""
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Failed to send message: {e}")

manager = ConnectionManager()

@app.websocket("/ws/tasks")
async def websocket_tasks(websocket: WebSocket):
    """任务监控 WebSocket 端点"""
    await manager.connect(websocket)

    try:
        # 发送初始状态
        await websocket.send_json({
            "type": "connected",
            "timestamp": datetime.utcnow().isoformat()
        })

        while True:
            # 等待客户端消息（心跳）
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        manager.disconnect(websocket)

# 事件广播端点
@app.post("/events")
async def broadcast_event(event: dict):
    """接收事件并广播"""
    await manager.broadcast(event)
    return {"status": "broadcasted"}
```

### 2.2 事件类型

```python
# 任务状态变更事件
{
    "type": "task_status_changed",
    "task_id": "task-20260414-001",
    "status": "running",
    "progress": 25,
    "timestamp": "2026-04-14T15:30:00Z"
}

# 日志事件
{
    "type": "log_entry",
    "task_id": "task-20260414-001",
    "level": "INFO",
    "message": "Iteration 3 completed",
    "timestamp": "2026-04-14T15:30:05Z"
}

# 质量检查事件
{
    "type": "quality_check_result",
    "task_id": "task-20260414-001",
    "check": "typecheck",
    "status": "passed",
    "duration": 5.2,
    "timestamp": "2026-04-14T15:35:00Z"
}

# 错误事件
{
    "type": "error",
    "task_id": "task-20260414-001",
    "error": "Execution timeout",
    "details": {...},
    "timestamp": "2026-04-14T16:00:00Z"
}
```

---

## 3. Dashboard API

### 3.1 REST API 端点

```python
from fastapi import FastAPI, HTTPException
from typing import List, Optional

app = FastAPI()

# 获取任务列表
@app.get("/api/v1/tasks")
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
):
    """获取任务列表"""
    state = RalphState()

    if status:
        tasks = state.list(status=status, limit=limit, offset=offset)
    else:
        tasks = state.list(limit=limit, offset=offset)

    return {
        "tasks": tasks,
        "total": len(tasks),
        "limit": limit,
        "offset": offset
    }

# 获取任务详情
@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    state = RalphState()
    task = state.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task

# 获取任务日志
@app.get("/api/v1/tasks/{task_id}/logs")
async def get_task_logs(
    task_id: str,
    tail: Optional[int] = None
):
    """获取任务日志"""
    state = RalphState()
    task = state.get(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    logs = task["logs"]

    if tail:
        log_lines = logs.split("\n")
        logs = "\n".join(log_lines[-tail:])

    return {
        "task_id": task_id,
        "logs": logs
    }

# 获取任务进度
@app.get("/api/v1/tasks/{task_id}/progress")
async def get_task_progress(task_id: str):
    """获取任务进度"""
    runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task_id}")
    progress = runner.parse_progress()

    return {
        "task_id": task_id,
        "progress": progress
    }

# 获取任务统计
@app.get("/api/v1/stats")
async def get_stats():
    """获取任务统计"""
    state = RalphState()
    stats = state.get_stats_by_status()

    return {
        "status_counts": stats,
        "completion_rate": state.get_completion_rate(),
        "avg_execution_time": state.get_average_execution_time(),
        "total_tasks": sum(stats.values())
    }

# 创建任务
@app.post("/api/v1/tasks")
async def create_task(task_spec: dict):
    """创建新任务"""
    prd = task_spec_to_prd_json(task_spec)

    state = RalphState()
    state.create(
        task_id=task_spec["taskId"],
        status="queued",
        metadata={"prd": prd}
    )

    return {
        "task_id": task_spec["taskId"],
        "status": "created"
    }

# 取消任务
@app.post("/api/v1/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    state = RalphState()
    state.update(task_id, status="cancelled")

    runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task_id}")
    runner.terminate()

    return {
        "task_id": task_id,
        "status": "cancelled"
    }
```

### 3.2 API 响应格式

```json
{
  "data": {...},
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

### 3.3 错误响应

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task task-001 not found",
    "details": {...}
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## 4. Web Dashboard

### 4.1 前端架构

```javascript
// WebSocket 客户端
class TaskMonitor {
  constructor(taskId) {
    this.taskId = taskId;
    this.ws = null;
  }

  connect() {
    this.ws = new WebSocket(`ws://localhost:8000/ws/tasks`);

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      this.handleEvent(data);
    };

    this.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    this.ws.onclose = () => {
      console.log('WebSocket closed, reconnecting...');
      setTimeout(() => this.connect(), 5000);
    };
  }

  handleEvent(event) {
    switch (event.type) {
      case 'task_status_changed':
        this.updateStatus(event);
        break;
      case 'log_entry':
        this.appendLog(event);
        break;
      case 'quality_check_result':
        this.updateQualityCheck(event);
        break;
      case 'error':
        this.showError(event);
        break;
    }
  }

  updateStatus(event) {
    document.getElementById('status').textContent = event.status;
    document.getElementById('progress').value = event.progress;
  }

  appendLog(event) {
    const logContainer = document.getElementById('logs');
    const logLine = document.createElement('div');
    logLine.className = `log-${event.level.toLowerCase()}`;
    logLine.textContent = `[${event.timestamp}] ${event.message}`;
    logContainer.appendChild(logLine);
    logContainer.scrollTop = logContainer.scrollHeight;
  }

  showError(event) {
    const errorContainer = document.getElementById('errors');
    const errorMessage = document.createElement('div');
    errorMessage.className = 'error-message';
    errorMessage.textContent = event.error;
    errorContainer.appendChild(errorMessage);
  }
}

// 使用示例
const monitor = new TaskMonitor('task-20260414-001');
monitor.connect();
```

### 4.2 Dashboard 组件

```html
<!DOCTYPE html>
<html>
<head>
  <title>Ralph Task Monitor</title>
  <style>
    .task-card {
      border: 1px solid #ddd;
      padding: 20px;
      margin: 10px 0;
      border-radius: 5px;
    }
    .status-badge {
      display: inline-block;
      padding: 5px 10px;
      border-radius: 3px;
      font-weight: bold;
    }
    .status-running { background: #ffc107; color: #000; }
    .status-completed { background: #28a745; color: #fff; }
    .status-failed { background: #dc3545; color: #fff; }
    .progress-bar {
      width: 100%;
      height: 20px;
      background: #e0e0e0;
      border-radius: 10px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: #007bff;
      transition: width 0.3s;
    }
    .log-container {
      height: 300px;
      overflow-y: auto;
      background: #f5f5f5;
      padding: 10px;
      font-family: monospace;
      font-size: 12px;
    }
    .log-info { color: #333; }
    .log-warning { color: #856404; }
    .log-error { color: #721c24; }
  </style>
</head>
<body>
  <div class="task-card">
    <h2>Task: task-20260414-001</h2>
    <p>Status: <span id="status" class="status-badge">queued</span></p>
    <p>Progress: <span id="progress-text">0</span>%</p>
    <div class="progress-bar">
      <div id="progress-fill" class="progress-fill" style="width: 0%"></div>
    </div>
    <h3>Logs</h3>
    <div id="logs" class="log-container"></div>
    <h3>Errors</h3>
    <div id="errors"></div>
  </div>

  <script src="monitor.js"></script>
</body>
</html>
```

---

## 5. CLI 客户端

### 5.1 实时监控命令

```bash
# 监控单个任务
ralph-cli watch task-20260414-001

# 监控所有运行中的任务
ralph-cli watch --status running

# 监控并显示日志
ralph-cli watch task-20260414-001 --logs

# 自定义刷新间隔
ralph-cli watch task-20260414-001 --interval 10
```

### 5.2 CLI 实现示例

```python
import time
import sys
from ralph_state import RalphState
from ralph_runner import RalphRunner

def watch_task(task_id, interval=5, show_logs=False):
    """实时监控任务"""
    state = RalphState()
    runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task_id}")

    last_log_length = 0

    try:
        while True:
            # 获取状态
            task = state.get(task_id)
            progress = runner.parse_progress()

            # 清屏
            print("\033[2J\033[H")

            # 显示状态
            print(f"Task: {task_id}")
            print(f"Status: {task['status']}")
            print(f"Progress: {progress['progress_percent']}%")
            print(f"Iterations: {progress['iterations']}/{progress['total_iterations']}")

            # 显示用户故事
            print("\nUser Stories:")
            for story in progress['stories']:
                status_icon = "✓" if story['passes'] else "✗"
                print(f"  [{status_icon}] {story['id']}: {story['title']}")

            # 显示日志
            if show_logs:
                logs = task['logs']
                if len(logs) > last_log_length:
                    new_logs = logs[last_log_length:]
                    print("\nLogs:")
                    print(new_logs)
                    last_log_length = len(logs)

            # 检查是否完成
            if task['status'] in ('completed', 'failed', 'cancelled'):
                print(f"\nTask {task['status']}")
                break

            # 等待
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped")
```

---

## 6. 告警系统

### 6.1 告警规则

```python
class AlertRule:
    """告警规则基类"""

    def __init__(self, name, condition, severity="warning"):
        self.name = name
        self.condition = condition
        self.severity = severity

    def evaluate(self, task):
        """评估是否触发告警"""
        return self.condition(task)

# 定义告警规则
ALERT_RULES = [
    AlertRule(
        name="Task Timeout",
        condition=lambda t: (
            t['status'] == 'running' and
            (datetime.utcnow() - datetime.fromisoformat(t['updated_at'])).total_seconds() > 7200
        ),
        severity="critical"
    ),
    AlertRule(
        name="Quality Check Failed",
        condition=lambda t: t['status'] == 'ci_failed',
        severity="critical"
    ),
    AlertRule(
        name="Task Stalled",
        condition=lambda t: (
            t['status'] == 'running' and
            t['progress'] > 0 and
            (datetime.utcnow() - datetime.fromisoformat(t['updated_at'])).total_seconds() > 1800
        ),
        severity="warning"
    )
]

def check_alerts(task):
    """检查任务是否触发告警"""
    alerts = []

    for rule in ALERT_RULES:
        if rule.evaluate(task):
            alerts.append({
                "rule": rule.name,
                "severity": rule.severity,
                "task_id": task['task_id']
            })

    return alerts
```

### 6.2 告警通知

```python
import requests

class AlertNotifier:
    """告警通知器"""

    def __init__(self, config):
        self.config = config

    def send_slack(self, alert):
        """发送 Slack 通知"""
        webhook_url = self.config['slack_webhook']

        color = {
            "critical": "#dc3545",
            "warning": "#ffc107",
            "info": "#17a2b8"
        }.get(alert['severity'], "#6c757d")

        payload = {
            "attachments": [{
                "color": color,
                "title": f"🚨 {alert['rule']}",
                "text": f"Task: {alert['task_id']}",
                "footer": "Ralph Monitor"
            }]
        }

        requests.post(webhook_url, json=payload)

    def send_email(self, alert):
        """发送邮件通知"""
        # 实现邮件发送逻辑
        pass

    def send_telegram(self, alert):
        """发送 Telegram 通知"""
        bot_token = self.config['telegram_bot_token']
        chat_id = self.config['telegram_chat_id']

        message = f"🚨 {alert['rule']}\nTask: {alert['task_id']}"

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message
        })

    def notify(self, alert):
        """根据配置发送通知"""
        for channel in self.config['channels']:
            if channel == 'slack':
                self.send_slack(alert)
            elif channel == 'email':
                self.send_email(alert)
            elif channel == 'telegram':
                self.send_telegram(alert)
```

---

## 7. 性能优化

### 7.1 连接池

```python
# 使用 WebSocket 连接池管理多个连接
class ConnectionPool:
    def __init__(self, max_connections=100):
        self.connections = {}
        self.max_connections = max_connections

    def add(self, task_id, websocket):
        if len(self.connections) >= self.max_connections:
            raise Exception("Connection pool full")

        self.connections[task_id] = websocket

    def remove(self, task_id):
        self.connections.pop(task_id, None)

    def broadcast_to_task(self, task_id, message):
        if task_id in self.connections:
            await self.connections[task_id].send_json(message)
```

### 7.2 批量更新

```python
# 批量获取任务状态，减少数据库查询
def batch_get_task_states(task_ids):
    state = RalphState()

    # 使用 IN 查询
    placeholders = ','.join(['?'] * len(task_ids))
    query = f"SELECT * FROM ralph_state WHERE task_id IN ({placeholders})"

    return state._execute(query, task_ids).fetchall()
```

### 7.3 缓存

```python
from functools import lru_cache
from datetime import datetime, timedelta

class CachedTaskMonitor:
    """带缓存的任务监控器"""

    def __init__(self, ttl=60):
        self.ttl = ttl
        self.cache = {}

    def get_task(self, task_id):
        """获取任务（带缓存）"""
        now = datetime.utcnow()

        if task_id in self.cache:
            cached_time, cached_data = self.cache[task_id]
            if (now - cached_time).total_seconds() < self.ttl:
                return cached_data

        # 缓存未命中，从数据库读取
        state = RalphState()
        task = state.get(task_id)

        self.cache[task_id] = (now, task)
        return task
```

---

## 8. 测试

### 8.1 WebSocket 测试

```python
import pytest
import websockets

@pytest.mark.asyncio
async def test_websocket_connection():
    uri = "ws://localhost:8000/ws/tasks"

    async with websockets.connect(uri) as ws:
        # 发送心跳
        await ws.send("ping")
        response = await ws.recv()
        assert response == "pong"
```

### 8.2 API 测试

```python
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_list_tasks():
    response = client.get("/api/v1/tasks")
    assert response.status_code == 200

    data = response.json()
    assert "tasks" in data
    assert "total" in data

def test_get_task_not_found():
    response = client.get("/api/v1/tasks/nonexistent")
    assert response.status_code == 404
```

---

## 9. 最佳实践

1. **心跳机制**: 定期发送心跳保持连接活跃
2. **重连策略**: 实现指数退避重连，避免连接风暴
3. **速率限制**: 对 API 端点实施速率限制，防止滥用
4. **身份验证**: WebSocket 和 API 都需要验证
5. **日志审计**: 记录所有监控操作，便于审计
6. **优雅降级**: WebSocket 断开时降级到轮询
7. **资源清理**: 及时清理断开的连接和缓存

---

## 10. 扩展性

### 10.1 多租户支持

```python
@app.websocket("/ws/organizations/{org_id}/tasks")
async def websocket_org_tasks(websocket: WebSocket, org_id: str):
    """组织级别的任务监控"""
    # 验证用户权限
    user = verify_user(websocket)
    if not user.has_org_access(org_id):
        await websocket.close(code=4003)
        return

    await manager.connect(websocket)
    # ...
```

### 10.2 集成 Prometheus 指标

```python
from prometheus_client import Counter, Gauge, start_http_server

# 定义指标
task_created = Counter('ralph_tasks_created', 'Total tasks created')
task_completed = Counter('ralph_tasks_completed', 'Total tasks completed')
task_duration = Gauge('ralph_task_duration_seconds', 'Task duration')

# 暴露指标端点
start_http_server(9090)
```

---

## 11. 参考文档

- [FastAPI WebSocket 文档](https://fastapi.tiangolo.com/advanced/websockets/)
- [WebSockets RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455)
- [完整集成文档](../RALPH_INTEGRATION.md)
