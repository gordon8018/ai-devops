# Package 3 Acceptance

> 用途：验证包 3 已把 legacy 队列执行入口收口到 `WorkItem + ContextPack + AgentRun guard`，并为不可恢复的坏队列文件提供 dead-letter。此包不修改 dispatch queue schema。

---

## 前置条件

1. 进入包 3 worktree：`/home/user01/ai-devops/.claude/worktrees/package-3-entrypoint-guard`
2. Python 环境可用：`source .venv/bin/activate`
3. 相关代码已落盘：
   - `packages/shared/domain/protocols.py`
   - `packages/kernel/services/work_items.py`
   - `orchestrator/bin/zoe-daemon.py`
   - `scripts/package_3_acceptance.py`

---

## 自动化验收

**命令**

```bash
source .venv/bin/activate
python3 scripts/package_3_acceptance.py
```

**预期退出码**：`0`

**预期输出要点**

输出是一个 dict，至少满足：

```python
{
  "queueSchema": {
    "hasWorkItem": False,
    "hasContextPack": False,
    "hasAgentRun": False,
  },
  "spawnAgent": {
    "workItemId": "wi_...",
    "contextPackId": "ctx_...",
    "agentRunContextPackId": "ctx_...",
  },
  "deadLetter": {
    "deadFileExists": True,
    "errFileExists": True,
    "originalRemoved": True,
  },
}
```

---

## 覆盖点

### 1. Queue schema 保持不变

- `dispatch.build_execution_task()` 仍然只输出当前 queue schema
- queue payload 的 `metadata` 不会预写 `workItem/contextPack/agentRun`
- 说明本包的兼容策略正确：补建发生在 daemon 侧，而不是 dispatch 侧

### 2. spawn_agent 惰性补建执行上下文

- legacy queue task 进入 `spawn_agent()` 后，会在 launch 前补建 `WorkItem + ContextPack`
- 还会通过 `prepare_agent_run()` 生成 `AgentRun`
- `agentRun.contextPackId` 必须与 `contextPack.packId` 一致

### 3. dead-letter 收敛坏队列文件

- 对于 `prepare_agent_run` 类的不可恢复错误，主循环会把原始 queue 文件移动到 `queue/dead/`
- 同目录下会生成 `.err` 文件，记录异常类型和消息
- 原 queue 文件会被移除，避免 daemon 无限刷错

---

## 测试护栏

跑包 3 相关测试：

```bash
source .venv/bin/activate
pytest tests/test_work_item_service.py \
       tests/test_zoe_daemon.py \
       tests/test_zoe_daemon_entrypoint_guard.py \
       tests/test_zoe_tools_work_item_bridge.py \
       tests/test_kernel_runtime_services.py -q
```

**预期**：`38 passed`

---

## 失败排查

- `queueSchema.hasWorkItem == True`
  说明 dispatch schema 被意外改宽了，检查 `orchestrator/bin/dispatch.py`

- `spawnAgent.contextPackId != spawnAgent.agentRunContextPackId`
  说明 daemon 没有统一使用 `prepare_agent_run()` 的结果

- `deadLetter.deadFileExists == False`
  说明 main loop 仍把不可恢复入口错误当成普通可重试错误处理

- `.err` 文件缺失
  说明 dead-letter 仅移动了 JSON，没有留下排障证据
