# Package 3 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 legacy 执行入口，让任何从 Zoe 队列进入的任务在真正 spawn agent 之前都补齐 `WorkItem + ContextPack + AgentRun guard`，并为坏队列文件提供最小 dead-letter 收敛。

**Architecture:** 本包不改 `dispatch.py` 的 queue schema，也不引入新的 worker。实现策略是在 `zoe-daemon.spawn_agent()` 内惰性构建 `LegacyWorkItemSession`，把 `workItem/contextPack/planRequest` 回填到任务对象和运行态 metadata，再调用 `WorkItemService.prepare_agent_run()` 统一执行前校验。同时把 `WorkItemService` 对 `ContextPackAssembler` 的硬依赖改成 protocol 注入，保证 Kernel 不直接 import Context 实现。

**Tech Stack:** Python 3.12, pytest, existing zoe-daemon queue loop, WorkItemService, InMemoryEventBus, existing runtime state / SQLite dual-write

---

## 决策冻结

- `P3-D1`: 不修改 `dispatch.build_execution_task()` 输出 schema；queue 文件继续兼容当前结构。
- `P3-D2`: `spawn_agent()` 在 pick-up 时惰性补建 `LegacyWorkItemSession`，而不是要求上游全部先写入 `workItem/contextPack`。
- `P3-D3`: `prepare_agent_run()` 是执行前唯一 guard；任何缺失 `ContextPack` 的路径都必须在这里失败。
- `P3-D4`: dead-letter 仅处理“无法解析 / 无法补建执行上下文 / 无法通过 prepare_agent_run 校验”的坏队列文件；移动到 `.queue/dead/` 并写 `.err`。
- `P3-D5`: 兼容入口 `zoe_tools.build_work_item_session()` 保留，但 `zoe-daemon` 不再依赖它；daemon 直接使用 `WorkItemService`。

## 文件边界

### 需要新增

- `packages/shared/domain/protocols.py`
  - 定义 `ContextPackProvider` protocol
- `tests/test_zoe_daemon_entrypoint_guard.py`
  - 覆盖 lazy build、AgentRun guard、dead-letter
- `scripts/package_3_acceptance.py`
  - 真链路验收脚本
- `docs/architecture/package-3-acceptance.md`
  - 验收步骤与预期

### 需要修改

- `packages/kernel/services/work_items.py`
  - `WorkItemService` 改为依赖 protocol，而不是硬 import `ContextPackAssembler`
- `packages/shared/domain/__init__.py`
  - 导出 protocol
- `orchestrator/bin/zoe-daemon.py`
  - `spawn_agent()` 内补建 session / prepare_agent_run / metadata 回填 / dead-letter
- `packages/kernel/runtime/services.py`
  - 若需要，补最小 helper 以便 daemon 复用运行态记录
- `tests/test_work_item_service.py`
  - 补 protocol 注入与 prepare guard 行为
- `tests/test_zoe_daemon.py`
  - 补 daemon 主循环遇到坏队列文件时的 dead-letter 行为

---

## Task 1: 抽出 Context protocol，去掉 Kernel 对 Context 实现的硬依赖

**Files:**
- Create: `packages/shared/domain/protocols.py`
- Modify: `packages/shared/domain/__init__.py`
- Modify: `packages/kernel/services/work_items.py`
- Test: `tests/test_work_item_service.py`

- [ ] **Step 1: 写失败测试，固定 WorkItemService 可以接受 protocol provider**

```python
from packages.kernel.services.work_items import WorkItemService


class StubContextProvider:
    def build(self, work_item, *, legacy_task_input=None):
        return expected_context_pack


def test_work_item_service_accepts_protocol_context_provider(expected_context_pack) -> None:
    service = WorkItemService(context_assembler=StubContextProvider())
    assert service is not None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest tests/test_work_item_service.py::test_work_item_service_accepts_protocol_context_provider -v`
Expected: FAIL，直到 protocol 类型和默认 provider 逻辑落地。

- [ ] **Step 3: 定义 protocol 并切换 WorkItemService 依赖**

