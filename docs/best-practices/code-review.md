# Code Review 标准

## 概述

本文档定义 Ralph 集成系统的 Code Review 标准，确保代码质量和一致性。

---

## Review 流程

### Review 前准备

**提交者：**

1. 确保 PR 通过所有质量检查
2. 更新相关文档
3. 提供清晰的 PR 描述
4. 添加必要的标签

**Reviewer：**

1. 熟悉相关代码
2. 理解业务需求
3. 准备 Review 检查清单

---

### Review 过程

1. **自动化检查**
   - CI/CD 检查通过
   - 所有测试通过
   - 代码覆盖率达标

2. **代码 Review**
   - 检查代码质量
   - 验证实现正确性
   - 确保符合规范

3. **测试验证**
   - 运行本地测试
   - 验证功能
   - 检查边界情况

4. **批准或请求修改**

---

### Review 后

**批准：**

1. 合并到主分支
2. 更新版本号
3. 发布 Release Note

**请求修改：**

1. 提供清晰的修改意见
2. 等待作者更新
3. 重新 Review

---

## Review 检查清单

### 功能性

- [ ] 实现符合需求
- [ ] 边界情况处理正确
- [ ] 错误处理完善
- [ ] 性能可接受

### 代码质量

- [ ] 代码可读性良好
- [ ] 变量和函数命名清晰
- [ ] 代码结构合理
- [ ] 没有冗余代码

### 测试

- [ ] 单元测试覆盖充分
- [ ] 集成测试通过
- [ ] 测试用例有意义
- [ ] 测试覆盖率达标

### 文档

- [ ] 更新了相关文档
- [ ] 代码注释充分
- [ ] API 文档更新
- [ ] README 更新（如需要）

### 安全性

- [ ] 没有安全漏洞
- [ ] 敏感信息未泄露
- [ ] 输入验证充分
- [ ] 权限控制正确

---

## Review 规范

### 代码风格

**Python (PEP 8):**

```python
# 好的代码
def process_task(task_id: str, status: str) -> dict:
    """Process a task and update its status."""
    state = RalphState()
    return state.update(task_id, status=status)


# 不好的代码
def pt(tid,s):
    state=RalphState()
    return state.update(tid, status=s)
```

**TypeScript:**

```typescript
// 好的代码
async function createTask(task: TaskCreateDTO): Promise<Task> {
  const taskEntity = new TaskEntity();
  Object.assign(taskEntity, task);
  return this.taskRepository.save(taskEntity);
}

// 不好的代码
async function ct(t:any) {
  const te=new TaskEntity();
  Object.assign(te,t);
  return this.tr.save(te);
}
```

---

### 命名规范

**变量和函数：**

```python
# 好的命名
task_id = "task-001"
user_name = "John"
def get_task_status(task_id: str) -> str:
    pass

# 不好的命名
tid = "task-001"
un = "John"
def gts(t: str) -> str:
    pass
```

**类：**

```python
# 好的命名
class TaskManager:
    pass

class DatabaseConnection:
    pass

# 不好的命名
class TM:
    pass

class DBConn:
    pass
```

---

### 注释规范

**函数文档：**

```python
# 好的注释
def create_task(task_spec: dict) -> dict:
    """Create a new task from TaskSpec.

    Args:
        task_spec: TaskSpec dictionary containing task information

    Returns:
        dict: Created task information including task_id

    Raises:
        ValueError: If task_spec is invalid
        DatabaseError: If database operation fails
    """
    # Implementation

# 不好的注释
def create_task(task_spec):
    # Create task
    pass
```

**行内注释：**

```python
# 好的注释
# Retry connection up to 3 times with exponential backoff
for attempt in range(3):
    try:
        connect()
        break
    except ConnectionError:
        wait_time = 2 ** attempt
        time.sleep(wait_time)

# 不好的注释
# Try to connect
for i in range(3):
    try:
        connect()
        break
    except:
        time.sleep(i)
```

---

### 错误处理

**好的错误处理：**

```python
try:
    result = runner.run(max_iterations=10)
except subprocess.TimeoutExpired:
    logger.error("Task timed out")
    state.update(task_id, status="failed")
except FileNotFoundError as e:
    logger.error(f"File not found: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    raise
```

**不好的错误处理：**

```python
try:
    result = runner.run(max_iterations=10)
except:
    pass  # 静默忽略所有错误
```

---

## Review 反馈

### 反馈格式

**使用友好的语气：**

```
好的反馈：
"I noticed that the error handling in this function could be improved.
Consider using specific exceptions instead of a generic Exception."

不好的反馈：
"This error handling is terrible. Fix it."
```

