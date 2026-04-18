# AI-DevOps（简体中文）

[![CI](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml/badge.svg)](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/pytest-676%20passed%20%7C%201%20skipped-brightgreen.svg)](./docs/TEST_COVERAGE.md)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

语言: [README.md](./README.md) | **简体中文**

---

## 项目定位

**AI-DevOps = 面向产品交付的智能体工程操作系统。**

这个仓库已经不再只是一个“把任务塞给 Agent 的脚本集合”，而是在逐步收敛为一个平台化控制平面，用统一的领域对象、上下文装配、事件流、质量门禁、发布控制、事故处理和控制台界面，驱动一项工作从请求到交付。

当前实现是一个**平台化重构进行中的可运行版本**：

- 保留了已经验证稳定的 Zoe / Orchestrator 内核
- 新增了 `apps/ + packages/ + infra/` 的平台结构
- 引入了 `WorkItem + ContextPack` 作为平台原生对象
- 已经落下 Console API、Console Web、Release Worker、Incident Worker、Quality/Eval 等新层
- 兼容旧入口，现有 `orchestrator/bin` 和 Zoe Tool API 仍然可直接使用

换句话说，这个仓库现在同时包含两层：

- **兼容层**：旧的 `orchestrator/bin/*`、`zoe_tool_api.py`、`zoe-daemon.py`
- **平台层**：新的 `apps/*`、`packages/*`、WorkItem/ContextPack/Release/Incident/Console 模型

---

## 当前实现状态

### 已经落地的核心能力

- **Kernel 内核**：规划、DAG 校验、依赖调度、任务分发、Agent 启动、监控、重试、工作树管理
- **Context 系统**：Git / Obsidian adapter、仓库索引、关系图、ContextPack 装配
- **Quality 系统**：质量门禁、策略引擎、评估指标
- **Release 系统**：Statsig flag adapter、rollout stage、guardrail breach rollback
- **Incident 系统**：告警摄取、指纹聚类、严重性评分、验证关闭
- **Console**：Console API 聚合层 + Next.js 控制台前端
- **Control Plane 存储**：PostgreSQL schema 与 SQLite 迁移器已落地，本地运行仍兼容现有 SQLite/运行时状态

### 已经通过真实联调验证的行为

- **分阶段代码任务默认共享工作树**  
  对于 `Prepare the implementation surface -> Land the primary implementation -> Add validation and regression coverage` 这类串行子任务，Planner 现在默认输出 `worktreeStrategy=shared`，下游子任务会继承上游代码产物，而不是只继承状态。

- **旧的隔离模式仍然保留**  
  显式声明 `worktreeStrategy=isolated` 时，仍然保持一任务一工作树/一分支的旧行为。

- **真实任务全流程跑通**  
  使用真实 `codex exec` runner、本地 daemon、watch 调度、真实 Git 仓库，完成了一个三阶段复杂任务的全链路执行，最终 `S1 / S2 / S3` 全部进入 `ready`。

- **Console 事件聚合可见真实状态**  
  跨进程状态变更会落入共享事件历史，`/api/console/evals` 能看到真实任务的 `ready` 数量和事件统计。

### 最近一次完整回归

执行命令：

```bash
pytest -q
```

结果：

- `676 passed`
- `1 skipped`
- `3 warnings`

耗时：`54.55s`

---

## 架构总览

当前仓库采用“**保留旧内核，逐层升级为平台**”的结构。

### 1. Kernel

来源于原有 `ai-devops / orchestrator`，负责：

- Plan schema 与 DAG 校验
- Dispatcher / Scheduler
- Agent Runtime
- Workspace / Worktree 管理
- Monitor / Retry / Heartbeat
- Event bus 与运行状态记录

关键目录：

- `orchestrator/bin/`
- `packages/kernel/`

### 2. Context

把执行前的上下文从 prompt 拼接，升级为结构化 `ContextPack`。

关键目录：

- `packages/context/indexer/`
- `packages/context/graph/`
- `packages/context/packer/`
- `packages/context/adapters/`

当前已落地的适配器包括：

- Git
- Obsidian

### 3. Quality

把“是否过关”从松散观察变成显式结构化输出。

关键目录：

- `packages/quality/gates/`
- `packages/quality/policy/`
- `packages/quality/evals/`
- `packages/quality/ai_review/`

### 4. Release

把“部署”和“发布”分离，发布控制由 Release Worker 订阅事件执行。

关键目录：

- `packages/release/flags/`
- `packages/release/rollout/`
- `packages/release/rollback/`
- `apps/release_worker/`

当前 rollout stage 包括：

- `team-only`
- `beta`
- `1%`
- `5%`
- `20%`
- `full`

### 5. Incident

把线上异常从文本告警升级为结构化 Incident 对象。

关键目录：

