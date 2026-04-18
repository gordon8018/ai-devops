# 七层架构契约 (Layer Contracts)

> 版本：`v2.0`
> 状态：Agent SDK 层已落地 (2026-04-18)，原六层升级为七层

---

## 0. 文档定位

这份文档不讨论"应该有哪些层"——那是设计思路文档的职责。

这份文档只回答四件事：

1. 每一层**拥有**哪些对象？
2. 每个对象的**合法状态迁移**是什么？
3. 哪一层可以**写**哪个字段，其它层只能**读**？
4. 贯穿所有层的**不变量**（invariants）是什么？

如果两个层对同一对象的理解出现分歧，必须回来改这份文档——而不是在代码里偷偷调和。

如果一次 PR 让现有代码违反了这里列出的任何一条不变量，PR 描述必须**显式指出违反项**，否则拒绝合并。

---

## 1. 层与横切关注点

### 1.1 七个纵向层

| 层 | 职责 | 主入口代码 |
|---|---|---|
| `Console` | API 聚合 + Web UI | `apps/console_api/` + `apps/console-web/` |
| `Agent SDK` | LLM 执行引擎 + 工具 + 护栏 + 追踪 (2.0 新增) | `packages/agent_sdk/` |
| `Kernel` | 计划 + 派发 + 执行 + 监控 | `packages/kernel/` + `orchestrator/bin/` |
| `Context` | 代码图谱 + 文档索引 + 上下文装配 | `packages/context/` |
| `Quality` | 门禁 + AI review + 评估 | `packages/quality/` |
| `Release` | flag + rollout + rollback | `packages/release/` + `apps/release_worker/` |
| `Incident` | 摄取 + 聚类 + 工单 + 验证 | `packages/incident/` + `apps/incident_worker/` |

### 1.2 三个横切关注点（不是层）

| 横切 | 职责 | 存在形式 |
|---|---|---|
| `Audit` | 所有状态变更产生可审计事件 | 约束 + `AuditEvent` 对象，每层都写 |
| `Eval` | 每层暴露可度量指标，统一聚合 | 订阅全量事件，产出 `EvalRun` |
| `Policy` | 组织价值判断（谁有权批准） | `PolicyDecision` 对象，独立于 Quality 的事实判断 |

**横切关注点不出现在纵向导入链中。** 它们以**约束**和**独立对象**的形式存在，不属于任何纵向层。

**Policy 刻意从 Quality 拆出**：Quality 回答"事实上过了没"（lint/test/typecheck），Policy 回答"组织上批了没"（高风险变更是否有人签字）。两种决策不应共用一套代码路径。

---

## 2. 一等对象与所有者

| 对象 | 所有者 | 生命周期 |
|---|---|---|
| `WorkItem` | 共享域（Kernel 驱动其 status） | 平台入口，跨层引用的锚点 |
| `ContextPack` | **Context** | 创建即冻结，immutable |
| `Plan` / `Subtask` | **Kernel** | 从 WorkItem 派生 |
| `AgentRun` / `RunStep` | **Kernel** | 从 Subtask 派生 |
| `AgentRunResult` | **Agent SDK** | 可变包装器（AgentRun + ReviewFindings + token_usage） |
| `ReviewFinding` | **共享域** | 护栏/审查发现，由 Agent SDK 护栏产出 |
| `QualityRun` | **Quality** | 绑定到 AgentRun 或 Plan |
| `Release` | **Release** | 绑定到 WorkItem，1:1 或 1:N |
| `Incident` / `Ticket` | **Incident** | 从 alert 生成，可反向引用 WorkItem |
| `EvalRun` | **Eval**（横切） | 按周期或按事件触发 |
| `AuditEvent` | **Audit**（横切） | append-only，永不修改 |
| `PolicyDecision` | **Policy**（横切） | 绑定到一次具体决策（approve / reject / escalate） |

**所有者 = 唯一有权创建该对象并写入其可变字段的层。** 其它层只能读取或通过事件间接影响。

`WorkItem` 例外：它是跨层锚点，**多个层都能触发创建**（Console 来自人工、Incident 来自告警、Kernel 来自计划回灌），但它的 `status` 状态机**只能由一个层在某一时刻推动**——见 §3.1。

---

## 3. 对象状态机

### 3.1 WorkItem.status

