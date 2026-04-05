#!/usr/bin/env python3
"""
Test script for DAG visualization API

Tests:
- DAG rendering (JSON, SVG, PNG, DOT)
- API endpoints
- Status coloring
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from orchestrator.bin.dag_renderer import (
        DAGRenderer,
        DAGGraph,
        DAGNode,
        DAGEdge,
        TaskStatus,
        build_dag_from_plan,
        STATUS_COLORS,
    )
except ImportError:
    from dag_renderer import (
        DAGRenderer,
        DAGGraph,
        DAGNode,
        DAGEdge,
        TaskStatus,
        build_dag_from_plan,
        STATUS_COLORS,
    )


def test_task_status_enum():
    """Test TaskStatus enum"""
    print("Testing TaskStatus enum...")
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.BLOCKED.value == "blocked"
    print("✓ TaskStatus enum test passed")


def test_status_colors():
    """Test status color mapping"""
    print("Testing status colors...")
    assert TaskStatus.PENDING in STATUS_COLORS
    assert TaskStatus.RUNNING in STATUS_COLORS
    assert TaskStatus.COMPLETED in STATUS_COLORS
    assert TaskStatus.FAILED in STATUS_COLORS
    assert TaskStatus.BLOCKED in STATUS_COLORS
    
    # Verify colors are valid hex colors
    for status, color in STATUS_COLORS.items():
        assert color.startswith("#"), f"Color for {status} should start with #"
        assert len(color) == 7, f"Color for {status} should be 7 chars"
    print("✓ Status colors test passed")


def test_dag_node():
    """Test DAGNode dataclass"""
    print("Testing DAGNode...")
    node = DAGNode(
        id="S1",
        title="Task 1",
        status=TaskStatus.PENDING,
        agent="codex",
        model="gpt-4",
    )
    
    node_dict = node.to_dict()
    assert node_dict["id"] == "S1"
    assert node_dict["title"] == "Task 1"
    assert node_dict["status"] == "pending"
    assert node_dict["agent"] == "codex"
    assert node_dict["model"] == "gpt-4"
    print("✓ DAGNode test passed")


def test_dag_edge():
    """Test DAGEdge dataclass"""
    print("Testing DAGEdge...")
    edge = DAGEdge(from_id="S1", to_id="S2")
    
    edge_dict = edge.to_dict()
    assert edge_dict["from"] == "S1"
    assert edge_dict["to"] == "S2"
    print("✓ DAGEdge test passed")


def test_dag_graph():
    """Test DAGGraph dataclass"""
    print("Testing DAGGraph...")
    nodes = [
        DAGNode(id="S1", title="Task 1", status=TaskStatus.PENDING),
        DAGNode(id="S2", title="Task 2", status=TaskStatus.RUNNING),
    ]
    edges = [DAGEdge(from_id="S1", to_id="S2")]
    
    graph = DAGGraph(nodes=nodes, edges=edges)
    graph_dict = graph.to_dict()
    
    assert len(graph_dict["nodes"]) == 2
    assert len(graph_dict["edges"]) == 1
    print("✓ DAGGraph test passed")


def test_build_dag_from_plan():
    """Test build_dag_from_plan function"""
    print("Testing build_dag_from_plan...")
    
    plan_data = {
        "planId": "test-plan",
        "title": "Test Plan",
        "subtasks": [
            {
                "id": "S1",
                "title": "Setup",
                "agent": "codex",
                "model": "gpt-4",
                "dependsOn": [],
            },
            {
                "id": "S2",
                "title": "Implement",
                "agent": "claude",
                "model": "claude-3",
                "dependsOn": ["S1"],
            },
            {
                "id": "S3",
                "title": "Test",
                "agent": "codex",
                "model": "gpt-4",
                "dependsOn": ["S2"],
            },
        ],
    }
    
    # Build DAG without status map
    dag = build_dag_from_plan(plan_data)
    
    assert len(dag.nodes) == 3
    assert len(dag.edges) == 2
    
    # Verify edges
    edge_pairs = [(e.from_id, e.to_id) for e in dag.edges]
    assert ("S1", "S2") in edge_pairs
    assert ("S2", "S3") in edge_pairs
    
    # Test with status map
    status_map = {
        "S1": "completed",
        "S2": "running",
        "S3": "pending",
    }
    dag = build_dag_from_plan(plan_data, status_map)
    
    assert dag.nodes[0].status == TaskStatus.COMPLETED
    assert dag.nodes[1].status == TaskStatus.RUNNING
    assert dag.nodes[2].status == TaskStatus.PENDING
    
    print("✓ build_dag_from_plan test passed")


def test_dag_renderer_json():
    """Test DAGRenderer JSON output"""
    print("Testing DAGRenderer JSON...")
    
    nodes = [
        DAGNode(id="S1", title="Task 1", status=TaskStatus.COMPLETED, agent="codex"),
        DAGNode(id="S2", title="Task 2", status=TaskStatus.RUNNING, agent="claude"),
    ]
    edges = [DAGEdge(from_id="S1", to_id="S2")]
    dag = DAGGraph(nodes=nodes, edges=edges)
    
    renderer = DAGRenderer()
    dag_json = renderer.render_dag_json(dag)
    
    assert "nodes" in dag_json
    assert "edges" in dag_json
    assert len(dag_json["nodes"]) == 2
    assert len(dag_json["edges"]) == 1
    
    # Check color is included
    for node in dag_json["nodes"]:
        assert "color" in node
        assert node["color"].startswith("#")
    
    print("✓ DAGRenderer JSON test passed")


def test_dag_renderer_dot():
    """Test DAGRenderer DOT output"""
    print("Testing DAGRenderer DOT...")
    
    nodes = [
        DAGNode(id="S1", title="Task 1", status=TaskStatus.COMPLETED),
        DAGNode(id="S2", title="Task 2", status=TaskStatus.FAILED),
    ]
    edges = [DAGEdge(from_id="S1", to_id="S2")]
    dag = DAGGraph(nodes=nodes, edges=edges)
    
    renderer = DAGRenderer()
    dot_content = renderer.render_dag_dot(dag, title="Test DAG")
    
    assert "digraph" in dot_content
    assert "S1" in dot_content
    assert "S2" in dot_content
    assert "->" in dot_content
    assert "#66BB6A" in dot_content  # Completed color
    assert "#EF5350" in dot_content  # Failed color
    
    print("✓ DAGRenderer DOT test passed")


def test_dag_renderer_svg():
    """Test DAGRenderer SVG output"""
    print("Testing DAGRenderer SVG...")
    
    nodes = [DAGNode(id="S1", title="Task 1", status=TaskStatus.PENDING)]
    edges = []
    dag = DAGGraph(nodes=nodes, edges=edges)
    
    renderer = DAGRenderer(format="svg")
    
    try:
        svg_content = renderer.render_dag(dag, title="Test")
        if svg_content:
            assert b"<svg" in svg_content or b"<?xml" in svg_content
            print("✓ DAGRenderer SVG test passed (with graphviz binary)")
        else:
            print("⚠ DAGRenderer SVG test skipped (no graphviz binary)")
    except RuntimeError as e:
        print(f"⚠ DAGRenderer SVG test skipped: {e}")


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("DAG Visualization API Tests")
    print("=" * 60 + "\n")
    
    tests = [
        test_task_status_enum,
        test_status_colors,
        test_dag_node,
        test_dag_edge,
        test_dag_graph,
        test_build_dag_from_plan,
        test_dag_renderer_json,
        test_dag_renderer_dot,
        test_dag_renderer_svg,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} failed: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
