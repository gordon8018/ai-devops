#!/usr/bin/env python3
"""
Context Injector - 上下文注入器

提供规划任务的上下文注入功能，包括：
- 共享工作区上下文
- 消息历史上下文
- 成功模式记忆（Ralph Loop v2）
- 失败上下文注入
- 上下文模板渲染
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .config import ai_devops_home
    from .message_bus import get_message_bus, Message
except ImportError:
    from config import ai_devops_home
    from message_bus import get_message_bus, Message


@dataclass
class SuccessPattern:
    """成功模式记录"""
    pattern_id: str
    task_type: str
    approach: str
    files_touched: List[str]
    execution_time_minutes: int
    success_rate: float
    attempt_count: int
    last_success_at: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FailureContext:
    """失败上下文记录"""
    failure_id: str
    task_id: str
    error_type: str
    error_message: str
    failed_at: int
    retry_count: int
    resolution: Optional[str] = None
    resolution_hints: List[str] = field(default_factory=list)


class ContextInjector:
    """
    上下文注入器
    
    Features:
    - 从共享工作区读取上下文
    - 从消息历史读取上下文
    - 上下文模板渲染
    - 成功模式记忆（Ralph Loop v2）
    - 失败上下文注入
    """
    
    def __init__(self, persist: bool = True):
        self.persist = persist
        self._cache: Dict[str, Any] = {}
        if self.persist:
            try:
                from .db import get_plan, get_task
            except ImportError:
                from db import get_plan, get_task
    
    def get_shared_workspace_path(self, plan_id: str) -> Path:
        """获取共享工作区路径"""
        base = ai_devops_home()
        return base / ".clawdbot" / "workspaces" / plan_id
    
    def read_workspace_context(self, plan_id: str) -> Dict[str, Any]:
        """从共享工作区读取上下文"""
        workspace_path = self.get_shared_workspace_path(plan_id)
        context: Dict[str, Any] = {}
        
        if not workspace_path.exists():
            return context
        
        context_file = workspace_path / "context.json"
        if context_file.exists():
            try:
                context["workspace"] = json.loads(context_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                pass
        
        notes_file = workspace_path / "notes.md"
        if notes_file.exists():
            try:
                context["notes"] = notes_file.read_text(encoding="utf-8")
            except OSError:
                pass
        
        return context
    
    def write_workspace_context(self, plan_id: str, context: Dict[str, Any], merge: bool = True) -> None:
        """写入共享工作区上下文"""
        workspace_path = self.get_shared_workspace_path(plan_id)
        workspace_path.mkdir(parents=True, exist_ok=True)
        
        if merge:
            existing = self.read_workspace_context(plan_id)
            existing.update(context)
            context = existing
        
        context_file = workspace_path / "context.json"
        context_file.write_text(
            json.dumps(context.get("workspace", context), ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    
    def get_message_history(self, agent_id: str, limit: int = 20, topics: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """获取消息历史"""
        bus = get_message_bus()
        messages = bus.receive_messages(agent_id, limit=limit)
        
        result = []
        for msg in messages:
            msg_dict = msg.to_dict()
            if topics and msg_dict.get("topic") not in topics:
                continue
            result.append(msg_dict)
        
        return result
    
    def extract_context_from_messages(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """从消息历史中提取上下文"""
        context: Dict[str, Any] = {
            "recent_alerts": [],
            "task_updates": [],
            "error_patterns": [],
        }
        
        for msg in messages:
            topic = msg.get("topic")
            content = msg.get("content", {})
            
            if topic == "alert":
                context["recent_alerts"].append(content)
            elif topic == "task_update":
                context["task_updates"].append(content)
            elif topic == "error":
                context["error_patterns"].append(content)
        
        return context
    
    def get_success_patterns_path(self) -> Path:
        """获取成功模式存储路径"""
        base = ai_devops_home()
        return base / ".clawdbot" / "success_patterns.json"
    
    def load_success_patterns(self) -> Dict[str, SuccessPattern]:
        """加载成功模式"""
        patterns_path = self.get_success_patterns_path()
        if not patterns_path.exists():
            return {}
        
        try:
            data = json.loads(patterns_path.read_text(encoding="utf-8"))
            patterns = {}
            for pattern_id, pattern_data in data.items():
                patterns[pattern_id] = SuccessPattern(
                    pattern_id=pattern_data["pattern_id"],
                    task_type=pattern_data["task_type"],
                    approach=pattern_data["approach"],
                    files_touched=pattern_data.get("files_touched", []),
                    execution_time_minutes=pattern_data.get("execution_time_minutes", 0),
                    success_rate=pattern_data.get("success_rate", 1.0),
                    attempt_count=pattern_data.get("attempt_count", 1),
                    last_success_at=pattern_data.get("last_success_at", 0),
                    metadata=pattern_data.get("metadata", {}),
                )
            return patterns
        except (json.JSONDecodeError, ValueError, KeyError):
            return {}
    
    def save_success_patterns(self, patterns: Dict[str, SuccessPattern]) -> None:
        """保存成功模式"""
        patterns_path = self.get_success_patterns_path()
        patterns_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {}
        for pattern_id, pattern in patterns.items():
            data[pattern_id] = {
                "pattern_id": pattern.pattern_id,
                "task_type": pattern.task_type,
                "approach": pattern.approach,
                "files_touched": pattern.files_touched,
                "execution_time_minutes": pattern.execution_time_minutes,
                "success_rate": pattern.success_rate,
                "attempt_count": pattern.attempt_count,
                "last_success_at": pattern.last_success_at,
                "metadata": pattern.metadata,
            }
        
        patterns_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    def record_success_pattern(
        self,
        task_type: str,
        approach: str,
        files_touched: List[str],
        execution_time_minutes: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """记录成功模式"""
        patterns = self.load_success_patterns()
        pattern_id = self._find_or_create_pattern_id(patterns, task_type, approach, files_touched)
        
        if pattern_id in patterns:
            pattern = patterns[pattern_id]
            pattern.attempt_count += 1
            pattern.success_rate = (pattern.success_rate * (pattern.attempt_count - 1) + 1.0) / pattern.attempt_count
            pattern.last_success_at = int(time.time() * 1000)
            pattern.execution_time_minutes = (pattern.execution_time_minutes * (pattern.attempt_count - 1) + execution_time_minutes) / pattern.attempt_count
            if metadata:
                pattern.metadata.update(metadata)
        else:
            import hashlib
            content = f"{task_type}:{approach}:{':'.join(sorted(files_touched[:3]))}"
            hash_part = hashlib.md5(content.encode()).hexdigest()[:8]
            pattern_id = f"pattern-{task_type}-{hash_part}"
            
            pattern = SuccessPattern(
                pattern_id=pattern_id,
                task_type=task_type,
                approach=approach,
                files_touched=files_touched,
                execution_time_minutes=execution_time_minutes,
                success_rate=1.0,
                attempt_count=1,
                last_success_at=int(time.time() * 1000),
                metadata=metadata or {},
            )
            patterns[pattern_id] = pattern
        
        self.save_success_patterns(patterns)
        return pattern_id
    
    def _find_or_create_pattern_id(self, patterns: Dict[str, SuccessPattern], task_type: str, approach: str, files_touched: List[str]) -> str:
        """查找或创建模式 ID"""
        for pattern_id, pattern in patterns.items():
            if pattern.task_type == task_type and pattern.approach == approach:
                overlap = len(set(pattern.files_touched) & set(files_touched))
                if overlap >= min(len(files_touched), 2):
                    return pattern_id
        
        import hashlib
        content = f"{task_type}:{approach}:{':'.join(sorted(files_touched[:3]))}"
        hash_part = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"pattern-{task_type}-{hash_part}"
    
    def find_similar_success_patterns(self, task_type: str, files_hint: List[str], limit: int = 3) -> List[SuccessPattern]:
        """查找相似的成功模式"""
        patterns = self.load_success_patterns()
        
        candidates = []
        for pattern in patterns.values():
            if pattern.task_type != task_type:
                continue
            overlap = len(set(pattern.files_touched) & set(files_hint))
            if overlap > 0:
                candidates.append((overlap, pattern.success_rate, pattern))
        
        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [pattern for _, _, pattern in candidates[:limit]]
    
    def get_failures_path(self) -> Path:
        """获取失败记录存储路径"""
        base = ai_devops_home()
        return base / ".clawdbot" / "failure_contexts.json"
    
    def load_failure_contexts(self) -> Dict[str, FailureContext]:
        """加载失败上下文"""
        failures_path = self.get_failures_path()
        if not failures_path.exists():
            return {}
        
        try:
            data = json.loads(failures_path.read_text(encoding="utf-8"))
            failures = {}
            for failure_id, failure_data in data.items():
                failures[failure_id] = FailureContext(
                    failure_id=failure_data["failure_id"],
                    task_id=failure_data["task_id"],
                    error_type=failure_data["error_type"],
                    error_message=failure_data["error_message"],
                    failed_at=failure_data["failed_at"],
                    retry_count=failure_data.get("retry_count", 0),
                    resolution=failure_data.get("resolution"),
                    resolution_hints=failure_data.get("resolution_hints", []),
                )
            return failures
        except (json.JSONDecodeError, ValueError, KeyError):
            return {}
    
    def save_failure_contexts(self, failures: Dict[str, FailureContext]) -> None:
        """保存失败上下文"""
        failures_path = self.get_failures_path()
        failures_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {}
        for failure_id, failure in failures.items():
            data[failure_id] = {
                "failure_id": failure.failure_id,
                "task_id": failure.task_id,
                "error_type": failure.error_type,
                "error_message": failure.error_message,
                "failed_at": failure.failed_at,
                "retry_count": failure.retry_count,
                "resolution": failure.resolution,
                "resolution_hints": failure.resolution_hints,
            }
        
        failures_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    def record_failure(
        self,
        task_id: str,
        error_type: str,
        error_message: str,
        retry_count: int = 0,
        resolution_hints: Optional[List[str]] = None
    ) -> str:
        """记录失败上下文"""
        failures = self.load_failure_contexts()
        
        import hashlib
        content = f"{task_id}:{error_type}:{error_message[:100]}"
        hash_part = hashlib.md5(content.encode()).hexdigest()[:8]
        failure_id = f"failure-{task_id}-{hash_part}"
        
        failure = FailureContext(
            failure_id=failure_id,
            task_id=task_id,
            error_type=error_type,
            error_message=error_message,
            failed_at=int(time.time() * 1000),
            retry_count=retry_count,
            resolution_hints=resolution_hints or [],
        )
        
        failures[failure_id] = failure
        self.save_failure_contexts(failures)
        return failure_id
    
    def resolve_failure(self, failure_id: str, resolution: str) -> None:
        """标记失败已解决"""
        failures = self.load_failure_contexts()
        if failure_id in failures:
            failures[failure_id].resolution = resolution
            self.save_failure_contexts(failures)
    
    def get_recent_failures(self, task_id: Optional[str] = None, error_type: Optional[str] = None, limit: int = 10) -> List[FailureContext]:
        """获取最近的失败记录"""
        failures = self.load_failure_contexts()
        
        candidates = []
        for failure in failures.values():
            if task_id and failure.task_id != task_id:
                continue
            if error_type and failure.error_type != error_type:
                continue
            if not failure.resolution:
                candidates.append(failure)
        
        candidates.sort(key=lambda x: x.failed_at, reverse=True)
        return candidates[:limit]
    
    def render_context_template(self, template: str, context: Dict[str, Any]) -> str:
        """渲染上下文模板"""
        def replace_var(match):
            var_name = match.group(1).strip()
            keys = var_name.split(".")
            value = context
            for key in keys:
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return match.group(0)
            if value is None:
                return match.group(0)
            return str(value)
        
        result = re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, template)
        return result
    
    def inject_context(
        self,
        plan_id: str,
        task_input: Dict[str, Any],
        agent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """注入上下文到任务输入"""
        context: Dict[str, Any] = {}
        
        # 1. 从共享工作区读取上下文
        workspace_context = self.read_workspace_context(plan_id)
        if workspace_context:
            context["workspace"] = workspace_context
        
        # 2. 从消息历史读取上下文
        if agent_id:
            messages = self.get_message_history(agent_id, limit=20)
            message_context = self.extract_context_from_messages(messages)
            if message_context:
                context["messages"] = message_context
        
        # 3. 查找相似成功模式
        task_type = self._infer_task_type(task_input)
        files_hint = task_input.get("context", {}).get("filesHint", [])
        success_patterns = self.find_similar_success_patterns(task_type, files_hint)
        if success_patterns:
            context["successPatterns"] = [
                {
                    "pattern_id": p.pattern_id,
                    "title": p.approach[:80],
                    "attemptCount": p.attempt_count,
                }
                for p in success_patterns
            ]
        
        # 4. 获取相关失败上下文
        recent_failures = self.get_recent_failures(limit=5)
        if recent_failures:
            context["recentFailures"] = [
                {
                    "failure_id": f.failure_id,
                    "error_type": f.error_type,
                    "error_message": f.error_message[:200],
                    "resolution_hints": f.resolution_hints,
                }
                for f in recent_failures
            ]
        
        # 5. 合并到 task_input
        enhanced = dict(task_input)
        existing_context = enhanced.get("context", {})
        if not isinstance(existing_context, dict):
            existing_context = {}
        
        for key, value in context.items():
            if key not in existing_context:
                existing_context[key] = value
        
        enhanced["context"] = existing_context
        return enhanced
    
    def _infer_task_type(self, task_input: Dict[str, Any]) -> str:
        """推断任务类型"""
        title = task_input.get("title", "").lower()
        objective = task_input.get("objective", "").lower()
        combined = f"{title} {objective}"
        
        if "fix" in combined or "修复" in combined:
            return "fix"
        elif "implement" in combined or "实现" in combined:
            return "implement"
        elif "refactor" in combined or "重构" in combined:
            return "refactor"
        elif "test" in combined or "测试" in combined:
            return "test"
        elif "doc" in combined or "文档" in combined:
            return "docs"
        elif "analyze" in combined or "分析" in combined:
            return "analysis"
        else:
            return "general"


_global_injector: Optional[ContextInjector] = None


def get_context_injector() -> ContextInjector:
    """获取全局上下文注入器实例"""
    global _global_injector
    if _global_injector is None:
        _global_injector = ContextInjector(persist=True)
    return _global_injector


if __name__ == "__main__":
    injector = ContextInjector(persist=False)
    
    task_input = {
        "repo": "test-repo",
        "title": "Fix login bug",
        "objective": "Fix the authentication issue",
        "context": {"filesHint": ["src/auth.py"]},
    }
    
    enhanced = injector.inject_context("test-plan-123", task_input, agent_id="agent-1")
    print("Enhanced context:", json.dumps(enhanced.get("context", {}), indent=2))
    
    pattern_id = injector.record_success_pattern(
        task_type="fix",
        approach="Updated auth validation logic",
        files_touched=["src/auth.py", "tests/test_auth.py"],
        execution_time_minutes=15
    )
    print(f"Recorded pattern: {pattern_id}")
    
    failure_id = injector.record_failure(
        task_id="task-456",
        error_type="TimeoutError",
        error_message="Task timed out after 180 minutes",
        resolution_hints=["Increase timeout", "Reduce scope"]
    )
    print(f"Recorded failure: {failure_id}")