```
                    ┌─────────┐
         create     │ queued  │
       ──────────>  └────┬────┘
                         │ Kernel(planner picks up)
                         ▼
                    ┌──────────┐
                    │ planning │
                    └────┬─────┘
                         │ Kernel(dispatch starts first run)
                         ▼
            ┌──────> ┌─────────┐ <──────┐
            │        │ running │        │
            │        └────┬────┘        │
  any layer │             │             │ Kernel
  emits     │             │ Kernel      │ (block cleared)
  block     │             ▼             │
            │        ┌─────────┐        │
            └──────  │ blocked │ ───────┘
                     └────┬────┘
                          │ Kernel(all subtasks ready + quality passed)
                          ▼
                     ┌─────────┐
                     │  ready  │
                     └────┬────┘
                          │ Release(rollout reaches 'full' stage)
                          ▼
                     ┌──────────┐
                     │ released │
                     └────┬─────┘
       Incident(verify pass)  │  Console(human close, for feature/ops)
                          ▼
                     ┌─────────┐
                     │ closed  │ ← terminal
                     └─────────┘
```

**转移权限：**

| 转移 | 触发层 | 触发条件 |
|---|---|---|
| `queued → planning` | Kernel | planner 接手 |
| `planning → running` | Kernel | dispatch 启动第一个 AgentRun |
| `running → blocked` | Kernel | 任何层可发 `block` 事件，Kernel 统一写状态 |
| `blocked → running` | Kernel | block 源层发出 `unblock` 事件 |
| `running → ready` | Kernel | 所有 Subtask 终态 + 所有 QualityRun = passed |
| `ready → released` | Release | rollout 推进到 `full` |
| `released → closed` | 视 type 而定（下表） |

**`released → closed` 的责任划分：**

| WorkItem.type | 写状态的层 | 触发条件 |
|---|---|---|
| `bugfix` / `incident` | Incident | verify 通过 + 关联 Incident 无 regression |
| `feature` / `experiment` | Console（人工） | 人工按"完成"按钮，或 Eval 达到既定指标 |
| `release_note` / `ops` | Kernel | 没有下游闭环，rollout 完成即 close |

**禁止的迁移：**

- 从任何 terminal（`closed`）回退 → 必须建新 WorkItem 并 `parent_id` 关联
- 跳过中间状态（例如 `planning → ready`）→ 一律拒绝，即便中间阶段可瞬时完成也要显式写过

### 3.2 AgentRun.status

```
pending ──> running ──> { completed | failed | blocked }
```

- 只有 Kernel 写。
- `blocked` 的 AgentRun **不能自愈**——只能由外部信号（Quality failed / 超时 handler / 人工 kill）推进到 `failed`，或由 Kernel 创建新的 Run 接替。
- 已进入 terminal 的 Run 记录不得修改，复盘只能读。

### 3.3 QualityRun.status

```
{ passed | failed | blocked }    // 无中间态，一次评估直接终态
```

- 只有 Quality 写。
- 新一次评估产生**新的 QualityRun**（新 id），旧的保留用于 eval。
- `blocked` 表示人工复核介入的等待态——由 PolicyDecision 触发解锁。

### 3.4 Release.status

```
       ┌─────────┐
       │ planned │
       └────┬────┘
            │ Release.start()
            ▼
       ┌─────────────┐ ──┐
       │ rolling_out │   │ stage_advanced  (at_stage N → N+1)
       └────┬────────┘ <─┘
            │
        ┌───┴───┬──────────────┐
        ▼       ▼              ▼
   ┌─────────┐ ┌──────────┐ ┌────────────┐
   │succeeded│ │rolled_back│ │ superseded │ ← by a linked new Release
   └─────────┘ └──────────┘ └────────────┘
```

- 只有 Release 写。
- `succeeded` / `rolled_back` / `superseded` 均 terminal。
- 回滚后要再发一次：创建**新 Release** 指向同一 WorkItem，并把旧 release 置为 `superseded`——原 release 记录永远保留。

### 3.5 Incident.status

```
open ──> investigating ──> fix_in_progress ──> verifying ──> { resolved | regressed }
                                                                    │
                                                 (resolved stable)  │
                                                                    ▼
                                                                  closed
```

- 只有 Incident 写。
- `regressed` **不是终态**——自动回到 `investigating` 并 reopen 关联 WorkItem（建新 WorkItem 还是复用旧的，依 §I-6）。

