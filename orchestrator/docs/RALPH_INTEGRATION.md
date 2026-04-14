# Ralph Integration Documentation

## Phase 1: Core Executor
- RalphRunner: wraps ralph.sh execution
- Quality Gate: automated code review enforcement
- CI Monitor: continuous integration tracking

## Phase 2: Pipeline Orchestration
- Enhanced quality gate with retry logic
- CI integration with GitHub Actions
- Dashboard and real-time status tracking
- See: [PHASE2_QUICKSTART.md](PHASE2_QUICKSTART.md), [RALPH_PHASE2_COMPLETION_REPORT.md](RALPH_PHASE2_COMPLETION_REPORT.md)

## Phase 3: Knowledge Base Integration

### Overview
Automated sync of task artifacts to Obsidian vault (with cloud push) and gbrain vector knowledge base.

### Pipeline
```
ralph → quality_gate → CI → obsidian_sync → gbrain_indexer → complete
```

### Key Components
- **ObsidianSync** (`bin/obsidian_sync.py`): Syncs reports, reviews, decisions to vault + FastNodeSync cloud push
- **GbrainIndexer** (`bin/gbrain_indexer.py`): Imports artifacts with auto-tagging, triggers vector embedding
- **knowledge_config.json**: Configuration for sync rules, paths, timeouts
- **RalphRunner.run_full_pipeline()`: Orchestrates the complete flow

### Usage
```python
runner = RalphRunner("/path/to/workspace")
result = runner.run_full_pipeline(
    task_id="PROJ-123",
    repo_dir=Path("/path/to/repo"),
    enable_obsidian_sync=True,
    enable_gbrain_indexer=True,
)
```

### Documentation
- [RALPH_PHASE3_COMPLETION_REPORT.md](RALPH_PHASE3_COMPLETION_REPORT.md)
- [KNOWLEDGE_SYNC_GUIDE.md](KNOWLEDGE_SYNC_GUIDE.md)

## Phase 4+: Historical Context Enhancement

### Overview
Enables Ralph to reference historical implementation patterns by injecting relevant past task context into new task execution. Uses gbrain's vector search to find similar tasks and assemble structured context.

### Pipeline (Phase 4+)
```
context_injection → ralph → quality_gate → CI → obsidian_sync → gbrain_indexer → complete
```

### Key Components

#### 1. GbrainRetriever (`bin/gbrain_retriever.py`)
Retrieves relevant historical tasks from gbrain knowledge base.

- **Search Strategies:**
  - Keyword search: Matches task description and tags
  - Vector search: Semantic similarity via embeddings
  - Hybrid search: Combines keyword + vector with score averaging
- **Features:**
  - Configurable top-n results (default: 3)
  - Minimum relevance threshold (default: 0.5)
  - Returns: `HistoricalTask` objects with code patterns, design decisions, review comments

```python
from gbrain_retriever import GbrainRetriever, SearchStrategy

retriever = GbrainRetriever(top_n=3, min_relevance=0.5)
tasks = retriever.retrieve(task_spec, strategy=SearchStrategy.HYBRID)
```

#### 2. ContextAssembler (`bin/context_assembler.py`)
Assembles retrieved tasks into Ralph-readable markdown context.

- **Features:**
  - Structured markdown with task hierarchy
  - Configurable sections (code patterns, decisions, reviews, file structure)
  - Compact mode for space-constrained scenarios
  - Automatic prioritization by relevance

```python
from context_assembler import ContextAssembler

assembler = ContextAssembler()
context = assembler.assemble(task_spec, historical_tasks)
compact_context = assembler.assemble_compact(task_spec, historical_tasks)
```

#### 3. Enhanced PRD Format (`bin/task_to_prd.py`)
Added `context` field to prd.json for historical reference.

```json
{
  "project": "my-repo",
  "description": "Task description",
  "context": "# 历史参考上下文\n\n## 相关任务 1: AUTH-001\n...",
  "userStories": [...]
}
```

#### 4. RalphRunner Enhancement (`bin/ralph_runner.py`)
Added `inject_historical_context()` method and integrated into `run_full_pipeline()`.

```python
runner = RalphRunner("/path/to/workspace")

# Inject context
context_result = runner.inject_historical_context(
    task_spec=task_spec,
    top_n=3,
    min_relevance=0.5,
    compact=False,
)

