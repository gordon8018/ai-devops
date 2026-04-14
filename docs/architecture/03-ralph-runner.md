# Ralph 执行器设计 (ralph_runner.py)

## 概述

`ralph_runner.py` 是 Ralph.sh 的包装器，负责启动、监控、管理和同步 Ralph 执行过程。它提供了同步/异步执行、超时处理、进度追踪等功能。

---

## 1. 架构设计

### 1.1 组件职责

```
┌─────────────────────────────────────────────────────────┐
│                   RalphRunner                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  Executor   │  │  Monitor    │  │  Parser     │ │
│  │  启动 ralph  │  │  监控进程   │  │  解析输出    │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
│         │                 │                 │          │
└─────────┼─────────────────┼─────────────────┼──────────┘
          │                 │                 │
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │ ralph.sh │      │  prd.json │      │progress  │
    │  进程    │      │          │      │  .txt    │
    └──────────┘      └──────────┘      └──────────┘
```

### 1.2 核心类

```python
class RalphRunner:
    """Ralph 执行器"""

    def __init__(self, ralph_dir: str, ralph_sh_path: str = None, tool: str = "claude"):
        """初始化执行器"""

    def save_prd_json(self, prd: dict) -> str:
        """保存 prd.json"""

    def run(self, max_iterations: int = 10, timeout: int = 7200, background: bool = False):
        """运行 Ralph"""

    def get_status(self) -> dict:
        """获取执行状态"""

    def parse_progress(self) -> dict:
        """解析进度文件"""

    def parse_prd_json(self) -> dict:
        """解析 prd.json"""

    def wait_for_completion(self, poll_interval: int = 30, timeout: int = 7200) -> str:
        """等待完成"""

    def terminate(self) -> bool:
        """终止执行"""

    def get_logs(self, tail: int = None) -> str:
        """获取日志"""
```

---

## 2. 初始化配置

### 2.1 基本初始化

```python
from ralph_runner import RalphRunner

# 默认配置（推荐）
runner = RalphRunner(
    ralph_dir="/path/to/ralph/dir",
    ralph_sh_path="~/.openclaw/workspace-alpha/ralph/ralph.sh",
    tool="claude"
)

# 使用 Amp 替代 Claude
runner = RalphRunner(
    ralph_dir="/path/to/ralph/dir",
    ralph_sh_path="~/.openclaw/workspace-alpha/ralph/ralph.sh",
    tool="amp"
)

# 指定自定义 ralph.sh 路径
runner = RalphRunner(
    ralph_dir="/path/to/ralph/dir",
    ralph_sh_path="/custom/path/ralph.sh",
    tool="claude"
)
```

### 2.2 配置参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `ralph_dir` | str | 必填 | Ralph 工作目录 |
| `ralph_sh_path` | str | ~/.openclaw/workspace-alpha/ralph/ralph.sh | ralph.sh 脚本路径 |
| `tool` | str | "claude" | AI 工具：claude 或 amp |
| `env` | dict | {} | 环境变量 |
| `log_level` | str | "INFO" | 日志级别 |
| `timeout` | int | 7200 | 默认超时（秒） |

---

## 3. 执行流程

### 3.1 完整执行流程

```python
from ralph_runner import RalphRunner
from task_to_prd import task_spec_to_prd_json
from ralph_state import RalphState

# 1. 准备任务
task_spec = {
    "taskId": "task-20260414-001",
    "task": "Add priority field",
    "repo": "user01/ai-devops",
    "userStories": [...]
}

# 2. 转换为 PRD
prd = task_spec_to_prd_json(task_spec)

# 3. 初始化状态存储
state = RalphState()
state.create(task_spec["taskId"], status="queued")

# 4. 初始化 Runner
runner = RalphRunner(
    ralph_dir="/tmp/ralph-task-001",
    tool="claude"
)

# 5. 保存 PRD
runner.save_prd_json(prd)

# 6. 更新状态
state.update(task_spec["taskId"], status="running")

# 7. 执行（后台）
result = runner.run(
    max_iterations=10,
    timeout=7200,
    background=True
)

# 8. 监控进度
while True:
    status = runner.get_status()
    progress = runner.parse_progress()

    # 同步到状态存储
    state.update(
        task_spec["taskId"],
        progress=progress.get("progress_percent", 0)
    )
    state.append_log(
        task_spec["taskId"],
        f"Iteration {progress.get('iterations', 0)} completed"
    )

    # 检查是否完成
    if status["status"] in ("completed", "failed"):
        break

    time.sleep(30)

# 9. 获取最终状态
final_status = runner.get_status()
state.update(task_spec["taskId"], status=final_status["status"])
```

### 3.2 同步执行

```python
# 前台执行（阻塞直到完成）
result = runner.run(
    max_iterations=10,
    timeout=7200,
    background=False
)

print(f"Execution completed: {result}")
```

### 3.3 异步执行

