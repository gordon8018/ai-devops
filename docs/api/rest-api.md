# REST API 参考

## 概述

本文档提供 Ralph 集成系统的 REST API 完整参考，包括所有 Dashboard API 端点的请求和响应格式。

---

## 基础信息

**Base URL:** `http://localhost:8000/api/v1`

**认证:** Bearer Token（可选，取决于配置）

**Content-Type:** `application/json`

---

## API 端点目录

- [任务管理](#任务管理)
- [任务状态](#任务状态)
- [任务日志](#任务日志)
- [任务进度](#任务进度)
- [统计信息](#统计信息)
- [质量检查](#质量检查)
- [Code Review](#code-review)
- [CI/CD](#cicd)

---

## 任务管理

### GET /tasks

获取任务列表。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | string | 否 | 按状态筛选 |
| `limit` | integer | 否 | 最大返回数量（默认: 50） |
| `offset` | integer | 否 | 偏移量（默认: 0） |
| `sort_by` | string | 否 | 排序字段（默认: created_at） |
| `order` | string | 否 | 排序方向（asc 或 desc，默认: desc） |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/tasks?status=running&limit=10"
```

**响应示例：**

```json
{
  "data": [
    {
      "id": 1,
      "task_id": "task-20260414-001",
      "status": "running",
      "progress": 45,
      "logs": "...",
      "metadata": {},
      "created_at": "2026-04-14T15:00:00Z",
      "updated_at": "2026-04-14T15:30:00Z"
    }
  ],
  "meta": {
    "total": 1,
    "limit": 10,
    "offset": 0
  }
}
```

---

### GET /tasks/{task_id}

获取单个任务详情。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/tasks/task-20260414-001"
```

**响应示例：**

```json
{
  "data": {
    "id": 1,
    "task_id": "task-20260414-001",
    "status": "running",
    "progress": 45,
    "logs": "Started iteration 1\nIteration 2 completed...",
    "metadata": {
      "branch": "ralph/task-20260414-001",
      "repo": "user01/ai-devops"
    },
    "created_at": "2026-04-14T15:00:00Z",
    "updated_at": "2026-04-14T15:30:00Z"
  }
}
```

**错误响应：**

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "Task task-001 not found"
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

### POST /tasks

创建新任务。

**请求体：**

```json
{
  "taskId": "task-20260414-001",
  "task": "Add priority field to database",
  "repo": "user01/ai-devops",
  "userStories": [
    {
      "title": "Create migration for priority column",
      "description": "Create database migration",
      "acceptanceCriteria": ["Add priority column"],
      "priority": 1
    }
  ]
}
```

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/tasks" \
  -H "Content-Type: application/json" \
  -d @task_spec.json
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "status": "created"
  },
  "meta": {
    "timestamp": "2026-04-14T15:00:00Z",
    "request_id": "req-123456"
  }
}
```

---

### PUT /tasks/{task_id}

更新任务。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求体：**

```json
{
  "status": "running",
  "progress": 50,
  "metadata": {
    "branch": "ralph/task-001"
  }
}
```

**请求示例：**

```bash
curl -X PUT "http://localhost:8000/api/v1/tasks/task-20260414-001" \
  -H "Content-Type: application/json" \
  -d @update.json
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "updated": true
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

### DELETE /tasks/{task_id}

删除任务。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求示例：**

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/task-20260414-001"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "deleted": true
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

### POST /tasks/{task_id}/cancel

取消任务。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/tasks/task-20260414-001/cancel"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "status": "cancelled"
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## 任务状态

### GET /tasks/{task_id}/status

获取任务状态。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/tasks/task-20260414-001/status"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "status": "running",
    "progress": 45,
    "created_at": "2026-04-14T15:00:00Z",
    "updated_at": "2026-04-14T15:30:00Z",
    "duration": 1800
  }
}
```

---

## 任务日志

### GET /tasks/{task_id}/logs

获取任务日志。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `tail` | integer | 否 | 只返回最后 N 行 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/tasks/task-20260414-001/logs?tail=100"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "logs": "[2026-04-14T15:00:00] INFO: Starting Ralph execution\n[2026-04-14T15:30:00] INFO: Iteration 3 completed..."
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

### POST /tasks/{task_id}/logs

追加任务日志。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求体：**

```json
{
  "message": "Iteration 4 completed",
  "level": "INFO"
}
```

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/tasks/task-20260414-001/logs" \
  -H "Content-Type: application/json" \
  -d '{"message": "Iteration 4 completed", "level": "INFO"}'
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "appended": true
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## 任务进度

### GET /tasks/{task_id}/progress

获取任务进度。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 是 | 任务唯一标识符 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/tasks/task-20260414-001/progress"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "iterations": 5,
    "total_iterations": 10,
    "progress_percent": 50,
    "stories": [
      {
        "id": "US-001",
        "title": "Create migration",
        "passes": true,
        "notes": ""
      },
      {
        "id": "US-002",
        "title": "Update API",
        "passes": false,
        "notes": "API endpoint not updated"
      }
    ]
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## 统计信息

### GET /stats

获取任务统计信息。

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/stats"
```

**响应示例：**

```json
{
  "data": {
    "status_counts": {
      "queued": 5,
      "running": 2,
      "completed": 15,
      "failed": 1
    },
    "completion_rate": 0.882,
    "average_execution_time": 3600,
    "total_tasks": 23
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

### GET /stats/completion-rate

获取完成率趋势。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `days` | integer | 否 | 统计天数（默认: 30） |
| `window` | integer | 否 | 滑动窗口大小（默认: 7） |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/stats/completion-rate?days=30&window=7"
```

**响应示例：**

```json
{
  "data": {
    "trend": [
      {"date": "2026-04-01", "rate": 0.85},
      {"date": "2026-04-02", "rate": 0.87},
      ...
    ],
    "overall_trend": "improving"
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## 质量检查

### POST /quality-checks/run

运行质量检查。

**请求体：**

```json
{
  "branch": "ralph/task-20260414-001",
  "checks": ["typecheck", "lint", "test"]
}
```

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/quality-checks/run" \
  -H "Content-Type: application/json" \
  -d @checks.json
```

**响应示例：**

```json
{
  "data": {
    "branch": "ralph/task-20260414-001",
    "results": {
      "typecheck": {
        "status": "passed",
        "duration": 5.2,
        "output": ""
      },
      "lint": {
        "status": "passed",
        "duration": 3.1,
        "output": ""
      },
      "test": {
        "status": "failed",
        "duration": 8.5,
        "output": "Test failed: ..."
      }
    },
    "all_passed": false
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

---

## Code Review

### GET /reviews

获取 Code Review 列表。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 否 | 按任务 ID 筛选 |
| `status` | string | 否 | 按状态筛选 |
| `limit` | integer | 否 | 最大返回数量 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/reviews?task_id=task-20260414-001"
```

**响应示例：**

```json
{
  "data": [
    {
      "id": 1,
      "task_id": "task-20260414-001",
      "pr_number": 123,
      "status": "approved",
      "reviewer": "@gordon",
      "comments": 2,
      "created_at": "2026-04-14T15:00:00Z",
      "updated_at": "2026-04-14T16:00:00Z"
    }
  ],
  "meta": {
    "total": 1,
    "limit": 50,
    "offset": 0
  }
}
```

---

### POST /reviews

创建 Code Review 请求。

**请求体：**

```json
{
  "task_id": "task-20260414-001",
  "branch": "ralph/task-20260414-001",
  "title": "Add priority field",
  "reviewers": ["@gordon"]
}
```

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/reviews" \
  -H "Content-Type: application/json" \
  -d @review.json
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "pr_number": 123,
    "status": "pending",
    "url": "https://github.com/user01/ai-devops/pull/123"
  },
  "meta": {
    "timestamp": "2026-04-14T15:00:00Z",
    "request_id": "req-123456"
  }
}
```

---

### GET /reviews/{review_id}

获取单个 Review 详情。

**路径参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `review_id` | integer | 是 | Review ID |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/reviews/1"
```

**响应示例：**

```json
{
  "data": {
    "id": 1,
    "task_id": "task-20260414-001",
    "pr_number": 123,
    "status": "approved",
    "reviewer": "@gordon",
    "comments": [
      {
        "id": 1,
        "file": "src/api/tasks.ts",
        "line": 45,
        "comment": "Great work!",
        "created_at": "2026-04-14T15:30:00Z"
      }
    ],
    "created_at": "2026-04-14T15:00:00Z",
    "updated_at": "2026-04-14T16:00:00Z"
  },
  "meta": {
    "timestamp": "2026-04-14T16:00:00Z",
    "request_id": "req-123456"
  }
}
```

---

## CI/CD

### GET /ci/status

获取 CI 状态。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `task_id` | string | 否 | 按任务 ID 筛选 |
| `pr_number` | integer | 否 | 按 PR 编号筛选 |

**请求示例：**

```bash
curl -X GET "http://localhost:8000/api/v1/ci/status?task_id=task-20260414-001"
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "pr_number": 123,
    "checks": {
      "build": {
        "name": "Build",
        "status": "success",
        "conclusion": "success",
        "started_at": "2026-04-14T15:00:00Z",
        "completed_at": "2026-04-14T15:05:00Z",
        "url": "https://github.com/..."
      },
      "test": {
        "name": "Test",
        "status": "completed",
        "conclusion": "failure",
        "started_at": "2026-04-14T15:05:00Z",
        "completed_at": "2026-04-14T15:10:00Z",
        "url": "https://github.com/..."
      }
    },
    "overall_status": "failure"
  },
  "meta": {
    "timestamp": "2026-04-14T15:10:00Z",
    "request_id": "req-123456"
  }
}
```

---

### POST /ci/retry

重试失败的 CI 检查。

**请求体：**

```json
{
  "task_id": "task-20260414-001",
  "pr_number": 123
}
```

**请求示例：**

```bash
curl -X POST "http://localhost:8000/api/v1/ci/retry" \
  -H "Content-Type: application/json" \
  -d @retry.json
```

**响应示例：**

```json
{
  "data": {
    "task_id": "task-20260414-001",
    "retry_triggered": true
  },
  "meta": {
    "timestamp": "2026-04-14T15:10:00Z",
    "request_id": "req-123456"
  }
}
```

---

## WebSocket API

### 连接端点

```
ws://localhost:8000/ws/tasks
```

### 连接

**客户端示例（JavaScript）：**

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/tasks');

ws.onopen = () => {
  console.log('Connected to WebSocket');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  handleEvent(data);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('WebSocket closed, reconnecting...');
  setTimeout(() => connect(), 5000);
};
```

### 事件类型

#### task_status_changed

任务状态变更事件。

```json
{
  "type": "task_status_changed",
  "task_id": "task-20260414-001",
  "status": "running",
  "progress": 45,
  "timestamp": "2026-04-14T15:30:00Z"
}
```

#### log_entry

日志事件。

```json
{
  "type": "log_entry",
  "task_id": "task-20260414-001",
  "level": "INFO",
  "message": "Iteration 3 completed",
  "timestamp": "2026-04-14T15:30:00Z"
}
```

#### quality_check_result

质量检查结果事件。

```json
{
  "type": "quality_check_result",
  "task_id": "task-20260414-001",
  "check": "typecheck",
  "status": "passed",
  "duration": 5.2,
  "timestamp": "2026-04-14T15:30:00Z"
}
```

#### error

错误事件。

```json
{
  "type": "error",
  "task_id": "task-20260414-001",
  "error": "Execution timeout",
  "details": {},
  "timestamp": "2026-04-14T16:00:00Z"
}
```

---

## 错误响应格式

所有错误响应遵循统一格式：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable error message",
    "details": {}
  },
  "meta": {
    "timestamp": "2026-04-14T15:30:00Z",
    "request_id": "req-123456"
  }
}
```

### 常见错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `TASK_NOT_FOUND` | 404 | 任务不存在 |
| `INVALID_REQUEST` | 400 | 请求参数无效 |
| `UNAUTHORIZED` | 401 | 未授权 |
| `FORBIDDEN` | 403 | 无权限 |
| `INTERNAL_ERROR` | 500 | 内部服务器错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务不可用 |

---

## 认证

如果启用了认证，需要在请求头中包含 Bearer Token：

```bash
curl -X GET "http://localhost:8000/api/v1/tasks" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## 速率限制

API 实施速率限制：

- 默认：每 IP 每 60 秒最多 100 个请求
- 超过限制会返回 `429 Too Many Requests`

响应头包含速率限制信息：

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1617145200
```

---

## 参考文档

- [Python API 参考](./python-api.md)
- [CLI 工具参考](./cli-api.md)
- [完整集成文档](../RALPH_INTEGRATION.md)
