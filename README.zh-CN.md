# AI DevOps（中文说明）

用于 Zoe 的本地工具层：负责规划、分发并在本地 Git worktree 中执行编码代理任务。

[![CI](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml/badge.svg)](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml)

Language: [English](README.md) | **简体中文**

## 项目作用

这个仓库是 Zoe 背后的“确定性工作流层”：

- **Zoe**（OpenClaw agent）负责决定调用哪个工具
- **本仓库**提供规划、校验、分发、执行、监控等稳定能力
- **discord.py bot**（可选）提供本地开发/兜底控制入口
- **Dispatcher** 归档 plan，并把可执行子任务写入本地队列
- **zoe-daemon** 消费队列、创建 worktree、写入 prompt、启动代理
- **monitor** 监控活跃任务、PR 和 CI，并在失败时触发重试

### 核心能力

- 结构化任务规划与校验
- 按子任务编译 Prompt
- 分阶段多子任务规划（实现 -> 验证 -> 文档）
- 依赖感知分发
- 基于 SQLite 的任务跟踪
- GitHub Webhook 集成
- CI 失败自动重试（Ralph Loop v2）
- Obsidian 业务上下文注入重试 Prompt
- 成功模式记忆（胜利 Prompt 存储并用于后续规划）
- 本地 PR 评审流水线（Codex + Claude 自动评论）
- 每日清理守护进程（陈旧 worktree + 旧日志）
- Telegram 任务状态通知

## 快速开始

### 前置要求

- Python 3.12+
- Node.js（OpenClaw 运行需要）
- tmux（可选）
- GitHub CLI（可选）

### 安装

```bash
git clone https://github.com/gordon8018/ai-devops.git
cd ai-devops
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-cov python-dotenv
```

### 环境变量

```bash
cp discord/.env.example discord/.env
# 按需填写 DISCORD_TOKEN、DISCORD_GUILD_ID、DISCORD_CHANNEL 等
```

### 运行测试

```bash
./scripts/test.sh
./scripts/test.sh --coverage
./scripts/test.sh --test tests/test_db.py::TestTaskCRUD
```

## 关键目录

| 目录 | 说明 |
|------|------|
| `discord/` | 可选本地控制适配层与 bot 环境 |
| `orchestrator/bin/` | 工具层、schema、daemon、monitor、dispatch |
| `orchestrator/queue/` | 待执行任务队列 |
| `tasks/` | 归档计划（`tasks/<planId>/plan.json`） |
| `worktrees/` | 按任务隔离的 Git worktree |
| `repos/` | 源仓库目录 |
| `agents/` | 编码代理运行脚本 |
| `scripts/` | 辅助脚本（spawn、cleanup、babysit、test） |
| `.clawdbot/` | SQLite、失败日志、Prompt 模板 |
| `docs/` | 文档 |
| `tests/` | Pytest 测试集 |

## 关键文件

| 文件 | 说明 |
|------|------|
| `orchestrator/bin/zoe_tools.py` | 统一工具层入口（规划/分发） |
| `orchestrator/bin/zoe_tool_api.py` | 供 agent 调用的 JSON I/O 适配器 |
| `orchestrator/bin/planner_engine.py` | 规划引擎 |
| `orchestrator/bin/plan_schema.py` | 计划校验（DAG、Prompt 限制） |
| `orchestrator/bin/dispatch.py` | 依赖感知分发与队列生成 |
| `orchestrator/bin/zoe-daemon.py` | 队列消费、worktree 管理、代理启动 |
| `orchestrator/bin/monitor.py` | PR/CI 监控与重试逻辑 |
| `orchestrator/bin/reviewer.py` | PR 自动评审（Codex + Claude） |
| `orchestrator/bin/obsidian_client.py` | Obsidian Local REST API 客户端 |
| `orchestrator/bin/cleanup_daemon.py` | 每日清理任务 |
| `orchestrator/bin/notify.py` | Telegram 通知 |
| `orchestrator/bin/db.py` | SQLite 任务追踪 |
| `orchestrator/bin/webhook_server.py` | GitHub Webhook 接收器 |
| `orchestrator/bin/agent.py` | Agent CLI（spawn/list/status/kill） |