```python
# 后台执行（立即返回）
result = runner.run(
    max_iterations=10,
    timeout=7200,
    background=True
)

print(f"Ralph started in background: {result['pid']}")

# 后续监控
time.sleep(60)
status = runner.get_status()
print(f"Current status: {status}")
```

---

## 4. 进度监控

### 4.1 获取状态

```python
status = runner.get_status()

# 返回格式
{
    "status": "running",  # running, completed, failed, timeout
    "pid": 12345,
    "exit_code": None,
    "start_time": "2026-04-14T15:00:00",
    "end_time": None,
    "duration": 3600
}
```

### 4.2 解析进度

```python
progress = runner.parse_progress()

# 返回格式
{
    "iterations": 5,
    "total_iterations": 10,
    "stories": [
        {"id": "US-001", "title": "Story 1", "passes": true},
        {"id": "US-002", "title": "Story 2", "passes": false}
    ],
    "progress_percent": 50
}
```

### 4.3 解析 PRD

```python
prd_info = runner.parse_prd_json()

# 返回格式
{
    "project": "ai-devops",
    "branchName": "ralph/task-20260414-001",
    "description": "Add priority field",
    "userStories": [...],
    "qualityChecks": {...}
}
```

### 4.4 等待完成

```python
final_status = runner.wait_for_completion(
    poll_interval=30,  # 每 30 秒检查一次
    timeout=7200       # 最多等待 2 小时
)

# final_status: "completed", "failed", "timeout"
```

---

## 5. 超时处理

### 5.1 软超时（迭代超时）

```python
# 设置最大迭代次数
runner.run(
    max_iterations=10,  # 最多迭代 10 次
    timeout=None         # 不限制总时间
)
```

### 5.2 硬超时（总执行超时）

```python
# 设置总执行时间限制
runner.run(
    max_iterations=None,  # 不限制迭代次数
    timeout=7200         # 最多执行 2 小时
)
```

### 5.3 组合超时

```python
# 同时设置两种超时
runner.run(
    max_iterations=10,   # 最多迭代 10 次
    timeout=7200         # 或最多 2 小时
)
```

### 5.4 超时回调

```python
def on_timeout():
    print("Execution timed out!")
    # 执行清理操作
    runner.terminate()

runner.run(
    max_iterations=10,
    timeout=7200,
    on_timeout=on_timeout
)
```

---

## 6. 日志管理

### 6.1 获取日志

```python
# 获取所有日志
logs = runner.get_logs()

# 获取最后 N 行日志
logs = runner.get_logs(tail=100)

# 实时日志流
for line in runner.log_stream():
    print(line, end='')
```

### 6.2 日志格式

```
[2026-04-14T15:00:00] INFO: Starting Ralph execution
[2026-04-14T15:00:01] INFO: Loading prd.json
[2026-04-14T15:00:05] INFO: Iteration 1 started
[2026-04-14T15:05:00] INFO: US-001 passes
[2026-04-14T15:10:00] INFO: Iteration 2 started
...
```

### 6.3 日志文件

```python
# 指定日志文件路径
runner = RalphRunner(
    ralph_dir="/path/to/ralph",
    log_file="/tmp/ralph-task-001.log"
)
```

---

## 7. 错误处理

### 7.1 常见错误

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| `ralph.sh not found` | ralph.sh 路径错误 | 检查 ralph_sh_path 参数 |
| `prd.json not found` | 未保存 PRD | 调用 save_prd_json() |
| `Execution failed` | Ralph 返回非 0 退出码 | 检查日志和输出 |
| `Timeout exceeded` | 执行时间超过限制 | 增加 timeout 或优化任务 |
| `Process killed` | 进程被外部终止 | 检查系统资源 |

### 7.2 异常处理

```python
try:
    result = runner.run(max_iterations=10, timeout=7200)
except FileNotFoundError as e:
    print(f"File not found: {e}")
except subprocess.TimeoutExpired:
    print("Execution timed out")
    runner.terminate()
except Exception as e:
    print(f"Unexpected error: {e}")
    raise
```

---

## 8. CLI 工具

### 8.1 命令行接口

```bash
# 运行 Ralph
./ralph_runner.py run <ralph_dir> [max_iterations] [timeout]
./ralph_runner.py run /tmp/ralph-task-001 10 7200

# 获取状态
./ralph_runner.py status <ralph_dir>
./ralph_runner.py status /tmp/ralph-task-001

# 获取进度
./ralph_runner.py progress <ralph_dir>
./ralph_runner.py progress /tmp/ralph-task-001

# 等待完成
./ralph_runner.py wait <ralph_dir> [poll_interval] [timeout]
./ralph_runner.py wait /tmp/ralph-task-001 30 7200

# 终止执行
./ralph_runner.py terminate <ralph_dir>
./ralph_runner.py terminate /tmp/ralph-task-001

# 获取日志
./ralph_runner.py logs <ralph_dir> [tail]
./ralph_runner.py logs /tmp/ralph-task-001 100
```