### 3.6 ContextPack 无状态机

ContextPack 在创建时即 freeze。任何"修改"都必须产生**新 pack_id 的新 ContextPack**。旧 pack 永久保留用于复盘和 eval。

原因：若允许原地修改，已经引用此 pack 的 AgentRun 就无法复现当时的上下文——复盘、重跑、eval 全部失去基准。

### 3.7 Ticket 状态

Ticket 镜像外部系统（Linear / GitHub Issue / Jira）的状态。**AI-DevOps 侧不试图建模外部状态机**，只记录 `external_status` 字符串 + 最后同步时间。Incident 层通过 polling 或 webhook 更新。

---

## 4. 变更权限矩阵

**图例：** `C` = create, `W` = write, `R` = read, `—` = no access

| 对象 ＼ 层 | Kernel | Context | Quality | Release | Incident | Console | Audit | Eval | Policy |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| `WorkItem` | **C, W**(status: `queued` → `ready`；及 type=`release_note`/`ops` 的 `released → closed`) | R | R | W(status: `ready → released`) | C(from alert), W(status: `released → closed` for bugfix/incident) | C(from human), W(status: `released → closed` for feature/experiment) | R + W(自己的 audit) | R | — |
| `ContextPack` | R | **C**（唯一） | R | R | R | R | R | R | — |
| `Plan` / `Subtask` | **C, W** | R | R | R | R | R | R | R | — |
| `AgentRun` / `RunStep` | **C, W** | R | R | R | R | R | R | R | — |
| `QualityRun` / `ReviewFinding` | R | R | **C, W** | R | R | R | R | R | — |
| `Release` | R | — | R | **C, W** | R | R | R | R | — |
| `Incident` / `Ticket` | R | — | R | R（用于 rollback 触发） | **C, W** | R | R | R | — |
| `EvalRun` | R | R | R | R | R | R | R | **C, W** | — |
| `AuditEvent` | W(append) | W(append) | W(append) | W(append) | W(append) | W(append, 受限) | **C**（存储 owner） | W(append) | W(append) |
| `PolicyDecision` | R | — | R | R | R | R(展示用) | R | — | **C, W** |

### 核心规则

1. **每个对象每个字段有且仅有一个 writer 层**。多层都想写的字段一定要拆成多个字段或多个对象。
2. **跨层影响状态只能通过事件**，不能直接写对方的对象。
3. `AuditEvent` 是唯一允许所有层写入的对象，但写入语义**强制 append-only**，无 update、无 delete。
4. Console 层的 `W` 代表"代表人工"的写入，必须携带人类 `actor_id`（见 §I-5）。

---

## 5. 事件目录

事件是层间**状态变更广播**的唯一通道。**订阅方不得直接查询发布方的存储**（见 §I-9）。

### 5.1 命名约定

`{entity}.{past_tense_action}`，小写 snake_case。例：`work_item.status_changed`、`release.rolled_back`。

过去式。事件描述的是**已发生的事实**，不是"请求"。

### 5.2 事件清单

**Kernel 发布：**
- `work_item.created`
- `work_item.status_changed`（payload: `old_status`, `new_status`, `work_item_id`）
- `plan.ready`
- `agent_run.started`
- `agent_run.completed` / `agent_run.failed` / `agent_run.blocked`

**Context 发布：**
- `context_pack.created`（payload: `pack_id`, `work_item_id`, `risk_profile`）

**Quality 发布：**
- `quality_run.completed`（payload: `gate_type`, `status`, `work_item_id`）
- `quality_run.blocked`（需要人工/Policy 介入）

**Release 发布：**
- `release.started`
- `release.stage_advanced`（payload: `from_stage`, `to_stage`）
- `release.rolled_back`（payload: `reason`）
- `release.succeeded` / `release.superseded`
- `guardrail.breach`（由 Release 的 guardrail 监控触发）

**Incident 发布：**
- `incident.opened`（payload: `fingerprint`, `severity`）
- `incident.verified` / `incident.regressed`
- `ticket.synced`

**Incident 订阅（外部入口）：**
- `alert.received`（Sentry / CloudWatch / 人工提交）

**Policy 发布：**
- `policy_decision.recorded`（payload: `policy_id`, `decision`, `reason`, `decided_by`）

