# OpenAI Agents SDK Integration Design

**Date:** 2026-04-18
**Status:** Approved
**Approach:** B (Deep Fusion) + SDK-Embedded Architecture

## 1. Overview

Integrate OpenAI Agents Python SDK into AI-DevOps as the agent execution engine, replacing the current shell script + tmux process management layer. This is a deep fusion approach that preserves the existing orchestrator architecture (DAG planner, GlobalScheduler, QualityGate, Release, Incident) while embedding SDK capabilities into four areas: execution, tools, guardrails, and observability.

### Decision Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Integration depth | B (Deep Fusion) | Preserve existing tests, DAG planner, quality gates; avoid full rewrite risk |
| LLM providers | OpenAI + Anthropic | Maintain dual-agent strategy via LiteLLM adapter |
| Priority order | Execution > Tools > Guardrails > Observability | Execution is the foundation; others depend on it |
| Transition strategy | Hard switch | Direct replacement of shell scripts with SDK Runner |
| Context delivery | Hybrid | Constraints in system prompt; bulk context via MCP Server |
| Model routing | Task-type based | Automatic routing table; no manual plan-level specification |
| Architecture | SDK-Embedded | In-process async calls; eliminate tmux dependency |

### Why Not Approach C (Core Rewrite)

- DAG provides global visibility, priority scheduling, and precise recovery that Handoff chains cannot
- Agents SDK Handoff solves "conversation delegation between agents," not "production workflow orchestration"
- Rewriting ~17K lines of orchestrator code carries high risk for marginal gain
- Approach B achieves ~80% of C's capability ceiling with ~30% of the effort

## 2. Module Architecture

### New Module: `packages/agent_sdk/`

```
packages/agent_sdk/
├── __init__.py
├── models/                  # LLM provider adaptation
│   ├── router.py            # Task type → model routing
│   ├── openai_model.py      # OpenAI native (passthrough)
│   └── anthropic_model.py   # Anthropic adapter (via LiteLLM)
├── runner/                  # Agent execution engine
│   ├── executor.py          # Runner.run() wrapper + retry + recovery
│   ├── agent_factory.py     # Build Agent instances from Subtask
│   └── context_bridge.py    # ContextPack → instructions + RunContextWrapper
├── tools/                   # Tool registration and management
│   ├── registry.py          # FunctionTool registry
│   ├── builtin/             # Built-in tools (git, file, test, etc.)
│   └── mcp_servers/         # MCP Server definitions
│       └── context_server.py  # ContextPack MCP Server
├── guardrails/              # Guardrail definitions
│   ├── input_guards.py      # Input guardrails
│   └── output_guards.py     # Output guardrails
└── tracing/                 # Observability bridge
    └── event_bridge.py      # SDK Trace → InMemoryEventBus adapter
```

### Modified Modules

| Module | Change |
|--------|--------|
| `packages/kernel/runtime/services.py` | `AgentLauncher` calls `agent_sdk.runner.executor` instead of subprocess |
| `packages/kernel/events/bus.py` | New `agent_run.trace` event type for SDK tracing data |
| `packages/context/packer/service.py` | New `to_agent_instructions(subtask: Subtask) -> str` and `to_mcp_resources() -> dict[str, Any]` methods on `ContextPack` |
| `packages/quality/gates/service.py` | New `from_guardrail_result()` to convert SDK guardrail results to QualityRun |
| `orchestrator/bin/zoe-daemon.py` | asyncio event loop initialization; replace tmux session management |
| `orchestrator/bin/plan_schema.py` | Add `TaskType` enum and `task_type` field to `Subtask` dataclass |
| `apps/console_api/service.py` | New endpoint fields for token usage, tool history, model used, cost estimate |

### Unchanged Modules

- `packages/kernel/planner/` — DAG planning unchanged
- `packages/kernel/scheduler/` — GlobalScheduler unchanged
- `packages/release/` — Release control unaffected
- `packages/incident/` — Incident management unaffected
- `apps/console-web/` — Frontend unaffected (data consumed from console_api)

### Dependency Graph

```
agent_sdk depends on:
  ← packages/shared (domain models: WorkItem, ContextPack, AgentRun)
  ← packages/context (ContextPackAssembler)

kernel depends on:
  ← agent_sdk (new AgentLauncher implementation)

quality depends on:
  ← agent_sdk (guardrail result conversion)
```

## 3. LLM Provider Adaptation & Task Routing

### Dual-Provider Model Layer

**OpenAI (passthrough):** Uses Agents SDK's built-in OpenAI Model directly.

