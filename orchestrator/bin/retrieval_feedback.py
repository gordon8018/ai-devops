#!/usr/bin/env python3
"""
Retrieval Feedback Module - Phase 4+

Records and evaluates the quality of historical task retrieval,
tracks Ralph's usage of historical context, and optimizes retrieval weights.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum


class FeedbackRating(Enum):
    """Rating for retrieval quality."""
    VERY_USEFUL = 5
    USEFUL = 4
    SOMEWHAT_USEFUL = 3
    NOT_RELEVANT = 2
    HARMFUL = 1


@dataclass
class RetrievalEvent:
    """Represents a single retrieval event."""
    task_id: str
    retrieval_time: str
    retrieved_tasks: List[Dict[str, Any]]
    context_injected: bool
    ralph_used_context: bool
    user_rating: Optional[int]  # 1-5 scale
    feedback_notes: Optional[str]
    execution_metrics: Dict[str, Any]  # iterations, duration, quality_score, etc.


class RetrievalFeedbackError(Exception):
    pass


class RetrievalFeedback:
    """Manages retrieval feedback and quality assessment."""

    def __init__(
        self,
        feedback_dir: Optional[str] = None,
    ):
        home = Path.home()
        self.feedback_dir = Path(
            feedback_dir or
            home / ".openclaw" / "workspace-alpha" / "gbrain_feedback"
        )
        self.feedback_dir.mkdir(parents=True, exist_ok=True)

    def _get_feedback_file_path(self, task_id: str) -> Path:
        """Get the feedback file path for a task."""
        return self.feedback_dir / f"{task_id}_feedback.json"

    def record_retrieval(
        self,
        task_id: str,
        retrieved_tasks: List[Dict[str, Any]],
        context_injected: bool,
        execution_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record a retrieval event.

        Args:
            task_id: Current task identifier
            retrieved_tasks: List of retrieved historical tasks
            context_injected: Whether context was injected into PRD
            execution_metrics: Optional execution metrics (iterations, duration, quality_score)

        Returns:
            Result dictionary with feedback record info
        """
        event = RetrievalEvent(
            task_id=task_id,
            retrieval_time=datetime.now(timezone.utc).isoformat(),
            retrieved_tasks=retrieved_tasks,
            context_injected=context_injected,
            ralph_used_context=None,  # To be filled later
            user_rating=None,  # To be filled by user
            feedback_notes=None,
            execution_metrics=execution_metrics or {},
        )

        # Save to file
        feedback_path = self._get_feedback_file_path(task_id)
        feedback_path.write_text(json.dumps(asdict(event), indent=2), encoding='utf-8')

        return {
            "success": True,
            "task_id": task_id,
            "feedback_path": str(feedback_path),
            "retrieval_time": event.retrieval_time,
            "num_retrieved_tasks": len(retrieved_tasks),
        }

    def update_usage_feedback(
        self,
        task_id: str,
        ralph_used_context: bool,
        user_rating: Optional[int] = None,
        feedback_notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update usage feedback after Ralph execution.

        Args:
            task_id: Task identifier
            ralph_used_context: Whether Ralph used the historical context
            user_rating: Optional user rating (1-5)
            feedback_notes: Optional user feedback notes

        Returns:
            Result dictionary
        """
        feedback_path = self._get_feedback_file_path(task_id)

        if not feedback_path.exists():
            return {
                "success": False,
                "error": f"Feedback file not found for task {task_id}",
            }

        # Load and update
        event_data = json.loads(feedback_path.read_text(encoding='utf-8'))
        event_data["ralph_used_context"] = ralph_used_context
        event_data["user_rating"] = user_rating
        event_data["feedback_notes"] = feedback_notes

        # Save
        feedback_path.write_text(json.dumps(event_data, indent=2), encoding='utf-8')

        return {
            "success": True,
            "task_id": task_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_feedback(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get feedback for a specific task.

        Args:
            task_id: Task identifier

        Returns:
            Feedback data or None if not found
        """
        feedback_path = self._get_feedback_file_path(task_id)

        if not feedback_path.exists():
            return None

        return json.loads(feedback_path.read_text(encoding='utf-8'))

    def evaluate_retrieval_quality(
        self,
        task_id: str,
    ) -> Dict[str, Any]:
        """
        Evaluate retrieval quality for a task.

        Args:
            task_id: Task identifier

        Returns:
            Quality assessment dictionary
        """
        feedback = self.get_feedback(task_id)

        if not feedback:
            return {
                "task_id": task_id,
                "error": "Feedback not found",
            }

        # Assess quality
        assessment = {
            "task_id": task_id,
            "retrieval_time": feedback.get("retrieval_time"),
            "num_retrieved_tasks": len(feedback.get("retrieved_tasks", [])),
            "context_injected": feedback.get("context_injected", False),
            "ralph_used_context": feedback.get("ralph_used_context"),
            "user_rating": feedback.get("user_rating"),
            "feedback_notes": feedback.get("feedback_notes"),
            "execution_metrics": feedback.get("execution_metrics", {}),
        }

        # Calculate quality score
        retrieved_tasks = feedback.get("retrieved_tasks", [])
        if retrieved_tasks:
            avg_relevance = sum(t.get("relevance_score", 0) for t in retrieved_tasks) / len(retrieved_tasks)
            assessment["avg_relevance_score"] = avg_relevance

            # Determine quality tier
            if avg_relevance >= 0.8:
                assessment["quality_tier"] = "high"
            elif avg_relevance >= 0.6:
                assessment["quality_tier"] = "medium"
            else:
                assessment["quality_tier"] = "low"

        # Usage effectiveness
        if assessment["ralph_used_context"] is not None:
            if assessment["ralph_used_context"]:
                assessment["usage_effectiveness"] = "used"
            else:
                assessment["usage_effectiveness"] = "ignored"

        # Overall assessment
        quality_score = 0
        if assessment.get("avg_relevance_score"):
            quality_score += assessment["avg_relevance_score"] * 0.5  # 50% weight
        if assessment["user_rating"]:
            quality_score += (assessment["user_rating"] / 5) * 0.3  # 30% weight
        if assessment["ralph_used_context"]:
            quality_score += 0.2  # 20% weight

        assessment["overall_quality_score"] = quality_score

        return assessment

    def get_all_feedback(self) -> List[Dict[str, Any]]:
        """
        Get all feedback records.

        Returns:
            List of all feedback data
        """
        all_feedback = []

        for feedback_file in self.feedback_dir.glob("*_feedback.json"):
            try:
                feedback_data = json.loads(feedback_file.read_text(encoding='utf-8'))
                all_feedback.append(feedback_data)
            except (json.JSONDecodeError, IOError):
                continue

        return all_feedback

    def generate_quality_report(self) -> Dict[str, Any]:
        """
        Generate a quality report across all feedback records.

        Returns:
            Quality report with statistics and recommendations
        """
        all_feedback = self.get_all_feedback()

        if not all_feedback:
            return {
                "total_retrievals": 0,
                "message": "No feedback records found",
            }

        # Statistics
        total_retrievals = len(all_feedback)
        total_tasks = sum(len(f.get("retrieved_tasks", [])) for f in all_feedback)
        context_injected_count = sum(1 for f in all_feedback if f.get("context_injected"))
        ralph_used_context_count = sum(1 for f in all_feedback if f.get("ralph_used_context"))

        # Average ratings
        ratings = [f.get("user_rating") for f in all_feedback if f.get("user_rating") is not None]
        avg_rating = sum(ratings) / len(ratings) if ratings else None

        # Average relevance
        all_relevance_scores = []
        for f in all_feedback:
            for task in f.get("retrieved_tasks", []):
                if "relevance_score" in task:
                    all_relevance_scores.append(task["relevance_score"])

        avg_relevance = sum(all_relevance_scores) / len(all_relevance_scores) if all_relevance_scores else None

        # Quality distribution
        quality_assessments = [self.evaluate_retrieval_quality(f["task_id"]) for f in all_feedback]
        high_quality = sum(1 for a in quality_assessments if a.get("quality_tier") == "high")
        medium_quality = sum(1 for a in quality_assessments if a.get("quality_tier") == "medium")
        low_quality = sum(1 for a in quality_assessments if a.get("quality_tier") == "low")

        # Recommendations
        recommendations = []

        if avg_relevance is not None and avg_relevance < 0.6:
            recommendations.append(
                "Average relevance score is low. Consider adjusting retrieval parameters "
                "(increase min_relevance_threshold, improve tagging, or tune vector embeddings)."
            )

        if ralph_used_context_count / context_injected_count < 0.5:
            recommendations.append(
                "Ralph is ignoring historical context in most cases. "
                "Consider improving context formatting or reducing context size."
            )

        if avg_rating is not None and avg_rating < 3:
            recommendations.append(
                "User ratings are below average. Review feedback notes to identify patterns."
            )

        return {
            "total_retrievals": total_retrievals,
            "total_retrieved_tasks": total_tasks,
            "avg_tasks_per_retrieval": total_tasks / total_retrievals if total_retrievals > 0 else 0,
            "context_injection_rate": context_injected_count / total_retrievals if total_retrievals > 0 else 0,
            "context_usage_rate": ralph_used_context_count / context_injected_count if context_injected_count > 0 else 0,
            "avg_user_rating": avg_rating,
            "avg_relevance_score": avg_relevance,
            "quality_distribution": {
                "high": high_quality,
                "medium": medium_quality,
                "low": low_quality,
            },
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("RetrievalFeedback CLI")
        print("Usage:")
        print("  retrieval_feedback.py record <task_id> <retrieved_tasks.json> [--context-injected]")
        print("  retrieval_feedback.py update <task_id> [--used] [--rating 1-5] [--notes 'feedback']")
        print("  retrieval_feedback.py get <task_id>")
        print("  retrieval_feedback.py evaluate <task_id>")
        print("  retrieval_feedback.py report")
        sys.exit(0)

    cmd = sys.argv[1]

    try:
        if cmd == "record":
            task_id = sys.argv[2]
            retrieved_tasks_path = sys.argv[3]

            with open(retrieved_tasks_path, 'r') as f:
                retrieved_tasks = json.load(f)

            context_injected = "--context-injected" in sys.argv

            feedback = RetrievalFeedback()
            result = feedback.record_retrieval(
                task_id=task_id,
                retrieved_tasks=retrieved_tasks,
                context_injected=context_injected,
            )

            print(json.dumps(result, indent=2))

        elif cmd == "update":
            task_id = sys.argv[2]

            ralph_used_context = "--used" in sys.argv
            user_rating = None
            feedback_notes = None

            i = 3
            while i < len(sys.argv):
                if sys.argv[i] == "--rating" and i + 1 < len(sys.argv):
                    user_rating = int(sys.argv[i + 1])
                    i += 2
                elif sys.argv[i] == "--notes" and i + 1 < len(sys.argv):
                    feedback_notes = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1

            feedback = RetrievalFeedback()
            result = feedback.update_usage_feedback(
                task_id=task_id,
                ralph_used_context=ralph_used_context,
                user_rating=user_rating,
                feedback_notes=feedback_notes,
            )

            print(json.dumps(result, indent=2))

        elif cmd == "get":
            task_id = sys.argv[2]

            feedback = RetrievalFeedback()
            result = feedback.get_feedback(task_id)

            if result:
                print(json.dumps(result, indent=2))
            else:
                print(f"No feedback found for task {task_id}")

        elif cmd == "evaluate":
            task_id = sys.argv[2]

            feedback = RetrievalFeedback()
            result = feedback.evaluate_retrieval_quality(task_id)

            print(json.dumps(result, indent=2))

        elif cmd == "report":
            feedback = RetrievalFeedback()
            result = feedback.generate_quality_report()

            print(json.dumps(result, indent=2))

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
