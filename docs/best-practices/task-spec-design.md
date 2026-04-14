# TaskSpec 设计指南

## 概述

TaskSpec 是 ai-devops 任务的标准化格式。本文档提供 TaskSpec 设计的最佳实践，帮助编写高质量的任务规范。

---

## TaskSpec 基础结构

### 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `taskId` | string | 任务唯一标识符 |
| `task` | string | 简短任务描述 |
| `repo` | string | 目标仓库（owner/repo） |
| `userStories` | array | 用户故事列表 |

### 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | string | 详细任务描述 |
| `acceptanceCriteria` | array | 全局验收标准 |
| `metadata` | object | 元数据 |

---

## 命名规范

### taskId 格式

**推荐格式：** `task-YYYYMMDD-NNN`

**示例：**

```json
{
  "taskId": "task-20260414-001"
}
```

**规则：**

- 使用 `task-` 前缀
- 日期格式：YYYYMMDD
- 序号：3 位数字（001-999）

---

### task 描述

**好的描述：**

```json
{
  "task": "Add priority field to database"
}
```

**不好的描述：**

```json
{
  "task": "Add priority field"
}
```

**规则：**

- 简洁明了（1-2 行）
- 描述主要目标
- 避免技术细节（放在 User Story 中）

---

## User Stories 设计

### User Story 结构

**完整结构：**

```json
{
  "title": "Create migration for priority column",
  "description": "Create database migration to add priority field to tasks table",
  "acceptanceCriteria": [
    "priority column is INTEGER with default 0",
    "Migration is reversible"
  ],
  "priority": 1
}
```

### Title 规范

**好的 Title：**

```json
{
  "title": "Create migration for priority column"
}
```

**不好的 Title：**

```json
{
  "title": "migration"
}
```

**规则：**

- 使用动词开头
- 描述具体动作
- 一行描述完整

---

### Description 规范

**好的 Description：**

```json
{
  "description": "Create database migration to add priority field to tasks table. The priority field should be used to prioritize tasks in the dashboard."
}
```

**不好的 Description：**

```json
{
  "description": "Add priority to tasks table."
}
```

**规则：**

- 说明"为什么"和"是什么"
- 1-3 句话
- 提供上下文

---

### Acceptance Criteria 规范

**好的验收标准：**

```json
{
  "acceptanceCriteria": [
    "priority column is INTEGER with default 0",
    "Migration is reversible",
    "All existing rows have priority set to 0",
    "Typecheck passes",
    "Tests pass"
  ]
}
```

**不好的验收标准：**

```json
{
  "acceptanceCriteria": [
    "Add priority column",
    "Tests work"
  ]
}
```

**规则：**

- **可测试**: 每个标准都可以验证
- **具体**: 避免模糊的描述
- **独立**: 标准之间不相互依赖
- **完整**: 覆盖所有关键功能
- **可量化**: 使用具体的数值或状态

---

## Priority 设置

### 优先级规则

| 优先级 | 范围 | 说明 |
|--------|------|------|
| **高** | 1-3 | 阻塞其他任务的核心功能 |
| **中** | 4-6 | 重要但非阻塞的功能 |
| **低** | 7-10 | 可选功能或优化 |

**示例：**

```json
{
  "userStories": [
    {
      "title": "Create migration for priority column",
      "priority": 1
    },
    {
      "title": "Update API to support priority field",
      "priority": 2
    },
    {
      "title": "Add unit tests for priority field",
      "priority": 4
    },
    {
      "title": "Update documentation",
      "priority": 8
    }
  ]
}
```

---

## 元数据使用

### 元数据字段

```json
{
  "metadata": {
    "source": "github-issue",
    "issueNumber": 123,
    "labels": ["feature", "database"],
    "assignee": "@gordon",
    "milestone": "v1.0.0",
    "estimatedHours": 4,
    "dependencies": ["task-20260413-005"]
  }
}
```

### 常用元数据

| 字段 | 说明 | 示例 |
|------|------|------|
| `source` | 任务来源 | `github-issue`, `slack`, `manual` |
| `issueNumber` | 关联的 Issue 编号 | `123` |
| `labels` | 标签 | `["feature", "database"]` |
| `assignee` | 负责人 | `@gordon` |
| `milestone` | 里程碑 | `v1.0.0` |
| `estimatedHours` | 预估时间 | `4` |
| `dependencies` | 依赖任务 | `["task-20260413-005"]` |

---

## 完整示例

### 简单任务

