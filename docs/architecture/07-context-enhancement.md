# 上下文增强设计

## 概述

上下文增强模块负责在 Ralph 执行前、中、后动态检索、组装和注入相关上下文，为 AI 提供准确、及时的信息，提高生成代码质量和效率。

---

## 1. 上下文增强架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Context Enhancement Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Context    │  │  Context    │  │   Context    │         │
│  │  Retriever   │  │  Assembler  │  │  Injector    │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │  Static  │      │ Dynamic  │      │ Runtime  │
    │  Context │      │ Context  │      │ Context  │
    └──────────┘      └──────────┘      └──────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Enhanced    │
                    │  PRD / Input │
                    └──────────────┘
```

### 1.2 上下文类型

| 类型 | 说明 | 来源 | 注入时机 |
|------|------|------|----------|
| **静态上下文** | 项目结构、编码规范、架构文档 | 代码库、文档 | 任务开始前 |
| **动态上下文** | 当前代码状态、相关 PR、Issue | Git、GitHub API | 执行中动态检索 |
| **运行时上下文** | 执行日志、错误信息、中间结果 | Ralph 执行器 | 迭代间注入 |

---

## 2. 上下文检索

### 2.1 静态上下文检索

```python
import os
from pathlib import Path
from typing import List, Dict

class StaticContextRetriever:
    """静态上下文检索器"""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path)

    def get_project_structure(self) -> str:
        """获取项目结构"""
        structure = []

        for item in self.repo_path.rglob("*"):
            # 过滤掉不需要的目录
            if any(part in item.parts for part in ["node_modules", ".git", "dist", "build"]):
                continue

            if item.is_file():
                relative_path = item.relative_to(self.repo_path)
                structure.append(f"  {relative_path}")

        return "# Project Structure\n\n" + "\n".join(structure)

    def get_coding_standards(self) -> str:
        """获取编码规范"""
        standard_files = [
            "CONTRIBUTING.md",
            "docs/coding-standards.md",
            ".eslintrc",
            ".prettierrc",
            "pylintrc"
        ]

        context = "# Coding Standards\n\n"

        for file in standard_files:
            file_path = self.repo_path / file
            if file_path.exists():
                with open(file_path, "r", encoding="utf-8") as f:
                    context += f"## {file}\n\n{f.read()[:1000]}\n\n"

        return context

    def get_architecture_docs(self) -> str:
        """获取架构文档"""
        docs_dir = self.repo_path / "docs"

        if not docs_dir.exists():
            return "# Architecture Docs\n\nNo docs found.\n"

        context = "# Architecture Docs\n\n"

        # 查找架构相关文档
        for doc in docs_dir.rglob("*.md"):
            if "architecture" in doc.name.lower() or "design" in doc.name.lower():
                with open(doc, "r", encoding="utf-8") as f:
                    context += f"## {doc.name}\n\n{f.read()[:1000]}\n\n"

        return context

    def get_package_info(self) -> str:
        """获取包信息"""
        context = "# Package Info\n\n"

        # package.json
        package_json = self.repo_path / "package.json"
        if package_json.exists():
            import json
            with open(package_json, "r") as f:
                context += f"## package.json\n\n{json.dumps(json.load(f), indent=2)}\n\n"

        # requirements.txt
        requirements_txt = self.repo_path / "requirements.txt"
        if requirements_txt.exists():
            with open(requirements_txt, "r") as f:
                context += f"## requirements.txt\n\n{f.read()}\n\n"

        return context
```

### 2.2 动态上下文检索

```python
import subprocess
from github import Github

