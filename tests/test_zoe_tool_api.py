#!/usr/bin/env python3
"""Tests for ZoeToolAPI module"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from orchestrator.bin.zoe_tool_api import (
    build_arg_parser,
    _emit,
    _load_json_request,
    _success,
    _failure,
    _dispatch_tool_call,
    main,
)
from orchestrator.bin.errors import PlannerError, PolicyViolation


class TestBuildArgParser:
    def test_build_arg_parser_creates_parser(self):
        parser = build_arg_parser()
        assert parser is not None

    def test_parser_has_schema_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["schema"])
        assert args.command == "schema"

    def test_parser_has_invoke_command(self):
        parser = build_arg_parser()
        args = parser.parse_args(["invoke"])
        assert args.command == "invoke"

    def test_parser_schema_has_pretty_flag(self):
        parser = build_arg_parser()
        args = parser.parse_args(["schema", "--pretty"])
        assert args.pretty is True


class TestEmit:
    def test_emit_outputs_json(self, capsys):
        payload = {"test": "value", "number": 123}
        _emit(payload)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["test"] == "value"

    def test_emit_handles_unicode(self, capsys):
        payload = {"message": "测试消息"}
        _emit(payload)
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["message"] == "测试消息"


class TestLoadJsonRequest:
    def test_load_json_request_from_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({"test": "file"}, f)
            f.flush()
            result = _load_json_request(Path(f.name))
        assert result["test"] == "file"

    def test_load_json_request_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("not valid json")
            f.flush()
            with pytest.raises(PlannerError):
                _load_json_request(Path(f.name))


class TestSuccessFailure:
    def test_success_returns_dict(self):
        result = _success("test_tool", {"data": "value"})
        assert result["ok"] is True
        assert result["tool"] == "test_tool"
        assert result["governance"]["legacyCompatibility"]["status"] == "deprecated"
        assert result["governance"]["legacyCompatibility"]["preferredEntrypoint"] == "/api/work-items"

    def test_failure_returns_dict(self):
        exc = Exception("Test error")
        result = _failure("test_tool", exc, code="TEST_ERROR")
        assert result["ok"] is False
        assert result["error"]["code"] == "TEST_ERROR"

    def test_failure_with_none_tool(self):
        exc = Exception("Error")
        result = _failure(None, exc, code="ERROR")
        assert result["tool"] is None


class TestDispatchToolCall:
    def test_dispatch_unsupported_tool(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "unknown_tool", "args": {}}
            with pytest.raises(PlannerError):
                _dispatch_tool_call(payload, base_dir=base_dir)

    def test_dispatch_with_non_dict_args(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "plan_task", "args": "not a dict"}
            with pytest.raises(PlannerError):
                _dispatch_tool_call(payload, base_dir=base_dir)


class TestDispatchPlanTask:
    @patch('orchestrator.bin.zoe_tool_api.plan_task')
    def test_dispatch_plan_task(self, mock_plan_task):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"planId": "plan-123"}
        mock_plan_task.return_value = mock_result
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "plan_task", "args": {"title": "Test"}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert result["planId"] == "plan-123"


class TestDispatchTaskStatus:
    @patch('orchestrator.bin.zoe_tool_api.task_status')
    def test_dispatch_task_status(self, mock_task_status):
        mock_task_status.return_value = {"taskId": "task-123", "state": "completed"}
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "task_status", "args": {"task_id": "task-123"}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert result["taskId"] == "task-123"


class TestDispatchListPlans:
    @patch('orchestrator.bin.zoe_tool_api.list_plans')
    def test_dispatch_list_plans(self, mock_list_plans):
        mock_list_plans.return_value = {"plans": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "list_plans", "args": {"limit": 5}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert "plans" in result


class TestDispatchRetryTask:
    @patch('orchestrator.bin.zoe_tool_api.retry_task')
    def test_dispatch_retry_task(self, mock_retry_task):
        mock_retry_task.return_value = {"taskId": "task-456", "state": "pending"}
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "retry_task", "args": {"task_id": "task-456"}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert result["task"]["taskId"] == "task-456"

    def test_dispatch_retry_task_missing_task_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "retry_task", "args": {}}
            with pytest.raises(PlannerError):
                _dispatch_tool_call(payload, base_dir=base_dir)


class TestMain:
    def test_main_schema_command(self, capsys):
        with patch('sys.argv', ['zoe_tool_api', 'schema']):
            result = main()
        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "tools" in output or "functions" in output

    def test_main_schema_pretty(self, capsys):
        with patch('sys.argv', ['zoe_tool_api', 'schema', '--pretty']):
            result = main()
        assert result == 0

    @patch('orchestrator.bin.zoe_tool_api._load_json_request')
    @patch('orchestrator.bin.zoe_tool_api._dispatch_tool_call')
    def test_main_invoke_success(self, mock_dispatch, mock_load):
        mock_load.return_value = {"tool": "test", "args": {}}
        mock_dispatch.return_value = {"result": "ok"}
        with patch('sys.argv', ['zoe_tool_api', 'invoke']):
            result = main()
        assert result == 0

    @patch('orchestrator.bin.zoe_tool_api._load_json_request')
    def test_main_invoke_planner_error(self, mock_load):
        mock_load.side_effect = PlannerError("Test error")
        with patch('sys.argv', ['zoe_tool_api', 'invoke']):
            result = main()
        assert result == 1

    @patch('orchestrator.bin.zoe_tool_api._load_json_request')
    def test_main_invoke_policy_violation(self, mock_load):
        mock_load.side_effect = PolicyViolation("Policy violated")
        with patch('sys.argv', ['zoe_tool_api', 'invoke']):
            result = main()
        assert result == 3


class TestToolContracts:
    def test_tool_names_available(self):
        from orchestrator.bin.zoe_tool_contract import tool_names
        names = tool_names()
        assert isinstance(names, (list, set))
        assert "plan_task" in names

    def test_tool_contracts_payload(self):
        from orchestrator.bin.zoe_tool_contract import tool_contracts_payload
        payload = tool_contracts_payload()
        assert isinstance(payload, dict)


class TestDispatchPlanAndDispatch:
    @patch('orchestrator.bin.zoe_tool_api.plan_and_dispatch_task')
    def test_dispatch_plan_and_dispatch(self, mock_func):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"planId": "plan-789"}
        mock_func.return_value = mock_result
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "plan_and_dispatch_task", "args": {"title": "Test"}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert result["planId"] == "plan-789"


class TestDispatchDispatchPlan:
    def test_dispatch_dispatch_plan_missing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            payload = {"tool": "dispatch_plan", "args": {}}
            with pytest.raises(PlannerError):
                _dispatch_tool_call(payload, base_dir=base_dir)

    @patch('orchestrator.bin.zoe_tool_api.dispatch_plan')
    def test_dispatch_dispatch_plan_with_file(self, mock_func):
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"dispatched": 1}
        mock_func.return_value = mock_result
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            plan_file = Path(tmpdir) / "test.json"
            plan_file.write_text('{}')
            payload = {"tool": "dispatch_plan", "args": {"planFile": str(plan_file)}}
            result = _dispatch_tool_call(payload, base_dir=base_dir)
            assert result["dispatched"] == 1