**Eval 订阅：** 几乎所有 `*.completed` / `*.failed` / `*.status_changed`。
**Audit 订阅：** 全量事件。

### 5.3 事件 envelope 契约

每个事件必须携带以下字段：

```
event_id         // 全局唯一，幂等键
event_type       // 来自 §5.2 清单
occurred_at      // ms epoch
actor_id         // 谁触发
actor_type       // human | agent | system
entity_type      // work_item | release | incident | ...
entity_id        // 具体对象 id
payload          // 类型由 event_type 决定的 JSON
```

缺失任一字段的事件应被 event bus 拒绝发布。

---

## 6. 跨层不变量（Invariants）

这些规则**不是**某一层的实现细节，而是贯穿六层的架构断言。
**每一条都有一个稳定 ID（I-N）**，PR 审查时可直接引用。

---

### I-1 ContextPack before AgentRun

任何 `AgentRun` 在 `pending → running` 迁移前，必须绑定一个**已 freeze** 的 `context_pack_id`。

- 代码侧：`AgentRun.validate_for_execution()` 守这条
- 但当前只守 domain 层的字段绑定；**必须扩展**：Kernel dispatcher 在真正 spawn agent 进程前再校验一次，而不是信任 caller

### I-2 One writer per field

每个可变字段有且仅有一个拥有写权的层。

其它层"影响"该字段只能通过发事件 → 事件被拥有者订阅 → 拥有者自己改写。

**反例：** 若 `IncidentWorker` 直接改 `work_item.status = closed`——违反。正确做法：发 `incident.verified` 事件，Kernel（或按 §3.1 表格对应的责任层）订阅并改写。

### I-3 Append-only audit

`AuditEvent` 永不 update、永不 delete。

"纠正历史"通过追加反向事件实现（例：status 改错了，追加一条新的 `status_changed` 把它改回来），而不是修改原事件。

### I-4 Every mutation has an audit event

**状态变更** 与 **AuditEvent 写入** 必须**原子**——同一事务，或 transactional outbox。

"改了状态但没记 audit" 和 "记了 audit 但状态没改" 都违反。

### I-5 Actor identity required

每次写入必须携带 `actor_id` + `actor_type ∈ {human, agent, system}`。

- 匿名写入一律拒绝。
- `system` 写入必须在 payload 里指明具体触发源（`scheduler_tick` / `retry_timer` / `sentry_webhook` / ...）
- `agent` 写入必须指明哪个 Run 在写

### I-6 Forward-only terminals

terminal 状态（`closed` / `rolled_back` / `succeeded` / `completed` / `failed` / `superseded`）**不得向前回退**。

需要"重新处理"的场景：创建**新对象**并通过 `parent_id` / `reopened_from` 等字段与老对象关联。

对 `incident.regressed` 的解读：它不是从 `resolved` 回退，而是本身就是一个独立的可达终态分支——见 §3.5。

### I-7 Idempotency on inbound boundary

任何外部入口（webhook / alert / 人工提交）必须携带**幂等键**。

- 同一幂等键不得产生两个 WorkItem / Incident
- Incident 的 fingerprint 兼有去重作用，但**必须额外**带 source-provided dedup key（Sentry event_id / webhook delivery_id 等），防止 source 侧重推

### I-8 Risk profile propagates

`ContextPack.risk_profile` 是整条下游链路的**权威风险标签**：

- Quality 据此选 gate 集（`critical` 必须包含 security review + migration safety check）
- Release 据此定起始 stage 和推进速度（`critical` 禁止 skip-to-full，且每阶段 dwell time 加长）
- Policy 据此决定是否强制人工审批

**任何下游层不得独立估一个自己的风险级别**——risk 语义只在 ContextPack 装配时定一次。

### I-9 No cross-layer direct reads of mutable state

写端（worker）**不得**跨层直接 join 查询另一层的持久化存储。

- Release 要知道 WorkItem 是否 `ready` → 订阅 `work_item.status_changed`，在 Release 自己的存储里维护投影
- Incident 要知道最近一次 Release 的 stage → 订阅 `release.stage_advanced`，维护投影

**例外：** 读端（Console API）为了聚合展示可以跨层读各自的 query 接口——因为 Console 不会据此写回任何层。

### I-10 Policy decisions are objects, not booleans