class DynamicContextRetriever:
    """动态上下文检索器"""

    def __init__(self, repo: str, github_token: str):
        self.repo = repo
        self.github_token = github_token
        self.github = Github(github_token)
        self.repo_obj = self.github.get_repo(repo)

    def get_current_branch_state(self, branch: str) -> str:
        """获取当前分支状态"""
        context = f"# Current Branch: {branch}\n\n"

        # 获取分支信息
        try:
            branch_obj = self.repo_obj.get_branch(branch)
            context += f"Last commit: {branch_obj.commit.sha}\n"
            context += f"Commit message: {branch_obj.commit.commit.message}\n"
        except Exception as e:
            context += f"Error getting branch info: {e}\n"

        return context

    def get_related_prs(self, base: str = "main") -> str:
        """获取相关 PR"""
        context = "# Related Pull Requests\n\n"

        prs = self.repo_obj.get_pulls(state="open", base=base)

        for pr in list(prs)[:5]:  # 最多 5 个 PR
            context += f"## {pr.title} (#{pr.number})\n"
            context += f"Branch: {pr.head.ref}\n"
            context += f"Author: {pr.user.login}\n"
            context += f"Created: {pr.created_at}\n"
            context += f"Description: {pr.body[:200] if pr.body else 'No description'}\n\n"

        return context

    def get_recent_issues(self, labels: List[str] = None) -> str:
        """获取最近的 Issue"""
        context = "# Recent Issues\n\n"

        issues = self.repo_obj.get_issues(
            state="open",
            labels=labels,
            sort="created",
            direction="desc"
        )

        for issue in list(issues)[:5]:  # 最多 5 个 Issue
            context += f"## {issue.title} (#{issue.number})\n"
            context += f"Labels: {', '.join([l.name for l in issue.labels])}\n"
            context += f"Created: {issue.created_at}\n"
            context += f"Description: {issue.body[:200] if issue.body else 'No description'}\n\n"

        return context

    def get_file_changes(self, branch: str) -> str:
        """获取文件变更"""
        context = f"# File Changes (vs main)\n\n"

        try:
            comparison = self.repo_obj.compare("main", branch)

            context += f"## Changed Files ({comparison.total_commits} commits)\n\n"

            for file in comparison.files[:20]:  # 最多 20 个文件
                context += f"- {file.filename} ({file.status})\n"
                if file.patch:
                    context += f"  ```diff\n{file.patch[:500]}\n  ```\n"

        except Exception as e:
            context += f"Error getting changes: {e}\n"

        return context

    def get_recent_activity(self) -> str:
        """获取最近活动"""
        context = "# Recent Activity\n\n"

        # 获取最近 10 次提交
        commits = self.repo_obj.get_commits()
        for commit in list(commits)[:10]:
            context += f"- {commit.commit.message} ({commit.sha[:7]})\n"
            context += f"  Author: {commit.author.login if commit.author else 'Unknown'}\n"
            context += f"  Date: {commit.commit.author.date}\n\n"

        return context
```

### 2.3 运行时上下文检索

```python
from ralph_runner import RalphRunner
from ralph_state import RalphState

class RuntimeContextRetriever:
    """运行时上下文检索器"""

    def __init__(self, task_id: str, ralph_dir: str):
        self.task_id = task_id
        self.ralph_dir = ralph_dir
        self.runner = RalphRunner(ralph_dir=ralph_dir)
        self.state = RalphState()

    def get_execution_progress(self) -> str:
        """获取执行进度"""
        progress = self.runner.parse_progress()

        context = f"# Execution Progress\n\n"
        context += f"Iterations: {progress['iterations']}/{progress['total_iterations']}\n"
        context += f"Progress: {progress['progress_percent']}%\n\n"

        context += "## User Stories\n\n"
        for story in progress['stories']:
            status = "✓" if story['passes'] else "✗"
            context += f"- [{status}] {story['id']}: {story['title']}\n"
            if story.get('notes'):
                context += f"  Notes: {story['notes']}\n"

        return context

    def get_recent_logs(self, tail: int = 50) -> str:
        """获取最近日志"""
        task = self.state.get(self.task_id)
        logs = task['logs']

        log_lines = logs.split('\n')
        recent_logs = log_lines[-tail:]

        context = f"# Recent Logs (last {tail} lines)\n\n"
        context += "\n".join(recent_logs)

        return context

    def get_errors(self) -> str:
        """获取错误信息"""
        task = self.state.get(self.task_id)
        logs = task['logs']

        # 提取错误行
        error_lines = [
            line for line in logs.split('\n')
            if 'ERROR' in line or 'FAILED' in line or 'Exception' in line
        ]

        if not error_lines:
            return "# Errors\n\nNo errors found.\n"

        context = f"# Errors\n\n"
        context += "\n".join(error_lines[-10])  # 最近 10 个错误

        return context

    def get_quality_check_results(self) -> str:
        """获取质量检查结果"""
        context = "# Quality Check Results\n\n"

        # 从 progress.txt 获取
        progress = self.runner.parse_progress()

        # 模拟质量检查结果
        context += "## Local Checks\n\n"
        context += "- Typecheck: ✓ Passed (2.3s)\n"
        context += "- Lint: ✓ Passed (1.5s)\n"
        context += "- Test: ✗ Failed (3.2s)\n\n"

        context += "## CI Checks (if any)\n\n"
        context += "Not yet submitted to CI.\n"

        return context
