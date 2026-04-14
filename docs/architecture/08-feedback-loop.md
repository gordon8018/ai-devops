# 反馈循环设计

## 概述

反馈循环模块负责收集 Ralph 执行过程中的质量数据、错误信息和用户反馈，分析执行效果，并持续优化 AI 表现和流程效率。

---

## 1. 反馈循环架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Feedback Loop Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Data       │  │   Analysis   │  │  Optimizer   │         │
│  │  Collector   │  │   Engine     │  │    Engine    │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │  Quality │      │  Error   │      │  User    │
    │  Metrics │      │  Logs    │      │ Feedback │
    └──────────┘      └──────────┘      └──────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Insights   │
                    │  Database   │
                    └──────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │  Continuous  │
                    │ Improvement │
                    └──────────────┘
```

### 1.2 反馈流

```
执行数据收集
      │
      ├─▶ 质量指标（成功率、完成时间、迭代次数）
      ├─▶ 错误日志（失败原因、错误类型）
      ├─▶ 用户反馈（满意度、改进建议）
      └─▶ 性能指标（资源使用、响应时间）
      │
      ▼
数据分析
      │
      ├─▶ 模式识别（常见失败模式）
      ├─▶ 趋势分析（成功率变化）
      └─▶ 相关性分析（因素关联）
      │
      ▼
优化建议
      │
      ├─▶ 提示词优化
      ├─▶ 参数调整
      ├─▶ 流程改进
      └─▶ 上下文增强策略
      │
      ▼
应用改进
      │
      ▼
   新一轮执行
```

---

## 2. 数据收集

### 2.1 质量指标收集

```python
from ralph_state import RalphState
from ralph_runner import RalphRunner
from datetime import datetime, timedelta
import statistics