## 工具契约（Tool Contracts）

通过 `zoe_tool_api.py` 暴露：

| 工具 | 说明 |
|------|------|
| `plan_task` | 只生成计划，不分发 |
| `plan_and_dispatch_task` | 生成计划并立即分发 |
| `dispatch_plan` | 分发已有计划 |
| `task_status` | 查询任务状态 |
| `list_plans` | 列出最近计划 |
| `retry_task` | 手动触发失败任务重试 |

```bash
./.venv/bin/python orchestrator/bin/zoe_tool_api.py schema --pretty
printf '%s\n' '{"tool":"list_plans","args":{"limit":3}}' | \
  ./.venv/bin/python orchestrator/bin/zoe_tool_api.py invoke
```

## 队列与执行模型

### 任务状态流转

```text
queued -> running -> pr_created -> ready -> merged
                      |
                      -> needs_rebase / blocked / timeout
```

## 常用环境变量

| 变量 | 说明 |
|------|------|
| `DISCORD_TOKEN` | Discord Bot Token |
| `DISCORD_GUILD_ID` | Discord 服务器 ID |
| `DISCORD_CHANNEL` | 默认频道 ID |
| `DISCORD_ALLOWED_USERS` | 允许用户 ID（逗号分隔） |
| `AI_DEVOPS_HOME` | AI DevOps 根目录（默认 `~/ai-devops`） |
| `CODEX_RUNNER_PATH` | Codex 运行脚本路径 |
| `GITHUB_WEBHOOK_SECRET` | Webhook 签名密钥 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | Telegram Chat/Group ID |
| `OBSIDIAN_API_TOKEN` | Obsidian API Token（可选） |
| `OBSIDIAN_API_PORT` | Obsidian API 端口（默认 `27123`） |

## CI/CD

GitHub Actions 自动执行：

- `test`：Python 3.12 + pytest + coverage
- `lint`：flake8 + black + isort
- `coverage`：上传 Codecov

触发条件：

- push 到 `main`/`master`
- PR 到 `main`/`master`

配置文件：`.github/workflows/ci.yml`

## 常用脚本

| 脚本 | 作用 |
|------|------|
| `scripts/spawn-agent.sh` | 从命令行发起 `plan_and_dispatch_task` |
| `scripts/cleanup-worktrees.sh` | 运行一次清理守护进程 |
| `scripts/babysit.sh` | 只读查看 tmux 会话与 SQLite 状态 |
| `scripts/test.sh` | 运行 pytest（支持 `--coverage`） |

```bash
./scripts/spawn-agent.sh my-org/my-repo "Fix login bug" "Auth token not invalidated on logout"
./scripts/babysit.sh
./scripts/cleanup-worktrees.sh
```

## 故障排查

| 问题 | 建议排查 |
|------|----------|
| 队列不消费 | 确认 `zoe-daemon.py` 是否运行 |
| 任务卡在 `running` | 看 `monitor.py` 日志并检查 tmux |
| CI 重试未触发 | 确认 `monitor.py` 与 `GITHUB_WEBHOOK_SECRET` |
| Telegram 无通知 | 检查 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` |
| Obsidian 上下文缺失 | 检查 `OBSIDIAN_API_TOKEN` 和插件状态 |
| worktree 堆积 | 手动执行 `./scripts/cleanup-worktrees.sh` |

## 延伸阅读

- [docs/zoe_planner.md](docs/zoe_planner.md)
- [docs/TEST_COVERAGE.md](docs/TEST_COVERAGE.md)
- [docs/agent-cli.md](docs/agent-cli.md)
- [docs/sqlite-migration-summary.md](docs/sqlite-migration-summary.md)
- [docs/webhook-setup.md](docs/webhook-setup.md)

---

**License:** MIT | **Maintainer:** Gordon Yang

