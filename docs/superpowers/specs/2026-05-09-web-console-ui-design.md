# Web Console UI — Design Spec

**Date:** 2026-05-09  
**Status:** Approved  
**Scope:** `apps/console-web/`（前端）+ 少量后端接口扩展

---

## 背景

当前 `apps/console-web/` 是 Next.js 15 App Router 纯 SSR 骨架（Phase 6），有 5 个只读页面，无交互、无实时性、无视觉语义。四个核心缺口：

1. 只能看，无法操作（没有任务提交入口）
2. 数据不实时（全页刷新才能看到新状态）
3. 视觉粗糙（状态全靠纯文字 pill）
4. 缺关键视图（Agent Runs、Plan 详情）

目标用户：内部开发团队 + 管理层，统一视图，不做权限分级。  
开发模式：AI Agent 驱动，人工审核，无认证阻塞。

---

## 架构

### 保留不变

- Next.js 15 App Router，SSR 为默认渲染模式
- `apps/console-web/` 目录结构
- 现有 API 层（`orchestrator/api/`），只新增接口，不重构现有接口

### 技术选型（收窄自原计划）

| 项目 | 决策 | 原因 |
|------|------|------|
| UI 组件库 | **引入 shadcn/ui** | 替换无样式 pill/table，统一 design token |
| 客户端状态 | **不引入 TanStack Query** | SSR fetch 已够用；mutation 用 Server Action + 原生 fetch |
| 实时更新 | **轮询（15s），不用 WebSocket** | WS server 与 HTTP server 分进程，需额外 reverse proxy；轮询简单可靠 |
| 可视化 | **步骤有序列表，不做 Plan DAG** | DAG ROI 低，步骤列表覆盖核心需求 |
| 认证 | **HTTP Basic Auth，可选，放最后** | 纯内部工具，不是交付阻塞项 |

### 渲染策略

- 纯展示页：Server Component（保持现状）
- 表单、Toast、轮询：`"use client"` Client Component，局部引入
- 不引入全局客户端状态（无 Zustand/Jotai）

---

## 交付切片

依赖关系：

```
切片 1 ──→ 切片 2, 3, 4（可并行）
切片 2, 3 ──→ 切片 5
切片 4 ──→ 切片 7
切片 6 独立（需后端接口，与 2-5 并行推进）
切片 8 可选，最后执行
```

### 切片 1 — Design System 基础

**范围：** 安装 shadcn/ui，建立 `Button`、`Badge`、`Dialog`、`Tabs` 四个基础组件；删除现有 `.pill` CSS  
**验收：** 四个组件可独立渲染；不破坏现有页面构建  
**约束：** 只改 `apps/console-web/`，不碰 backend

### 切片 2 — WorkItem 创建表单

**范围：** 新增 `<CreateWorkItemDialog>` Client Component；调用已有 `POST /api/work-items`；字段：repo / title / description / type / priority  
**验收：** 提交后列表刷新；错误时显示 inline 错误信息  
**约束：** 依赖切片 1 的 `Button`、`Dialog`

### 切片 3 — 状态徽章语义化

**范围：** 用 `Badge` 替换全站 `.pill`；颜色映射：QUEUED=灰、RUNNING=蓝、BLOCKED=橙、RELEASED=绿、CLOSED=暗  
**验收：** Work Items / Releases / Incidents 页所有状态有颜色区分  
**约束：** 只改组件层，不改 API

### 切片 4 — WorkItem 详情页重构

**范围：** 时间线用竖向 `<Timeline>` 组件替代 DataTable；Context Pack 展示 file hints + acceptance criteria  
**验收：** 详情页无裸 JSON；时间线按时间排序  
**约束：** 依赖切片 1 的 `Tabs`

### 切片 5 — 任务状态轮询

**范围：** RUNNING 状态的 WorkItem 详情页每 15s 自动 refetch；顶部显示"正在更新"指示器  
**验收：** 无需手动刷新；网络断开时优雅降级（停止轮询，显示提示）  
**约束：** Client Component，不引入新依赖；依赖切片 2、3 完成

### 切片 6 — Agent Runs 列表页

**范围：** 新增 `/agent-runs` 页；后端新增 `GET /api/agent-runs`；展示 run_id / agent / model / status / planned_steps 进度  
**验收：** 页面可访问；后端接口有 pytest 测试  
**约束：** 前后端同步交付；Sidebar 新增导航项

### 切片 7 — Plan 详情页

**范围：** 新增 `/plans/[planId]`；复用后端已有 `/api/plans/{id}`；展示 steps 有序列表 + 各步骤 status  
**验收：** 从 WorkItem 详情页可跳转；空状态有提示  
**约束：** 依赖切片 4 的路由结构

### 切片 8 — HTTP Basic Auth（可选）

**范围：** Next.js middleware 拦截所有路由；单一 `CONSOLE_PASSWORD` 环境变量；未登录跳转 `/login`  
**验收：** 未设置环境变量时不启用（向后兼容）  
**约束：** 只改 frontend middleware，不影响 API server

---

## 测试策略

### 三层验收（每切片必须）

**层 1 — 构建通过（自动）**
```bash
cd apps/console-web && npm run build
```
TypeScript 编译无错误，不引入新的隐式 `any`。

**层 2 — 单元测试（自动）**
- 使用现有 `apps/console-web/tests/` + Node `--test`
- 每个新组件：渲染正确、空状态、错误状态各一个测试用例
- 切片 6 后端接口：pytest 覆盖正常返回结构

**层 3 — 手动验收（合并前）**
- 用浏览器走核心路径，逐条对照切片验收标准

### 回归保护

切片 1 完成后建立 `tests/smoke.test.mjs`：
- 所有页面路由返回 HTTP 200
- 无 console.error 输出

之后每个切片必须保证 smoke test 通过。

### 不做的事

- 不引入 Playwright E2E（配置成本高，agent 多轮迭代时 flaky）
- 不追求 80% 覆盖率（UI 视觉行为靠手工验收）
- 不做 visual regression（当前无基准截图）

---

## 对原 Phase 7A/7B/7C 计划的改动摘要

| 原计划 | 调整 | 理由 |
|--------|------|------|
| shadcn/ui + TanStack Query 同时引入 | 只引入 shadcn/ui | 减少 agent 任务复杂度 |
| WebSocket 实时更新（Phase 7B） | 改为 15s 轮询 | WS 需额外 reverse proxy，风险高 |
| Plan DAG 可视化（Phase 7C） | 改为步骤有序列表 | ROI 低，步骤列表足够 |
| Scheduler 状态页（Phase 7C） | 去掉 | Agent Runs 页覆盖 80% 需求 |
| Agent Runs 页（Phase 7C） | 提前至切片 6 | 工程师最需要的调试视图 |
| 认证（Phase 7C） | 保留但设为可选最后切片 | 内部工具，不是交付阻塞项 |
