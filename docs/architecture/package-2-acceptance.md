# Package 2 Acceptance

> 用途：验证包 2 已把 `console_api / release_worker / incident_worker` 三条真实写路径收敛到统一 mutation 语义：`state persist -> audit -> publish`。本包不验证 outbox，也不验证完整状态机。

---

## 前置条件

1. 进入包 2 worktree：`/home/user01/ai-devops/.claude/worktrees/package-2-mutation-atomicity`
2. Python 环境可用：`source .venv/bin/activate`
3. 相关代码已落盘：
   - `packages/shared/mutation/service.py`
   - `apps/console_api/service.py`
   - `apps/release_worker/service.py`
   - `apps/incident_worker/service.py`

---

## 自动化验收

**命令**

```bash
source .venv/bin/activate
python3 scripts/package_2_acceptance.py
```

**预期退出码**：`0`

**预期输出要点**

输出是一个 JSON-like dict，至少满足：

```python
{
  "console": {
    "persisted": True,
    "eventNames": ["work_item.created", "context_pack.created", "plan.requested"],
    "rollbackStoreEmpty": True,
    "rollbackEventsEmpty": True,
  },
  "release": {
    "releaseExists": False,
    "storeReleaseExists": False,
    "flagCalls": [],
  },
  "incident": {
    "status": "open",
    "storedStatus": "open",
  },
}
```

---

## 覆盖点

### 1. Console 写路径

- `create_work_item()` 成功时，`work_item/context_pack/plan` 三个领域事件仍会发布
- 但这些事件现在是在 `store + audit` 成功后才进入 `EventManager`
- 当 `audit_recorder` 失败时，`work_item` / `context_pack` 会从 store 回滚，事件历史保持为空

### 2. Release 写路径

- `ready` 事件触发 release 创建时，若 audit 失败，不得留下 release 持久化结果
- 同一失败场景下，不得调用 flag adapter
- 说明 `save_release -> apply_flag -> audit` 已被收敛到 mutation 顺序

### 3. Incident 写路径

- `incident_verify` 关闭 incident 时，若 audit 失败，incident 必须保持 `open`
- store 中的 incident 状态也必须保持 `open`
- 说明 verify 分支已经具备 rollback 语义

---

## 测试护栏

跑包 2 相关测试：

```bash
source .venv/bin/activate
pytest tests/test_mutation_service.py \
       tests/test_console_work_items_service.py \
       tests/test_release_worker.py \
       tests/test_incident_worker.py -q
```

**预期**：`45 passed`

---

## 失败排查

- `console.rollbackEventsEmpty == False`
  说明 Console 仍在持久化前即时桥接事件，检查 `WorkItemsApplicationService.create_work_item()`

- `release.flagCalls` 非空
  说明 `ReleaseWorker` 仍在 audit 前调用 `apply_stage()`

- `incident.status == "closed"`
  说明 `IncidentWorker._verify_incident()` 的 rollback 未生效，或 store 未实现 `delete/save` 恢复

- 测试数少于 `45 passed`
  先确认是否在正确 worktree 内执行，以及新增测试文件是否已保存