```

---

## 3. 上下文组装

### 3.1 上下文组装器

```python
from typing import Dict, List

class ContextAssembler:
    """上下文组装器"""

    def __init__(self, task_spec: dict, prd: dict):
        self.task_spec = task_spec
        self.prd = prd

    def assemble_before_execution(self) -> str:
        """执行前组装上下文"""
        context_parts = []

        # 1. 项目上下文
        context_parts.append(self._get_project_context())

        # 2. 相关文档
        context_parts.append(self._get_documentation_context())

        # 3. 相关代码
        context_parts.append(self._get_code_context())

        # 4. 知识库上下文（来自 knowledge_sync）
        context_parts.append(self._get_knowledge_context())

        return "\n\n".join(context_parts)

    def assemble_during_execution(self) -> str:
        """执行中组装上下文"""
        context_parts = []

        # 1. 当前进度
        context_parts.append(self._get_progress_context())

        # 2. 最近日志
        context_parts.append(self._get_logs_context())

        # 3. 错误信息
        context_parts.append(self._get_errors_context())

        return "\n\n".join(context_parts)

    def assemble_after_iteration(self) -> str:
        """迭代后组装上下文"""
        context_parts = []

        # 1. 完成的故事
        context_parts.append(self._get_completed_stories_context())

        # 2. 待修复的问题
        context_parts.append(self._get_fixes_needed_context())

        # 3. 质量检查结果
        context_parts.append(self._get_quality_context())

        return "\n\n".join(context_parts)

    def _get_project_context(self) -> str:
        """获取项目上下文"""
        # 实现项目上下文检索
        return "# Project Context\n\n[Project information...]"

    def _get_documentation_context(self) -> str:
        """获取文档上下文"""
        # 实现文档上下文检索
        return "# Documentation Context\n\n[Documentation...]"

    def _get_code_context(self) -> str:
        """获取代码上下文"""
        # 实现代码上下文检索
        return "# Code Context\n\n[Code snippets...]"

    def _get_knowledge_context(self) -> str:
        """获取知识库上下文"""
        # 实现知识库上下文检索
        return "# Knowledge Context\n\n[Knowledge base...]"

    def _get_progress_context(self) -> str:
        """获取进度上下文"""
        # 实现进度上下文检索
        return "# Progress Context\n\n[Progress information...]"

    def _get_logs_context(self) -> str:
        """获取日志上下文"""
        # 实现日志上下文检索
        return "# Logs Context\n\n[Recent logs...]"

    def _get_errors_context(self) -> str:
        """获取错误上下文"""
        # 实现错误上下文检索
        return "# Errors Context\n\n[Error information...]"

    def _get_completed_stories_context(self) -> str:
        """获取已完成故事上下文"""
        # 实现已完成故事上下文检索
        return "# Completed Stories Context\n\n[Completed stories...]"

    def _get_fixes_needed_context(self) -> str:
        """获取需要修复的上下文"""
        # 实现需要修复的上下文检索
        return "# Fixes Needed Context\n\n[Required fixes...]"

    def _get_quality_context(self) -> str:
        """获取质量上下文"""
        # 实现质量上下文检索
        return "# Quality Context\n\n[Quality check results...]"