class QualityMetricsCollector:
    """质量指标收集器"""

    def __init__(self, state: RalphState):
        self.state = state

    def collect_completion_rate(self, days: int = 30) -> dict:
        """收集完成率"""
        start_date = datetime.utcnow() - timedelta(days=days)

        completed = self.state.list(status="completed", start_date=start_date)
        failed = self.state.list(status="failed", start_date=start_date)
        total = len(completed) + len(failed)

        if total == 0:
            return {"rate": 0.0, "completed": 0, "failed": 0}

        rate = len(completed) / total

        return {
            "rate": rate,
            "completed": len(completed),
            "failed": len(failed),
            "total": total
        }

    def collect_execution_time(self, days: int = 30) -> dict:
        """收集执行时间统计"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        durations = []

        for task in tasks:
            created = datetime.fromisoformat(task["created_at"])
            updated = datetime.fromisoformat(task["updated_at"])
            duration = (updated - created).total_seconds()
            durations.append(duration)

        if not durations:
            return {"mean": 0, "median": 0, "min": 0, "max": 0, "std": 0}

        return {
            "mean": statistics.mean(durations),
            "median": statistics.median(durations),
            "min": min(durations),
            "max": max(durations),
            "std": statistics.stdev(durations) if len(durations) > 1 else 0
        }

    def collect_iterations(self, days: int = 30) -> dict:
        """收集迭代次数统计"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        iterations = []

        for task in tasks:
            runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task['task_id']}")
            progress = runner.parse_progress()
            iterations.append(progress["iterations"])

        if not iterations:
            return {"mean": 0, "median": 0, "min": 0, "max": 0}

        return {
            "mean": statistics.mean(iterations),
            "median": statistics.median(iterations),
            "min": min(iterations),
            "max": max(iterations)
        }

    def collect_story_pass_rate(self, days: int = 30) -> dict:
        """收集故事通过率"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        total_stories = 0
        passed_stories = 0

        for task in tasks:
            runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task['task_id']}")
            progress = runner.parse_progress()

            for story in progress["stories"]:
                total_stories += 1
                if story["passes"]:
                    passed_stories += 1

        if total_stories == 0:
            return {"rate": 0.0, "total": 0, "passed": 0}

        rate = passed_stories / total_stories

        return {
            "rate": rate,
            "total": total_stories,
            "passed": passed_stories
        }
```

### 2.2 错误日志收集

```python
import re
from collections import Counter, defaultdict

class ErrorLogCollector:
    """错误日志收集器"""

    def __init__(self, state: RalphState):
        self.state = state

    def collect_errors(self, days: int = 30) -> dict:
        """收集错误日志"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="failed",
            start_date=start_date
        )

        errors = []

        for task in tasks:
            logs = task["logs"]

            # 提取错误行
            error_lines = [
                line for line in logs.split('\n')
                if 'ERROR' in line or 'FAILED' in line or 'Exception' in line
            ]

            for error_line in error_lines:
                errors.append({
                    "task_id": task["task_id"],
                    "error": error_line,
                    "timestamp": task["updated_at"]
                })

        return errors

    def categorize_errors(self, errors: list) -> dict:
        """错误分类"""
        categories = defaultdict(list)

        for error in errors:
            error_msg = error["error"].lower()

            if "timeout" in error_msg:
                categories["timeout"].append(error)
            elif "permission" in error_msg:
                categories["permission"].append(error)
            elif "syntax" in error_msg:
                categories["syntax"].append(error)
            elif "import" in error_msg or "module not found" in error_msg:
                categories["import"].append(error)
            elif "test" in error_msg:
                categories["test_failure"].append(error)
            else:
                categories["other"].append(error)

        return {
            category: len(errors_list)
            for category, errors_list in categories.items()
        }

    def get_common_errors(self, days: int = 30, top_n: int = 10) -> list:
        """获取最常见的错误"""
        errors = self.collect_errors(days)

        # 提取错误消息（去掉任务 ID 和时间戳）
        error_messages = []
        for error in errors:
            # 简化错误消息
            simplified = re.sub(r'\[.*?\]', '', error["error"])
            simplified = simplified.strip()
            error_messages.append(simplified)

        # 统计频率
        error_counts = Counter(error_messages)

        return [
            {"error": error, "count": count}
            for error, count in error_counts.most_common(top_n)
        ]
```

### 2.3 用户反馈收集

```python
class FeedbackCollector:
    """用户反馈收集器"""

    def __init__(self, state: RalphState):
        self.state = state

    def collect_satisfaction_ratings(self, days: int = 30) -> dict:
        """收集满意度评分"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        ratings = []

        for task in tasks:
            metadata = task.get("metadata", {})
            if "satisfaction" in metadata:
                ratings.append(metadata["satisfaction"])

        if not ratings:
            return {"mean": 0, "count": 0}

        return {
            "mean": statistics.mean(ratings),
            "median": statistics.median(ratings),
            "count": len(ratings)
        }

    def collect_feedback_comments(self, days: int = 30) -> list:
        """收集反馈评论"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        comments = []

        for task in tasks:
            metadata = task.get("metadata", {})
            if "feedback" in metadata:
                comments.append({
                    "task_id": task["task_id"],
                    "feedback": metadata["feedback"],
                    "timestamp": task["updated_at"]
                })

        return comments
```

---

## 3. 数据分析

### 3.1 模式识别

```python
from sklearn.cluster import KMeans
import numpy as np

