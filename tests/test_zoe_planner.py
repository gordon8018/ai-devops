#!/usr/bin/env python3
"""Tests for ZoePlanner module"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from orchestrator.bin.zoe_planner import (
    build_arg_parser,
    emit_json,
    main,
)


class TestBuildArgParser:
    def test_build_arg_parser_creates_parser(self):
        parser = build_arg_parser()
        assert parser is not None

    def test_parser_has_plan_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["plan", "--task-file", "/tmp/task.json"])
        assert args.command == "plan"

    def test_parser_has_dispatch_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["dispatch", "--plan-file", "/tmp/plan.json"])
        assert args.command == "dispatch"

    def test_parser_has_status_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_parser_has_list_plans_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["list-plans"])
        assert args.command == "list-plans"

    def test_parser_plan_requires_task_file(self):
        parser = build_arg_parser()
        args = parser.parse_args(["plan", "--task-file", "/tmp/task.json"])
        assert args.task_file == Path("/tmp/task.json")

    def test_parser_dispatch_requires_plan_file(self):
        parser = build_arg_parser()
        args = parser.parse_args(["dispatch", "--plan-file", "/tmp/plan.json"])
        assert args.plan_file == Path("/tmp/plan.json")

    def test_parser_dispatch_has_watch_flag(self):
        parser = build_arg_parser()
        args = parser.parse_args(["dispatch", "--plan-file", "/tmp/plan.json", "--watch"])
        assert args.watch is True

    def test_parser_status_with_task_id(self):
        parser = build_arg_parser()
        args = parser.parse_args(["status", "--task-id", "task-123"])
        assert args.task_id == "task-123"

    def test_parser_status_with_plan_id(self):
        parser = build_arg_parser()
        args = parser.parse_args(["status", "--plan-id", "plan-456"])
        assert args.plan_id == "plan-456"


class TestEmitJson:
    def test_emit_json_outputs_json(self, capsys):
        payload = {"test": "value", "number": 123}
        emit_json(payload)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["test"] == "value"

    def test_emit_json_handles_unicode(self, capsys):
        payload = {"message": "测试消息"}
        emit_json(payload)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["message"] == "测试消息"

    def test_emit_json_handles_nested_dict(self, capsys):
        payload = {"level1": {"level2": {"level3": "value"}}}
        emit_json(payload)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["level1"]["level2"]["level3"] == "value"


class TestMainPlan:
    @patch('orchestrator.bin.zoe_planner.read_json_file')
    @patch('orchestrator.bin.zoe_planner.plan_task')
    def test_main_plan_success(self, mock_plan, mock_read):
        mock_read.return_value = {"title": "Test Task"}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"planId": "plan-123"}
        mock_plan.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "task.json"
            task_file.write_text(json.dumps({"title": "Test"}))
            
            with patch('sys.argv', ['zoe_planner', 'plan', '--task-file', str(task_file)]):
                result = main()
        
        assert result == 0

    @patch('orchestrator.bin.zoe_planner.read_json_file')
    @patch('orchestrator.bin.zoe_planner.plan_task')
    def test_main_plan_emits_legacy_deprecation_notice(self, mock_plan, mock_read, capsys):
        mock_read.return_value = {"title": "Test Task"}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"planId": "plan-123"}
        mock_plan.return_value = mock_result

        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "task.json"
            task_file.write_text(json.dumps({"title": "Test"}))

            with patch('sys.argv', ['zoe_planner', 'plan', '--task-file', str(task_file)]):
                result = main()

        captured = capsys.readouterr()
        assert result == 0
        assert "DEPRECATED" in captured.err

    @patch('orchestrator.bin.zoe_planner.read_json_file')
    @patch('orchestrator.bin.zoe_planner.plan_task')
    def test_main_plan_with_policy_violation(self, mock_plan, mock_read):
        from orchestrator.bin.errors import PolicyViolation
        mock_read.return_value = {"title": "Test"}
        mock_plan.side_effect = PolicyViolation("Policy violated")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "task.json"
            task_file.write_text(json.dumps({"title": "Test"}))
            
            with patch('sys.argv', ['zoe_planner', 'plan', '--task-file', str(task_file)]):
                result = main()
        
        assert result == 3

    @patch('orchestrator.bin.zoe_planner.read_json_file')
    @patch('orchestrator.bin.zoe_planner.plan_task')
    def test_main_plan_with_planner_error(self, mock_plan, mock_read):
        from orchestrator.bin.errors import PlannerError
        mock_read.return_value = {"title": "Test"}
        mock_plan.side_effect = PlannerError("Planning failed")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "task.json"
            task_file.write_text(json.dumps({"title": "Test"}))
            
            with patch('sys.argv', ['zoe_planner', 'plan', '--task-file', str(task_file)]):
                result = main()
        
        assert result == 1


class TestMainDispatch:
    @patch('orchestrator.bin.zoe_planner.dispatch_plan')
    def test_main_dispatch_success(self, mock_dispatch):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"dispatched": 1}
        mock_dispatch.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "plan.json"
            plan_file.write_text(json.dumps({"planId": "plan-123"}))
            
            with patch('sys.argv', ['zoe_planner', 'dispatch', '--plan-file', str(plan_file)]):
                result = main()
        
        assert result == 0

    @patch('orchestrator.bin.zoe_planner.dispatch_plan')
    def test_main_dispatch_with_watch(self, mock_dispatch):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"dispatched": 1}
        mock_dispatch.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            plan_file = Path(tmpdir) / "plan.json"
            plan_file.write_text(json.dumps({"planId": "plan-123"}))
            
            with patch('sys.argv', ['zoe_planner', 'dispatch', '--plan-file', str(plan_file), '--watch']):
                result = main()
        
        assert result == 0


class TestMainPlanAndDispatch:
    @patch('orchestrator.bin.zoe_planner.read_json_file')
    @patch('orchestrator.bin.zoe_planner.plan_and_dispatch_task')
    def test_main_plan_and_dispatch_success(self, mock_func, mock_read):
        mock_read.return_value = {"title": "Test Task"}
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"planId": "plan-789", "dispatched": 2}
        mock_func.return_value = mock_result
        
        with tempfile.TemporaryDirectory() as tmpdir:
            task_file = Path(tmpdir) / "task.json"
            task_file.write_text(json.dumps({"title": "Test"}))
            
            with patch('sys.argv', ['zoe_planner', 'plan-and-dispatch', '--task-file', str(task_file)]):
                result = main()
        
        assert result == 0


class TestMainStatus:
    @patch('orchestrator.bin.zoe_planner.task_status')
    def test_main_status_with_task_id(self, mock_status):
        mock_status.return_value = {"taskId": "task-123", "state": "completed"}
        
        with patch('sys.argv', ['zoe_planner', 'status', '--task-id', 'task-123']):
            result = main()
        
        assert result == 0

    @patch('orchestrator.bin.zoe_planner.task_status')
    def test_main_status_with_plan_id(self, mock_status):
        mock_status.return_value = {"planId": "plan-456", "subtasks": []}
        
        with patch('sys.argv', ['zoe_planner', 'status', '--plan-id', 'plan-456']):
            result = main()
        
        assert result == 0


class TestMainListPlans:
    @patch('orchestrator.bin.zoe_planner.list_plans')
    def test_main_list_plans_default_limit(self, mock_list):
        mock_list.return_value = {"plans": []}
        
        with patch('sys.argv', ['zoe_planner', 'list-plans']):
            result = main()
        
        assert result == 0

    @patch('orchestrator.bin.zoe_planner.list_plans')
    def test_main_list_plans_with_limit(self, mock_list):
        mock_list.return_value = {"plans": []}
        
        with patch('sys.argv', ['zoe_planner', 'list-plans', '--limit', '5']):
            result = main()
        
        assert result == 0