```json
{
  "taskId": "task-20260414-001",
  "task": "Add priority field to database",
  "repo": "user01/ai-devops",
  "description": "Enable tasks to be marked as high/medium/low priority for better task management",
  "userStories": [
    {
      "title": "Create migration for priority column",
      "description": "Create database migration to add priority INTEGER field to tasks table",
      "acceptanceCriteria": [
        "priority column is INTEGER with default 0",
        "Migration is reversible",
        "All existing rows have priority set to 0"
      ],
      "priority": 1
    },
    {
      "title": "Update API to support priority field",
      "description": "Update POST and PUT endpoints to accept and return priority field",
      "acceptanceCriteria": [
        "POST /tasks accepts priority (optional, default 0)",
        "GET /tasks returns priority field",
        "PUT /tasks accepts priority field",
        "Typecheck passes",
        "API tests pass"
      ],
      "priority": 2
    }
  ],
  "metadata": {
    "source": "github-issue",
    "issueNumber": 123,
    "labels": ["feature", "database"],
    "estimatedHours": 4
  }
}
```

### 复杂任务

```json
{
  "taskId": "task-20260414-002",
  "task": "Implement real-time task updates with WebSocket",
  "repo": "user01/ai-devops",
  "description": "Enable real-time updates for task changes using WebSocket connections",
  "userStories": [
    {
      "title": "Set up WebSocket server",
      "description": "Configure FastAPI to support WebSocket connections",
      "acceptanceCriteria": [
        "WebSocket endpoint /ws/tasks is available",
        "Connection manager handles multiple clients",
        "Graceful disconnect handling"
      ],
      "priority": 1
    },
    {
      "title": "Broadcast task updates",
      "description": "Broadcast task status changes to all connected clients",
      "acceptanceCriteria": [
        "Task creation is broadcasted",
        "Task updates are broadcasted",
        "Task deletions are broadcasted",
        "Only active clients receive updates"
      ],
      "priority": 2
    },
    {
      "title": "Implement reconnection logic",
      "description": "Implement automatic reconnection with exponential backoff",
      "acceptanceCriteria": [
        "Client reconnects on disconnect",
        "Reconnection uses exponential backoff",
        "Max reconnection interval is 30s",
        "Connection state is persisted"
      ],
      "priority": 3
    },
    {
      "title": "Add authentication to WebSocket",
      "description": "Validate WebSocket connections with JWT token",
      "acceptanceCriteria": [
        "Connection requires valid JWT token",
        "Invalid connections are rejected",
        "Token expiration is handled",
        "Authentication tests pass"
      ],
      "priority": 4
    }
  ],
  "acceptanceCriteria": [
    "Typecheck passes",
    "Unit tests pass",
    "Integration tests pass",
    "Performance: <100ms latency for broadcasts",
    "Security: All connections authenticated"
  ],
  "metadata": {
    "source": "slack",
    "labels": ["feature", "websocket"],
    "estimatedHours": 16,
    "dependencies": ["task-20260414-001"]
  }
}
```

---

## 常见错误

### 错误 1：描述过于详细

**不好：**

```json
{
  "task": "Add priority INTEGER column with default value 0 and create index on it and update all existing rows"
}
```

**好：**

```json
{
  "task": "Add priority field to database"
}
```

---

### 错误 2：验收标准不可测试

**不好：**

```json
{
  "acceptanceCriteria": [
    "Migration is clean",
    "Code is good"
  ]
}
```

**好：**

```json
{
  "acceptanceCriteria": [
    "Migration is reversible",
    "Typecheck passes",
    "Tests pass"
  ]
}
```

---

### 错误 3：User Story 过于宽泛

**不好：**

```json
{
  "title": "Update API",
  "acceptanceCriteria": [
    "API works"
  ]
}
```

**好：**

```json
{
  "title": "Update POST /tasks to accept priority field",
  "acceptanceCriteria": [
    "POST /tasks accepts priority (optional)",
    "Priority defaults to 0 if not provided",
    "API tests pass"
  ]
}
```

---

## 最佳实践总结

1. **简洁明了**: TaskSpec 应该简洁，避免过度详细
2. **可测试性**: 所有验收标准都应该可测试
3. **原子性**: 每个 User Story 应该独立可完成
4. **优先级清晰**: 使用明确的优先级指导执行顺序
5. **元数据完整**: 使用元数据提供额外上下文
6. **一致性**: 遵循团队约定的命名和格式规范
7. **版本控制**: TaskSpec 应该纳入版本控制

---

## 参考文档

- [TaskSpec 模板](../TASK_SPEC_TEMPLATE.md)
- [PRD 编写指南](./prd-quality.md)
- [完整集成文档](../RALPH_INTEGRATION.md)
