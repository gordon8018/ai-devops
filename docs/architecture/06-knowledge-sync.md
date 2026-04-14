# 知识同步设计

## 概述

知识同步模块负责从外部知识源（如 Obsidian、gbrain）检索相关上下文，并将其注入到 Ralph 的 PRD 中，为 AI 提供更丰富的背景知识。

---

## 1. 知识同步架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Knowledge Sync Layer                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Knowledge   │  │  Context     │  │   Injection  │         │
│  │  Extractor   │  │  Assembler  │  │   Engine     │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          │                 │                 │
          ▼                 ▼                 ▼
    ┌──────────┐      ┌──────────┐      ┌──────────┐
    │ Obsidian │      │  gbrain  │      │  Custom  │
    │  Vault   │      │   API    │      │ Sources  │
    └──────────┘      └──────────┘      └──────────┘
          │                 │                 │
          └─────────────────┴─────────────────┘
                            │
                            ▼
                    ┌──────────────┐
                    │   PRD JSON   │
                    │  (Enhanced)  │
                    └──────────────┘
```

### 1.2 知识流

```
TaskSpec
   │
   ├─▶ 关键词提取
   │   │
   │   ▼
   ├─▶ 知识源检索
   │   │   ├─▶ Obsidian (Markdown 笔记)
   │   │   ├─▶ gbrain (知识图谱)
   │   │   └─▶ 自定义源
   │   │
   │   ▼
   ├─▶ 上下文组装
   │   │
   │   ▼
   ├─▶ 相关性排序
   │   │
   │   ▼
   └─▶ 注入 PRD
```

---

## 2. Obsidian 集成

### 2.1 知识库结构

```
~/Documents/ObsidianVault/
├── 📁 Architecture/
│   ├── System Design.md
│   ├── Database Schema.md
│   └── API Design.md
├── 📁 Best Practices/
│   ├── Coding Standards.md
│   ├── Testing Guidelines.md
│   └── Deployment Guide.md
├── 📁 Projects/
│   ├── ai-devops/
│   │   ├── Project Overview.md
│   │   ├── Roadmap.md
│   │   └── Known Issues.md
│   └── other-project/
└── 📁 Reference/
    ├── Third-party APIs.md
    ├── Design Patterns.md
    └── Algorithms.md
```

### 2.2 笔记格式

```markdown
---
tags: [architecture, database, design]
created: 2026-04-14
project: ai-devops
---

# Database Schema Design

## Overview

The ai-devops system uses SQLite for task storage...

## Key Tables

### ralph_state
- Stores task execution state
- Schema: ...

## Best Practices

1. Always use transactions
2. Add indexes for frequently queried fields
```

### 2.3 Obsidian 检索器

```python
import os
import re
from pathlib import Path
from typing import List, Dict
import frontmatter  # pip install python-frontmatter

class ObsidianExtractor:
    """Obsidian 知识提取器"""

    def __init__(self, vault_path: str):
        self.vault_path = Path(vault_path)

    def extract_keywords(self, task_spec: dict) -> List[str]:
        """从 TaskSpec 提取关键词"""
        keywords = []

        # 从任务描述提取
        task_desc = task_spec.get("task", "")
        keywords.extend(self._extract_words(task_desc))

        # 从用户故事提取
        for story in task_spec.get("userStories", []):
            keywords.extend(self._extract_words(story.get("title", "")))
            keywords.extend(self._extract_words(story.get("description", "")))

        # 从验收标准提取
        for criteria in task_spec.get("acceptanceCriteria", []):
            keywords.extend(self._extract_words(criteria))

        # 去重并过滤停用词
        keywords = list(set(keywords))
        keywords = self._filter_stopwords(keywords)

        return keywords

    def _extract_words(self, text: str) -> List[str]:
        """提取单词"""
        # 简单的分词（生产环境可用更复杂的 NLP）
        words = re.findall(r'\b\w+\b', text.lower())
        return words

    def _filter_stopwords(self, words: List[str]) -> List[str]:
        """过滤停用词"""
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by"}
        return [w for w in words if len(w) > 2 and w not in stopwords]

    def search_notes(self, keywords: List[str], max_results: int = 10) -> List[Dict]:
        """搜索相关笔记"""
        results = []

        for md_file in self.vault_path.rglob("*.md"):
            # 读取笔记
            with open(md_file, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)

            # 计算相关性分数
            score = self._calculate_relevance_score(post, keywords)

            if score > 0:
                results.append({
                    "file": str(md_file.relative_to(self.vault_path)),
                    "title": post.get("title", md_file.stem),
                    "tags": post.get("tags", []),
                    "content": post.content[:500],  # 前 500 字符
                    "score": score
                })

        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)

        return results[:max_results]

    def _calculate_relevance_score(self, post: frontmatter.Post, keywords: List[str]) -> float:
        """计算相关性分数"""
        score = 0.0
        content = post.content.lower()
        metadata = str(post.metadata).lower()

        # 关键词匹配（标题权重更高）
        title = post.get("title", "").lower()
        for keyword in keywords:
            if keyword in title:
                score += 2.0
            if keyword in content:
                score += 1.0
            if keyword in metadata:
                score += 0.5

        # Tag 匹配
        tags = post.get("tags", [])
        for tag in tags:
            if tag.lower() in keywords:
                score += 1.5

        # 项目匹配
        project = post.get("project", "")
        if project:
            for keyword in keywords:
                if keyword in project.lower():
                    score += 1.0

        return score
