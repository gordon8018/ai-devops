#!/usr/bin/env python3
"""
TaskSpec → prd.json Converter

Converts ai-devops TaskSpec format to ralph prd.json format.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class TaskSpecError(ValueError):
    """Raised when TaskSpec is missing, malformed, or invalid."""
    pass


def sanitize_slug(text: str) -> str:
    """Convert text to a URL-safe slug."""
    # Replace spaces and special chars with hyphens
    slug = re.sub(r'[^a-zA-Z0-9\s-]', '', text)
    slug = re.sub(r'[\s-]+', '-', slug).strip('-').lower()
    return slug[:50]  # Limit length


def task_spec_to_prd_json(
    task_spec: Dict[str, Any],
    quality_checks: Optional[Dict[str, Any]] = None,
    historical_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convert ai-devops TaskSpec to ralph prd.json format.

    Args:
        task_spec: ai-devops TaskSpec dictionary
        quality_checks: Optional quality check commands
        historical_context: Optional historical context from gbrain

    Returns:
        ralph prd.json dictionary

    Raises:
        TaskSpecError: If task_spec is invalid
    """
    # Validate required fields
    required_fields = ["taskId", "task", "acceptanceCriteria", "repo"]
    for field in required_fields:
        if field not in task_spec:
            raise TaskSpecError(f"TaskSpec missing required field: {field}")
    
    # Default quality checks
    if quality_checks is None:
        quality_checks = {
            "typecheck": "bun run typecheck",
            "lint": "bun run lint",
            "test": "bun run test",
            "browserVerification": False
        }
    
    # Extract task details
    task_id = task_spec["taskId"]
    task_title = task_spec["task"]
    repo = task_spec["repo"]
    
    # Parse user stories from task (may be a list or string)
    user_stories_raw = task_spec.get("userStories", [])
    if isinstance(user_stories_raw, str):
        # Split by newlines and filter empty
        user_stories_raw = [s.strip() for s in user_stories_raw.split('\n') if s.strip()]
    
    # Parse acceptance criteria
    acceptance_criteria_raw = task_spec["acceptanceCriteria"]
    if isinstance(acceptance_criteria_raw, str):
        acceptance_criteria_raw = [ac.strip() for ac in acceptance_criteria_raw.split('\n') if ac.strip()]
    
    # Build prd.json structure
    prd = {
        "project": repo.split('/')[-1] if '/' in repo else repo,
        "branchName": f"ralph/{sanitize_slug(task_id)}",
        "description": task_title,
        "aiDevopsTaskId": task_id,
        "qualityChecks": quality_checks,
        "context": historical_context or "",  # Phase 4+: Historical context from gbrain
        "userStories": []
    }
    
    # Add user stories
    for idx, story in enumerate(user_stories_raw):
        story_data = {
            "id": f"US-{idx+1:03d}",
            "title": story if len(story) < 100 else story[:97] + "...",
            "description": story,
            "acceptanceCriteria": acceptance_criteria_raw,
            "priority": idx + 1,
            "passes": False,
            "notes": "",
            "sourceSubtaskId": f"{task_id}-{idx}"
        }
        prd["userStories"].append(story_data)
    
    # If no user stories provided, create one from the task itself
    if not prd["userStories"]:
        prd["userStories"] = [{
            "id": "US-001",
            "title": task_title if len(task_title) < 100 else task_title[:97] + "...",
            "description": task_title,
            "acceptanceCriteria": acceptance_criteria_raw,
            "priority": 1,
            "passes": False,
            "notes": "",
            "sourceSubtaskId": task_id
        }]
    
    return prd


def save_prd_json(prd: Dict[str, Any], output_path: str | Path) -> None:
    """
    Save prd.json to file.
    
    Args:
        prd: prd.json dictionary
        output_path: Path to save the file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(prd, f, indent=2, ensure_ascii=False)


def load_task_spec_from_file(path: str | Path) -> Dict[str, Any]:
    """
    Load TaskSpec from JSON file.
    
    Args:
        path: Path to TaskSpec JSON file
        
    Returns:
        TaskSpec dictionary
        
    Raises:
        TaskSpecError: If file not found or invalid JSON
    """
    path = Path(path)
    if not path.exists():
        raise TaskSpecError(f"TaskSpec file not found: {path}")
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise TaskSpecError(f"Invalid JSON in TaskSpec file: {e}")


def validate_prd_json(prd: Dict[str, Any]) -> bool:
    """
    Validate prd.json structure.
    
    Args:
        prd: prd.json dictionary
        
    Returns:
        True if valid
        
    Raises:
        TaskSpecError: If validation fails
    """
    required_fields = ["project", "branchName", "description", "userStories"]
    for field in required_fields:
        if field not in prd:
            raise TaskSpecError(f"prd.json missing required field: {field}")
    
    if not isinstance(prd["userStories"], list):
        raise TaskSpecError("prd.json userStories must be a list")
    
    for story in prd["userStories"]:
        story_fields = ["id", "title", "acceptanceCriteria", "priority", "passes"]
        for field in story_fields:
            if field not in story:
                raise TaskSpecError(f"User story missing required field: {field}")
    
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: task_to_prd.py <task_spec.json> [output.json] [--context context.md]")
        sys.exit(1)

    task_spec_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "prd.json"
    historical_context = None

    # Parse optional arguments
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == "--context" and i + 1 < len(sys.argv):
            context_path = Path(sys.argv[i + 1])
            if context_path.exists():
                historical_context = context_path.read_text(encoding='utf-8')
            i += 2
        else:
            i += 1

    try:
        # Load and convert
        task_spec = load_task_spec_from_file(task_spec_path)
        prd = task_spec_to_prd_json(task_spec, historical_context=historical_context)

        # Validate
        validate_prd_json(prd)

        # Save
        save_prd_json(prd, output_path)

        print(f"✓ Successfully converted {task_spec_path} to {output_path}")
        print(f"  Project: {prd['project']}")
        print(f"  Branch: {prd['branchName']}")
        print(f"  User stories: {len(prd['userStories'])}")
        if historical_context:
            print(f"  Historical context: {len(historical_context)} bytes")

    except TaskSpecError as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