"这次变更已批准" 不是 WorkItem 上的一个 bool 字段，而是一个 `PolicyDecision` 对象：

```
PolicyDecision {
  decision_id
  subject_type      // work_item | release | ...
  subject_id
  policy_id
  decision          // approve | reject | escalate
  decided_by        // human actor_id
  decided_at
  reason
  evidence          // 关联的 QualityRun / ReviewFinding 等
}
```

决策历史可回溯，可审计，可被 eval 统计。

### I-11 Frozen after attach

`ContextPack` 在被某个 `AgentRun` 引用的那一刻起**完全冻结**。

要修改 → 建新 pack，原 Run 不受影响；下一个 Run 可以引用新 pack。

### I-12 Outbox for event emission

事件发布与状态变更必须原子。

实现方式：transactional outbox——状态变更与事件记录**写同一事务**进 DB，outbox publisher 异步投递到 event bus。

**反例：** 当前代码里进程内 `InMemoryEventBus` 是直接 publish，没有持久化 outbox。一旦 worker 崩溃，状态改了但事件没发出去就丢事件——违反。

### I-13 Layering import discipline

源代码的允许导入方向（详见 §7）必须在 CI 里用静态检查强制（可用 `import-linter` 或类似工具）。

**不允许"先过渡期，以后再管"**。新违反必须同 PR 修掉或显式加入白名单并注明失效时间。

---

## 7. 模块依赖规则

### 7.1 允许的导入方向

```
                  packages/shared/domain
                          ▲
      ┌───────────┬───────┼───────┬─────────┬─────────┐
      │           │       │       │         │         │
   kernel      context  quality  release  incident  (policy/eval/audit
      │                                                 live in shared)
      │
      │  不得直接 import  quality / release / incident / context
      └──> 只能通过  shared/domain  里的 Protocol 接口

  apps/*_worker   ──import──>  shared + 自己对应的一个 package
  apps/console_api  ──import──>  shared + 各 package 的  read-only 查询接口
  apps/console-web  ──HTTP only──>  console_api
```

### 7.2 硬规则

1. **`packages/shared/domain` 不得 import 任何 `packages/*` 或 `apps/*`** ——它是基础，不是汇聚点。
2. **`packages/kernel` 不得 import `packages/{quality, release, incident, context}`**。需要上下文？通过 `shared/domain` 的 `ContextServiceProtocol`，由 Context 层实现并注入（依赖倒置）。
3. **`apps/release_worker` 不得 import `apps/incident_worker`**（或反之）。worker 之间不共享进程内状态，协作通过 event bus。
4. **Console API 只能调各 package 的公开查询接口**，不得绕过接口直接读其它层的持久化存储。

### 7.3 依赖倒置示例

需求：Kernel 在 spawn AgentRun 前要求 ContextPack 存在。

**错误做法：**
```python
# packages/kernel/runtime/services.py
from packages.context.packer.service import ContextPackAssembler  # ❌
```

**正确做法：**
```python
# packages/shared/domain/protocols.py
class ContextServiceProtocol(Protocol):
    def get_or_build_pack(self, work_item_id: str) -> ContextPack: ...

# packages/kernel/runtime/services.py
def __init__(self, *, context_service: ContextServiceProtocol): ...

# apps/kernel_worker/bootstrap.py  ← 唯一知道具体实现的地方
from packages.context.packer.service import ContextPackAssembler
kernel_runtime = KernelRuntime(context_service=ContextPackAssembler())
```

---

## 8. 版本与演进

### 8.1 契约版本

顶部的 `CONTRACT_VERSION` 维护这份文档自身的版本：

- **Minor bump**：对象新增字段、新增 event type、权限矩阵新增列
- **Major bump**：字段语义变化、权限收紧、状态机方向变化、不变量变化

### 8.2 Breaking change 流程

任何违反既有契约的变更，合并前必须：

1. 同步更新本文档
2. PR 描述里指出违反的**具体条款编号**（例："本 PR 临时违反 I-9，原因是 …，预计在 #XXX 改回"）
3. 提供迁移路径：老数据如何兼容，老事件消费者如何过渡

### 8.3 与当前代码的差距

契约**领先于**现状。已知未达标项：

