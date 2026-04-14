# CLI 工具参考

## 概述

本文档提供 Ralph 集成系统的所有命令行工具完整参考。

---

## 目录

- [task_to_prd](#task_to_prd) - TaskSpec 转换工具
- [ralph_state](#ralph_state) - 状态管理工具
- [ralph_runner](#ralph_runner) - Ralph 执行工具
- [quality_gate](#quality_gate) - 质量检查工具
- [context_enhancement](#context_enhancement) - 上下文增强工具
- [feedback_loop](#feedback_loop) - 反馈分析工具

---

## task_to_prd

### 基本用法

```bash
./task_to_prd.py <task_spec.json> [output.json] [options]
```

### 参数

| 参数 | 说明 |
|------|------|
| `task_spec.json` | 输入 TaskSpec 文件路径（必填） |
| `output.json` | 输出 prd.json 文件路径（可选，默认: prd.json） |

### 选项

| 选项 | 说明 |
|------|------|
| `-h, --help` | 显示帮助信息 |
| `-v, --version` | 显示版本信息 |
| `--config <file>` | 使用自定义配置文件 |
| `--validate` | 只验证输出，不保存 |
| `--pretty` | 美化 JSON 输出 |
| `--verbose` | 显示详细输出 |

### 示例

**基本转换：**

```bash
./task_to_prd.py task_spec.json prd.json
```

**使用自定义配置：**

```bash
./task_to_prd.py task_spec.json prd.json --config custom_config.json
```

**只验证输出：**

```bash
./task_to_prd.py task_spec.json --validate
```

**美化输出：**

```bash
./task_to_prd.py task_spec.json --pretty
```

---

## ralph_state

### 基本用法

```bash
./ralph_state.py <command> [arguments] [options]
```

### 命令

#### create

创建新任务状态。

```bash
./ralph_state.py create <task_id> [status] [progress]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务唯一标识符 |
| `status` | 初始状态（默认: queued） |
| `progress` | 初始进度 0-100（默认: 0） |

**示例：**

```bash
./ralph_state.py create task-20260414-001 queued 0
```

---

#### get

获取任务状态。

```bash
./ralph_state.py get <task_id>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务唯一标识符 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--format <format>` | 输出格式（json, table, pretty） |

**示例：**

```bash
./ralph_state.py get task-20260414-001
./ralph_state.py get task-20260414-001 --format json
./ralph_state.py get task-20260414-001 --format table
```

---

#### list

列出任务状态。

```bash
./ralph_state.py list [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--status <status>` | 按状态筛选 |
| `--start-date <date>` | 开始日期（YYYY-MM-DD） |
| `--end-date <date>` | 结束日期（YYYY-MM-DD） |
| `--limit <n>` | 最大返回数量 |
| `--offset <n>` | 偏移量 |
| `--format <format>` | 输出格式（json, table） |

**示例：**

```bash
# 列出所有任务
./ralph_state.py list

# 列出运行中的任务
./ralph_state.py list --status running

# 列出最近 10 个任务
./ralph_state.py list --limit 10

# 按日期范围筛选
./ralph_state.py list --start-date 2026-04-01 --end-date 2026-04-30

# JSON 输出
./ralph_state.py list --format json
```

---

#### update

更新任务状态。

```bash
./ralph_state.py update <task_id> [status] [progress]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务唯一标识符 |
| `status` | 新状态 |
| `progress` | 新进度 0-100 |

**示例：**

```bash
# 更新状态
./ralph_state.py update task-20260414-001 running

# 更新状态和进度
./ralph_state.py update task-20260414-001 running 50
```

---

#### log

追加日志到任务。

```bash
./ralph_state.py log <task_id> <message>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务唯一标识符 |
| `message` | 日志消息 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--level <level>` | 日志级别（INFO, WARNING, ERROR） |

**示例：**

```bash
./ralph_state.py log task-20260414-001 "Iteration 3 completed"
./ralph_state.py log task-20260414-001 "Typecheck failed" --level ERROR
```

---

#### delete

删除任务状态。

```bash
./ralph_state.py delete <task_id>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_id` | 任务唯一标识符 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--force` | 强制删除（不确认） |

**示例：**

```bash
./ralph_state.py delete task-20260414-001
./ralph_state.py delete task-20260414-001 --force
```

---

#### stats

显示统计信息。

```bash
./ralph_state.py stats [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--days <n>` | 统计天数（默认: 30） |

**示例：**

```bash
./ralph_state.py stats
./ralph_state.py stats --days 7
```

**输出示例：**

```
Status Counts:
  queued:      5
  running:     2
  completed:   15
  failed:      1

Completion Rate: 88.2%
Average Execution Time: 3600s
Total Tasks: 23
```

---

## ralph_runner

### 基本用法

```bash
./ralph_runner.py <command> [arguments] [options]
```

### 命令

#### run

运行 Ralph。

```bash
./ralph_runner.py run <ralph_dir> [max_iterations] [timeout]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |
| `max_iterations` | 最大迭代次数（默认: 10） |
| `timeout` | 超时时间（秒，默认: 7200） |

**选项：**

| 选项 | 说明 |
|------|------|
| `--background` | 后台运行 |
| `--tool <tool>` | AI 工具（claude 或 amp，默认: claude） |
| `--prd <file>` | prd.json 文件路径 |

**示例：**

```bash
# 前台运行
./ralph_runner.py run /tmp/ralph-task-001 10 7200

# 后台运行
./ralph_runner.py run /tmp/ralph-task-001 --background

# 使用 Amp
./ralph_runner.py run /tmp/ralph-task-001 --tool amp
```

---

#### status

获取执行状态。

```bash
./ralph_runner.py status <ralph_dir>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |

**示例：**

```bash
./ralph_runner.py status /tmp/ralph-task-001
```

**输出示例：**

```
Status: running
PID: 12345
Start Time: 2026-04-14T15:00:00
Duration: 1800s
```

---

#### progress

获取执行进度。

```bash
./ralph_runner.py progress <ralph_dir>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |

**示例：**

```bash
./ralph_runner.py progress /tmp/ralph-task-001
```

**输出示例：**

```
Iterations: 5/10
Progress: 50%

User Stories:
  [✓] US-001: Create migration
  [✗] US-002: Update API
  [ ] US-003: Add tests
```

---

#### wait

等待执行完成。

```bash
./ralph_runner.py wait <ralph_dir> [poll_interval] [timeout]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |
| `poll_interval` | 轮询间隔（秒，默认: 30） |
| `timeout` | 超时时间（秒，默认: 7200） |

**示例：**

```bash
./ralph_runner.py wait /tmp/ralph-task-001 30 7200
```

---

#### terminate

终止执行。

```bash
./ralph_runner.py terminate <ralph_dir>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--force` | 强制终止（SIGKILL） |

**示例：**

```bash
./ralph_runner.py terminate /tmp/ralph-task-001
./ralph_runner.py terminate /tmp/ralph-task-001 --force
```

---

#### logs

获取日志。

```bash
./ralph_runner.py logs <ralph_dir> [tail]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `ralph_dir` | Ralph 工作目录 |
| `tail` | 只返回最后 N 行 |

**示例：**

```bash
./ralph_runner.py logs /tmp/ralph-task-001
./ralph_runner.py logs /tmp/ralph-task-001 100
```

---

## quality_gate

### 基本用法

```bash
./quality_gate.py <command> [arguments] [options]
```

### 命令

#### check

运行质量检查。

```bash
./quality_gate.py check <branch> [options]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `branch` | 分支名称 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--checks <list>` | 检查列表（逗号分隔） |
| `--verbose` | 显示详细输出 |

**示例：**

```bash
# 运行所有检查
./quality_gate.py check ralph/task-20260414-001

# 运行特定检查
./quality_gate.py check ralph/task-20260414-001 --checks typecheck,lint
```

---

#### create-pr

创建 Pull Request。

```bash
./quality_gate.py create-pr <branch> [options]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `branch` | 分支名称 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--title <title>` | PR 标题 |
| `--body <file>` | PR 描述文件 |
| `--reviewers <list>` | Reviewer 列表（逗号分隔） |

**示例：**

```bash
./quality_gate.py create-pr ralph/task-20260414-001 \
  --title "Add priority field" \
  --reviewers @gordon,@alice
```

---

#### status

获取质量门禁状态。

```bash
./quality_gate.py status <pr_number>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `pr_number` | PR 编号 |

**示例：**

```bash
./quality_gate.py status 123
```

**输出示例：**

```
PR #123 Status:
  Status: review_pending
  Local Checks: ✓ passed
  CI Checks: ⏳ pending
  Code Review: ⏳ pending

Overall: ⏳ waiting
```

---

#### watch

监控 PR。

```bash
./quality_gate.py watch <pr_number> [options]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `pr_number` | PR 编号 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--interval <n>` | 轮询间隔（秒，默认: 30） |
| `--timeout <n>` | 超时时间（秒，默认: 7200） |

**示例：**

```bash
./quality_gate.py watch 123
./quality_gate.py watch 123 --interval 10
```

---

## context_enhancement

### 基本用法

```bash
./context_enhancement.py <command> [arguments] [options]
```

### 命令

#### retrieve

检索上下文。

```bash
./context_enhancement.py retrieve <task_spec.json> [options]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_spec.json` | TaskSpec 文件路径 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--type <type>` | 检索类型（static, dynamic, runtime, all） |
| `--output <file>` | 输出文件路径 |

**示例：**

```bash
# 检索所有上下文
./context_enhancement.py retrieve task_spec.json

# 只检索静态上下文
./context_enhancement.py retrieve task_spec.json --type static

# 保存到文件
./context_enhancement.py retrieve task_spec.json --output context.md
```

---

#### assemble

组装上下文。

```bash
./context_enhancement.py assemble <task_spec.json> <prd.json> [options]
```

**参数：**

| 参数 | 说明 |
|------|------|
| `task_spec.json` | TaskSpec 文件路径 |
| `prd.json` | prd.json 文件路径 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--output <file>` | 输出文件路径 |
| `--max-length <n>` | 最大上下文长度 |

**示例：**

```bash
./context_enhancement.py assemble task_spec.json prd.json
./context_enhancement.py assemble task_spec.json prd.json --output context.md
```

---

#### inject

注入上下文。

```bash
./context_enhancement.py inject <prd.json> <context.md>
```

**参数：**

| 参数 | 说明 |
|------|------|
| `prd.json` | prd.json 文件路径 |
| `context.md` | 上下文文件路径 |

**选项：**

| 选项 | 说明 |
|------|------|
| `--output <file>` | 输出文件路径 |

**示例：**

```bash
./context_enhancement.py inject prd.json context.md
./context_enhancement.py inject prd.json context.md --output prd_enhanced.json
```

---

## feedback_loop

### 基本用法

```bash
./feedback_loop.py <command> [arguments] [options]
```

### 命令

#### collect-metrics

收集质量指标。

```bash
./feedback_loop.py collect-metrics [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--days <n>` | 统计天数（默认: 30） |
| `--output <file>` | 输出文件路径 |

**示例：**

```bash
./feedback_loop.py collect-metrics
./feedback_loop.py collect-metrics --days 7
```

**输出示例：**

```
Quality Metrics (last 30 days):

Completion Rate: 88.2%
  - Completed: 15
  - Failed: 2
  - Total: 17

Execution Time:
  - Mean: 3600s
  - Median: 3500s
  - Min: 1800s
  - Max: 7200s

Iterations:
  - Mean: 5.2
  - Median: 5
  - Min: 2
  - Max: 10
```

---

#### analyze-errors

分析错误。

```bash
./feedback_loop.py analyze-errors [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--days <n>` | 分析天数（默认: 30） |
| `--top <n>` | 显示前 N 个错误（默认: 10） |
| `--output <file>` | 输出文件路径 |

**示例：**

```bash
./feedback_loop.py analyze-errors
./feedback_loop.py analyze-errors --days 7 --top 5
```

**输出示例：**

```
Top 10 Common Errors (last 30 days):

1. "ImportError: No module named 'X'" - 8 occurrences
2. "TimeoutError: Operation timed out" - 5 occurrences
3. "SyntaxError: invalid syntax" - 3 occurrences
...
```

---

#### optimize

运行优化周期。

```bash
./feedback_loop.py optimize [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--days <n>` | 分析天数（默认: 30） |
| `--output <file>` | 输出文件路径 |
| `--apply` | 自动应用优化 |

**示例：**

```bash
./feedback_loop.py optimize
./feedback_loop.py optimize --days 7 --output optimization.json
./feedback_loop.py optimize --apply
```

**输出示例：**

```
Optimization Suggestions:

Prompt Improvements:
  1. Add context about project dependencies
  2. Include coding standards and examples

Parameter Adjustments:
  1. Timeout: 7200s -> 9000s (suggested)
  2. Max iterations: 10 -> 12 (suggested)
```

---

#### report

生成报告。

```bash
./feedback_loop.py report [options]
```

**选项：**

| 选项 | 说明 |
|------|------|
| `--days <n>` | 报告天数（默认: 30） |
| `--format <format>` | 报告格式（markdown, json, html） |
| `--output <file>` | 输出文件路径 |

**示例：**

```bash
./feedback_loop.py report
./feedback_loop.py report --days 7 --format markdown --output report.md
```

---

## 通用选项

所有工具支持以下通用选项：

| 选项 | 说明 |
|------|------|
| `-h, --help` | 显示帮助信息 |
| `-v, --version` | 显示版本信息 |
| `--verbose` | 显示详细输出 |
| `--quiet` | 静默模式 |
| `--config <file>` | 使用自定义配置文件 |
| `--log-level <level>` | 日志级别（DEBUG, INFO, WARNING, ERROR） |

---

## 配置文件

工具支持通过配置文件设置默认值。

配置文件位置（按优先级）：
1. `./.ralphconfig.json`
2. `~/.ralphconfig.json`
3. `/etc/ralph/config.json`

**配置文件示例：**

```json
{
  "ralph_state": {
    "db_path": "~/.ralph/agent_tasks.db",
    "default_limit": 50
  },
  "ralph_runner": {
    "default_timeout": 7200,
    "default_iterations": 10,
    "default_tool": "claude"
  },
  "quality_gate": {
    "github_token": "${GITHUB_TOKEN}",
    "default_repo": "user01/ai-devops",
    "policy": "strict"
  },
  "context_enhancement": {
    "obsidian_path": "~/Documents/ObsidianVault",
    "gbrain_url": "https://api.gbrain.example.com",
    "max_context_length": 5000
  }
}
```

---

## 环境变量

工具支持以下环境变量：

| 变量 | 说明 |
|------|------|
| `GITHUB_TOKEN` | GitHub API token |
| `RALPH_DB_PATH` | 数据库路径 |
| `RALPH_DIR` | Ralph 工作目录 |
| `RALPH_LOG_LEVEL` | 日志级别 |
| `RALPH_CONFIG` | 配置文件路径 |

**示例：**

```bash
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
export RALPH_LOG_LEVEL="DEBUG"
./ralph_runner.py run /tmp/ralph-task-001
```

---

## 参考文档

- [Python API 参考](./python-api.md)
- [REST API 参考](./rest-api.md)
- [完整集成文档](../RALPH_INTEGRATION.md)