# Or use enhanced pipeline
result = runner.run_full_pipeline(
    task_id="PROJ-123",
    task_spec=task_spec,  # Required for context injection
    enable_historical_context=True,
    historical_context_top_n=3,
    historical_context_min_relevance=0.5,
    compact_context=False,
    # ... other params
)
```

#### 5. Retrieval Feedback (`bin/retrieval_feedback.py`)
Tracks and evaluates retrieval quality for continuous improvement.

- **Features:**
  - Records retrieval events with execution metrics
  - Captures user ratings and feedback notes
  - Evaluates quality with tiered assessment (high/medium/low)
  - Generates quality reports with recommendations

```python
from retrieval_feedback import RetrievalFeedback

feedback = RetrievalFeedback()

# Record retrieval
feedback.record_retrieval(
    task_id="PROJ-123",
    retrieved_tasks=retrieved_tasks_dict,
    context_injected=True,
    execution_metrics={"iterations": 5, "duration_seconds": 3600},
)

# Update usage feedback
feedback.update_usage_feedback(
    task_id="PROJ-123",
    ralph_used_context=True,
    user_rating=4,
    feedback_notes="Very helpful for JWT implementation",
)

# Evaluate quality
assessment = feedback.evaluate_retrieval_quality("PROJ-123")

# Generate report
report = feedback.generate_quality_report()
```

#### 6. Enhanced GbrainIndexer (`bin/gbrain_indexer.py`)
Added execution metadata support for retrieval optimization.

```python
indexer.index_task_artifacts(
    task_id="PROJ-123",
    artifact_dir=artifact_dir,
    project="ai-devops",
    task_type="feature",
    execution_metadata={
        "iterations": 5,
        "duration_seconds": 3600,
        "quality_score": 8.5,
        "used_historical_context": True,
    },
)
```

### Usage Patterns

#### Pattern 1: Manual Context Injection
```python
# 1. Retrieve historical tasks
retriever = GbrainRetriever()
tasks = retriever.retrieve(task_spec)

# 2. Assemble context
assembler = ContextAssembler()
context = assembler.assemble(task_spec, tasks)

# 3. Convert to PRD with context
prd = task_spec_to_prd_json(task_spec, historical_context=context)

# 4. Save and run
runner = RalphRunner(workspace_dir)
runner.save_prd_json(prd)
runner.run()
```

#### Pattern 2: Full Pipeline with Context
```python
runner = RalphRunner(workspace_dir)
result = runner.run_full_pipeline(
    task_id="PROJ-123",
    task_spec=task_spec,
    repo_dir=Path("/path/to/repo"),
    enable_historical_context=True,
    enable_quality_gate=True,
    enable_obsidian_sync=True,
    enable_gbrain_indexer=True,
    # Context injection params
    historical_context_top_n=3,
    historical_context_min_relevance=0.5,
    compact_context=False,
)
```

### Documentation
- [RALPH_PHASE4_COMPLETION_REPORT.md](RALPH_PHASE4_COMPLETION_REPORT.md)
- Phase 4+ Context Enhancement Guide (see below)

## Context Enhancement Guide

### When to Use Historical Context
- **Use when:** Similar tasks have been completed successfully in the past
- **Use when:** Code patterns can be reused or adapted
- **Use when:** Historical design decisions apply to current task
- **Skip when:** Completely new or novel requirements
- **Skip when:** Historical patterns are deprecated or outdated

### Context Size Management
- **Full mode:** ~3 tasks, includes all sections (~2-5KB)
- **Compact mode:** ~2 tasks, excludes reviews (~1-2KB)
- **Threshold tuning:** Adjust `min_relevance` to control quality vs quantity

### Quality Assessment
- **High quality:** avg_relevance ≥ 0.8, user rating ≥ 4
- **Medium quality:** 0.6 ≤ avg_relevance < 0.8
- **Low quality:** avg_relevance < 0.6

### Feedback Loop
1. Record retrieval when task starts
2. Update feedback after Ralph completes (used context or not)
3. Rate usefulness (1-5) and add notes
4. Review quality reports periodically
5. Tune retrieval parameters based on recommendations

### Troubleshooting
- **No relevant tasks found:** Lower `min_relevance` or check tagging
- **Ralph ignores context:** Try compact mode or improve formatting
- **Poor relevance scores:** Improve vector embeddings or task descriptions
- **Context too large:** Use compact mode or reduce `top_n`
