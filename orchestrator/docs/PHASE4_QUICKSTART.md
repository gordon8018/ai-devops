# Phase 4+ Quick Start Guide

## Overview

Phase 4+ adds historical context enhancement to Ralph, enabling it to reference and learn from previous task implementations.

## Prerequisites

- gbrain installed and configured
- Historical tasks indexed in gbrain
- Python 3.8+
- Existing Ralph setup (Phase 3+)

## Quick Start (3 Steps)

### Step 1: Retrieve Historical Context

```python
from gbrain_retriever import GbrainRetriever, SearchStrategy

# Load your task spec
task_spec = {
    "taskId": "PROJ-123",
    "task": "Implement user authentication",
    "userStories": ["Create login endpoint"],
    "acceptanceCriteria": ["Login returns JWT"],
    "repo": "my-org/my-repo",
}

# Retrieve similar historical tasks
retriever = GbrainRetriever(top_n=3, min_relevance=0.5)
tasks = retriever.retrieve(task_spec, strategy=SearchStrategy.HYBRID)

# Inspect retrieved tasks
for task in tasks:
    print(f"Task: {task.task_id}")
    print(f"Relevance: {task.relevance_score:.2%}")
    print(f"Description: {task.description}")
    print(f"Code Pattern: {task.code_pattern[:100]}...")
    print()
```

### Step 2: Assemble Context

```python
from context_assembler import ContextAssembler

# Assemble into Ralph-readable format
assembler = ContextAssembler()
context = assembler.assemble(task_spec, tasks)

# Preview context
print(context[:500] + "...")

# Save to file (optional)
assembler.save_context(context, "context.md")
```

### Step 3: Inject and Run Ralph

**Option A: Manual Injection**

```python
from task_to_prd import task_spec_to_prd_json
from ralph_runner import RalphRunner

# Convert task spec to PRD with context
prd = task_spec_to_prd_json(task_spec, historical_context=context)

# Save and run
runner = RalphRunner("/path/to/workspace")
runner.save_prd_json(prd)
result = runner.run(max_iterations=10)

print(f"Status: {result['success']}")
```

**Option B: Full Pipeline (Recommended)**

```python
from ralph_runner import RalphRunner
from pathlib import Path

runner = RalphRunner("/path/to/workspace")

result = runner.run_full_pipeline(
    task_id="PROJ-123",
    task_spec=task_spec,  # Required for context injection!
    repo_dir=Path("/path/to/repo"),
    enable_historical_context=True,  # Enable Phase 4+
    enable_quality_gate=True,
    enable_obsidian_sync=True,
    enable_gbrain_indexer=True,
    # Context parameters (optional)
    historical_context_top_n=3,
    historical_context_min_relevance=0.5,
    compact_context=False,
)

print(f"Final status: {result['final_status']}")
print(f"Context injected: {result['historical_context']['success']}")
print(f"Retrieved tasks: {result['historical_context']['retrieved_tasks']}")
```

## After Execution: Provide Feedback

```python
from retrieval_feedback import RetrievalFeedback

feedback = RetrievalFeedback()

# Record that Ralph used the context
feedback.update_usage_feedback(
    task_id="PROJ-123",
    ralph_used_context=True,
    user_rating=4,  # 1-5 scale
    feedback_notes="Context helped with JWT implementation",
)

# Check quality
assessment = feedback.evaluate_retrieval_quality("PROJ-123")
print(f"Quality tier: {assessment['quality_tier']}")
print(f"Overall score: {assessment['overall_quality_score']:.2f}")
```

## Common Patterns

### Pattern 1: Compact Mode (Token-Constrained)

```python
# Use compact mode when you have limited token budget
context = assembler.assemble_compact(task_spec, tasks)
# - Fewer tasks (2 instead of 3)
# - No review comments
# - Higher relevance threshold (0.7)
```

### Pattern 2: High Quality Only

```python
# Only retrieve very relevant tasks
retriever = GbrainRetriever(top_n=5, min_relevance=0.8)
tasks = retriever.retrieve(task_spec)

# You might get 0-3 tasks, but they'll all be highly relevant
```

### Pattern 3: Focus on Code Patterns

```python
# Customize what's included in context
from context_assembler import ContextConfig

config = ContextConfig(
    max_tasks=3,
    include_code_patterns=True,
    include_decisions=True,
    include_review_comments=False,  # Skip reviews
    include_file_structure=False,   # Skip file structure
)

assembler = ContextAssembler(config)
context = assembler.assemble(task_spec, tasks)
```

## CLI Usage

### Retrieve Historical Tasks

```bash
cd /home/user01/ai-devops/orchestrator/bin

# Retrieve with hybrid search
python3 gbrain_retriever.py retrieve /path/to/task_spec.json \
    --strategy hybrid --top-n 3 > historical_tasks.json

# Get specific task by ID
python3 gbrain_retriever.py get AUTH-001
```

