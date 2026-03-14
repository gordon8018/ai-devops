# Agent CLI 使用文档

## 概述

`agent` 是 AI DevOps 系统的统一命令行接口，提供任务管理、规划、派发等核心功能。

## 安装

CLI 已内置于 `~/ai-devops/orchestrator/bin/agent.py`

**可选：创建全局别名**

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
alias agent='python3 ~/ai-devops/orchestrator/bin/agent.py'

# 或者创建符号链接
sudo ln -s ~/ai-devops/orchestrator/bin/agent.py /usr/local/bin/agent
```

## 命令参考

### 1. init - 初始化数据库

```bash
agent init
```

初始化 SQLite 数据库（首次使用时执行）。

---

### 2. spawn - 派发简单任务

```bash
agent spawn --repo <repo> --title <title> [options]
```

**参数:**
- `--repo` (必填): 仓库名称
- `--title` (必填): 任务标题
- `--description`: 任务描述
- `--agent`: 使用的 agent (codex|claude), 默认 codex
- `--model`: 模型名称，默认 gpt-5.3-codex
- `--effort`: 工作量 (low|medium|high), 默认 medium
- `--files`: 文件提示 (逗号分隔)

**示例:**
```bash
agent spawn --repo my-app --title "Fix login bug"
agent spawn --repo my-app --title "Add tests" --effort high --files "tests/,src/auth.ts"
```

---

### 3. list - 列出任务

```bash
agent list [options]
```

**参数:**
- `--status`: 过滤状态 (all|running|queued|ready|blocked), 默认 all
- `--limit`: 最大显示数量，默认 20
- `--json`: 输出 JSON 格式

**示例:**
```bash
agent list
agent list --status running
agent list --json
```

**输出示例:**
```
============================================================
Tasks (3 found)
============================================================

ID                    STATUS   REPO       TITLE           AGENT  STARTED_AT
--------------------------------------------------------------------------------------
1773414298741-age...  running  my-app     Fix login bug   codex  2026-03-13 22:30:00
1773414298742-age...  queued   my-app     Add tests       codex
1773414298743-age...  ready    my-app     Update docs     codex  2026-03-13 21:00:00
```

---

### 4. status - 查看任务详情

```bash
agent status <task-id> [options]
```

**参数:**
- `task_id` (必填): 任务 ID
- `--json`: 输出 JSON 格式

**示例:**
```bash
agent status 1773414298741-my-app-fix-login-bug-S1
agent status 1773414298741-my-app-fix-login-bug-S1 --json
```

---

### 5. send - 发送消息给运行中的 Agent

```bash
agent send <task-id> <message>
```

**参数:**
- `task_id` (必填): 任务 ID
- `message` (必填): 要发送的消息

**要求:** 任务必须在 tmux 会话中运行

**示例:**
```bash
agent send 1773414298741-my-app-fix-login-bug-S1 "please check line 42"
```

---

### 6. kill - 终止任务

```bash
agent kill <task-id>
```

**参数:**
- `task_id` (必填): 任务 ID

**操作:**
- 终止 tmux 会话
- 杀死后台进程
- 更新状态为 `killed`

**示例:**
```bash
agent kill 1773414298741-my-app-fix-login-bug-S1
```

---

### 7. plan - 规划任务（不派发）

```bash
agent plan --repo <repo> --title <title> --description <desc> [options]
```

**参数:**
- `--repo` (必填): 仓库名称
- `--title` (必填): 任务标题
- `--description` (必填): 任务描述
- `--user`: 请求者，默认 cli
- `--agent`: 使用的 agent，默认 codex
- `--model`: 模型名称，默认 gpt-5.3-codex
- `--effort`: 工作量，默认 medium
- `--files`: 文件提示 (逗号分隔)
- `--quiet`: 安静模式，不显示 subtask 详情

**示例:**
```bash
agent plan --repo my-app --title "Refactor auth" --description "Refactor authentication flow"
agent plan --repo my-app --title "Add tests" --description "Add unit tests" --files "src/auth.ts"
```

**输出示例:**
```
✓ Plan created: 1773414298741-my-app-refactor-auth
  Subtasks: 3
  Plan file: /home/user01/ai-devops/tasks/1773414298741-my-app-refactor-auth/plan.json

Subtasks:
  S1: Prepare the implementation surface
  S2: Land the primary implementation
         Depends: S1
  S3: Add validation and regression coverage
         Depends: S2