```

### 2.4 使用示例

```python
extractor = ObsidianExtractor(vault_path="~/Documents/ObsidianVault")

# 从 TaskSpec 提取关键词
task_spec = {
    "taskId": "task-001",
    "task": "Add priority field to database",
    "userStories": [
        {"title": "Create migration for priority column"},
        {"title": "Update API to support priority"}
    ]
}

keywords = extractor.extract_keywords(task_spec)
# ["add", "priority", "field", "database", "migration", "column", "api"]

# 搜索相关笔记
notes = extractor.search_notes(keywords, max_results=5)

for note in notes:
    print(f"[{note['score']}] {note['title']}")
    print(f"  Tags: {', '.join(note['tags'])}")
    print(f"  Content: {note['content'][:100]}...")
    print()
```

---

## 3. gbrain 集成

### 3.1 gbrain API 概述

gbrain 提供知识图谱 API，支持语义搜索和实体关联。

```python
import requests

class GbrainExtractor:
    """gbrain 知识提取器"""

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def search_entities(self, query: str, limit: int = 10) -> List[Dict]:
        """搜索实体"""
        response = requests.post(
            f"{self.api_url}/search",
            headers=self.headers,
            json={
                "query": query,
                "limit": limit
            }
        )

        response.raise_for_status()
        return response.json()["results"]

    def get_entity_relations(self, entity_id: str) -> List[Dict]:
        """获取实体关系"""
        response = requests.get(
            f"{self.api_url}/entities/{entity_id}/relations",
            headers=self.headers
        )

        response.raise_for_status()
        return response.json()["relations"]

    def extract_knowledge(self, task_spec: dict) -> List[Dict]:
        """从任务提取相关知识"""
        knowledge = []

        # 从任务描述提取实体
        entities = self._extract_entities(task_spec)

        # 搜索每个实体
        for entity in entities:
            results = self.search_entities(entity, limit=3)
            knowledge.extend(results)

            # 获取关系
            for result in results:
                relations = self.get_entity_relations(result["id"])
                result["relations"] = relations

        return knowledge

    def _extract_entities(self, task_spec: dict) -> List[str]:
        """提取实体（简单实现）"""
        # 生产环境可用 NER (Named Entity Recognition)
        entities = []

        task_desc = task_spec.get("task", "")
        # 提取大写单词（可能是实体名）
        entities.extend(re.findall(r'\b[A-Z][a-zA-Z]+\b', task_desc))

        return list(set(entities))
```

### 3.2 使用示例

```python
extractor = GbrainExtractor(
    api_url="https://api.gbrain.example.com",
    api_key="gb-api-key-123"
)

knowledge = extractor.extract_knowledge(task_spec)

for item in knowledge:
    print(f"Entity: {item['name']}")
    print(f"  Type: {item['type']}")
    print(f"  Description: {item['description'][:100]}...")
    if item.get("relations"):
        print(f"  Relations:")
        for rel in item["relations"][:3]:
            print(f"    - {rel['type']}: {rel['target']}")
    print()
