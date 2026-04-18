# AI-DevOps 2.0（简体中文）

[![CI](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml/badge.svg)](https://github.com/gordon8018/ai-devops/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/pytest-812%20passed%20%7C%201%20skipped-brightgreen.svg)](./docs/TEST_COVERAGE.md)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://python.org)
[![Agents SDK](https://img.shields.io/badge/OpenAI%20Agents%20SDK-0.14%2B-green.svg)](https://github.com/openai/openai-agents-python)

语言: [English](./README.md) | **简体中文**

---

## 项目定位

**AI-DevOps 2.0 = 面向产品交付的智能体工程操作系统。**

2.0 版本的核心升级是集成了 **OpenAI Agents Python SDK**，将 Agent 执行从外部 shell 脚本 + tmux 进程管理升级为进程内异步 SDK 调用，同时引入了 MCP 工具生态、LLM 输入/输出护栏、以及统一的可观测性追踪。

当前实现是一个**完整可运行的平台化系统**：

- 保留了已经验证稳定的 Orchestrator 内核（DAG 规划、全局调度、质量门禁）
- 新增 `packages/agent_sdk/` 模块，封装全部 Agents SDK 整合逻辑
- 支持 **OpenAI + Anthropic 双提供商**，基于任务类型自动路由
- 引入运行时护栏（Prompt 注入检测、密钥泄漏扫描、路径边界强制）
- 统一的 Token 用量追踪与成本估算

---

## 2.0 新增能力

### Agent 执行引擎

| 能力 | 说明 |
|------|------|
| SDK Runner | 用 `Runner.run()` 替代 shell 脚本 + tmux，进程内异步执行 |
| 双提供商路由 | 根据任务类型自动选择 OpenAI 或 Anthropic 模型 |
| 模型升级重试 | `MaxTurnsExceeded` 时自动升级到更强模型 |
| 指数退避重试 | 失败后 30s → 90s → 270s 退避，最多 3 次 |
| 并发控制 | `asyncio.Semaphore` 限制最大并发 subtask 数 |
| 结构化上下文 | ContextBridge 将约束注入 prompt，大块上下文通过 MCP 按需查询 |

### 工具生态

| 能力 | 说明 |
|------|------|
| FunctionTool | 文件读写、命令执行、代码搜索，通过 `@function_tool` 装饰器注册 |
| 安全边界 | 文件操作限制在 workspace 内，命令白名单 + 元字符拒绝 |
| ToolRegistry | 根据任务类型自动解析工具集 |
| ContextPack MCP | 代码图谱、变更历史、文档通过 MCP Server 按需查询 |

### 质量护栏

| 护栏 | 类型 | 行为 |
|------|------|------|
| PromptInjectionGuard | 输入 | 检测角色覆盖、越狱尝试 → 中止执行 |
| BoundaryGuard | 输入 | 校验约束完整性 → 中止执行 |
| SensitiveDataGuard | 输入 | 扫描 API 密钥模式 → 警告 |
| SecretLeakGuard | 输出 | 检测密钥泄漏 → 中止并丢弃 |
| CodeSafetyGuard | 输出 | 标记危险代码模式 → 警告 |
| ForbiddenPathGuard | 输出 | 验证文件写入未越界 → 中止执行 |
| OutputFormatGuard | 输出 | 验证结构化输出完整性 → 警告 |

### 可观测性

| 能力 | 说明 |
|------|------|
| AgentTraceBridge | SDK 追踪事件映射到 EventBus（10 种事件类型） |
| 敏感数据控制 | 可关闭 LLM 输入/输出原文传输 |
| TokenUsageCollector | Token 用量提取 + 成本估算 + 多运行聚合 |

---

## 已有平台能力（1.x 延续）

- **Kernel 内核**：规划、DAG 校验、依赖调度、任务分发、监控、重试、工作树管理
- **Context 系统**：Git / Obsidian adapter、仓库索引、关系图、ContextPack 装配
- **Quality 系统**：质量门禁、策略引擎、评估指标
- **Release 系统**：Statsig flag adapter、rollout stage、guardrail breach rollback
- **Incident 系统**：告警摄取、指纹聚类、严重性评分、验证关闭
- **Console**：Console API 聚合层 + Next.js 控制台前端

---

## 最近一次完整回归

```bash
pytest -q
# 812 passed, 1 skipped, 3 warnings (~38s)
```

---

## 架构总览

### 七层架构（2.0）

```text
┌─────────────────────────────────────────────────────────┐
│                     Console Layer                        │
├─────────────────────────────────────────────────────────┤
│                   Agent SDK Layer (NEW)                   │
│  ModelRouter │ AgentFactory │ AgentExecutor               │
│  ToolRegistry │ MCP Server │ Guardrails │ TraceBridge     │
├─────────────────────────────────────────────────────────┤
│                     Kernel Layer                         │
├─────────────────────────────────────────────────────────┤
│                    Context Layer                         │
├─────────────────────────────────────────────────────────┤
│                    Quality Layer                         │
├─────────────────────────────────────────────────────────┤
│                    Release Layer                         │
├─────────────────────────────────────────────────────────┤
│                   Incident Layer                         │
└─────────────────────────────────────────────────────────┘
        ↕ Audit (横切)  ↕ Eval (横切)  ↕ Policy (横切)
```

### 任务类型路由表

| 任务类型 | 提供商 | 模型 |
|---------|--------|------|
| code_generation | OpenAI | gpt-5.4 |
| code_review | Anthropic | claude-opus-4-6 |
| bug_fix | OpenAI | gpt-5.4 |
| documentation | Anthropic | claude-sonnet-4-6 |
| test_generation | OpenAI | gpt-5.4-mini |
| planning | Anthropic | claude-opus-4-6 |

路由表可通过环境变量覆盖：`ROUTE_CODE_GENERATION=anthropic:claude-opus-4-6`

---

## 仓库结构

```text
apps/           平台应用层（Console、Workers）
packages/
  shared/       领域模型、公共基础设施
  kernel/       事件总线 / 运行时 / 调度 / 存储
  context/      索引 / 图谱 / ContextPack 装配
  quality/      质量门禁 / 策略 / 评估
  release/      发布标记 / 灰度 / 回滚
  incident/     告警 / 分诊 / 工单 / 验证
  agent_sdk/    (2.0 新增) Agent SDK 整合层
    models/     LLM 提供商适配与任务路由
    runner/     AgentFactory / AgentExecutor / ContextBridge
    tools/      FunctionTool 注册表 / MCP Server
    guardrails/ 输入/输出护栏
    tracing/    事件桥接 / Token 用量采集
orchestrator/   兼容层与已验证内核
infra/          Docker / GitHub Actions / Terraform / K8s
docs/           架构、运行手册、API
tests/          主测试集（812+ 测试）
```

---

## 快速开始

```bash
git clone https://github.com/gordon8018/ai-devops.git
cd ai-devops

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
pip install pytest pytest-asyncio

export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# 运行测试
pytest -q

# 启动内核
python orchestrator/bin/zoe-daemon.py

# 启动控制台
cd apps/console-web && npm ci && npm run dev
```

---

## 设计原则

- **WorkItem-first**：系统服务的是工作项，不只是代码文件
- **ContextPack-first**：Agent 执行前必须有结构化上下文
- **SDK-Embedded**：Agent 执行通过 SDK 进程内调用
- **Dual-Provider**：OpenAI + Anthropic 按任务类型自动路由
- **Guardrails-first**：输入/输出护栏在执行路径中强制运行
- **Event-driven control plane**：状态变化通过事件流传播

---

## 文档索引

- [架构层级合约](./docs/architecture/layer-contracts.md)
- [Agent SDK 整合设计规格](./docs/superpowers/specs/2026-04-18-agents-sdk-integration-design.md)
- [Agent SDK 实施计划](./docs/superpowers/plans/2026-04-18-agents-sdk-integration.md)
- [REST API](./docs/api/rest-api.md)
- [部署指南](./docs/ops/deployment.md)

---

## 许可证

[MIT](./LICENSE)
