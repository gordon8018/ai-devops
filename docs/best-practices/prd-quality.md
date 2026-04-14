# 高质量 PRD 编写指南

## 概述

PRD (Product Requirements Document) 是 Ralph 使用的产品需求文档。本文档提供 PRD 编写的最佳实践，帮助编写高质量的 PRD。

---

## PRD 基础结构

### 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `project` | string | 项目名称 |
| `branchName` | string | 分支名称 |
| `description` | string | 项目描述 |
| `userStories` | array | 用户故事列表 |

### 推荐字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `aiDevopsTaskId` | string | 关联的 ai-devops 任务 ID |
| `qualityChecks` | object | 质量检查配置 |
| `context` | string | 上下文信息 |

---

## 项目配置

### project 字段

**规则：** 从 `owner/repo` 提取项目名

**示例：**

```json
{
  "project": "ai-devops"
}
```

**来源：** `user01/ai-devops` → `ai-devops`

---

### branchName 字段

**推荐格式：** `ralph/{taskId}`

**示例：**

```json
{
  "branchName": "ralph/task-20260414-001"
}
```

**规则：**

- 使用 `ralph/` 前缀
- 包含完整的 taskId
- 避免使用特殊字符（除 `-` 和 `_`）

---

### description 字段

**好的描述：**

```json
{
  "description": "Add priority field to database to enable task prioritization in the dashboard"
}
```

**不好的描述：**

```json
{
  "description": "Add priority"
}
```

**规则：**

- 1-2 句话
- 说明业务价值
- 避免技术细节（放在 User Story 中）

---

## User Stories 设计

### User Story 结构

**完整结构：**

```json
{
  "id": "US-001",
  "title": "Create migration for priority column",
  "description": "Create database migration to add priority field to tasks table",
  "acceptanceCriteria": [
    "priority column is INTEGER with default 0",
    "Migration is reversible"
  ],
  "priority": 1,
  "passes": false,
  "notes": "",
  "sourceSubtaskId": "task-20260414-001-0"
}
```

### ID 规范

**格式：** `US-{序号}`

**示例：**

```json
{
  "id": "US-001"
}
```

**规则：**

- 从 001 开始编号
- 零填充到 3 位
- 每个项目独立编号

---

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
- 避免技术术语（除非必要）

---

### Description 规范

**好的 Description：**

```json
{
  "description": "Create database migration to add priority field to tasks table. The priority field should be used to prioritize tasks in the dashboard, with values 0 (low), 1 (medium), and 2 (high)."
}
```

**不好的 Description：**

```json
{
  "description": "Add priority column to table."
}
```

**规则：**

- 说明"为什么"（业务价值）
- 说明"是什么"（技术目标）
- 提供必要的上下文
- 1-3 句话

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

## 质量检查配置

### 基本配置

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false
  }
}
```

### 完整配置

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test --coverage",
    "browserVerification": false,
    "securityScan": {
      "enabled": true,
      "tools": ["snyk", "trivy"],
      "blocking": true
    },
    "performanceCheck": {
      "enabled": true,
      "maxLoadTime": 2000
    }
  }
}
```

### 配置规则

1. **Typecheck**: 必须启用
2. **Lint**: 必须启用
3. **Test**: 必须启用
4. **Browser Verification**: 可选，根据项目需求
5. **Security Scan**: 建议启用

---

## 上下文增强

### 系统上下文

```json
{
  "context": "# System Context\n\nThe ai-devops system uses SQLite for task storage with the following schema:\n\n```sql\nCREATE TABLE ralph_state (...)\n```\n\nPlease follow the coding standards defined in CONTRIBUTING.md."
}
```

### 故事上下文

```json
{
  "userStories": [
    {
      "id": "US-001",
      "title": "Create migration",
      "context": "# Migration Context\n\nUse SQLAlchemy for migrations. All migrations must be reversible. Test both up and down migrations."
    }
  ]
}
```

### 上下文规则

1. **简洁**: 控制上下文长度（<5000 字符）
2. **相关**: 只包含相关信息
3. **格式化**: 使用 Markdown 格式
4. **代码示例**: 提供代码示例

---

## 完整示例

### 简单 PRD