```

---

## 4. 上下文组装

### 4.1 上下文组装器

```python
from typing import List, Dict

class ContextAssembler:
    """上下文组装器"""

    def __init__(self, obsidian_path: str, gbrain_url: str, gbrain_key: str):
        self.obsidian_extractor = ObsidianExtractor(obsidian_path)
        self.gbrain_extractor = GbrainExtractor(gbrain_url, gbrain_key)

    def assemble_context(self, task_spec: dict, max_length: int = 5000) -> str:
        """组装上下文"""
        # 提取关键词
        keywords = self.obsidian_extractor.extract_keywords(task_spec)

        # 搜索 Obsidian 笔记
        obsidian_notes = self.obsidian_extractor.search_notes(keywords)

        # 搜索 gbrain 实体
        gbrain_knowledge = self.gbrain_extractor.extract_knowledge(task_spec)

        # 组装上下文
        context_parts = []

        # 添加 Obsidian 内容
        if obsidian_notes:
            context_parts.append("## Relevant Notes\n")
            for note in obsidian_notes[:5]:  # 最多 5 个笔记
                context_parts.append(f"### {note['title']}\n")
                context_parts.append(f"{note['content'][:300]}\n")

        # 添加 gbrain 内容
        if gbrain_knowledge:
            context_parts.append("\n## Related Knowledge\n")
            for item in gbrain_knowledge[:3]:  # 最多 3 个实体
                context_parts.append(f"### {item['name']}\n")
                context_parts.append(f"{item['description'][:300]}\n")

        # 合并并限制长度
        full_context = "\n".join(context_parts)

        if len(full_context) > max_length:
            full_context = full_context[:max_length] + "\n... (truncated)"

        return full_context

    def enhance_prd(self, prd: dict, task_spec: dict) -> dict:
        """增强 PRD"""
        # 组装上下文
        context = self.assemble_context(task_spec)

        # 添加到 PRD
        prd = prd.copy()
        prd.setdefault("context", "")

        if context:
            prd["context"] += f"\n\n# Context from Knowledge Base\n\n{context}"

        return prd
```

### 4.2 使用示例

```python
assembler = ContextAssembler(
    obsidian_path="~/Documents/ObsidianVault",
    gbrain_url="https://api.gbrain.example.com",
    gbrain_key="gb-api-key-123"
)

# 增强 PRD
prd = task_spec_to_prd_json(task_spec)
enhanced_prd = assembler.enhance_prd(prd, task_spec)

# 保存增强后的 PRD
with open("prd_enhanced.json", "w") as f:
    json.dump(enhanced_prd, f, indent=2)
```

---

## 5. 注入策略

### 5.1 注入位置

```python
def inject_context_into_prd(prd: dict, context: str) -> dict:
    """将上下文注入到 PRD 的不同位置"""

    # 策略 1: 添加到全局上下文
    prd["context"] = context

    # 策略 2: 添加到每个用户故事
    for story in prd["userStories"]:
        story.setdefault("context", "")
        story["context"] += context

    # 策略 3: 添加到描述中
    prd["description"] = f"{prd['description']}\n\n{context}"

    return prd
```

### 5.2 分级注入

```python
def inject_by_relevance(prd: dict, notes: List[Dict]):
    """根据相关性分级注入"""

    # 高相关性的添加到 PRD 顶部
    high_relevance = [n for n in notes if n["score"] > 2.0]
    if high_relevance:
        prd["high_priority_context"] = "\n".join([
            f"## {note['title']}\n{note['content'][:200]}"
            for note in high_relevance
        ])

    # 中等相关的添加到每个故事
    medium_relevance = [n for n in notes if 1.0 < n["score"] <= 2.0]
    for story in prd["userStories"]:
        relevant_notes = [
            n for n in medium_relevance
            if any(keyword in story["title"] for keyword in n["tags"])
        ]
        if relevant_notes:
            story["context"] = "\n".join([
                f"- {note['title']}: {note['content'][:100]}"
                for note in relevant_notes
            ])

    return prd
```

---

## 6. Python API

### 6.1 主接口

```python
from knowledge_sync import KnowledgeSync

# 初始化
sync = KnowledgeSync(
    obsidian_path="~/Documents/ObsidianVault",
    gbrain_url="https://api.gbrain.example.com",
    gbrain_key="gb-api-key-123"
)