class PatternAnalyzer:
    """模式分析器"""

    def __init__(self, state: RalphState):
        self.state = state

    def analyze_failure_patterns(self, days: int = 30) -> dict:
        """分析失败模式"""
        start_date = datetime.utcnow() - timedelta(days=days)

        failed_tasks = self.state.list(
            status="failed",
            start_date=start_date
        )

        patterns = defaultdict(list)

        for task in failed_tasks:
            logs = task["logs"]

            # 提取失败特征
            features = self._extract_features(logs)
            patterns[task["task_id"]] = features

        return dict(patterns)

    def _extract_features(self, logs: str) -> dict:
        """提取失败特征"""
        features = {
            "error_count": logs.count("ERROR"),
            "warning_count": logs.count("WARNING"),
            "has_timeout": "timeout" in logs.lower(),
            "has_permission_error": "permission" in logs.lower(),
            "has_syntax_error": "syntax" in logs.lower(),
            "iteration_count": logs.count("Iteration"),
            "log_length": len(logs)
        }

        return features

    def cluster_failures(self, features: dict, n_clusters: int = 3) -> dict:
        """聚类失败模式"""
        # 转换为矩阵
        task_ids = list(features.keys())
        feature_matrix = np.array([
            [
                features[task_id]["error_count"],
                features[task_id]["warning_count"],
                features[task_id]["iteration_count"],
                features[task_id]["log_length"]
            ]
            for task_id in task_ids
        ])

        # 聚类
        kmeans = KMeans(n_clusters=n_clusters)
        clusters = kmeans.fit_predict(feature_matrix)

        # 组织结果
        clustered = defaultdict(list)
        for task_id, cluster_id in zip(task_ids, clusters):
            clustered[cluster_id].append(task_id)

        return dict(clustered)

    def detect_anomalies(self, features: dict, threshold: float = 2.0) -> list:
        """检测异常"""
        task_ids = list(features.keys())
        values = [features[task_id]["log_length"] for task_id in task_ids]

        mean = statistics.mean(values)
        std = statistics.stdev(values)

        anomalies = []

        for task_id, log_length in zip(task_ids, values):
            z_score = abs(log_length - mean) / std if std > 0 else 0
            if z_score > threshold:
                anomalies.append({
                    "task_id": task_id,
                    "log_length": log_length,
                    "z_score": z_score
                })

        return anomalies
```

### 3.2 趋势分析

```python
class TrendAnalyzer:
    """趋势分析器"""

    def __init__(self, state: RalphState):
        self.state = state

    def analyze_completion_trend(self, days: int = 30, window: int = 7) -> dict:
        """分析完成率趋势"""
        trend_data = []

        for i in range(days - window, 0, -1):
            start_date = datetime.utcnow() - timedelta(days=i + window)
            end_date = datetime.utcnow() - timedelta(days=i)

            completed = self.state.list(
                status="completed",
                start_date=start_date,
                end_date=end_date
            )
            failed = self.state.list(
                status="failed",
                start_date=start_date,
                end_date=end_date
            )

            total = len(completed) + len(failed)
            rate = len(completed) / total if total > 0 else 0

            trend_data.append({
                "date": end_date.strftime("%Y-%m-%d"),
                "rate": rate,
                "completed": len(completed),
                "failed": len(failed)
            })

        return {
            "data": trend_data,
            "trend": "improving" if trend_data[-1]["rate"] > trend_data[0]["rate"] else "declining"
        }

    def analyze_iteration_trend(self, days: int = 30) -> dict:
        """分析迭代次数趋势"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(
            status="completed",
            start_date=start_date
        )

        iteration_data = []

        for task in tasks:
            runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task['task_id']}")
            progress = runner.parse_progress()

            iteration_data.append({
                "task_id": task["task_id"],
                "iterations": progress["iterations"],
                "date": task["updated_at"]
            })

        # 按日期排序
        iteration_data.sort(key=lambda x: x["date"])

        return {
            "data": iteration_data,
            "mean": statistics.mean([d["iterations"] for d in iteration_data])
        }
```

---

## 4. 优化引擎

### 4.1 提示词优化

```python
class PromptOptimizer:
    """提示词优化器"""

    def __init__(self, state: RalphState):
        self.state = state

    def suggest_prompt_improvements(self, days: int = 30) -> list:
        """建议提示词改进"""
        # 分析常见错误
        collector = ErrorLogCollector(self.state)
        common_errors = collector.get_common_errors(days, top_n=5)

        suggestions = []

        for error in common_errors:
            if "import" in error["error"]:
                suggestions.append({
                    "type": "prompt",
                    "issue": "Import errors",
                    "suggestion": "Add context about project dependencies and import paths"
                })
            elif "timeout" in error["error"]:
                suggestions.append({
                    "type": "prompt",
                    "issue": "Timeout errors",
                    "suggestion": "Reduce task scope or add time management instructions"
                })
            elif "syntax" in error["error"]:
                suggestions.append({
                    "type": "prompt",
                    "issue": "Syntax errors",
                    "suggestion": "Include coding standards and syntax examples"
                })

        return suggestions

    def generate_optimized_prompt(self, task_spec: dict) -> str:
        """生成优化后的提示词"""
        base_prompt = f"""