- `packages/incident/triage/`
- `packages/incident/verify/`
- `packages/incident/tickets/`
- `apps/incident_worker/`

当前已落地能力：

- 指纹聚类
- 严重性评分
- 验证后自动关闭

### 6. Console

当前控制台包含两个部分：

- `apps/console_api/`：BFF / 聚合服务
- `apps/console-web/`：Next.js 控制台前端

已提供的页面与聚合视图包括：

- Mission Control
- Work Items
- Task Workspace
- Releases
- Incidents
- Evals
- Governance

---

## 一等领域对象

平台原生对象定义位于 [packages/shared/domain/models.py](/home/user01/ai-devops/worktrees/feat-platform-kernel-bootstrap/packages/shared/domain/models.py)。

当前已经落地的核心对象包括：

- `WorkItem`
- `ContextPack`
- `AgentRun`
- `QualityRun`
- `EvalRun`
- `AuditEvent`

其中：

- `WorkItem` 统一承载 feature / bugfix / incident / release_note / experiment / ops
- `ContextPack` 统一承载 repo scope、docs、recent changes、known failures、risk profile
- `AgentRun` 强制要求执行前绑定 `context_pack_id`
- `AuditEvent` 用于治理、审计与控制台统计

---

## 仓库结构

### 顶层目录

```text
apps/          平台应用层
packages/      平台包与领域实现
orchestrator/  兼容层与已验证内核
infra/         Docker / GitHub Actions / Terraform / K8s
docs/          架构、运行手册、API、最佳实践
agent_scripts/ Agent runner 脚本
scripts/       本地辅助脚本
tests/         主测试集
```

### 应用层

```text
apps/
  console-web/      Next.js 控制台前端
  console_api/      控制台聚合服务 / BFF
  kernel_worker/    预留的内核 worker 应用边界
  incident_worker/  Incident 事件消费与闭环
  release_worker/   Release rollout / rollback 控制
  report_worker/    报告类 worker 预留边界
```

### 平台包

```text
packages/
  shared/    领域模型、运行时状态、公共 schema/config/logging/utils
  kernel/    events / runtime / monitor / storage / scheduler / services
  context/   indexer / graph / packer / adapters
  quality/   gates / policy / evals / ai_review
  release/   flags / rollout / rollback / experiments
  incident/  ingest / triage / tickets / verify
```

### 兼容层

`orchestrator/bin/` 仍然保留了当前线上/本地可直接使用的主流程：

- `zoe-daemon.py`
- `monitor.py`
- `dispatch.py`
- `planner_engine.py`
- `zoe_tools.py`
- `zoe_tool_api.py`

这些兼容入口现在会逐步桥接到平台原生对象，而不是直接把 prompt 和 queue payload 作为唯一核心。

---

## 关键执行路径

### 路径 1：Legacy Zoe 入口

适用于当前仍在使用的本地工具流。

```text
task input
  -> zoe_tool_api / zoe_tools
  -> planner_engine / dispatch
  -> zoe-daemon
  -> agent runner
  -> monitor / status propagation
  -> console / evals / governance
```

### 路径 2：Platform-native WorkItem 入口

适用于新的控制台与平台接口。

```text
WorkItem payload
  -> apps/console_api
  -> WorkItemService
  -> ContextPackAssembler
  -> WorkItem + ContextPack
  -> legacy planner bridge / new kernel services
```

### 路径 3：发布与事故闭环

```text
task_status ready
  -> ReleaseWorker
  -> rollout stage / flag adapter
  -> guardrail breach?
  -> rollback / alert

alert event
  -> IncidentWorker
  -> fingerprint / severity
  -> verify event
  -> close incident
```

---

## 快速开始

### 前置要求

- Python `3.11+`
- Node.js `20+` 或更高版本
- `tmux`，推荐安装
- Git
- 可选：`gh`（GitHub CLI）

### 安装

```bash
git clone https://github.com/gordon8018/ai-devops.git
cd ai-devops

python3 -m venv .venv
source .venv/bin/activate

pip install -U pip setuptools wheel
pip install -e .
pip install pytest pytest-cov python-dotenv

export AI_DEVOPS_HOME="$(pwd)"
export PYTHONPATH="$(pwd)"
```

### 启动本地内核与 API

```bash
source .venv/bin/activate
export AI_DEVOPS_HOME="$(pwd)"
export PYTHONPATH="$(pwd)"

python orchestrator/bin/zoe-daemon.py
```

默认会拉起：

- 任务消费与 Agent 启动
- 控制台 API
- Release Worker
- Incident Worker

### 使用 Zoe Tool API 创建任务

