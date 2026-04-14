#!/usr/bin/env python3
"""
gbrain Historical Task Retriever - Phase 4+

Retrieves relevant historical tasks from gbrain knowledge base
based on new TaskSpec using keyword, vector, and hybrid search strategies.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum


class SearchStrategy(Enum):
    """Search strategy types."""
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"


@dataclass
class HistoricalTask:
    """Represents a historical task retrieved from gbrain."""
    task_id: str
    description: str
    code_pattern: str
    decisions: str
    review_comments: str
    file_structure: str
    relevance_score: float
    retrieval_method: str
    tags: List[str]
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GbrainRetrieverError(Exception):
    pass


class GbrainRetriever:
    """Retrieves relevant historical tasks from gbrain knowledge base."""

    def __init__(
        self,
        gbrain_dir: Optional[str] = None,
        default_strategy: SearchStrategy = SearchStrategy.HYBRID,
        top_n: int = 3,
        min_relevance: float = 0.5,
    ):
        home = Path.home()
        self.gbrain_dir = Path(gbrain_dir or home / ".openclaw" / "workspace-alpha" / "gbrain")
        self.default_strategy = default_strategy
        self.top_n = top_n
        self.min_relevance = min_relevance

    def _run_gbrain_cmd(self, args: List[str], timeout: int = 120) -> Dict[str, Any]:
        """Execute a gbrain CLI command."""
        if not self.gbrain_dir.exists():
            return {"success": False, "error": f"gbrain dir not found: {self.gbrain_dir}"}

        cmd = ["bun", "run", "src/cli.ts"] + args
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.gbrain_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout if result.stdout else ""
            try:
                data = json.loads(output) if output else {}
            except json.JSONDecodeError:
                data = {"raw_output": output}

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "data": data,
                "stderr": result.stderr[-500:] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"gbrain command timed out after {timeout}s"}
        except FileNotFoundError:
            return {"success": False, "error": "bun not found in PATH"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _extract_keywords_from_task_spec(self, task_spec: Dict[str, Any]) -> List[str]:
        """Extract relevant keywords from TaskSpec for searching."""
        keywords = []

        # From task description
        task = task_spec.get("task", "")
        keywords.extend(task.split())

        # From user stories
        user_stories = task_spec.get("userStories", [])
        if isinstance(user_stories, str):
            keywords.extend(user_stories.split())
        elif isinstance(user_stories, list):
            for story in user_stories:
                keywords.extend(str(story).split())

        # From acceptance criteria
        acceptance_criteria = task_spec.get("acceptanceCriteria", "")
        if isinstance(acceptance_criteria, str):
            keywords.extend(acceptance_criteria.split())

        # Clean and deduplicate
        cleaned = []
        seen = set()
        for kw in keywords:
            kw_clean = kw.strip(".,;:!?()[]{}\"'").lower()
            if len(kw_clean) > 2 and kw_clean not in seen:
                seen.add(kw_clean)
                cleaned.append(kw_clean)

        return cleaned[:20]  # Limit to top 20 keywords

    def _keyword_search(
        self,
        task_spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Perform keyword-based search in gbrain."""
        keywords = self._extract_keywords_from_task_spec(task_spec)

        if not keywords:
            return []

        # Search gbrain using keywords
        search_query = " ".join(keywords[:10])  # Use top 10 keywords
        result = self._run_gbrain_cmd(["search", search_query, "--limit", str(self.top_n * 2)])

        if not result["success"]:
            raise GbrainRetrieverError(f"Keyword search failed: {result.get('error', 'Unknown error')}")

        # Parse results
        search_data = result.get("data", {})
        results = search_data.get("results", [])

        # Format results
        formatted_results = []
        for item in results[:self.top_n]:
            content = item.get("content", {})
            formatted_results.append({
                "task_id": self._extract_task_id_from_content(content),
                "description": content.get("description", ""),
                "code_pattern": content.get("code_pattern", ""),
                "decisions": content.get("decisions", ""),
                "review_comments": content.get("review_comments", ""),
                "file_structure": content.get("file_structure", ""),
                "relevance_score": 0.7,  # Default relevance for keyword search
                "retrieval_method": "keyword",
                "tags": item.get("tags", []),
                "metadata": item.get("metadata", {}),
            })

        return formatted_results

    def _vector_search(
        self,
        task_spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Perform vector-based semantic search in gbrain."""
        # Create a query from the task spec
        query_parts = [
            task_spec.get("task", ""),
            str(task_spec.get("userStories", "")),
            str(task_spec.get("acceptanceCriteria", "")),
        ]
        query = " ".join([str(p) for p in query_parts])

        if not query.strip():
            return []

        # Search gbrain using vector similarity
        result = self._run_gbrain_cmd(
            ["search", query, "--limit", str(self.top_n * 2), "--vector"]
        )

        if not result["success"]:
            # Vector search might not be available, fall back gracefully
            return []

        # Parse results
        search_data = result.get("data", {})
        results = search_data.get("results", [])

        # Format results
        formatted_results = []
        for item in results[:self.top_n]:
            content = item.get("content", {})
            relevance = item.get("score", 0.5)

            if relevance >= self.min_relevance:
                formatted_results.append({
                    "task_id": self._extract_task_id_from_content(content),
                    "description": content.get("description", ""),
                    "code_pattern": content.get("code_pattern", ""),
                    "decisions": content.get("decisions", ""),
                    "review_comments": content.get("review_comments", ""),
                    "file_structure": content.get("file_structure", ""),
                    "relevance_score": relevance,
                    "retrieval_method": "vector",
                    "tags": item.get("tags", []),
                    "metadata": item.get("metadata", {}),
                })

        return formatted_results

    def _hybrid_search(
        self,
        task_spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining keyword and vector results."""
        keyword_results = self._keyword_search(task_spec)
        vector_results = self._vector_search(task_spec)

        # Merge and deduplicate by task_id
        merged = {}
        for item in keyword_results + vector_results:
            task_id = item["task_id"]
            if task_id not in merged:
                merged[task_id] = item
            else:
                # Combine scores: average if both methods found it
                existing = merged[task_id]
                if item["retrieval_method"] != existing["retrieval_method"]:
                    # Average the scores
                    existing["relevance_score"] = (
                        existing["relevance_score"] + item["relevance_score"]
                    ) / 2
                    existing["retrieval_method"] = "hybrid"

        # Sort by relevance and filter by min_relevance
        sorted_results = sorted(
            merged.values(),
            key=lambda x: x["relevance_score"],
            reverse=True
        )

        return [r for r in sorted_results if r["relevance_score"] >= self.min_relevance][:self.top_n]

    def _extract_task_id_from_content(self, content: Dict[str, Any]) -> str:
        """Extract task ID from content or generate a fallback."""
        # Try to find in tags
        tags = content.get("tags", [])
        for tag in tags:
            if tag and isinstance(tag, str) and not tag.startswith("date:") and not tag.startswith("project:") and not tag.startswith("type:"):
                return tag

        # Try to find in metadata
        metadata = content.get("metadata", {})
        if "task_id" in metadata:
            return metadata["task_id"]

        # Generate a fallback from description
        desc = content.get("description", "")
        if desc:
            # Extract first word or number pattern
            words = desc.split()
            if words:
                return words[0][:20]

        return "UNKNOWN"

    def retrieve(
        self,
        task_spec: Dict[str, Any],
        strategy: Optional[SearchStrategy] = None,
    ) -> List[HistoricalTask]:
        """
        Retrieve relevant historical tasks based on TaskSpec.

        Args:
            task_spec: ai-devops TaskSpec dictionary
            strategy: Search strategy (defaults to class default)

        Returns:
            List of HistoricalTask objects sorted by relevance

        Raises:
            GbrainRetrieverError: If retrieval fails
        """
        strategy = strategy or self.default_strategy

        # Execute search based on strategy
        if strategy == SearchStrategy.KEYWORD:
            results = self._keyword_search(task_spec)
        elif strategy == SearchStrategy.VECTOR:
            results = self._vector_search(task_spec)
        elif strategy == SearchStrategy.HYBRID:
            results = self._hybrid_search(task_spec)
        else:
            raise GbrainRetrieverError(f"Unknown search strategy: {strategy}")

        # Convert to HistoricalTask objects
        tasks = []
        for result in results:
            tasks.append(HistoricalTask(**result))

        return tasks

    def retrieve_by_task_id(self, task_id: str) -> Optional[HistoricalTask]:
        """
        Retrieve a specific task by its ID.

        Args:
            task_id: Task identifier

        Returns:
            HistoricalTask object or None if not found
        """
        result = self._run_gbrain_cmd(["get", task_id])

        if not result["success"]:
            return None

        data = result.get("data", {})
        if not data:
            return None

        content = data.get("content", {})
        task_data = {
            "task_id": task_id,
            "description": content.get("description", ""),
            "code_pattern": content.get("code_pattern", ""),
            "decisions": content.get("decisions", ""),
            "review_comments": content.get("review_comments", ""),
            "file_structure": content.get("file_structure", ""),
            "relevance_score": 1.0,
            "retrieval_method": "direct",
            "tags": data.get("tags", []),
            "metadata": data.get("metadata", {}),
        }

        return HistoricalTask(**task_data)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("GbrainRetriever CLI")
        print("Usage:")
        print("  gbrain_retriever.py retrieve <task_spec.json> [--strategy keyword|vector|hybrid] [--top-n N]")
        print("  gbrain_retriever.py get <task_id>")
        sys.exit(0)

    cmd = sys.argv[1]

    try:
        if cmd == "retrieve":
            task_spec_path = sys.argv[2]
            strategy = None
            top_n = 3
            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--strategy" and i + 1 < len(sys.argv):
                    strategy = SearchStrategy(sys.argv[i + 1])
                    i += 2
                elif sys.argv[i] == "--top-n" and i + 1 < len(sys.argv):
                    top_n = int(sys.argv[i + 1])
                    i += 2
                else:
                    i += 1

            # Load task spec
            with open(task_spec_path, 'r') as f:
                task_spec = json.load(f)

            # Retrieve
            retriever = GbrainRetriever(top_n=top_n)
            tasks = retriever.retrieve(task_spec, strategy=strategy)

            # Output
            print(json.dumps([t.to_dict() for t in tasks], indent=2))

        elif cmd == "get":
            task_id = sys.argv[2]

            retriever = GbrainRetriever()
            task = retriever.retrieve_by_task_id(task_id)

            if task:
                print(json.dumps(task.to_dict(), indent=2))
            else:
                print(f"Task {task_id} not found")
                sys.exit(1)

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
