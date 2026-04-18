# AI-DevOps 2.0 文档索引

## 文档导航

本文档提供 AI-DevOps 2.0 系统的完整文档索引和快速导航。

---

## 快速开始

### 新手入门

1. **阅读顺序**
   - [README.md](../README.md) - 项目概览与 2.0 新能力
   - [Agent SDK 整合设计](./superpowers/specs/2026-04-18-agents-sdk-integration-design.md) - 了解 2.0 架构设计
   - [架构层级合约](./architecture/layer-contracts.md) - 七层架构契约
   - [RALPH_ARCHITECTURE.md](./RALPH_ARCHITECTURE.md) - 了解遗留系统架构
   - [TASK_SPEC_TEMPLATE.md](./TASK_SPEC_TEMPLATE.md) - 查看任务模板

2. **快速链接**
   - [部署指南](./ops/deployment.md) - 如何部署
   - [配置参考](./ops/configuration.md) - 如何配置
   - [故障排查](./ops/troubleshooting.md) - 遇到问题怎么办

---

## 文档分类

### 1. 系统架构

| 文档 | 说明 | 适合人群 |
|------|------|----------|
| [RALPH_ARCHITECTURE.md](./RALPH_ARCHITECTURE.md) | 系统整体架构和设计原则 | 所有人 |
| [RALPH_INTEGRATION.md](./RALPH_INTEGRATION.md) | 集成快速入门和示例 | 开发者、运维 |

---

### 2. 组件详细设计

| 文档 | 说明 | 关键内容 |
|------|------|----------|
| [01-task-to-prd.md](./architecture/01-task-to-prd.md) | TaskSpec → prd.json 转换器 | 格式转换、Python API |
| [02-ralph-state.md](./architecture/02-ralph-state.md) | 状态存储设计 | SQLite schema、状态管理 |
| [03-ralph-runner.md](./architecture/03-ralph-runner.md) | Ralph 执行器设计 | 执行流程、超时处理 |
| [04-quality-gate.md](./architecture/04-quality-gate.md) | 质量门禁设计 | Code Review、CI 监控 |
| [05-realtime-monitoring.md](./architecture/05-realtime-monitoring.md) | 实时监控设计 | WebSocket、Dashboard API |
| [06-knowledge-sync.md](./architecture/06-knowledge-sync.md) | 知识同步设计 | Obsidian、gbrain 集成 |
| [07-context-enhancement.md](./architecture/07-context-enhancement.md) | 上下文增强设计 | 检索、组装、注入 |
| [08-feedback-loop.md](./architecture/08-feedback-loop.md) | 反馈循环设计 | 质量评估、持续改进 |

---

### 3. API 参考

| 文档 | 说明 | 适用场景 |
|------|------|----------|
| [python-api.md](./api/python-api.md) | Python API 参考 | Python 开发 |
| [rest-api.md](./api/rest-api.md) | REST API 参考 | API 集成 |
| [cli-api.md](./api/cli-api.md) | CLI 工具参考 | 命令行使用 |

---

### 4. 部署和运维

| 文档 | 说明 | 关键任务 |
|------|------|----------|
| [deployment.md](./ops/deployment.md) | 部署指南 | 安装、配置、启动 |
| [configuration.md](./ops/configuration.md) | 配置参考 | 环境变量、配置文件 |
| [monitoring.md](./ops/monitoring.md) | 监控指南 | 日志、指标、告警 |
| [troubleshooting.md](./ops/troubleshooting.md) | 故障排查 | 常见问题、解决方案 |
| [backup-restore.md](./ops/backup-restore.md) | 备份和恢复 | 数据备份、灾难恢复 |

---

### 5. 最佳实践

| 文档 | 说明 | 适合人群 |
|------|------|----------|
| [task-spec-design.md](./best-practices/task-spec-design.md) | TaskSpec 设计指南 | 任务创建者 |
| [prd-quality.md](./best-practices/prd-quality.md) | PRD 编写指南 | PRD 编写者 |
| [code-review.md](./best-practices/code-review.md) | Code Review 标准 | 开发者、Reviewer |
| [knowledge-management.md](./best-practices/knowledge-management.md) | 知识管理最佳实践 | 所有团队 |

---

### 6. 模板和示例