```bash
printf '%s\n' '{
  "tool": "plan_and_dispatch_task",
  "args": {
    "repo": "my-org/my-repo",
    "title": "Fix login timeout",
    "description": "Fix timeout handling and add regression coverage.",
    "requested_by": "local-user",
    "agent": "codex",
    "model": "gpt-5.3-codex",
    "effort": "high",
    "watch": true,
    "poll_interval_sec": 2.0
  }
}' | ./.venv/bin/python orchestrator/bin/zoe_tool_api.py invoke
```

### 使用平台 WorkItem API

启动 daemon 后，可直接访问：

- `GET /api/health`
- `GET /api/tasks`
- `GET /api/work-items`
- `POST /api/work-items`
- `GET /api/console/mission-control`
- `GET /api/console/releases`
- `GET /api/console/incidents`
- `GET /api/console/evals`
- `GET /api/console/governance`

示例：

```bash
curl -fsS http://127.0.0.1:8080/api/health
```

如果你通过环境变量指定了端口，例如：

```bash
export ZOE_API_PORT=18085
```

则改为访问对应端口。

### 启动控制台前端

```bash
cd apps/console-web
npm ci
npm run dev
```

当前技术栈：

- Next.js 15
- React 19
- TypeScript 5

---

## 工作树策略

系统支持两种工作树策略：

- `shared`
  同一 Plan 的串行子任务复用同一条 `plan/<planId>` 分支和同一工作树。适用于“基础重构 -> 主实现 -> 回归验证”这类需要真实产物继承的任务。

- `isolated`
  每个子任务使用独立 `feat/<taskId>` 分支和工作树。适用于互相独立、需要强隔离的执行单元。

### 当前默认行为

- Planner 对**分阶段代码任务**默认输出 `shared`
- 显式声明时仍可使用 `isolated`
- 真实联调已经验证 `shared` 链路的产物继承确实生效

---

## 存储与迁移

### 当前本地运行

本地运行仍兼容现有的 SQLite / 运行时状态文件机制，保证旧链路不被破坏。

### 新控制平面存储

`packages/kernel/storage/postgres.py` 中已经定义了 PostgreSQL 控制平面 schema，包括：

- `work_items`
- `context_packs`
- `plans`
- `plan_subtasks`
- `agent_runs`
- `run_steps`
- `quality_runs`
- `review_findings`
- `releases`
- `incidents`
- `tickets`
- `eval_runs`
- `audit_events`

### 迁移能力

`packages/kernel/storage/migration.py` 提供了从 legacy SQLite agent task 状态回填到新控制平面模型的迁移器。

这表示当前状态不是“推翻旧系统重写”，而是：

- 保留旧运行时
- 引入新领域模型
- 通过迁移器与双写路径逐步切流

---

## 测试与验收

### 主测试命令

```bash
pytest -q
```

### 控制台前端测试

```bash
cd apps/console-web
npm test
```

### 最近真实任务联调验收

这类验收不是 fake runner，也不是只跑 unit test，而是：

- 真实 Git 仓库
- 真实 `codex exec`
- 真实 daemon / queue / watch 调度
- 真实共享工作树
- 真实任务状态写回与控制台聚合

已完成验证的关键点：

- `S1 -> S2 -> S3` 依赖链可自动推进
- S2 能看到 S1 在同一共享工作树中的真实代码改动
- S3 能在 S2 的实现基础上继续补回归验证
- `/api/console/evals` 能看到真实 `ready` 计数

---

## 文档索引

### 架构与平台化重构

- [docs/architecture/platform-bootstrap.md](./docs/architecture/platform-bootstrap.md)
- [docs/zoe_planner.md](./docs/zoe_planner.md)
- [docs/INDEX.md](./docs/INDEX.md)

### API 与运维

- [docs/api/rest-api.md](./docs/api/rest-api.md)
- [docs/ops/deployment.md](./docs/ops/deployment.md)
- [docs/ops/configuration.md](./docs/ops/configuration.md)
- [docs/ops/troubleshooting.md](./docs/ops/troubleshooting.md)

### 运行手册

- [docs/runbooks/README.md](./docs/runbooks/README.md)
- [docs/agent-sops/README.md](./docs/agent-sops/README.md)

### Ralph 与兼容集成

- [docs/RALPH_INTEGRATION.md](./docs/RALPH_INTEGRATION.md)
- [docs/RALPH_ARCHITECTURE.md](./docs/RALPH_ARCHITECTURE.md)

---

## 设计原则

- **WorkItem-first**：系统服务的是工作项，不只是代码文件
- **ContextPack-first**：Agent 执行前必须有结构化上下文，而不是临时拼 prompt
- **Explicit gates**：质量、发布、事故都应有显式结构化输出
- **Compatibility-first migration**：旧链路不停机，逐步桥接到新架构
- **Event-driven control plane**：状态变化通过事件流传播，而不是模块间硬耦合调用

---

## 许可证

[MIT](./LICENSE)