**Anthropic (via LiteLLM):** Implements Agents SDK's `Model` interface, internally delegates to Anthropic API through LiteLLM. LiteLLM handles message format conversion, tool call format differences, and streaming response alignment.

### Task-Type Routing Table

```python
TASK_ROUTE_TABLE = {
    # task_type          → (provider,    model,               rationale)
    "code_generation":   ("openai",    "gpt-5.4",           "highest code generation accuracy"),
    "code_review":       ("anthropic", "claude-opus-4-6",   "strongest deep reasoning for review"),
    "bug_fix":           ("openai",    "gpt-5.4",           "precise tool calling"),
    "refactor":          ("openai",    "gpt-5.4",           "structured refactoring"),
    "documentation":     ("anthropic", "claude-sonnet-4-6", "high-quality text, good cost ratio"),
    "test_generation":   ("openai",    "gpt-5.4-mini",      "pattern tasks, lightweight model"),
    "planning":          ("anthropic", "claude-opus-4-6",   "deep reasoning for planning"),
    "incident_analysis": ("anthropic", "claude-opus-4-6",   "long log deep analysis"),
}

DEFAULT_ROUTE = ("openai", "gpt-5.4")
```

### Subtask.task_type Field

`task_type` is a **new field** added to the `Subtask` dataclass in `orchestrator/bin/plan_schema.py`:

```python
class TaskType(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    BUG_FIX = "bug_fix"
    REFACTOR = "refactor"
    DOCUMENTATION = "documentation"
    TEST_GENERATION = "test_generation"
    PLANNING = "planning"
    INCIDENT_ANALYSIS = "incident_analysis"

@dataclass
class Subtask:
    # ... existing fields ...
    task_type: TaskType = TaskType.CODE_GENERATION  # new field, default for backward compat
```

The DAG planner populates `task_type` based on subtask description analysis. For existing plans without `task_type`, the default `CODE_GENERATION` applies.

Routing logic:
1. Look up `Subtask.task_type` in route table
2. Unmatched types fall back to `DEFAULT_ROUTE`
3. Route table overridable via environment variables or config file
4. Returns constructed `Model` instance for `Agent`

### API Key Management

```
OPENAI_API_KEY     → OpenAI calls
ANTHROPIC_API_KEY  → Anthropic calls (via LiteLLM)
```

Reuses existing `packages/shared/config/` environment variable loading.

## 4. Agent Execution Engine

### AgentFactory

Builds Agents SDK `Agent` instances from `Subtask` + `ContextPack`:

1. Resolve `Model` via `ModelRouter` based on `subtask.task_type`
2. Build `instructions` via `ContextBridge` (constraints + key context)
3. Resolve tool set via `ToolRegistry`
4. Attach guardrails via `GuardrailRegistry`
5. Construct and return `Agent` instance

### ContextBridge — Hybrid Context Injection

**Injected into system prompt (small, critical):**
- Task description and objective
- `allowedPaths` / `forbiddenPaths` / `mustTouch` constraints
- `definitionOfDone` acceptance criteria
- Risk level
- Known failure patterns (brief)

**NOT in system prompt (available via MCP):**
- Full code dependency graph
- Full documentation content
- Complete Git change history

**Injected into RunContextWrapper (runtime metadata, not sent to LLM):**
- `work_item_id`, `plan_id` (for event correlation)
- `workspace_path` (working directory)
- `event_bus` reference (for tool callbacks to publish events)

### Executor — Execution with Recovery

Core execution flow:
1. Build `Agent` from subtask
2. Build `RunContextWrapper` from work_item
3. Execute `Runner.run()` with `max_turns=50`
4. On success: convert `RunResult` → `AgentRun` domain object
5. On `MaxTurnsExceeded`: rebuild agent with escalated model, retry
6. On other failure: exponential backoff retry (30s, 90s, 270s), max 3 attempts
7. Publish events at each stage (`agent_run.started`, `agent_run.completed`, `agent_run.failed`)

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| sync vs async | `async` throughout | Agents SDK is native async; avoid `run_sync()` thread blocking |
| Retry strategy | 3 attempts + exponential backoff | Consistent with existing `recovery_state_machine.py` |
| Model escalation | Upgrade model on MaxTurnsExceeded | Weak model loop → auto-upgrade (e.g., mini → standard) |
| max_turns | 50 | Covers complex tasks; prevents infinite loops |
| Result mapping | RunResult → AgentRun | Domain model unchanged; downstream (quality gate, event bus) zero changes |

### zoe-daemon Modifications

