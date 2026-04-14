# TaskSpec → prd.json 转换器设计

## 概述

`task_to_prd.py` 负责将 ai-devops 的 TaskSpec 格式转换为 Ralph 可识别的 prd.json 格式。这是连接两个系统的关键桥梁。

---

## 1. 输入格式：TaskSpec

### 1.1 完整结构

```json
{
  "taskId": "task-20260414-001",
  "task": "Add priority field to database",
  "description": "Enable tasks to be marked as high/medium/low priority",
  "acceptanceCriteria": [
    "Add priority column to tasks table",
    "Typecheck passes",
    "Tests pass"
  ],
  "repo": "user01/ai-devops",
  "userStories": [
    {
      "title": "Create migration for priority column",
      "description": "Create database migration to add priority field",
      "acceptanceCriteria": [
        "priority column is INTEGER with default 0",
        "Migration is reversible"
      ],
      "priority": 1
    },
    {
      "title": "Update API to support priority field",
      "description": "API endpoints accept and return priority",
      "acceptanceCriteria": [
        "POST /tasks accepts priority",
        "GET /tasks returns priority"
      ],
      "priority": 2
    }
  ],
  "metadata": {
    "source": "github-issue",
    "issueNumber": 123,
    "labels": ["feature", "database"]
  }
}
```

### 1.2 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `taskId` | string | 是 | 唯一任务标识符，格式：task-YYYYMMDD-NNN |
| `task` | string | 是 | 简短任务描述 |
| `description` | string | 否 | 详细任务描述 |
| `acceptanceCriteria` | string[] | 否 | 全局验收标准 |
| `repo` | string | 是 | 目标仓库，格式：owner/repo |
| `userStories` | object[] | 是 | 用户故事列表 |
| `metadata` | object | 否 | 元数据，用于追踪和分类 |

### 1.3 User Story 结构

```json
{
  "title": "Story title",
  "description": "Story description",
  "acceptanceCriteria": ["criteria 1", "criteria 2"],
  "priority": 1
}
```

---

## 2. 输出格式：prd.json

### 2.1 完整结构

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
      "description": "Create database migration to add priority field",
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

### 2.2 字段映射

| TaskSpec 字段 | prd.json 字段 | 转换逻辑 |
|---------------|---------------|----------|
| `repo` | `project` | 从 "user01/ai-devops" 提取 "ai-devops" |
| `taskId` | `branchName` | 转换为 "ralph/{taskId}" |
| `taskId` | `aiDevopsTaskId` | 直接复制 |
| `task` | `description` | 直接复制 |
| `userStories` | `userStories` | 扩展每个 story，添加运行时字段 |

### 2.3 生成的字段

以下字段由转换器自动生成：

| 字段 | 值来源 | 说明 |
|------|--------|------|
| `userStories[].id` | 自动生成 | 格式：US-{序号}，从 001 开始 |
| `userStories[].passes` | 固定值 | `false`，初始状态 |
| `userStories[].notes` | 固定值 | 空字符串 "" |
| `userStories[].sourceSubtaskId` | 生成 | 格式：{taskId}-{序号} |
| `qualityChecks` | 配置 | 从默认配置或 TaskSpec metadata 继承 |

---

## 3. 核心转换逻辑

### 3.1 主函数

```python
def task_spec_to_prd_json(task_spec: dict, config: dict = None) -> dict:
    """
    将 TaskSpec 转换为 prd.json 格式

    Args:
        task_spec: TaskSpec 字典
        config: 可选配置覆盖（如 qualityChecks）

    Returns:
        prd.json 字典
    """
    project = task_spec["repo"].split("/")[-1]
    task_id = task_spec["taskId"]

    prd = {
        "project": project,
        "branchName": f"ralph/{task_id}",
        "description": task_spec["task"],
        "aiDevopsTaskId": task_id,
        "qualityChecks": config.get("qualityChecks", DEFAULT_QUALITY_CHECKS),
        "userStories": []
    }

    # 转换 user stories
    for idx, story in enumerate(task_spec.get("userStories", []), start=1):
        story_id = f"US-{idx:03d}"
        source_subtask_id = f"{task_id}-{idx-1}"

        prd["userStories"].append({
            "id": story_id,
            "title": story["title"],
            "description": story.get("description", ""),
            "acceptanceCriteria": story.get("acceptanceCriteria", []),
            "priority": story.get("priority", idx),
            "passes": False,
            "notes": "",
            "sourceSubtaskId": source_subtask_id
        })

    return prd
```

### 3.2 默认质量检查

```python
DEFAULT_QUALITY_CHECKS = {
    "typecheck": "bun run typecheck",
    "lint": "bun run lint",
    "test": "bun run test",
    "browserVerification": False
}

# 可以通过 TaskSpec.metadata 覆盖
task_spec["metadata"]["qualityChecks"] = {
    "typecheck": "npm run typecheck",
    "test": "pytest"
}
```

---

## 4. Python API

### 4.1 导入模块