```json
{
  "project": "ai-devops",
  "branchName": "ralph/task-20260414-001",
  "description": "Add priority field to database",
  "aiDevopsTaskId": "task-20260414-001",
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": false
  },
  "userStories": [
    {
      "id": "US-001",
      "title": "Create migration for priority column",
      "description": "Create database migration to add priority field to tasks table",
      "acceptanceCriteria": [
        "priority column is INTEGER with default 0",
        "Migration is reversible"
      ],
      "priority": 1,
      "passes": false,
      "notes": "",
      "sourceSubtaskId": "task-20260414-001-0"
    }
  ]
}
```

### 复杂 PRD

```json
{
  "project": "ai-devops",
  "branchName": "ralph/task-20260414-002",
  "description": "Implement real-time task updates with WebSocket",
  "aiDevopsTaskId": "task-20260414-002",
  "context": "# Project Context\n\nThe ai-devops system uses FastAPI for the backend. WebSocket support should follow FastAPI documentation patterns.\n\nKey files:\n- main.py: FastAPI application\n- websocket/manager.py: WebSocket connection manager\n\nCoding standards:\n- Type hints required\n- Docstrings for all functions\n- Maximum line length: 100",
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": true,
    "securityScan": {
      "enabled": true,
      "tools": ["snyk"],
      "blocking": true
    }
  },
  "userStories": [
    {
      "id": "US-001",
      "title": "Set up WebSocket server",
      "description": "Configure FastAPI to support WebSocket connections",
      "acceptanceCriteria": [
        "WebSocket endpoint /ws/tasks is available",
        "Connection manager handles multiple clients",
        "Graceful disconnect handling",
        "Typecheck passes"
      ],
      "priority": 1,
      "passes": false,
      "notes": "",
      "sourceSubtaskId": "task-20260414-002-0"
    },
    {
      "id": "US-002",
      "title": "Broadcast task updates",
      "description": "Broadcast task status changes to all connected clients",
      "acceptanceCriteria": [
        "Task creation is broadcasted",
        "Task updates are broadcasted",
        "Task deletions are broadcasted",
        "Only active clients receive updates",
        "WebSocket tests pass"
      ],
      "priority": 2,
      "passes": false,
      "notes": "",
      "sourceSubtaskId": "task-20260414-002-1"
    },
    {
      "id": "US-003",
      "title": "Implement reconnection logic",
      "description": "Implement automatic reconnection with exponential backoff",
      "acceptanceCriteria": [
        "Client reconnects on disconnect",
        "Reconnection uses exponential backoff",
        "Max reconnection interval is 30s",
        "Connection state is persisted"
      ],
      "priority": 3,
      "passes": false,
      "notes": "",
      "sourceSubtaskId": "task-20260414-002-2"
    }
  ]
}
```

---

## 常见错误

### 错误 1：User Story 过于宽泛

**不好：**

```json
{
  "title": "Update API",
  "acceptanceCriteria": ["API works"]
}
```

**好：**

```json
{
  "title": "Update POST /tasks to accept priority field",
  "acceptanceCriteria": [
    "POST /tasks accepts priority (optional, default 0)",
    "API tests pass"
  ]
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

### 错误 3：缺少质量检查

**不好：**

```json
{
  "qualityChecks": {}
}
```

**好：**

```json
{
  "qualityChecks": {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test"
  }
}
```

---

## PRD 评审检查清单

- [ ] `project` 字段正确
- [ ] `branchName` 格式正确
- [ ] `description` 清晰简洁
- [ ] 每个 User Story 都有唯一的 ID
- [ ] 每个 User Story 都有清晰的 Title
- [ ] 每个 User Story 都有详细的 Description
- [ ] 每个 User Story 都有可测试的 Acceptance Criteria
- [ ] Priority 设置合理
- [ ] `qualityChecks` 配置完整
- [ ] 必要的上下文已添加
- [ ] PRD 通过 JSON 验证

---

## 最佳实践总结

1. **清晰的描述**: description 应该说明业务价值
2. **可测试的标准**: 所有验收标准都应该可测试
3. **原子性的故事**: 每个 User Story 应该独立可完成
4. **合理的优先级**: 使用明确的优先级指导执行顺序
5. **完整的质量检查**: 确保 typecheck、lint、test 都配置
6. **必要的上下文**: 为 AI 提供必要的上下文信息
7. **一致性**: 遵循团队约定的命名和格式规范

---

## 参考文档

- [TaskSpec 设计指南](./task-spec-design.md)
- [完整集成文档](../RALPH_INTEGRATION.md)
- [TaskSpec 模板](../TASK_SPEC_TEMPLATE.md)