1. Initialize asyncio event loop at startup
2. Convert `QueueConsumer` task dispatch to async
3. Replace tmux multi-session with `asyncio.gather()` for concurrent subtasks
4. Remove `tmux_manager.py` dependency
5. Graceful shutdown: await all agent runs before exit

## 5. Tool Ecosystem & MCP Server

### Tool Registry

**Common tools (all task types):** `read_file`, `write_file`, `list_directory`, `run_command`, `search_code`

**Task-specific tools:**

| Task Type | Additional Tools |
|-----------|-----------------|
| code_generation | `run_tests`, `lint_check`, `type_check` |
| code_review | `git_diff`, `git_blame`, `get_pr_context` |
| bug_fix | `run_tests`, `git_log`, `search_errors` |
| refactor | `run_tests`, `dependency_graph`, `type_check` |
| test_generation | `run_tests`, `coverage_report` |
| documentation | `read_file`, `get_api_schema` |
| planning | (none — no code tools) |
| incident_analysis | `get_logs`, `get_metrics`, `get_alerts` |

### Tool Security Boundaries

- All file operations restricted to `workspace_path` (`allowedPaths` enforced)
- `run_command` limited to whitelisted commands (`pytest`, `npm test`, `make`, `git`, etc.)
- Network access commands prohibited unless explicitly enabled
- Unified tool execution timeout: 120 seconds

### Built-in FunctionTools

Implemented using `@function_tool` decorator with auto-generated JSON Schema. Each tool is a separate file under `packages/agent_sdk/tools/builtin/`.

### ContextPack MCP Server

**Transport:** `MCPServerStdio` (local subprocess)

**Exposed Resources:**
- `context://code-graph` — Code dependency graph (file relations, import chains)
- `context://recent-changes` — Recent Git changes (commit log + diff summary)
- `context://documentation` — Relevant documentation (aggregated from repo + Obsidian)
- `context://known-failures` — Known failure patterns and solutions
- `context://success-patterns` — Historical success patterns (migrated from context_injector)

**Exposed Tools:**
- `get_file_context` — Query context for a specific file (related files, tests, docs)
- `get_dependency_tree` — Query dependency tree for a specific file
- `search_knowledge` — Search knowledge base (Obsidian adapter proxy)

**Lifecycle:**
```
subtask start
  → ContextPackAssembler.build(work_item)
  → ContextPackMCPServer.start(context_pack)
  → try:
      Runner.run(agent, mcp_servers=[server])
    finally:
      ContextPackMCPServer.stop()  # guaranteed cleanup on cancel/failure
```

**Concurrency bound:** Maximum concurrent MCP Server subprocesses is capped at `MAX_CONCURRENT_SUBTASKS` (default: 8) to prevent fd/process exhaustion. This is enforced by `asyncio.Semaphore` in the executor.

### Migration from Existing Mechanisms

| Existing | New | Relationship |
|----------|-----|-------------|
| `context_injector.py` prompt injection | `ContextBridge.to_instructions()` | **Replace** |
| `context_injector.py` success patterns | MCP Server `success-patterns` resource | **Migrate** |
| `context_assembler.py` | `ContextPackAssembler` + MCP Server | **Replace** |
| `agent.py` CLI argument passing | `AgentFactory.build()` | **Replace** |
| tmux session filesystem access | FunctionTools (read_file, write_file, etc.) | **Replace** |

## 6. Quality Guardrails

### Two-Layer Defense

SDK Guardrails intercept at **runtime**; existing QualityGate validates at **post-run**:

```
Input → InputGuardrails → Agent Execution → OutputGuardrails → QualityGateRunner
         (runtime)           (tools)          (runtime)          (post-run)
```

### Input Guardrails

| Guardrail | Function | Tripwire |
|-----------|----------|----------|
| `PromptInjectionGuard` | Detect prompt injection in context/input using lightweight model | `True` → abort |
| `BoundaryGuard` | Verify constraints (allowedPaths, mustTouch, definitionOfDone) are present | `True` → abort |
| `SensitiveDataInputGuard` | Scan context for API keys, passwords, internal URLs; sanitizes as side effect within guardrail body | Never triggers tripwire (`False`); always warns via `info` |

### Output Guardrails

| Guardrail | Function | Tripwire |
|-----------|----------|----------|
| `SecretLeakGuard` | Scan agent output for leaked secrets (AWS keys, tokens, private keys) | `True` → abort, discard output |
| `CodeSafetyGuard` | Detect dangerous patterns (eval, exec, shell=True, SQL concat, rm -rf) | `False` → warn, pass risk list to QualityGate |
| `ForbiddenPathGuard` | Verify agent tool calls didn't write to forbiddenPaths | `True` → abort |
| `OutputFormatGuard` | Validate structured output completeness against schema | `False` → warn |