```python
from typing import Protocol
from packages.shared.domain.models import ContextPack, WorkItem


class ContextPackProvider(Protocol):
    def build(
        self,
        work_item: WorkItem,
        *,
        legacy_task_input: dict[str, object] | None = None,
    ) -> ContextPack: ...
```

说明：
- `work_items.py` 保留默认 `ContextPackAssembler()`，但 import 放到构造函数内部，避免模块级硬依赖。
- 类型标注改为 `ContextPackProvider | None`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_work_item_service.py::test_work_item_service_accepts_protocol_context_provider -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add packages/shared/domain/protocols.py packages/shared/domain/__init__.py packages/kernel/services/work_items.py tests/test_work_item_service.py
git commit -m "refactor: inject context provider through protocol"
```

## Task 2: 为 daemon 的 lazy session + AgentRun guard 写 fail-first 测试

**Files:**
- Create: `tests/test_zoe_daemon_entrypoint_guard.py`
- Modify: `tests/test_zoe_daemon.py`

- [ ] **Step 1: 写失败测试，固定 spawn_agent 会为 legacy queue task 补建 work item session**

```python
def test_spawn_agent_builds_work_item_session_for_legacy_queue_task() -> None:
    task = {
        "id": "task-001",
        "repo": "acme/platform",
        "title": "Legacy queue task",
        "description": "Should lazy-build work item session",
    }
    result = zoe_daemon.spawn_agent(task)
    assert result["metadata"]["workItem"]["workItemId"].startswith("wi_")
    assert result["metadata"]["contextPack"]["packId"].startswith("ctx_")
```

- [ ] **Step 2: 写失败测试，固定 spawn_agent 在 launch 前必须经过 prepare_agent_run**

```python
def test_spawn_agent_prepares_agent_run_before_launch() -> None:
    prepared_runs = []

    class StubWorkItemService:
        def create_legacy_session(self, task_input, *, base_dir=None):
            return session

        def prepare_agent_run(self, **kwargs):
            prepared_runs.append(kwargs)
            return agent_run

    result = zoe_daemon.spawn_agent(task)

    assert prepared_runs
    assert result["metadata"]["agentRun"]["contextPackId"] == session.context_pack.pack_id
```

- [ ] **Step 3: 写失败测试，固定 prepare 失败的坏队列文件会进入 dead-letter**

```python
def test_main_moves_invalid_queue_task_to_dead_letter_on_prepare_failure(tmp_path) -> None:
    # 构造 queue/bad.json，mock spawn path 触发 MissingContextPackError
    # 断言 queue/dead/bad.json 和 bad.err 存在，原文件被移走