| 文档 | 说明 | 用途 |
|------|------|------|
| [TASK_SPEC_TEMPLATE.md](./TASK_SPEC_TEMPLATE.md) | TaskSpec 模板 | 创建新任务 |
| [示例配置](./ops/configuration.md#配置文件) | 配置文件示例 | 配置参考 |

---

## 按角色导航

### 开发者

**必读文档：**
1. [RALPH_ARCHITECTURE.md](./RALPH_ARCHITECTURE.md) - 了解系统架构
2. [python-api.md](./api/python-api.md) - Python API 参考
3. [task-spec-design.md](./best-practices/task-spec-design.md) - TaskSpec 设计
4. [prd-quality.md](./best-practices/prd-quality.md) - PRD 编写
5. [code-review.md](./best-practices/code-review.md) - Code Review

**推荐阅读：**
- [01-task-to-prd.md](./architecture/01-task-to-prd.md) - 转换器设计
- [03-ralph-runner.md](./architecture/03-ralph-runner.md) - 执行器设计

---

### 运维工程师

**必读文档：**
1. [deployment.md](./ops/deployment.md) - 部署指南
2. [configuration.md](./ops/configuration.md) - 配置参考
3. [monitoring.md](./ops/monitoring.md) - 监控指南
4. [troubleshooting.md](./ops/troubleshooting.md) - 故障排查
5. [backup-restore.md](./ops/backup-restore.md) - 备份和恢复

**推荐阅读：**
- [05-realtime-monitoring.md](./architecture/05-realtime-monitoring.md) - 实时监控

---

### 项目经理

**必读文档：**
1. [RALPH_ARCHITECTURE.md](./RALPH_ARCHITECTURE.md) - 系统概览
2. [task-spec-design.md](./best-practices/task-spec-design.md) - 任务设计
3. [knowledge-management.md](./best-practices/knowledge-management.md) - 知识管理

**推荐阅读：**
- [04-quality-gate.md](./architecture/04-quality-gate.md) - 质量门禁

---

### 新成员

**学习路径：**

**第 1 周：**
- 阅读 [RALPH_ARCHITECTURE.md](./RALPH_ARCHITECTURE.md)
- 了解 [RALPH_INTEGRATION.md](./RALPH_INTEGRATION.md)
- 查看 [TASK_SPEC_TEMPLATE.md](./TASK_SPEC_TEMPLATE.md)

**第 2 周：**
- 学习 [task-spec-design.md](./best-practices/task-spec-design.md)
- 学习 [prd-quality.md](./best-practices/prd-quality.md)
- 熟悉 [python-api.md](./api/python-api.md)

**第 3 周：**
- 阅读 [deployment.md](./ops/deployment.md)
- 阅读 [configuration.md](./ops/configuration.md)
- 学习 [troubleshooting.md](./ops/troubleshooting.md)

**第 4 周：**
- 深入 [architecture/](./architecture/) - 组件设计
- 学习 [code-review.md](./best-practices/code-review.md)
- 了解 [knowledge-management.md](./best-practices/knowledge-management.md)

---

## 按任务导航

### 创建新任务

**步骤：**
1. 阅读 [task-spec-design.md](./best-practices/task-spec-design.md)
2. 使用 [TASK_SPEC_TEMPLATE.md](./TASK_SPEC_TEMPLATE.md)
3. 参考 [01-task-to-prd.md](./architecture/01-task-to-prd.md)

**相关文档：**
- [python-api.md](./api/python-api.md#task_to_prd)
- [cli-api.md](./api/cli-api.md#task_to_prd)

---

### 部署系统

**步骤：**
1. 阅读 [deployment.md](./ops/deployment.md)
2. 配置环境变量（[configuration.md](./ops/configuration.md)）
3. 启动服务

**相关文档：**
- [troubleshooting.md](./ops/troubleshooting.md)
- [backup-restore.md](./ops/backup-restore.md)

---

### 监控系统

**步骤：**
1. 配置日志（[monitoring.md](./ops/monitoring.md)）
2. 设置指标收集（[monitoring.md](./ops/monitoring.md)）
3. 配置告警（[monitoring.md](./ops/monitoring.md)）

**相关文档：**
- [05-realtime-monitoring.md](./architecture/05-realtime-monitoring.md)
- [configuration.md](./ops/configuration.md#监控配置)

---

### 优化性能

**步骤：**
1. 分析性能数据（[monitoring.md](./ops/monitoring.md)）
2. 查看反馈循环（[08-feedback-loop.md](./architecture/08-feedback-loop.md)）
3. 应用优化建议

**相关文档：**
- [troubleshooting.md](./ops/troubleshooting.md#性能问题)
- [best-practices/](./best-practices/)

---

### Code Review

**步骤：**
1. 阅读 [code-review.md](./best-practices/code-review.md)
2. 使用检查清单
3. 提供建设性反馈

**相关文档：**
- [04-quality-gate.md](./architecture/04-quality-gate.md)
- [prd-quality.md](./best-practices/prd-quality.md)

---

## 关键概念

### 核心组件

| 组件 | 文档 | 说明 |
|------|------|------|
| **TaskSpec** | [task-spec-design.md](./best-practices/task-spec-design.md) | 任务规范格式 |
| **prd.json** | [prd-quality.md](./best-practices/prd-quality.md) | Ralph 产品需求文档 |
| **Ralph State** | [02-ralph-state.md](./architecture/02-ralph-state.md) | 任务状态存储 |
| **Ralph Runner** | [03-ralph-runner.md](./architecture/03-ralph-runner.md) | Ralph 执行器 |
| **Quality Gate** | [04-quality-gate.md](./architecture/04-quality-gate.md) | 质量门禁 |

### 状态流转

| 状态 | 说明 | 转换条件 |
|------|------|----------|
| `queued` | 任务已排队 | 创建任务时 |
| `running` | 正在执行 | Ralph 启动时 |
| `completed` | 已完成 | 所有故事完成时 |
| `failed` | 执行失败 | 超时或错误时 |
| `ci_passed` | CI 通过 | CI 检查通过 |
| `merged` | 已合并 | PR 合并后 |

---

## 常见任务快速链接

| 任务 | 快速链接 |
|------|----------|
| 创建 TaskSpec | [task-spec-design.md](./best-practices/task-spec-design.md) |
| 转换为 PRD | [01-task-to-prd.md](./architecture/01-task-to-prd.md) |
| 启动 Ralph | [03-ralph-runner.md](./architecture/03-ralph-runner.md) |
| 监控任务 | [05-realtime-monitoring.md](./architecture/05-realtime-monitoring.md) |
| 故障排查 | [troubleshooting.md](./ops/troubleshooting.md) |
| 备份数据 | [backup-restore.md](./ops/backup-restore.md) |

---

## 文档贡献

### 如何贡献

1. 确认文档是否存在
2. 提出改进建议
3. 提交 Pull Request
4. 等待 Code Review

### 文档规范

- 使用清晰的标题结构
- 提供代码示例
- 添加必要图表
- 保持内容准确
- 定期更新

---

## 更新日志

### 最新更新

- **2026-04-14**: 创建完整文档体系
- 架构文档（8 个组件）
- API 参考（Python、REST、CLI）
- 运维文档（部署、配置、监控、故障排查、备份）
- 最佳实践（TaskSpec、PRD、Code Review、知识管理）

---

## 获取帮助

### 文档问题

如果文档有错误或不清楚的地方：

1. 检查 [troubleshooting.md](./ops/troubleshooting.md)
2. 搜索现有 Issue
3. 提交新的 Issue

### 技术支持

- **GitHub Issues**: https://github.com/user01/ai-devops/issues
- **Slack Channel**: #ralph-support
- **Email**: support@example.com

---

## 外部资源

| 资源 | 链接 |
|------|------|
| **Ralph 官方文档** | https://github.com/ralphai/ralph |
| **Claude Code CLI** | https://docs.anthropic.com/claude/code |
| **FastAPI 文档** | https://fastapi.tiangolo.com/ |
| **Obsidian 文档** | https://help.obsidian.md/ |
| **SQLite 文档** | https://www.sqlite.org/docs.html |

---

## 版本信息

- **文档版本**: 1.0.0
- **系统版本**: 1.0.0
- **最后更新**: 2026-04-14

---

## 反馈和改进

我们欢迎任何反馈和改进建议！

**如何提供反馈：**

1. 提交 GitHub Issue
2. 发送邮件
3. 在团队会议上讨论

**反馈内容：**

- 文档错误
- 缺失的内容
- 不清楚的部分
- 改进建议

---

**祝您使用愉快！**