```python
from task_to_prd import (
    task_spec_to_prd_json,
    load_task_spec_from_file,
    save_prd_to_file,
    validate_prd_json
)
```

### 4.2 主要函数

#### `task_spec_to_prd_json(task_spec, config=None)`

将 TaskSpec 字典转换为 prd.json 字典。

**参数：**
- `task_spec` (dict): TaskSpec 字典
- `config` (dict, optional): 配置覆盖

**返回：**
- `dict`: prd.json 字典

**示例：**
```python
task_spec = {
    "taskId": "task-20260414-001",
    "task": "Add feature",
    "repo": "user01/ai-devops",
    "userStories": [...]
}

prd = task_spec_to_prd_json(task_spec)
```

#### `load_task_spec_from_file(path)`

从 JSON 文件加载 TaskSpec。

**参数：**
- `path` (str): JSON 文件路径

**返回：**
- `dict`: TaskSpec 字典

**示例：**
```python
spec = load_task_spec_from_file("task_spec.json")
```

#### `save_prd_to_file(prd, path)`

将 prd.json 保存到文件。

**参数：**
- `prd` (dict): prd.json 字典
- `path` (str): 输出文件路径

**示例：**
```python
save_prd_to_file(prd, "prd.json")
```

#### `validate_prd_json(prd)`

验证 prd.json 结构是否有效。

**参数：**
- `prd` (dict): prd.json 字典

**返回：**
- `bool`: 是否有效
- `list[str]`: 错误列表（如果无效）

**示例：**
```python
is_valid, errors = validate_prd_json(prd)
if not is_valid:
    print("Validation errors:", errors)
```

---

## 5. CLI 工具

### 5.1 命令行接口

```bash
# 基本用法
./task_to_prd.py <task_spec.json> [output.json]

# 示例
./task_to_prd.py task_spec.json prd.json

# 验证输出
./task_to_prd.py --validate prd.json

# 使用自定义配置
./task_to_prd.py task_spec.json prd.json --config custom_config.json
```

### 5.2 配置文件

```json
{
  "qualityChecks": {
    "typecheck": "npm run typecheck",
    "lint": "npm run lint",
    "test": "pytest",
    "browserVerification": true
  }
}
```

---

## 6. 错误处理

### 6.1 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `Missing required field: taskId` | TaskSpec 缺少 taskId | 检查 TaskSpec 格式 |
| `Invalid repo format` | repo 不是 owner/repo 格式 | 确保 repo 字段正确 |
| `No user stories found` | userStories 为空 | 至少需要一个用户故事 |
| `Invalid priority value` | priority 不是整数 | 检查 priority 字段 |

### 6.2 验证规则

转换器在输出前会验证：

1. **必填字段存在**: `project`, `branchName`, `userStories`
2. **User Story 完整性**: 每个 story 必须有 `id`, `title`, `acceptanceCriteria`
3. **Priority 范围**: priority 必须是正整数
4. **Branch Name 唯一性**: 格式必须为 `ralph/{taskId}`

---

## 7. 测试

### 7.1 单元测试

```python
def test_task_spec_to_prd_json():
    task_spec = {
        "taskId": "task-001",
        "task": "Test task",
        "repo": "user01/test-repo",
        "userStories": [
            {"title": "Story 1", "acceptanceCriteria": []}
        ]
    }

    prd = task_spec_to_prd_json(task_spec)

    assert prd["project"] == "test-repo"
    assert prd["branchName"] == "ralph/task-001"
    assert len(prd["userStories"]) == 1
    assert prd["userStories"][0]["id"] == "US-001"
```

### 7.2 集成测试

```bash
# 运行完整测试套件
python3 -m pytest tests/test_task_to_prd.py

# 覆盖率
python3 -m pytest --cov=task_to_prd tests/test_task_to_prd.py
```

---

## 8. 最佳实践

1. **保持 TaskSpec 简洁**: 只包含必要信息，避免过度设计
2. **合理设置优先级**: 使用 1-10 的范围，1 最高优先级
3. **明确的验收标准**: 每个验收标准应该是可测试的
4. **使用元数据**: 通过 metadata 传递额外上下文（如 issue 链接）
5. **验证输出**: 每次转换后验证 prd.json 结构

---

## 9. 扩展性

### 9.1 自定义转换器

```python
def custom_converter(task_spec: dict) -> dict:
    """自定义转换逻辑"""
    prd = task_spec_to_prd_json(task_spec)

    # 添加自定义字段
    prd["customField"] = "value"

    # 修改默认行为
    prd["branchName"] = f"custom/{task_spec['taskId']}"

    return prd
```

### 9.2 多格式支持

未来可扩展支持其他 AI 工具格式：

- `task_spec_to_autopr_json()`
- `task_spec_to_cline_config()`
- `task_spec_to aider_prompt()`

---

## 10. 参考文档

- [TaskSpec 模板](../TASK_SPEC_TEMPLATE.md)
- [Ralph PRD 格式](https://github.com/ralphai/ralph)
- [完整集成文档](../RALPH_INTEGRATION.md)