```

- [ ] **Step 4: 运行测试，确认失败**

Run: `pytest tests/test_zoe_daemon_entrypoint_guard.py tests/test_zoe_daemon.py -v`
Expected: FAIL，直到 daemon 入口被修正。

- [ ] **Step 5: 提交**

```bash
git add tests/test_zoe_daemon_entrypoint_guard.py tests/test_zoe_daemon.py
git commit -m "test: lock daemon entrypoint guard behavior"
```

## Task 3: 在 spawn_agent 中惰性补建 WorkItem/ContextPack，并回填运行态 metadata

**Files:**
- Modify: `orchestrator/bin/zoe-daemon.py`
- Modify: `packages/kernel/runtime/services.py`
- Test: `tests/test_zoe_daemon_entrypoint_guard.py`

- [ ] **Step 1: 最小实现 daemon session helper**

要求：
- 新增 helper，例如 `_ensure_execution_session(task: dict) -> tuple[dict, LegacyWorkItemSession, AgentRun]`
- 若 `task["metadata"]` 已带 `workItem/contextPack`，允许复用；否则调用 `WorkItemService.create_legacy_session(task, base_dir=...)`
- 调用 `prepare_agent_run()` 生成 `AgentRun`

- [ ] **Step 2: 在 spawn_agent 内回填 metadata**

回填字段至少包括：

```python
metadata["workItem"] = session.work_item.to_dict()
metadata["contextPack"] = session.context_pack.to_dict()
metadata["planRequest"] = session.plan_request
metadata["agentRun"] = agent_run.to_dict()
```

- [ ] **Step 3: 让 RunStateRecorder 记录上述 metadata**

保持现有 record shape，不新增顶层字段；继续把结构化对象放在 `metadata` 下，避免打断 SQLite / API 兼容。

- [ ] **Step 4: 运行测试，确认通过**

Run: `pytest tests/test_zoe_daemon_entrypoint_guard.py::test_spawn_agent_builds_work_item_session_for_legacy_queue_task tests/test_zoe_daemon_entrypoint_guard.py::test_spawn_agent_prepares_agent_run_before_launch -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add orchestrator/bin/zoe-daemon.py packages/kernel/runtime/services.py tests/test_zoe_daemon_entrypoint_guard.py
git commit -m "fix: build execution session before spawning agent"
```

## Task 4: 给坏队列文件增加最小 dead-letter 收敛

**Files:**
- Modify: `orchestrator/bin/zoe-daemon.py`
- Test: `tests/test_zoe_daemon.py`
- Test: `tests/test_zoe_daemon_entrypoint_guard.py`

- [ ] **Step 1: 新增 dead-letter helper**

行为要求：
- 目标目录：`queue_dir()/dead/`
- 原始 JSON 文件移动到 `dead/<original>.json`
- 额外写 `dead/<original>.err`，内容包含异常类型和消息
- 只在“不可重试”的入口错误上调用：JSON 解析失败、缺少 `id/repo`、lazy session / prepare_agent_run 失败

- [ ] **Step 2: main loop 中区分坏文件与暂时性错误**

规则：
- `json.JSONDecodeError`、`RuntimeError("Invalid task JSON...")`、`MissingContextPackError`、`ValueError` from `validate_for_execution` → dead-letter
- 其他运行时错误继续保留原文件，维持现有重试语义

- [ ] **Step 3: 运行测试，确认通过**

Run: `pytest tests/test_zoe_daemon.py tests/test_zoe_daemon_entrypoint_guard.py -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add orchestrator/bin/zoe-daemon.py tests/test_zoe_daemon.py tests/test_zoe_daemon_entrypoint_guard.py
git commit -m "fix: dead-letter invalid daemon queue tasks"
```

## Task 5: 补包 3 验收脚本和真链路验证

**Files:**
- Create: `scripts/package_3_acceptance.py`
- Create: `docs/architecture/package-3-acceptance.md`

- [ ] **Step 1: 写验收脚本**

验收线：
- 从 legacy task dict 直接走 `spawn_agent()`，返回 record 的 `metadata` 中存在 `workItem/contextPack/agentRun`
- `agentRun.contextPackId == contextPack.packId`
- 构造坏 queue file，daemon 主循环一轮后文件进入 `queue/dead/`

- [ ] **Step 2: 写验收文档**

记录：
- 运行命令
- 预期输出
- dead-letter 文件位置
- 兼容性声明：dispatch schema 未变

- [ ] **Step 3: 运行包 3 相关测试**

Run:

```bash
pytest tests/test_work_item_service.py \
       tests/test_zoe_daemon.py \
       tests/test_zoe_daemon_entrypoint_guard.py \
       tests/test_runtime_state.py -q
```

Expected: PASS

- [ ] **Step 4: 运行验收脚本**

Run: `python3 scripts/package_3_acceptance.py`
Expected: exit code `0`

- [ ] **Step 5: 提交**

```bash
git add scripts/package_3_acceptance.py docs/architecture/package-3-acceptance.md
git commit -m "test: add package 3 acceptance coverage"
```

---

## 自检

- 包 3 是否保持 `dispatch.py` queue schema 不变：是，所有补建发生在 daemon 侧。
- 是否修复 `work_items.py` 对 `packages.context.packer.service` 的模块级硬 import：是，要求改为 protocol + 构造时默认注入。
- 是否让 legacy 队列路径经过 `prepare_agent_run()`：是，这是本包的主目标。
- 是否把 dead-letter 控制在最小范围：是，只收敛入口坏文件，不改变 agent 运行期重试策略。