### Guardrail Registration

- **All task types:** `COMMON_INPUT` (PromptInjection, Boundary, SensitiveData) + `COMMON_OUTPUT` (SecretLeak, ForbiddenPath)
- **Code tasks** (generation, bug_fix, refactor, test): add `CodeSafetyGuard` + `OutputFormatGuard`

### ReviewFinding Domain Object

`ReviewFinding` is a new frozen dataclass added to `packages/shared/domain/models.py`:

```python
@dataclass(slots=True, frozen=True)
class ReviewFinding:
    finding_id: str           # SHA1-based unique ID
    category: str             # "security", "safety", "boundary", "format"
    severity: str             # "critical", "high", "medium", "low"
    message: str              # Human-readable finding description
    source_guardrail: str     # Guardrail class name that produced this finding
    metadata: dict[str, Any] = field(default_factory=dict)  # Extra context
```

### AgentRunResult Wrapper

Since `AgentRun` is `frozen=True` and cannot be mutated post-construction, a mutable wrapper carries guardrail findings alongside the immutable run:

```python
@dataclass
class AgentRunResult:
    agent_run: AgentRun                    # Immutable, constructed from RunResult
    review_findings: list[ReviewFinding]   # Mutable, populated from guardrail output
    token_usage: dict[str, Any]            # Mutable, populated from RunResult.usage
```

`AgentRunResult` is defined in `packages/agent_sdk/runner/executor.py` (not in shared domain — it is an SDK-internal concept). `QualityGateRunner` receives `AgentRunResult` and reads `review_findings` as additional input.

### Result Bridging

Guardrail results (info lists) → `ReviewFinding` domain objects → stored in `AgentRunResult.review_findings` → consumed by `QualityGateRunner` as additional input influencing final `QualityRun` judgment.

## 7. Observability & Event Bridge

### Tracing Bridge

```
Agents SDK Tracing → TraceProcessor (custom) → EventBridge → InMemoryEventBus (existing)
```

### Event Mapping

| SDK Trace Event | EventBus event_type |
|----------------|---------------------|
| `agent.start` | `agent_run.started` |
| `agent.end` | `agent_run.completed` |
| `llm.generation.start` | `agent_run.llm_call` |
| `llm.generation.end` | `agent_run.llm_response` |
| `tool.call` | `agent_run.tool_called` |
| `tool.result` | `agent_run.tool_result` |
| `guardrail.triggered` | `agent_run.guardrail_triggered` |
| `handoff` | `agent_run.handoff` |

### Sensitive Data Control

When `trace_include_sensitive_data=False`: no LLM input/output text transmitted; metadata only (token count, tool name, duration).

### Token Usage Tracking

Collected per run from `RunResult.usage`:
- `input_tokens`, `output_tokens`, `total_tokens`
- `model`, `tool_calls_count`, `turns`, `duration_seconds`, `cost_estimate`

Aggregated to WorkItem level across all subtasks; written to `EvalRun` for dashboard display.

### Monitor Migration

| Existing Monitor Function | Post-Integration Owner | Change |
|--------------------------|----------------------|--------|
| Agent process liveness | `asyncio.Task` state | **Replace** |
| Task timeout detection | `Runner.run(max_turns)` + asyncio timeout | **Replace** |
| Heartbeat detection | EventBridge `llm_call` event stream | **Replace** |
| Log file change detection | Not needed | **Remove** |
| PR creation detection | `tool_result` event checking git output | **Migrate** |
| Status propagation | EventBridge → EventBus → status_propagator | **Preserve** |

### AuditEvent Integration

Events producing AuditEvent (immutable audit records):
- `agent_run.started`, `agent_run.completed`, `agent_run.failed`, `guardrail.triggered`, `agent_run.tool_called`

Events NOT producing AuditEvent (too frequent, tracing only):
- `llm_call`, `llm_response`

### Console Frontend Data Flow

New fields in `console_api`: `agent_run.token_usage`, `agent_run.tool_history`, `agent_run.model_used`, `agent_run.cost_estimate`

New UI displays: real-time tool call stream, token consumption dashboard, model usage distribution, guardrail trigger log.

## 8. Delivery Phases & Acceptance Criteria

### Phase Dependencies