**提供具体的建议：**

```
好的反馈：
"Instead of using list.index() which is O(n), consider using a dictionary for O(1) lookup."

不好的反馈：
"This function is slow. Make it faster."
```

**解释原因：**

```
好的反馈：
"I suggest moving this validation to the beginning of the function to fail fast.
This will make debugging easier and avoid unnecessary processing."

不好的反馈：
"Move this code to the top."
```

---

### 常见 Review 意见

#### 1. 魔法数字

**不好：**

```python
if len(tasks) > 10:
    process_tasks(tasks[:10])
```

**好：**

```python
MAX_TASKS = 10
if len(tasks) > MAX_TASKS:
    process_tasks(tasks[:MAX_TASKS])
```

---

#### 2. 重复代码

**不好：**

```python
def process_task_1(task):
    if task['status'] == 'running':
        log_task(task)
        update_task(task)

def process_task_2(task):
    if task['status'] == 'running':
        log_task(task)
        update_task(task)
```

**好：**

```python
def process_task(task):
    if task['status'] == 'running':
        log_task(task)
        update_task(task)
```

---

#### 3. 长函数

**不好：**

```python
def process_complex_task(task):
    # 100 lines of code
```

**好：**

```python
def process_complex_task(task):
    validate_task(task)
    transform_task(task)
    save_task(task)

def validate_task(task):
    # 10 lines

def transform_task(task):
    # 10 lines

def save_task(task):
    # 10 lines
```

---

#### 4. 硬编码路径

**不好：**

```python
db_path = "/home/user/agent_tasks.db"
```

**好：**

```python
import os
db_path = os.getenv("RALPH_DB_PATH", "~/.ralph/agent_tasks.db")
```

---

## Review 角色

### 提交者

**职责：**
- 确保代码质量
- 编写清晰的 PR 描述
- 响应 Review 意见
- 及时更新代码

**最佳实践：**
- 在提交前自测
- 使用描述性的提交信息
- 为复杂代码提供注释

---

### Reviewer

**职责：**
- 彻底 Review 代码
- 提供建设性反馈
- 确保代码符合规范
- 验证功能正确性

**最佳实践：**
- 及时 Review
- 使用友好的语气
- 解释 Review 意见的原因
- 确认误解

---

### Approver

**职责：**
- 最终批准合并
- 确保所有 Review 意见已解决
- 验证 CI/CD 通过
- 合并代码

**最佳实践：**
- 确保至少一个 Reviewer 批准
- 检查所有测试通过
- 验证文档更新

---

## 自动化 Review

### Pre-commit Hooks

**配置：**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/psf/black
    rev: 23.3.0
    hooks:
      - id: black

  - repo: https://github.com/PyCQA/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
```

**安装：**

```bash
pip install pre-commit
pre-commit install
```

---

### CI/CD 集成

**GitHub Actions:**

```yaml
# .github/workflows/code-review.yml
name: Code Review

on:
  pull_request:
    branches: [main]

jobs:
  review:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          pip install black flake8 mypy

      - name: Run Black
        run: black --check .

      - name: Run Flake8
        run: flake8 .

      - name: Run MyPy
        run: mypy .
```

---

## Review 指标

### 关键指标

| 指标 | 目标 | 说明 |
|------|------|------|
| **Review 响应时间** | < 24 小时 | 从提交到首次 Review |
| **Review 完成时间** | < 48 小时 | 从提交到批准 |
| **修改轮次** | < 3 轮 | PR 修改次数 |
| **代码覆盖率** | > 80% | 测试覆盖率 |
| **Lint 通过率** | 100% | Lint 检查通过率 |

---

## 最佳实践

### 对于提交者

1. **小而频繁的 PR**: 避免大型的 PR
2. **清晰的描述**: 说明变更的目的和影响
3. **自测**: 提交前本地测试
4. **响应反馈**: 及时响应 Review 意见

### 对于 Reviewer

1. **及时 Review**: 不拖延 Review
2. **建设性反馈**: 提供可操作的建议
3. **友好语气**: 使用礼貌的语言
4. **解释原因**: 说明为什么需要修改

### 对于团队

1. **定期 Review**: 固定时间集中 Review
2. **结对 Review**: 重要的 PR 多人 Review
3. **持续改进**: 定期评估和改进 Review 流程
4. **知识共享**: 通过 Review 传播知识

---

## 参考文档

- [质量门禁设计](../architecture/04-quality-gate.md)
- [TaskSpec 设计指南](./task-spec-design.md)
- [PRD 编写指南](./prd-quality.md)