```

---

### 8. dispatch - 派发已有 Plan

```bash
agent dispatch --plan <plan-file>
```

**参数:**
- `--plan` (必填): plan.json 文件路径

**示例:**
```bash
agent dispatch --plan ~/ai-devops/tasks/1773414298741-my-app-refactor-auth/plan.json
```

---

### 9. plan-and-dispatch - 规划并派发

```bash
agent plan-and-dispatch --repo <repo> --title <title> --description <desc> [options]
```

**参数:** 同 `plan` 命令

**示例:**
```bash
agent plan-and-dispatch --repo my-app --title "Fix bug" --description "Fix the login bug"
```

---

### 10. retry - 重试失败任务

```bash
agent retry <task-id> [--force]
```

**参数:**
- `task_id` (必填): 任务 ID
- `--force`: 强制重试（即使状态不是失败）

**适用状态:** blocked, agent_failed, timeout, log_stale

**示例:**
```bash
agent retry 1773414298741-my-app-fix-login-bug-S1
agent retry 1773414298741-my-app-fix-login-bug-S1 --force
```

---

### 11. clean - 清理旧任务

```bash
agent clean --days <N> [--dry-run]
```

**参数:**
- `--days`: 删除 N 天前的任务，默认 30
- `--dry-run`: 预览不删除

**清理条件:** 状态为 ready/killed/agent_exited 且超过指定天数

**示例:**
```bash
agent clean --days 30 --dry-run
agent clean --days 7
```

---

## 工作流示例

### 场景 1: 快速派发简单任务

```bash
# 派发任务
agent spawn --repo my-app --title "Update README"

# 查看队列
agent list --status queued

# 等待 daemon 消费
agent list --status running
```

### 场景 2: 规划复杂任务

```bash
# 先规划（不执行）
agent plan --repo my-app --title "Add OAuth" --description "Add GitHub OAuth login"

# 检查 plan
cat ~/ai-devops/tasks/*/plan.json

# 确认后派发
agent dispatch --plan ~/ai-devops/tasks/xxx/plan.json
```

### 场景 3: 监控任务进度

```bash
# 查看所有运行中任务
agent list --status running

# 查看特定任务详情
agent status <task-id>

# 发送提醒给 agent
agent send <task-id> "don't forget to update tests"
```

### 场景 4: 处理失败任务

```bash
# 查看失败任务
agent list --status blocked

# 查看失败原因
agent status <task-id>

# 重试
agent retry <task-id>

# 或者强制重试
agent retry <task-id> --force
```

---

## 任务状态说明

| 状态 | 说明 |
|------|------|
| `queued` | 等待 daemon 消费 |
| `running` | 正在执行 |
| `pr_created` | PR 已创建，等待 CI |
| `ready` | CI 通过，可合并 |
| `needs_rebase` | 需要 rebase |
| `retrying` | 正在重试 |
| `blocked` | 阻塞（重试次数耗尽） |
| `agent_failed` | Agent 执行失败 |
| `agent_exited` | Agent 正常退出 |
| `agent_dead` | Agent 进程死亡 |
| `log_stale` | 日志超过 60 分钟未更新 |
| `timeout` | 超过 180 分钟硬限制 |
| `killed` | 用户终止 |

---

## 故障排查

### 问题 1: 任务一直 queued

```bash
# 检查 daemon 是否在运行
ps aux | grep zoe-daemon

# 检查队列目录
ls -la ~/ai-devops/orchestrator/queue/

# 手动启动 daemon
python3 ~/ai-devops/orchestrator/bin/zoe-daemon.py
```

### 问题 2: 任务卡死

```bash
# 查看任务状态
agent status <task-id>

# 如果是 log_stale 或 timeout
agent kill <task-id>
agent retry <task-id>
```

### 问题 3: 数据库损坏

```bash
# 备份并重建
cp ~/.clawdbot/agent_tasks.db ~/.clawdbot/agent_tasks.db.bak
rm ~/.clawdbot/agent_tasks.db
agent init
```

---

## 高级用法

### 脚本化批量操作

```bash
#!/bin/bash
# 批量派发任务

repos=("repo1" "repo2" "repo3")
for repo in "${repos[@]}"; do
    agent spawn --repo "$repo" --title "Update dependencies"
done
```

### JSON 输出用于自动化

```bash
# 获取所有运行中任务的 JSON
agent list --status running --json | jq '.[] | {id, repo, title}'
```

---

## 相关文件

- 数据库：`~/.clawdbot/agent_tasks.db`
- 队列：`~/ai-devops/orchestrator/queue/`
- Plans: `~/ai-devops/tasks/<plan-id>/plan.json`
- 日志：`~/ai-devops/logs/<task-id>.log`