# 增强任务
enhanced_prd = sync.enhance_task(task_spec, prd)

# 只检索，不注入
notes = sync.retrieve_notes(task_spec)
knowledge = sync.retrieve_knowledge(task_spec)

# 自定义配置
sync = KnowledgeSync(
    obsidian_path="~/Documents/ObsidianVault",
    config={
        "max_notes": 5,
        "max_knowledge": 3,
        "context_length": 5000,
        "min_score": 1.0
    }
)
```

### 6.2 CLI 工具

```bash
# 增强任务
./knowledge_sync.py enhance <task_spec.json> <prd.json>

# 只检索笔记
./knowledge_sync.py retrieve-notes <task_spec.json>

# 只检索知识
./knowledge_sync.py retrieve-knowledge <task_spec.json>

# 测试知识源连接
./knowledge_sync.py test-connection
```

---

## 7. 缓存策略

### 7.1 本地缓存

```python
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

class CacheManager:
    """缓存管理器"""

    def __init__(self, cache_dir: str, ttl: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl  # 缓存过期时间（秒）
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Dict:
        """获取缓存"""
        cache_file = self._get_cache_file(key)

        if not cache_file.exists():
            return None

        # 检查是否过期
        modified_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.utcnow() - modified_time > timedelta(seconds=self.ttl):
            return None

        with open(cache_file, "r") as f:
            return json.load(f)

    def set(self, key: str, value: Dict):
        """设置缓存"""
        cache_file = self._get_cache_file(key)

        with open(cache_file, "w") as f:
            json.dump(value, f)

    def _get_cache_file(self, key: str) -> Path:
        """生成缓存文件路径"""
        hash_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{hash_key}.json"

# 使用
cache = CacheManager(cache_dir="~/.cache/knowledge_sync")

# 尝试从缓存获取
cache_key = f"notes:{task_spec['taskId']}"
notes = cache.get(cache_key)

if notes is None:
    # 缓存未命中，从 Obsidian 检索
    notes = extractor.search_notes(keywords)
    cache.set(cache_key, notes)
```

### 7.2 Redis 缓存

```python
import redis

class RedisCacheManager:
    """Redis 缓存管理器"""

    def __init__(self, redis_url: str, ttl: int = 3600):
        self.redis = redis.from_url(redis_url)
        self.ttl = ttl

    def get(self, key: str) -> Dict:
        """获取缓存"""
        value = self.redis.get(key)

        if value is None:
            return None

        return json.loads(value)

    def set(self, key: str, value: Dict):
        """设置缓存"""
        self.redis.setex(key, self.ttl, json.dumps(value))
```

---

## 8. 最佳实践

1. **渐进式检索**: 从快速检索（本地）开始，逐步扩展到慢速检索（远程）
2. **上下文限制**: 限制注入的上下文长度，避免 token 超限
3. **相关性过滤**: 只注入高相关性的内容
4. **定期更新**: 定期刷新知识库索引
5. **缓存命中**: 使用缓存减少重复检索
6. **隐私保护**: 敏感信息不要放入公共知识库
7. **版本控制**: 知识库使用 Git 追踪变更

---

## 9. 扩展性

### 9.1 自定义知识源

```python
class CustomKnowledgeSource(BaseExtractor):
    """自定义知识源"""

    def __init__(self, config: dict):
        self.config = config

    def extract_knowledge(self, task_spec: dict) -> List[Dict]:
        """提取知识"""
        # 实现自定义提取逻辑
        pass

# 注册自定义源
sync = KnowledgeSync()
sync.register_source("custom", CustomKnowledgeSource(config))
```

### 9.2 多知识源组合

```python
sync = KnowledgeSync()

# 注册多个源
sync.register_source("obsidian", ObsidianExtractor(path="~/vault"))
sync.register_source("gbrain", GbrainExtractor(url="...", key="..."))
sync.register_source("confluence", ConfluenceExtractor(url="...", token="..."))

# 组合检索
results = sync.retrieve_all(task_spec)
```

---

## 10. 参考文档

- [Obsidian 文档](https://help.obsidian.md/)
- [python-frontmatter 文档](https://github.com/eyeseast/python-frontmatter)
- [完整集成文档](../RALPH_INTEGRATION.md)