```
Phase 1: Agent Execution Layer    ← Foundation, blocks all others
Phase 2: Tool Ecosystem + MCP    ← Depends on Phase 1
Phase 3: Quality Guardrails       ← Depends on Phase 1
Phase 4: Observability Bridge     ← Depends on Phase 1, parallel with Phase 2/3
```

### Phase 1: Agent Execution Layer

**Scope:** `packages/agent_sdk/models/`, `packages/agent_sdk/runner/`, `orchestrator/bin/zoe-daemon.py`, `packages/kernel/runtime/services.py`, remove `tmux_manager.py` dependency

**Acceptance Criteria:**
- [ ] Single subtask executes via SDK Runner (OpenAI)
- [ ] Single subtask executes via SDK Runner (Anthropic)
- [ ] Route table correctly dispatches tasks to corresponding models
- [ ] Retry logic activates on agent failure (3 attempts with backoff)
- [ ] MaxTurnsExceeded triggers automatic model escalation
- [ ] ContextBridge injects constraints into instructions
- [ ] zoe-daemon concurrently executes multiple subtasks via asyncio
- [ ] All non-tmux-related existing tests pass
- [ ] AgentRun domain objects correctly generated; downstream unchanged

### Phase 2: Tool Ecosystem + MCP Server

**Scope:** `packages/agent_sdk/tools/`

**Acceptance Criteria:**
- [ ] Common tool set (read_file, write_file, run_command, search_code) functional
- [ ] Task-specific tools (run_tests, git_diff, coverage_report, etc.) functional
- [ ] Tool security boundaries enforced (path restriction, command whitelist, timeout)
- [ ] MCP Server lifecycle bound to agent run start/stop
- [ ] Agent can query code graph, docs, change history via MCP on demand
- [ ] Success patterns migrated from `context_injector.py` to MCP resource
- [ ] End-to-end: a `code_generation` WorkItem with 2 subtasks (one OpenAI, one Anthropic) completes with both `AgentRun.status == COMPLETED`, all files written within `allowedPaths`, and `QualityRun.status == PASSED`

### Phase 3: Quality Guardrails

**Scope:** `packages/agent_sdk/guardrails/`, `packages/quality/gates/service.py`

**Acceptance Criteria:**
- [ ] PromptInjectionGuard detects and blocks injection samples
- [ ] BoundaryGuard prevents agent start when constraints missing
- [ ] SecretLeakGuard detects secret patterns in agent output
- [ ] CodeSafetyGuard flags dangerous code patterns
- [ ] ForbiddenPathGuard blocks out-of-bounds file operations
- [ ] Guardrail results correctly convert to ReviewFinding and influence QualityRun
- [ ] Guardrail triggers produce AuditEvent

### Phase 4: Observability Bridge

**Scope:** `packages/agent_sdk/tracing/`, console_api extensions

**Acceptance Criteria:**
- [ ] SDK trace events correctly map to EventBus event_type
- [ ] Sensitive data control effective (no LLM text when disabled)
- [ ] Token usage written to AgentRun metadata
- [ ] Usage aggregated to WorkItem level
- [ ] console_api returns tool call history and usage data
- [ ] AuditEvent records key trace events
- [ ] Legacy monitor file polling and tmux detection safely removed

## 9. New Dependencies

```toml
# pyproject.toml additions
dependencies = [
    "requests>=2.31",
    "schedule>=1.2",
    # New
    "openai-agents>=0.14",     # Agents SDK
    "litellm>=1.40",           # Anthropic adaptation
    "mcp>=1.19",               # MCP Server support
]
```

## 10. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| LiteLLM Anthropic tool call format incompatibility | Medium | Phase 1 blocked | Write integration tests upfront; fallback: hand-written Anthropic Model adapter |
| asyncio conversion introduces zoe-daemon stability regression | Medium | Phase 1 blocked | Validate async execution in standalone entry point first; convert zoe-daemon last |
| MCP Server stdio subprocess management complexity | Low | Phase 2 delayed | Degrade to FunctionTool exposing ContextPack queries directly |
| High guardrail false positive rate impacts agent completion | Medium | Phase 3 quality | Initially set all tripwires to False (warn only); enable gradually after observation |
| Hard switch causes production regression after tmux removal | Medium | Phase 1 blocked | Validate full async execution in standalone test harness before modifying zoe-daemon; keep `tmux_manager.py` importable (not deleted) until Phase 1 acceptance criteria all pass |
| `openai-agents` package name collision or import conflict | Low | Phase 1 blocked | Verify exact PyPI package name and import path (`from agents import ...`) in isolated venv before integration; pin exact version in requirements |