### Assemble Context

```bash
# Full context
python3 context_assembler.py assemble \
    /path/to/task_spec.json \
    historical_tasks.json \
    context.md

# Compact context
python3 context_assembler.py compact \
    /path/to/task_spec.json \
    historical_tasks.json \
    context_compact.md
```

### Convert PRD with Context

```bash
python3 task_to_prd.py \
    /path/to/task_spec.json \
    prd.json \
    --context context.md
```

### Feedback Management

```bash
# Record retrieval
python3 retrieval_feedback.py record \
    PROJ-123 \
    historical_tasks.json \
    --context-injected

# Update usage feedback
python3 retrieval_feedback.py update \
    PROJ-123 \
    --used \
    --rating 4 \
    --notes "Very helpful"

# Get feedback
python3 retrieval_feedback.py get PROJ-123

# Evaluate quality
python3 retrieval_feedback.py evaluate PROJ-123

# Generate quality report
python3 retrieval_feedback.py report
```

## Troubleshooting

### No Relevant Tasks Found

**Problem:** Retrieval returns 0 tasks

**Solutions:**
1. Lower `min_relevance` threshold (e.g., 0.5 → 0.3)
2. Increase `top_n` (e.g., 3 → 5)
3. Check if historical tasks are indexed in gbrain
4. Improve task descriptions in gbrain

### Context Too Large

**Problem:** PRD with context is too large

**Solutions:**
1. Use `compact_context=True`
2. Reduce `top_n` (e.g., 3 → 2)
3. Increase `min_relevance` to filter low-quality results
4. Exclude sections in `ContextConfig`

### Ralph Ignores Context

**Problem:** Context is injected but Ralph doesn't use it

**Solutions:**
1. Try compact mode (shorter, more focused)
2. Check context formatting (should be clear markdown)
3. Verify tasks are actually relevant
4. Review feedback: was context helpful?

### Low Relevance Scores

**Problem:** All retrieved tasks have low relevance (< 0.6)

**Solutions:**
1. Check historical task quality in gbrain
2. Improve tagging and descriptions
3. Ensure vector embeddings are up to date
4. Try keyword-only search (may work better)

## Best Practices

### 1. Start with Defaults
```python
# Good starting point
retriever = GbrainRetriever(top_n=3, min_relevance=0.5)
tasks = retriever.retrieve(task_spec, strategy=SearchStrategy.HYBRID)
```

### 2. Monitor Quality Weekly
```python
# Run this weekly
feedback = RetrievalFeedback()
report = feedback.generate_quality_report()
print(json.dumps(report, indent=2))
```

### 3. Provide Consistent Feedback
```python
# After every task completion
feedback.update_usage_feedback(
    task_id=task_id,
    ralph_used_context=bool(result["context_used"]),
    user_rating=rating,  # Be honest!
    feedback_notes=notes,  # What worked? What didn't?
)
```

### 4. Tune Gradually
```python
# Don't change too many parameters at once
# Change one, observe, then change another

# Example tuning process:
# Week 1: Default settings (top_n=3, min_rel=0.5)
# Week 2: Increase top_n to 5 if context too short
# Week 3: Adjust min_rel based on quality report
# Week 4: Enable compact mode if tokens limited
```

### 5. Use Hybrid Search
```python
# Hybrid search gives best of both worlds
strategy=SearchStrategy.HYBRID  # Keyword + Vector
```

## Integration with Existing Workflows

### For Manual Pipelines

```python
# If you're already running Ralph manually
# Just add context injection before running

# 1. Get task spec
task_spec = load_task_spec("task_spec.json")

# 2. Retrieve and assemble context
tasks = retriever.retrieve(task_spec)
context = assembler.assemble(task_spec, tasks)

# 3. Update PRD
prd = load_prd("prd.json")
prd["context"] = context
save_prd(prd, "prd.json")

# 4. Run Ralph as usual
ralph.run()
```

### For Automated Pipelines

```python
# If you're using run_full_pipeline
# Just enable context injection

result = runner.run_full_pipeline(
    task_id=task_id,
    task_spec=task_spec,  # Add this!
    enable_historical_context=True,  # Add this!
    # ... rest of your existing parameters
)
```

## Next Steps

1. **Read Full Documentation:** `docs/RALPH_INTEGRATION.md`
2. **Review Completion Report:** `docs/RALPH_PHASE4_COMPLETION_REPORT.md`
3. **Run Tests:** `pytest tests/test_phase4_workflow.py -v`
4. **Start Small:** Try with one task, then scale
5. **Collect Feedback:** Monitor quality reports and user feedback

## Support

- **Documentation:** `/home/user01/ai-devops/orchestrator/docs/`
- **Tests:** `/home/user01/ai-devops/orchestrator/tests/`
- **Source:** `/home/user01/ai-devops/orchestrator/bin/`

---

**Version:** Phase 4+ v1.0
**Last Updated:** April 14, 2025