```

### 3.2 优先级排序

```python
class PrioritizedAssembler(ContextAssembler):
    """带优先级的上下文组装器"""

    def assemble_with_priority(self) -> List[Dict]:
        """按优先级组装上下文"""
        contexts = []

        # 高优先级上下文（必须包含）
        contexts.append({
            "priority": "high",
            "content": self._get_project_context()
        })

        # 中优先级上下文（建议包含）
        contexts.append({
            "priority": "medium",
            "content": self._get_code_context()
        })
        contexts.append({
            "priority": "medium",
            "content": self._get_documentation_context()
        })

        # 低优先级上下文（可选）
        contexts.append({
            "priority": "low",
            "content": self._get_knowledge_context()
        })

        return contexts
```

---

## 4. 上下文注入

### 4.1 注入策略

```python
class ContextInjector:
    """上下文注入器"""

    def __init__(self, prd: dict):
        self.prd = prd

    def inject_before_execution(self, context: str) -> dict:
        """执行前注入"""
        prd = self.prd.copy()

        # 添加全局上下文
        prd.setdefault("systemContext", "")
        prd["systemContext"] += context

        # 为每个用户故事添加上下文
        for story in prd["userStories"]:
            story.setdefault("context", "")
            story["context"] += f"\n# System Context\n\n{context}\n"

        return prd

    def inject_during_execution(self, context: str) -> dict:
        """执行中注入（用于修复迭代）"""
        prd = self.prd.copy()

        # 添加到待修复的故事
        for story in prd["userStories"]:
            if not story["passes"]:
                story.setdefault("context", "")
                story["context"] += f"\n# Runtime Context\n\n{context}\n"

        return prd

    def inject_to_iteration_prompt(self, context: str) -> str:
        """注入到迭代提示词"""
        prompt = f"""You are working on the following task:

{self.prd['description']}

## Current Context

{context}

## User Stories

"""

        for story in self.prd["userStories"]:
            status = "COMPLETED" if story["passes"] else "IN PROGRESS"
            prompt += f"- [{status}] {story['id']}: {story['title']}\n"
            if story.get("context"):
                prompt += f"  Context: {story['context'][:200]}...\n"

        return prompt
```

### 4.2 迭代间注入

```python
def inject_context_between_iterations(
    runner: RalphRunner,
    task_id: str,
    context: str
):
    """在迭代之间注入上下文"""

    # 读取当前的 prd.json
    prd = runner.parse_prd_json()

    # 注入上下文
    injector = ContextInjector(prd)
    enhanced_prd = injector.inject_during_execution(context)

    # 保存增强后的 PRD
    runner.save_prd_json(enhanced_prd)
```

---

## 5. Python API

### 5.1 主接口

```python
from context_enhancement import (
    ContextManager,
    StaticContextRetriever,
    DynamicContextRetriever,
    RuntimeContextRetriever,
    ContextAssembler,
    ContextInjector
)

# 初始化上下文管理器
manager = ContextManager(
    repo_path="/home/user01/ai-devops",
    repo="user01/ai-devops",
    github_token=os.getenv("GITHUB_TOKEN"),
    task_id="task-20260414-001",
    ralph_dir="/tmp/ralph-task-001"
)

# 检索所有上下文
context = manager.retrieve_all_contexts()

# 组装上下文
assembler = ContextAssembler(task_spec, prd)
assembled = assembler.assemble_before_execution()

# 注入上下文
injector = ContextInjector(prd)
enhanced_prd = injector.inject_before_execution(assembled)
```

### 5.2 CLI 工具

```bash
# 检索上下文
./context_enhancement.py retrieve <task_id> [--type static|dynamic|runtime]

# 组装上下文
./context_enhancement.py assemble <task_spec.json> <prd.json>

# 注入上下文
./context_enhancement.py inject <prd.json> <context.md>

# 测试上下文检索
./context_enhancement.py test-retrieval --repo /path/to/repo
```

---

## 6. 智能上下文选择

### 6.1 相关性评分

```python
from typing import List, Dict
import re