| 条款 | 未达标的具体体现 | 优先级 |
|---|---|---|
| I-4 (audit atomicity) | `apps/console_api/service.py:52-66` 的 `save_work_item → save_context_pack → audit` 是三步独立调用，无事务包装 | 高 |
| I-9 (no cross-layer reads) | Console 聚合路径接受；但 worker 间读端边界尚未在代码中强制 | 中 |
| I-12 (outbox) | 当前 `InMemoryEventBus` 无持久化；进程崩溃会丢事件 | 高 |
| I-8 (risk propagates) | `apps/release_worker/service.py:88` 硬编码 `next_stage("unknown")`，从未读取 ContextPack.risk_profile | 高（同时也是 §3.4 的已知 bug） |
| I-1 (validate before spawn) | `AgentRun.validate_for_execution` 存在，但 Kernel dispatcher 是否在 spawn 前调用未验证 | 中 |
| I-13 (import discipline) | 无静态检查工具；违规暂靠 review 把关 | 低 |

契约的作用不是立刻让代码全部合规，而是**给每一次 PR 一把可以自检的尺子**。

不达标项每修掉一条，就从这张表里划掉一条；出现新违反则加一行并标明预计修复 PR。

---

## 附录 A：典型跨层流转示例

**示例 1：一个 bugfix 的完整闭环**

```
1. Sentry webhook  ──> alert.received (with dedup key)                    [外部]
2. Incident worker: 幂等校验 → 创建 Incident (open)                         [Incident 写]
3. Incident worker: 发 incident.opened                                      [Incident 广播]
4. Kernel 订阅 incident.opened → 自动创建 WorkItem(type=bugfix, queued)    [Kernel 写 WorkItem]
                   audit: work_item.created, actor=system, source=incident
5. Context 订阅 work_item.created → 装配 ContextPack (risk_profile=high)   [Context 写]
6. Kernel: planner picks up → status=planning → plan.ready → running       [Kernel 驱动]
7. Kernel: AgentRun 启动前校验 context_pack_id (I-1)                        [Kernel 校验]
8. AgentRun completed → Quality 订阅 → 跑 gates → QualityRun(passed)        [Quality 写]
9. Kernel: 所有 subtask ready + quality passed → status=ready                [Kernel 写]
10. Release 订阅 work_item.status_changed(ready) → 起 Release                [Release 写]
    读取 ContextPack.risk_profile=high → 起始 stage=team-only, 阶段严格      [I-8 生效]
11. stage 推进到 full → status=succeeded → 发 release.succeeded             [Release 写]
12. Kernel 订阅 release.succeeded → WorkItem.status=released                 [Kernel 写]
13. Incident verify engine 订阅 work_item.status_changed(released)           [Incident 读]
    检查原 fingerprint 是否消失 + guardrail 是否恢复
14. verify 通过 → 发 incident.verified                                       [Incident 广播]
15. Incident (按 §3.1 表格，bugfix 类型) 写 WorkItem.status=closed          [Incident 写]
    同时把 Incident.status=closed                                            [Incident 写]
16. Audit: 上述所有步骤各自产生 AuditEvent 条目（I-4）                       [Audit]
```

**示例 2：一次 guardrail breach 触发的回滚**

```
1. Release 自己的 guardrail 监控 → 发 guardrail.breach                      [Release 广播]
2. Release 订阅自己的 guardrail.breach → RollbackController.evaluate()      [Release 写]
3. 决定回滚 → Release.status=rolled_back                                    [Release 写]
4. 发 release.rolled_back                                                   [Release 广播]
5. Kernel 订阅 → WorkItem 从 released 回到 ready（特例：允许一次反向，
   对应 I-6 的明确例外，因为 released 本身是"进入 rollout"而非 terminal）    [见下 §附录 B]
6. Incident 订阅 release.rolled_back → 自动 open 一个 Incident               [Incident 写]
7. 循环回到示例 1 第 3 步
```

---

## 附录 B：I-6 的明确例外

`released` 严格说**不是 terminal**——它是"已进入灰度/发布"的活动态。`closed` 才是真正 terminal。

因此 `released → ready`（因回滚）**允许**，但必须：

- 以 `release.rolled_back` 事件为触发
- 在 Kernel 写入 `status=ready` 时携带 `rolled_back_from=<release_id>`
- 同时产生 AuditEvent 明确标注"因回滚返回"

这是唯一允许回退的迁移。其它 terminal（`closed` / `failed` / `succeeded` / `superseded`）无例外。
