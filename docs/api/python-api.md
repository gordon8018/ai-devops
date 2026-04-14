# Python API 参考

## 概述

本文档提供 Ralph 集成系统的 Python API 完整参考，包括所有模块的类、方法和参数说明。

---

## 目录

- [task_to_prd](#task_to_prd) - TaskSpec → prd.json 转换
- [ralph_state](#ralph_state) - 状态存储 API
- [ralph_runner](#ralph_runner) - Ralph 执行器 API
- [quality_gate](#quality_gate) - 质量门禁 API
- [context_enhancement](#context_enhancement) - 上下文增强 API
- [feedback_loop](#feedback_loop) - 反馈循环 API

---

## task_to_prd

### `task_spec_to_prd_json(task_spec: dict, config: dict = None) -> dict`

将 TaskSpec 转换为 prd.json 格式。

**参数：**
- `task_spec` (dict): TaskSpec 字典
  - `taskId` (str): 任务唯一标识符
  - `task` (str): 任务描述
  - `repo` (str): 仓库路径 (owner/repo)
  - `userStories` (list): 用户故事列表
- `config` (dict, optional): 配置覆盖
  - `qualityChecks` (dict): 质量检查配置

**返回：**
- `dict`: prd.json 字典

**示例：**
```python
from task_to_prd import task_spec_to_prd_json

task_spec = {
    "taskId": "task-20260414-001",
    "task": "Add priority field",
    "repo": "user01/ai-devops",
    "userStories": [
        {"title": "Create migration", "acceptanceCriteria": []}
    ]
}

prd = task_spec_to_prd_json(task_spec)
```

---

### `load_task_spec_from_file(path: str) -> dict`

从 JSON 文件加载 TaskSpec。

**参数：**
- `path` (str): JSON 文件路径

**返回：**
- `dict`: TaskSpec 字典

**示例：**
```python
from task_to_prd import load_task_spec_from_file

spec = load_task_spec_from_file("task_spec.json")
```

---

### `save_prd_to_file(prd: dict, path: str)`

将 prd.json 保存到文件。

**参数：**
- `prd` (dict): prd.json 字典
- `path` (str): 输出文件路径

**示例：**
```python
from task_to_prd import save_prd_to_file

save_prd_to_file(prd, "prd.json")
```

---

### `validate_prd_json(prd: dict) -> tuple[bool, list[str]]`

验证 prd.json 结构是否有效。

**参数：**
- `prd` (dict): prd.json 字典

**返回：**
- `tuple`: (是否有效, 错误列表)

**示例：**
```python
from task_to_prd import validate_prd_json

is_valid, errors = validate_prd_json(prd)
if not is_valid:
    print("Validation errors:", errors)
```

---

## ralph_state

### `class RalphState`

状态存储管理类。

#### `__init__(db_path: str = "agent_tasks.db")`

初始化状态存储。

**参数：**
- `db_path` (str): 数据库文件路径（默认: "agent_tasks.db"）

**示例：**
```python
from ralph_state import RalphState

state = RalphState()
# 或指定路径
state = RalphState(db_path="/path/to/db.db")
```

---

#### `create(task_id: str, status: str = "queued", progress: int = 0, metadata: dict = None) -> int`

创建新任务状态。

**参数：**
- `task_id` (str): 任务唯一标识符
- `status` (str): 初始状态（默认: "queued"）
- `progress` (int): 初始进度 0-100（默认: 0）
- `metadata` (dict, optional): 元数据字典

**返回：**
- `int`: 新插入行的 ID

**示例：**
```python
row_id = state.create(
    task_id="task-001",
    status="queued",
    progress=0,
    metadata={"branch": "ralph/task-001"}
)
```

---

#### `get(task_id: str) -> dict`

获取任务状态。

**参数：**
- `task_id` (str): 任务唯一标识符

**返回：**
- `dict`: 任务状态字典，或 None（如果不存在）

**示例：**
```python
task = state.get("task-001")
print(task["status"])
```

---

#### `update(task_id: str, status: str = None, progress: int = None, metadata: dict = None) -> bool`

更新任务状态。

**参数：**
- `task_id` (str): 任务唯一标识符
- `status` (str, optional): 新状态
- `progress` (int, optional): 新进度
- `metadata` (dict, optional): 新元数据（会覆盖旧值）

**返回：**
- `bool`: 是否更新成功

**示例：**
```python
state.update("task-001", status="running")
state.update("task-001", progress=50)
```

---

#### `append_log(task_id: str, message: str) -> bool`

追加日志到任务。

**参数：**
- `task_id` (str): 任务唯一标识符
- `message` (str): 日志消息

**返回：**
- `bool`: 是否追加成功

**示例：**
```python
state.append_log("task-001", "Iteration 3 completed")
```

---

#### `list(status: str = None, start_date: str = None, end_date: str = None, limit: int = None, offset: int = 0) -> list`

列出任务状态。

**参数：**
- `status` (str, optional): 按状态筛选
- `start_date` (str, optional): 开始日期（ISO 8601）
- `end_date` (str, optional): 结束日期（ISO 8601）
- `limit` (int, optional): 最大返回数量
- `offset` (int, optional): 偏移量

**返回：**
- `list`: 任务状态字典列表

**示例：**
```python
# 获取所有运行中的任务
running_tasks = state.list(status="running")

# 获取最近 10 个任务
recent_tasks = state.list(limit=10)

# 按日期范围筛选
tasks = state.list(
    start_date="2026-04-01",
    end_date="2026-04-30"
)
```

---

#### `delete(task_id: str) -> bool`

删除任务状态。

**参数：**
- `task_id` (str): 任务唯一标识符

**返回：**
- `bool`: 是否删除成功

**示例：**
```python
state.delete("task-001")
```

---

#### `get_stats_by_status() -> dict`

按状态统计任务数量。

**返回：**
- `dict`: 状态计数字典

**示例：**
```python
stats = state.get_stats_by_status()
# {"queued": 5, "running": 2, "completed": 15, ...}
```

---

#### `get_completion_rate() -> float`

计算任务完成率。

**返回：**
- `float`: 完成率（0.0 - 1.0）

**示例：**
```python
rate = state.get_completion_rate()
print(f"Completion rate: {rate * 100:.1f}%")
```

---

## ralph_runner

### `class RalphRunner`

Ralph 执行器类。

#### `__init__(ralph_dir: str, ralph_sh_path: str = None, tool: str = "claude", env: dict = None)`

初始化执行器。

**参数：**
- `ralph_dir` (str): Ralph 工作目录
- `ralph_sh_path` (str, optional): ralph.sh 脚本路径
- `tool` (str): AI 工具（"claude" 或 "amp"）
- `env` (dict, optional): 环境变量

**示例：**
```python
from ralph_runner import RalphRunner

runner = RalphRunner(
    ralph_dir="/tmp/ralph-task-001",
    tool="claude"
)
```

---

#### `save_prd_json(prd: dict) -> str`

保存 prd.json 到工作目录。

**参数：**
- `prd` (dict): prd.json 字典

**返回：**
- `str`: 保存的文件路径

**示例：**
```python
path = runner.save_prd_json(prd)
```

---

#### `run(max_iterations: int = 10, timeout: int = 7200, background: bool = False) -> dict`

运行 Ralph。

**参数：**
- `max_iterations` (int): 最大迭代次数
- `timeout` (int): 超时时间（秒）
- `background` (bool): 是否后台运行

**返回：**
- `dict`: 执行结果字典
  - `success` (bool): 是否成功启动
  - `pid` (int): 进程 ID（后台运行时）
  - `exit_code` (int): 退出码（前台运行时）

**示例：**
```python
# 前台运行
result = runner.run(max_iterations=10, timeout=7200)

# 后台运行
result = runner.run(max_iterations=10, background=True)
print(f"Started with PID: {result['pid']}")
```

---

#### `get_status() -> dict`

获取执行状态。

**返回：**
- `dict`: 状态字典
  - `status` (str): "running", "completed", "failed", "timeout"
  - `pid` (int): 进程 ID
  - `exit_code` (int): 退出码
  - `start_time` (str): 开始时间
  - `end_time` (str): 结束时间
  - `duration` (int): 持续时间（秒）

**示例：**
```python
status = runner.get_status()
print(f"Status: {status['status']}")
```

---

#### `parse_progress() -> dict`

解析进度文件。

**返回：**
- `dict`: 进度字典
  - `iterations` (int): 当前迭代次数
  - `total_iterations` (int): 总迭代次数
  - `stories` (list): 用户故事列表
  - `progress_percent` (int): 进度百分比

**示例：**
```python
progress = runner.parse_progress()
print(f"Progress: {progress['progress_percent']}%")
```

---

#### `parse_prd_json() -> dict`

解析 prd.json 文件。

**返回：**
- `dict`: prd.json 字典

**示例：**
```python
prd_info = runner.parse_prd_json()
```

---

#### `wait_for_completion(poll_interval: int = 30, timeout: int = 7200) -> str`

等待执行完成。

**参数：**
- `poll_interval` (int): 轮询间隔（秒）
- `timeout` (int): 超时时间（秒）

**返回：**
- `str`: 最终状态（"completed", "failed", "timeout"）

**示例：**
```python
final_status = runner.wait_for_completion(poll_interval=30)
print(f"Task finished: {final_status}")
```

---

#### `terminate() -> bool`

终止执行。

**返回：**
- `bool`: 是否终止成功

**示例：**
```python
runner.terminate()
```

---

#### `get_logs(tail: int = None) -> str`

获取日志。

**参数：**
- `tail` (int, optional): 只返回最后 N 行

**返回：**
- `str`: 日志内容

**示例：**
```python
logs = runner.get_logs(tail=100)
```

---

## quality_gate

### `class QualityGateManager`

质量门禁管理器。

#### `__init__(github_token: str, repo: str, policy: str = "strict")`

初始化质量门禁管理器。

**参数：**
- `github_token` (str): GitHub API token
- `repo` (str): 仓库路径（owner/repo）
- `policy` (str): 策略（"strict" 或 "lenient"）

**示例：**
```python
from quality_gate import QualityGateManager

qg = QualityGateManager(
    github_token=os.getenv("GITHUB_TOKEN"),
    repo="user01/ai-devops",
    policy="strict"
)
```

---

#### `run_local_checks(branch: str, checks: list = None) -> dict`

运行本地质量检查。

**参数：**
- `branch` (str): 分支名称
- `checks` (list, optional): 检查列表（默认: ["typecheck", "lint", "test"]）

**返回：**
- `dict`: 检查结果字典

**示例：**
```python
result = qg.run_local_checks(
    branch="ralph/task-001",
    checks=["typecheck", "lint", "test"]
)
```

---

#### `create_pr(branch: str, title: str, reviewers: list = None) -> object`

创建 Pull Request。

**参数：**
- `branch` (str): 分支名称
- `title` (str): PR 标题
- `reviewers` (list, optional): Reviewer 列表

**返回：**
- `object`: GitHub PR 对象

**示例：**
```python
pr = qg.create_pr(
    branch="ralph/task-001",
    title="Add priority field",
    reviewers=["@gordon"]
)
```

---

#### `get_quality_gate_status(pr_number: int) -> dict`

获取质量门禁状态。

**参数：**
- `pr_number` (int): PR 编号

**返回：**
- `dict`: 质量门禁状态字典
  - `local_checks` (dict): 本地检查结果
  - `ci_checks` (dict): CI 检查结果
  - `code_review` (dict): Code Review 状态
  - `all_passed` (bool): 是否全部通过
  - `blocking_issues` (list): 阻塞问题列表

**示例：**
```python
status = qg.get_quality_gate_status(pr_number)
if status["all_passed"]:
    print("All checks passed!")
```

---

## context_enhancement

### `class ContextManager`

上下文管理器。

#### `__init__(repo_path: str, repo: str, github_token: str, task_id: str, ralph_dir: str)`

初始化上下文管理器。

**参数：**
- `repo_path` (str): 本地仓库路径
- `repo` (str): 仓库路径（owner/repo）
- `github_token` (str): GitHub API token
- `task_id` (str): 任务 ID
- `ralph_dir` (str): Ralph 工作目录

**示例：**
```python
from context_enhancement import ContextManager

manager = ContextManager(
    repo_path="/home/user01/ai-devops",
    repo="user01/ai-devops",
    github_token=os.getenv("GITHUB_TOKEN"),
    task_id="task-20260414-001",
    ralph_dir="/tmp/ralph-task-001"
)
```

---

#### `retrieve_all_contexts() -> dict`

检索所有上下文。

**返回：**
- `dict`: 上下文字典
  - `static` (str): 静态上下文
  - `dynamic` (str): 动态上下文
  - `runtime` (str): 运行时上下文

**示例：**
```python
contexts = manager.retrieve_all_contexts()
```

---

### `class ContextAssembler`

上下文组装器。

#### `assemble_before_execution() -> str`

执行前组装上下文。

**返回：**
- `str`: 组装后的上下文

**示例：**
```python
from context_enhancement import ContextAssembler

assembler = ContextAssembler(task_spec, prd)
context = assembler.assemble_before_execution()
```

---

### `class ContextInjector`

上下文注入器。

#### `inject_before_execution(context: str) -> dict`

执行前注入上下文。

**参数：**
- `context` (str): 上下文字符串

**返回：**
- `dict`: 增强后的 prd.json

**示例：**
```python
from context_enhancement import ContextInjector

injector = ContextInjector(prd)
enhanced_prd = injector.inject_before_execution(context)
```

---

## feedback_loop

### `class QualityMetricsCollector`

质量指标收集器。

#### `__init__(state: RalphState)`

初始化收集器。

**示例：**
```python
from feedback_loop import QualityMetricsCollector
from ralph_state import RalphState

collector = QualityMetricsCollector(RalphState())
```

---

#### `collect_completion_rate(days: int = 30) -> dict`

收集完成率。

**参数：**
- `days` (int): 统计天数

**返回：**
- `dict`: 完成率数据

**示例：**
```python
rate = collector.collect_completion_rate(days=30)
```

---

### `class PatternAnalyzer`

模式分析器。

#### `__init__(state: RalphState)`

初始化分析器。

**示例：**
```python
from feedback_loop import PatternAnalyzer

analyzer = PatternAnalyzer(RalphState())
```

---

#### `analyze_failure_patterns(days: int = 30) -> dict`

分析失败模式。

**参数：**
- `days` (int): 分析天数

**返回：**
- `dict`: 失败模式字典

**示例：**
```python
patterns = analyzer.analyze_failure_patterns(days=30)
```

---

### `class AutoOptimizer`

自动优化器。

#### `__init__(state: RalphState)`

初始化优化器。

**示例：**
```python
from feedback_loop import AutoOptimizer

optimizer = AutoOptimizer(RalphState())
```

---

#### `run_optimization_cycle() -> dict`

运行优化周期。

**返回：**
- `dict`: 优化建议

**示例：**
```python
optimization = optimizer.run_optimization_cycle()
```

---

## 错误处理

### 常见异常

| 异常 | 原因 |
|------|------|
| `sqlite3.IntegrityError` | 数据库约束违反（如重复 task_id） |
| `sqlite3.OperationalError` | 数据库操作错误 |
| `FileNotFoundError` | 文件未找到 |
| `subprocess.TimeoutExpired` | 进程超时 |
| `github.GithubException` | GitHub API 错误 |

### 示例

```python
try:
    state.create(task_id="task-001", status="queued")
except sqlite3.IntegrityError as e:
    if "UNIQUE constraint" in str(e):
        print(f"Task {task_id} already exists")
    else:
        raise
```

---

## 参考文档

- [完整集成文档](../RALPH_INTEGRATION.md)
- [架构详细设计](../architecture/)