class ContextScorer:
    """上下文评分器"""

    def __init__(self, task_spec: dict):
        self.task_spec = task_spec
        self.keywords = self._extract_keywords()

    def _extract_keywords(self) -> List[str]:
        """提取关键词"""
        keywords = []

        # 从任务描述提取
        task_desc = self.task_spec.get("task", "")
        keywords.extend(re.findall(r'\b\w+\b', task_desc.lower()))

        # 从用户故事提取
        for story in self.task_spec.get("userStories", []):
            keywords.extend(re.findall(r'\b\w+\b', story["title"].lower()))

        return list(set(keywords))

    def score_context(self, context: str) -> float:
        """为上下文打分"""
        score = 0.0
        context_lower = context.lower()

        # 关键词匹配
        for keyword in self.keywords:
            count = context_lower.count(keyword)
            score += count * 0.1

        # 标题匹配（更高权重）
        lines = context.split('\n')
        for line in lines:
            if line.strip().startswith('#'):
                title = line.strip('#').strip().lower()
                for keyword in self.keywords:
                    if keyword in title:
                        score += 2.0

        # 代码片段权重
        if '```' in context:
            score += 1.0

        return score

    def select_best_contexts(self, contexts: List[str], max_count: int = 3) -> List[str]:
        """选择最佳上下文"""
        scored = [(self.score_context(ctx), ctx) for ctx in contexts]
        scored.sort(reverse=True, key=lambda x: x[0])

        return [ctx for score, ctx in scored[:max_count]]
```

### 6.2 自适应上下文长度

```python
def adapt_context_length(context: str, max_tokens: int = 4000) -> str:
    """自适应调整上下文长度"""
    # 粗略估算：1 token ≈ 4 字符
    max_chars = max_tokens * 4

    if len(context) <= max_chars:
        return context

    # 优先保留标题和代码块
    lines = context.split('\n')
    kept_lines = []

    for line in lines:
        # 标题行优先
        if line.strip().startswith('#'):
            kept_lines.append(line)
        # 代码块优先
        elif line.strip().startswith('```'):
            kept_lines.append(line)
        elif len('\n'.join(kept_lines) + '\n' + line) <= max_chars:
            kept_lines.append(line)

    return '\n'.join(kept_lines)
```

---

## 7. 最佳实践

1. **分层检索**: 先检索静态，再动态，最后运行时
2. **上下文限制**: 控制注入的上下文长度，避免 token 超限
3. **相关性优先**: 只注入高相关性的上下文
4. **迭代更新**: 每次迭代后更新运行时上下文
5. **缓存策略**: 静态上下文缓存，动态和运行时实时检索
6. **错误处理**: 上下文检索失败时优雅降级
7. **日志记录**: 记录上下文检索和注入的详细信息

---

## 8. 扩展性

### 8.1 自定义检索器

```python
class CustomContextRetriever(BaseRetriever):
    """自定义上下文检索器"""

    def __init__(self, config: dict):
        self.config = config

    def retrieve(self, task_spec: dict) -> str:
        """检索上下文"""
        # 实现自定义检索逻辑
        pass

# 注册自定义检索器
manager = ContextManager()
manager.register_retriever("custom", CustomContextRetriever(config))
```

### 8.2 插件系统

```python
class ContextPlugin:
    """上下文插件基类"""

    def before_retrieve(self, task_spec: dict):
        """检索前钩子"""
        pass

    def after_retrieve(self, context: str, task_spec: dict):
        """检索后钩子"""
        pass

    def before_inject(self, context: str, prd: dict):
        """注入前钩子"""
        pass

    def after_inject(self, prd: dict):
        """注入后钩子"""
        pass

# 使用插件
class LoggingPlugin(ContextPlugin):
    def after_retrieve(self, context: str, task_spec: dict):
        print(f"Retrieved {len(context)} chars for task {task_spec['taskId']}")

manager = ContextManager()
manager.register_plugin(LoggingPlugin())
```

---

## 9. 参考文档

- [Git 检索文档](https://git-scm.com/docs/git-grep)
- [GitHub API 文档](https://docs.github.com/en/rest)
- [知识同步设计](./06-knowledge-sync.md)
- [完整集成文档](../RALPH_INTEGRATION.md)
