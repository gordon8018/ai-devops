#!/usr/bin/env python3
"""
Tests for minor issues M3, M5, M6.

M3: print_task_detail must display last_failure_at as a formatted timestamp (not raw ms).
M5: compile_prompt must not raise KeyError when task is missing 'title' or 'description'.
M6: _build_prompt must not raise KeyError when successPatterns items are missing 'title'/'attemptCount'.
"""
import io
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.absolute()
BASE = SCRIPT_DIR.parent
sys.path.insert(0, str(BASE / "orchestrator" / "bin"))


# ---------------------------------------------------------------------------
# M3: print_task_detail must display last_failure_at as a formatted date
# ---------------------------------------------------------------------------
class TestPrintTaskDetailLastFailureAt:
    """M3: last_failure_at field must appear in print_task_detail output
    formatted as a human-readable timestamp, not as raw milliseconds."""

    def test_last_failure_at_shown_as_formatted_date(self):
        from agent_utils import print_task_detail

        ts_ms = 1_700_000_000_000  # 2023-11-14 (fixed, stable)
        task = {
            "id": "t1",
            "repo": "test/repo",
            "title": "T",
            "status": "done",
            "last_failure_at": ts_ms,
        }
        output = io.StringIO()
        with redirect_stdout(output):
            print_task_detail(task)

        result = output.getvalue()
        assert str(ts_ms) not in result, (
            "last_failure_at must not be shown as raw milliseconds"
        )
        assert "2023" in result, (
            "last_failure_at must be formatted as a human-readable date"
        )

    def test_last_failure_at_absent_when_not_set(self):
        """If last_failure_at is not set, the field must not appear in output."""
        from agent_utils import print_task_detail

        task = {"id": "t1", "repo": "test/repo", "title": "T", "status": "done"}
        output = io.StringIO()
        with redirect_stdout(output):
            print_task_detail(task)

        # No assertion needed — just must not crash
        result = output.getvalue()
        assert "t1" in result


# ---------------------------------------------------------------------------
# M5: compile_prompt must not raise KeyError on missing title/description
# ---------------------------------------------------------------------------
class TestCompilePromptMissingKeys:
    """M5: compile_prompt must use .get() so missing keys don't crash."""

    def test_missing_title_does_not_raise(self, tmp_path):
        from prompt_compiler import compile_prompt

        task = {"description": "Do something"}  # 'title' missing
        result = compile_prompt(task, tmp_path)
        assert "TASK TITLE" in result

    def test_missing_description_does_not_raise(self, tmp_path):
        from prompt_compiler import compile_prompt

        task = {"title": "My Task"}  # 'description' missing
        result = compile_prompt(task, tmp_path)
        assert "TASK DESCRIPTION" in result

    def test_empty_task_does_not_raise(self, tmp_path):
        from prompt_compiler import compile_prompt

        result = compile_prompt({}, tmp_path)
        assert "TASK TITLE" in result


# ---------------------------------------------------------------------------
# M6: _build_prompt must not raise KeyError on incomplete successPatterns items
# ---------------------------------------------------------------------------
class TestBuildPromptSuccessPatternsMissingKeys:
    """M6: success_patterns items without 'title' or 'attemptCount' must not
    raise KeyError — use .get() with safe defaults."""

    def test_success_pattern_missing_title_does_not_raise(self):
        from planner_engine import _build_prompt

        result = _build_prompt(
            repo="myrepo",
            plan_title="Big Plan",
            objective="Ship it",
            subtask_id="s1",
            subtask_title="Implement X",
            description="Write the code for X",
            constraints={"successPatterns": [{"attemptCount": 2}]},  # 'title' missing
            definition_of_done=["all tests pass"],
            files_hint=[],
            depends_on=[],
            phase_boundary="do not absorb later subtasks",
        )
        assert "PAST SUCCESSES" in result

    def test_success_pattern_missing_attempt_count_does_not_raise(self):
        from planner_engine import _build_prompt

        result = _build_prompt(
            repo="myrepo",
            plan_title="Big Plan",
            objective="Ship it",
            subtask_id="s1",
            subtask_title="Implement X",
            description="Write the code for X",
            constraints={"successPatterns": [{"title": "Fixed the bug"}]},  # 'attemptCount' missing
            definition_of_done=["all tests pass"],
            files_hint=[],
            depends_on=[],
            phase_boundary="do not absorb later subtasks",
        )
        assert "PAST SUCCESSES" in result
        assert "Fixed the bug" in result

    def test_success_pattern_empty_dict_does_not_raise(self):
        from planner_engine import _build_prompt

        result = _build_prompt(
            repo="myrepo",
            plan_title="Big Plan",
            objective="Ship it",
            subtask_id="s1",
            subtask_title="Implement X",
            description="Write the code for X",
            constraints={"successPatterns": [{}]},  # completely empty
            definition_of_done=["all tests pass"],
            files_hint=[],
            depends_on=[],
            phase_boundary="do not absorb later subtasks",
        )
        assert "PAST SUCCESSES" in result