---

## 9. 高级功能

### 9.1 自定义环境变量

```python
runner = RalphRunner(
    ralph_dir="/path/to/ralph",
    env={
        "OPENAI_API_KEY": "sk-...",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "GIT_AUTHOR_NAME": "Ralph AI",
        "GIT_AUTHOR_EMAIL": "ralph@example.com"
    }
)
```

### 9.2 信号处理

```python
import signal

def on_signal(signum, frame):
    print(f"Received signal {signum}")
    runner.terminate()

signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)
```

### 9.3 进程监控

```python
# 检查进程是否仍在运行
is_alive = runner.is_alive()

# 获取进程资源使用
resources = runner.get_resources()
# {
#     "cpu_percent": 45.2,
#     "memory_mb": 512,
#     "io_read_bytes": 1024000,
#     "io_write_bytes": 512000
# }
```

---

## 10. 测试

### 10.1 单元测试

```python
import pytest
from ralph_runner import RalphRunner

def test_save_and_parse_prd():
    runner = RalphRunner(ralph_dir="/tmp/test-ralph")

    prd = {
        "project": "test",
        "branchName": "test/branch",
        "userStories": []
    }

    path = runner.save_prd_json(prd)
    assert os.path.exists(path)

    parsed = runner.parse_prd_json()
    assert parsed["project"] == "test"
```

### 10.2 集成测试

```bash
# 运行完整测试
python3 -m pytest tests/test_ralph_runner.py

# Mock Ralph 执行
python3 -m pytest tests/test_ralph_runner.py -m mock
```

---

## 11. 最佳实践

1. **使用后台执行**: 对长时间运行的任务使用 `background=True`
2. **设置合理超时**: 根据任务复杂度设置 timeout，避免无限等待
3. **定期保存状态**: 在监控循环中定期更新状态存储
4. **清理临时文件**: 任务完成后清理工作目录
5. **日志级别控制**: 生产环境使用 WARNING 或 ERROR
6. **资源监控**: 监控 CPU 和内存使用，避免资源耗尽
7. **错误恢复**: 实现重试逻辑，对临时故障自动恢复

---

## 12. 性能优化

### 12.1 减少轮询频率

```python
# 不好的做法（过于频繁）
while True:
    status = runner.get_status()  # 每秒检查一次
    time.sleep(1)

# 好的做法（合理频率）
while True:
    status = runner.get_status()  # 每 30 秒检查一次
    time.sleep(30)
```

### 12.2 批量日志处理

```python
# 累积日志后批量写入
log_buffer = []
while True:
    log_line = read_log_line()
    log_buffer.append(log_line)

    if len(log_buffer) >= 100:  # 每 100 行批量写入
        state.append_log(task_id, "\n".join(log_buffer))
        log_buffer.clear()
```

---

## 13. 安全性

### 13.1 路径验证

```python
def validate_ralph_dir(path: str) -> bool:
    """验证 Ralph 目录安全性"""
    # 检查路径是否在允许的目录内
    allowed_dirs = ["/tmp/ralph", "/var/ralph"]
    return any(path.startswith(d) for d in allowed_dirs)
```

### 13.2 环境变量隔离

```python
# 使用独立环境变量
env = os.environ.copy()
env["RALPH_TASK_ID"] = task_id
# 不传递敏感环境变量
if "SECRET_KEY" in env:
    del env["SECRET_KEY"]
```

### 13.3 权限控制

```python
# 设置工作目录权限
os.chmod(ralph_dir, 0o755)

# 限制进程权限
runner.run(
    max_iterations=10,
    user="ralph",  # 以特定用户运行
    group="ralph"
)
```

---

## 14. 故障排查

### 14.1 诊断步骤

```bash
# 1. 检查 ralph.sh 是否存在
ls -la ~/.openclaw/workspace-alpha/ralph/ralph.sh

# 2. 检查工作目录
ls -la /path/to/ralph/dir

# 3. 检查 prd.json
cat /path/to/ralph/dir/prd.json

# 4. 检查日志
tail -f /path/to/ralph/dir/ralph.log

# 5. 手动运行 ralph.sh
cd /path/to/ralph/dir
~/.openclaw/workspace-alpha/ralph/ralph.sh
```

### 14.2 常见问题

**问题**: Ralph 启动失败
```bash
# 检查依赖
which claude  # Claude Code CLI 是否安装
which git    # Git 是否可用
```

**问题**: 执行超时
```python
# 增加 timeout 或拆分任务
runner.run(max_iterations=5, timeout=3600)  # 拆分为多个小任务
```

**问题**: 状态不同步
```python
# 强制刷新状态
status = runner.get_status(force=True)
```

---

## 15. 参考文档

- [Ralph 官方文档](https://github.com/ralphai/ralph)
- [完整集成文档](../RALPH_INTEGRATION.md)
- [状态存储设计](./02-ralph-state.md)
