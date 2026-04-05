"""
DAG Renderer - Generate DAG visualization for plans
Uses graphviz to generate DAG diagrams with status coloring.
"""
from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"

STATUS_COLORS = {
    TaskStatus.PENDING: "#B0BEC5",
    TaskStatus.RUNNING: "#42A5F5",
    TaskStatus.COMPLETED: "#66BB6A",
    TaskStatus.FAILED: "#EF5350",
    TaskStatus.BLOCKED: "#FFA726",
}

@dataclass
class DAGNode:
    id: str
    title: str
    status: TaskStatus
    agent: Optional[str] = None
    model: Optional[str] = None
    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status.value, "agent": self.agent, "model": self.model}

@dataclass
class DAGEdge:
    from_id: str
    to_id: str
    def to_dict(self) -> dict:
        return {"from": self.from_id, "to": self.to_id}

@dataclass
class DAGGraph:
    nodes: list[DAGNode]
    edges: list[DAGEdge]
    def to_dict(self) -> dict:
        return {"nodes": [n.to_dict() for n in self.nodes], "edges": [e.to_dict() for e in self.edges]}

class DAGRenderer:
    def __init__(self, format: str = "svg"):
        self.format = format

    def render_dag(self, dag: DAGGraph, title: Optional[str] = None, output_path: Optional[Path] = None) -> Optional[bytes]:
        try:
            import graphviz
        except ImportError:
            raise RuntimeError("graphviz package not installed. Install with: pip install graphviz")
        dot = graphviz.Digraph(comment=title or "DAG", format=self.format, engine="dot")
        dot.attr(rankdir="TB")
        dot.attr("node", shape="box", style="rounded,filled", fontname="Arial")
        dot.attr("edge", fontname="Arial")
        if title:
            dot.attr(label=title, labelloc="t", fontsize="16")
        for node in dag.nodes:
            color = STATUS_COLORS.get(node.status, STATUS_COLORS[TaskStatus.PENDING])
            label = f"{node.id}\\n{node.title}"
            if node.agent:
                label += f"\\n[{node.agent}]"
            dot.node(node.id, label=label, fillcolor=color, fontcolor="white" if node.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED] else "black")
        for edge in dag.edges:
            dot.edge(edge.from_id, edge.to_id)
        try:
            content = dot.pipe(format=self.format)
        except (subprocess.CalledProcessError, FileNotFoundError):
            if output_path:
                output_path.write_text(dot.source, encoding="utf-8")
            return None
        if output_path and content:
            output_path.write_bytes(content)
        return content

    def render_dag_dot(self, dag: DAGGraph, title: Optional[str] = None) -> str:
        try:
            import graphviz
        except ImportError:
            raise RuntimeError("graphviz package not installed")
        dot = graphviz.Digraph(comment=title or "DAG", format="svg", engine="dot")
        dot.attr(rankdir="TB")
        dot.attr("node", shape="box", style="rounded,filled", fontname="Arial")
        if title:
            dot.attr(label=title, labelloc="t", fontsize="16")
        for node in dag.nodes:
            color = STATUS_COLORS.get(node.status, STATUS_COLORS[TaskStatus.PENDING])
            label = f"{node.id}\\n{node.title}"
            if node.agent:
                label += f"\\n[{node.agent}]"
            dot.node(node.id, label=label, fillcolor=color, fontcolor="white" if node.status in [TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED] else "black")
        for edge in dag.edges:
            dot.edge(edge.from_id, edge.to_id)
        return dot.source

    def render_dag_json(self, dag: DAGGraph) -> dict:
        return {
            "nodes": [{"id": n.id, "title": n.title, "status": n.status.value, "agent": n.agent, "model": n.model, "color": STATUS_COLORS.get(n.status, STATUS_COLORS[TaskStatus.PENDING])} for n in dag.nodes],
            "edges": [{"from": e.from_id, "to": e.to_id} for e in dag.edges],
        }

def build_dag_from_plan(plan_data: dict, task_status_map: Optional[dict[str, str]] = None) -> DAGGraph:
    subtasks = plan_data.get("subtasks", [])
    nodes, edges = [], []
    for subtask in subtasks:
        task_id = subtask.get("id", "")
        status_str = "pending"
        if task_status_map and task_id in task_status_map:
            status_str = task_status_map[task_id].lower()
        try:
            status = TaskStatus(status_str)
        except ValueError:
            status = TaskStatus.PENDING
        node = DAGNode(id=task_id, title=subtask.get("title", ""), status=status, agent=subtask.get("agent"), model=subtask.get("model"))
        nodes.append(node)
        for dep_id in subtask.get("dependsOn", []):
            edge = DAGEdge(from_id=dep_id, to_id=task_id)
            edges.append(edge)
    return DAGGraph(nodes=nodes, edges=edges)

def build_dag_from_plan_and_registry(plan_data: dict, registry_items: list[dict]) -> DAGGraph:
    status_map = {}
    for item in registry_items:
        task_id = item.get("taskId", "")
        status = item.get("state", "pending")
        if task_id:
            status_map[task_id] = status
    return build_dag_from_plan(plan_data, status_map)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DAG Renderer")
    parser.add_argument("plan_file", type=Path, help="Path to plan.json")
    parser.add_argument("--format", default="svg", choices=["svg", "png", "pdf", "dot", "json"])
    parser.add_argument("--output", type=Path, help="Output file path")
    args = parser.parse_args()
    plan_data = json.loads(args.plan_file.read_text(encoding="utf-8"))
    dag = build_dag_from_plan(plan_data)
    if args.format == "json":
        renderer = DAGRenderer()
        result = renderer.render_dag_json(dag)
        output = json.dumps(result, indent=2)
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output)
    elif args.format == "dot":
        renderer = DAGRenderer()
        output = renderer.render_dag_dot(dag, title=plan_data.get("title"))
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output)
    else:
        renderer = DAGRenderer(format=args.format)
        content = renderer.render_dag(dag, title=plan_data.get("title"), output_path=args.output)
        if content and not args.output:
            import sys
            sys.stdout.buffer.write(content)
        elif not content:
            print(f"Warning: Could not generate {args.format.upper()}")
        else:
            print(f"Generated: {args.output}")
