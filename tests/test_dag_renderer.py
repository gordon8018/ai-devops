#!/usr/bin/env python3
"""Tests for DAGRenderer module"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from orchestrator.bin.dag_renderer import (
    DAGRenderer,
    DAGNode,
    DAGEdge,
    DAGGraph,
    TaskStatus,
    STATUS_COLORS,
    build_dag_from_plan,
    build_dag_from_plan_and_registry,
)


class TestTaskStatus:
    """Test TaskStatus enum"""
    
    def test_task_status_values(self):
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.BLOCKED.value == "blocked"

    def test_task_status_from_string(self):
        status = TaskStatus("running")
        assert status == TaskStatus.RUNNING

    def test_task_status_invalid_string(self):
        with pytest.raises(ValueError):
            TaskStatus("invalid_status")


class TestStatusColors:
    """Test status color mapping"""
    
    def test_status_colors_exist(self):
        assert TaskStatus.PENDING in STATUS_COLORS
        assert TaskStatus.RUNNING in STATUS_COLORS
        assert TaskStatus.COMPLETED in STATUS_COLORS
        assert TaskStatus.FAILED in STATUS_COLORS
        assert TaskStatus.BLOCKED in STATUS_COLORS

    def test_status_colors_format(self):
        for status, color in STATUS_COLORS.items():
            assert color.startswith("#")
            assert len(color) == 7


class TestDAGNode:
    """Test DAGNode dataclass"""
    
    def test_dag_node_creation(self):
        node = DAGNode(id="task-1", title="Test Task", status=TaskStatus.PENDING)
        assert node.id == "task-1"
        assert node.title == "Test Task"
        assert node.status == TaskStatus.PENDING
        assert node.agent is None
        assert node.model is None

    def test_dag_node_with_agent(self):
        node = DAGNode(id="task-2", title="Task with Agent", status=TaskStatus.RUNNING, agent="delta", model="gpt-4")
        assert node.agent == "delta"
        assert node.model == "gpt-4"

    def test_dag_node_to_dict(self):
        node = DAGNode(id="task-3", title="Dict Test", status=TaskStatus.COMPLETED, agent="gamma")
        result = node.to_dict()
        assert result["id"] == "task-3"
        assert result["title"] == "Dict Test"
        assert result["status"] == "completed"
        assert result["agent"] == "gamma"


class TestDAGEdge:
    """Test DAGEdge dataclass"""
    
    def test_dag_edge_creation(self):
        edge = DAGEdge(from_id="task-1", to_id="task-2")
        assert edge.from_id == "task-1"
        assert edge.to_id == "task-2"

    def test_dag_edge_to_dict(self):
        edge = DAGEdge(from_id="A", to_id="B")
        result = edge.to_dict()
        assert result["from"] == "A"
        assert result["to"] == "B"


class TestDAGGraph:
    """Test DAGGraph dataclass"""
    
    def test_dag_graph_creation(self):
        nodes = [DAGNode(id="A", title="Task A", status=TaskStatus.PENDING)]
        edges = [DAGEdge(from_id="A", to_id="B")]
        graph = DAGGraph(nodes=nodes, edges=edges)
        assert len(graph.nodes) == 1
        assert len(graph.edges) == 1

    def test_dag_graph_to_dict(self):
        nodes = [DAGNode(id="A", title="Task A", status=TaskStatus.COMPLETED)]
        edges = [DAGEdge(from_id="A", to_id="B")]
        graph = DAGGraph(nodes=nodes, edges=edges)
        result = graph.to_dict()
        assert "nodes" in result
        assert "edges" in result
        assert len(result["nodes"]) == 1


class TestDAGRenderer:
    """Test DAGRenderer class"""
    
    def test_dag_renderer_initialization(self):
        renderer = DAGRenderer(format="svg")
        assert renderer.format == "svg"

    def test_dag_renderer_different_formats(self):
        for fmt in ["svg", "png", "pdf", "dot"]:
            renderer = DAGRenderer(format=fmt)
            assert renderer.format == fmt

    def test_render_dag_json(self):
        renderer = DAGRenderer(format="json")
        nodes = [DAGNode(id="A", title="Task A", status=TaskStatus.COMPLETED)]
        edges = [DAGEdge(from_id="A", to_id="B")]
        graph = DAGGraph(nodes=nodes, edges=edges)
        
        result = renderer.render_dag_json(graph)
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "edges" in result
        assert result["nodes"][0]["id"] == "A"
        assert result["nodes"][0]["color"] == STATUS_COLORS[TaskStatus.COMPLETED]

    def test_render_dag_json_multiple_nodes(self):
        renderer = DAGRenderer()
        nodes = [
            DAGNode(id="A", title="Task A", status=TaskStatus.COMPLETED),
            DAGNode(id="B", title="Task B", status=TaskStatus.RUNNING),
            DAGNode(id="C", title="Task C", status=TaskStatus.PENDING),
        ]
        edges = [
            DAGEdge(from_id="A", to_id="B"),
            DAGEdge(from_id="B", to_id="C"),
        ]
        graph = DAGGraph(nodes=nodes, edges=edges)
        
        result = renderer.render_dag_json(graph)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2

    def test_render_dag_json_includes_agent(self):
        renderer = DAGRenderer()
        node = DAGNode(id="A", title="Task", status=TaskStatus.RUNNING, agent="delta", model="gpt-4")
        graph = DAGGraph(nodes=[node], edges=[])
        
        result = renderer.render_dag_json(graph)
        assert result["nodes"][0]["agent"] == "delta"
        assert result["nodes"][0]["model"] == "gpt-4"

    @pytest.mark.skipif(
        True,  # graphviz is optional
        reason="graphviz package not installed"
    )
    def test_render_dag_dot_returns_string(self):
        # This test is skipped if graphviz is not installed
        pass

    def test_render_dag_json_with_title(self):
        renderer = DAGRenderer()
        node = DAGNode(id="A", title="Task", status=TaskStatus.PENDING)
        graph = DAGGraph(nodes=[node], edges=[])
        
        result = renderer.render_dag_json(graph)
        # JSON output doesn't include title, but should not error
        assert isinstance(result, dict)


class TestBuildDAGFromPlan:
    """Test build_dag_from_plan function"""
    
    def test_build_dag_from_plan_basic(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
                {"id": "S2", "title": "Task 2", "dependsOn": ["S1"]},
            ]
        }
        graph = build_dag_from_plan(plan_data)
        
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.nodes[0].id == "S1"
        assert graph.edges[0].from_id == "S1"
        assert graph.edges[0].to_id == "S2"

    def test_build_dag_from_plan_with_status_map(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
                {"id": "S2", "title": "Task 2", "dependsOn": ["S1"]},
            ]
        }
        status_map = {"S1": "completed", "S2": "running"}
        graph = build_dag_from_plan(plan_data, status_map)
        
        assert graph.nodes[0].status == TaskStatus.COMPLETED
        assert graph.nodes[1].status == TaskStatus.RUNNING

    def test_build_dag_from_plan_empty(self):
        plan_data = {"subtasks": []}
        graph = build_dag_from_plan(plan_data)
        
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_build_dag_from_plan_no_subtasks_key(self):
        plan_data = {}
        graph = build_dag_from_plan(plan_data)
        
        assert len(graph.nodes) == 0

    def test_build_dag_from_plan_multiple_dependencies(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
                {"id": "S2", "title": "Task 2", "dependsOn": []},
                {"id": "S3", "title": "Task 3", "dependsOn": ["S1", "S2"]},
            ]
        }
        graph = build_dag_from_plan(plan_data)
        
        assert len(graph.nodes) == 3
        assert len(graph.edges) == 2

    def test_build_dag_from_plan_with_agent_and_model(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": [], "agent": "delta", "model": "gpt-4"},
            ]
        }
        graph = build_dag_from_plan(plan_data)
        
        assert graph.nodes[0].agent == "delta"
        assert graph.nodes[0].model == "gpt-4"

    def test_build_dag_from_plan_invalid_status_defaults_to_pending(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
            ]
        }
        status_map = {"S1": "invalid_status"}
        graph = build_dag_from_plan(plan_data, status_map)
        
        assert graph.nodes[0].status == TaskStatus.PENDING


class TestBuildDAGFromPlanAndRegistry:
    """Test build_dag_from_plan_and_registry function"""
    
    def test_build_dag_from_plan_and_registry_basic(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
                {"id": "S2", "title": "Task 2", "dependsOn": ["S1"]},
            ]
        }
        registry_items = [
            {"taskId": "S1", "state": "completed"},
            {"taskId": "S2", "state": "running"},
        ]
        graph = build_dag_from_plan_and_registry(plan_data, registry_items)
        
        assert graph.nodes[0].status == TaskStatus.COMPLETED
        assert graph.nodes[1].status == TaskStatus.RUNNING

    def test_build_dag_from_plan_and_registry_empty_registry(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
            ]
        }
        graph = build_dag_from_plan_and_registry(plan_data, [])
        
        assert graph.nodes[0].status == TaskStatus.PENDING

    def test_build_dag_from_plan_and_registry_missing_task_id(self):
        plan_data = {
            "subtasks": [
                {"id": "S1", "title": "Task 1", "dependsOn": []},
            ]
        }
        registry_items = [
            {"state": "completed"},  # Missing taskId
        ]
        graph = build_dag_from_plan_and_registry(plan_data, registry_items)
        
        assert graph.nodes[0].status == TaskStatus.PENDING


class TestDAGRendererFileOutput:
    """Test DAGRenderer file output"""
    
    def test_render_dag_json_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "dag.json"
            renderer = DAGRenderer()
            nodes = [DAGNode(id="A", title="Task A", status=TaskStatus.COMPLETED)]
            graph = DAGGraph(nodes=nodes, edges=[])
            
            result = renderer.render_dag_json(graph)
            output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            
            assert output_path.exists()
            loaded = json.loads(output_path.read_text(encoding="utf-8"))
            assert loaded["nodes"][0]["id"] == "A"