You are tasked with: {task_spec['task']}

## Requirements
"""

        for criteria in task_spec.get("acceptanceCriteria", []):
            base_prompt += f"- {criteria}\n"

        # 添加基于历史错误的提示
        base_prompt += "\n## Common Pitfalls to Avoid\n"
        base_prompt += "- Always check imports are correct\n"
        base_prompt += "- Verify syntax before testing\n"
        base_prompt += "- Handle edge cases\n"

        return base_prompt
```

### 4.2 参数优化

```python
class ParameterOptimizer:
    """参数优化器"""

    def __init__(self, state: RalphState):
        self.state = state

    def suggest_timeout_adjustments(self, days: int = 30) -> dict:
        """建议超时调整"""
        start_date = datetime.utcnow() - timedelta(days=days)

        completed = self.state.list(status="completed", start_date=start_date)
        failed = self.state.list(status="failed", start_date=start_date)

        # 分析完成时间
        durations = []
        for task in completed:
            created = datetime.fromisoformat(task["created_at"])
            updated = datetime.fromisoformat(task["updated_at"])
            duration = (updated - created).total_seconds()
            durations.append(duration)

        if not durations:
            return {"current": 7200, "suggested": 7200}

        mean_duration = statistics.mean(durations)
        max_duration = max(durations)

        # 建议设置为平均时间的 1.5 倍或最大时间的 1.2 倍
        suggested_timeout = max(mean_duration * 1.5, max_duration * 1.2)

        return {
            "current": 7200,
            "suggested": int(suggested_timeout),
            "mean_duration": mean_duration,
            "max_duration": max_duration
        }

    def suggest_iteration_adjustments(self, days: int = 30) -> dict:
        """建议迭代次数调整"""
        start_date = datetime.utcnow() - timedelta(days=days)

        tasks = self.state.list(status="completed", start_date=start_date)

        iterations = []

        for task in tasks:
            runner = RalphRunner(ralph_dir=f"/tmp/ralph-{task['task_id']}")
            progress = runner.parse_progress()
            iterations.append(progress["iterations"])

        if not iterations:
            return {"current": 10, "suggested": 10}

        mean_iterations = statistics.mean(iterations)
        max_iterations = max(iterations)

        return {
            "current": 10,
            "suggested": int(mean_iterations * 1.2),
            "mean": mean_iterations,
            "max": max_iterations
        }
```

---

## 5. 持续改进

### 5.1 改进追踪

```python
class ImprovementTracker:
    """改进追踪器"""

    def __init__(self, insights_db: str):
        self.insights_db = insights_db

    def log_improvement(self, improvement: dict):
        """记录改进"""
        # 实现数据库记录
        pass

    def get_improvements(self, days: int = 30) -> list:
        """获取改进记录"""
        # 实现查询逻辑
        pass

    def measure_impact(self, improvement_id: str) -> dict:
        """测量改进效果"""
        # 实现效果测量
        pass
```

### 5.2 自动化优化

```python
class AutoOptimizer:
    """自动优化器"""

    def __init__(self, state: RalphState):
        self.state = state

    def run_optimization_cycle(self) -> dict:
        """运行优化周期"""
        # 1. 收集指标
        collector = QualityMetricsCollector(self.state)
        metrics = {
            "completion_rate": collector.collect_completion_rate(),
            "execution_time": collector.collect_execution_time(),
            "iterations": collector.collect_iterations()
        }

        # 2. 分析问题
        analyzer = PatternAnalyzer(self.state)
        patterns = analyzer.analyze_failure_patterns()

        # 3. 生成优化建议
        prompt_optimizer = PromptOptimizer(self.state)
        prompt_suggestions = prompt_optimizer.suggest_prompt_improvements()

        param_optimizer = ParameterOptimizer(self.state)
        param_suggestions = {
            "timeout": param_optimizer.suggest_timeout_adjustments(),
            "iterations": param_optimizer.suggest_iteration_adjustments()
        }

        # 4. 应用优化（自动或手动）
        return {
            "metrics": metrics,
            "patterns": patterns,
            "prompt_suggestions": prompt_suggestions,
            "param_suggestions": param_suggestions
        }
```

---

## 6. Python API

### 6.1 主接口

```python
from feedback_loop import (
    QualityMetricsCollector,
    ErrorLogCollector,
    FeedbackCollector,
    PatternAnalyzer,
    TrendAnalyzer,
    PromptOptimizer,
    ParameterOptimizer,
    AutoOptimizer
)

# 初始化
state = RalphState()

# 收集质量指标
collector = QualityMetricsCollector(state)
completion_rate = collector.collect_completion_rate()
execution_time = collector.collect_execution_time()

# 分析错误
error_collector = ErrorLogCollector(state)
common_errors = error_collector.get_common_errors()

# 模式分析
analyzer = PatternAnalyzer(state)
patterns = analyzer.analyze_failure_patterns()

# 优化
optimizer = AutoOptimizer(state)
optimization = optimizer.run_optimization_cycle()
```

### 6.2 CLI 工具

```bash
# 收集质量指标
./feedback_loop.py collect-metrics [--days 30]

# 分析错误
./feedback_loop.py analyze-errors [--days 30]

# 运行优化周期
./feedback_loop.py optimize

# 生成报告
./feedback_loop.py report [--days 30] [--output report.md]

# 应用优化
./feedback_loop.py apply-optimization <optimization-id>
```

---

## 7. 最佳实践

1. **定期分析**: 每周或每月运行一次完整分析
2. **小步改进**: 采用小步快跑的方式，避免大规模改动
3. **A/B 测试**: 对优化建议进行 A/B 测试
4. **记录历史**: 保存所有改进决策和效果
5. **用户反馈**: 优先处理用户反馈的问题
6. **自动化**: 尽量自动化数据收集和分析
7. **可视化**: 使用图表展示趋势和模式

---

## 8. 扩展性

### 8.1 自定义分析器

```python
class CustomAnalyzer(BaseAnalyzer):
    """自定义分析器"""

    def analyze(self, data: dict) -> dict:
        """实现自定义分析逻辑"""
        pass

# 注册自定义分析器
auto_optimizer = AutoOptimizer(state)
auto_optimizer.register_analyzer("custom", CustomAnalyzer())
```

### 8.2 集成机器学习

```python
from sklearn.ensemble import RandomForestClassifier

class MLPredictor:
    """机器学习预测器"""

    def train(self, features: list, labels: list):
        """训练模型"""
        self.model = RandomForestClassifier()
        self.model.fit(features, labels)

    def predict(self, features: list) -> list:
        """预测结果"""
        return self.model.predict(features)

# 使用预测器预测任务是否可能失败
predictor = MLPredictor()
predictor.train(training_features, training_labels)
predictions = predictor.predict(new_features)
```

---

## 9. 参考文档

- [scikit-learn 文档](https://scikit-learn.org/)
- [统计分析方法](https://en.wikipedia.org/wiki/Statistical_analysis)
- [完整集成文档](../RALPH_INTEGRATION.md)
