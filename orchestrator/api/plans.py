"""
Plans REST API

Endpoints:
- GET /api/plans - Get plan list
- GET /api/plans/{plan_id} - Get plan details (with DAG)
- POST /api/plans/{plan_id}/dispatch - Dispatch a plan
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

import sys

# 添加 bin 目录到路径以导入模块
bin_dir = Path(__file__).parent.parent / "bin"
if str(bin_dir) not in sys.path:
    sys.path.insert(0, str(bin_dir))

try:
    from plan_schema import Plan, load_plan
    from dispatch import dispatch_ready_subtasks, preflight_dispatch, default_base_dir, tasks_dir
    from db import init_db, get_all_tasks
    from dag_renderer import (
        build_dag_from_plan_and_registry,
        DAGRenderer,
    )
except ImportError:
    from orchestrator.bin.plan_schema import Plan, load_plan
    from orchestrator.bin.dispatch import (
        dispatch_ready_subtasks,
        preflight_dispatch,
        default_base_dir,
        tasks_dir,
    )
    from orchestrator.bin.db import init_db, get_all_tasks
    from orchestrator.bin.dag_renderer import (
        build_dag_from_plan_and_registry,
        DAGRenderer,
    )


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    """Generate JSON response"""
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode('utf-8'), status, 'application/json'


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    """Generate error response"""
    return _json_response({"error": message, "success": False}, status)


def _parse_path(path: str) -> tuple[str, Optional[str], Optional[str]]:
    """Parse API path to extract resource, ID, and action"""
    parts = path.strip('/').split('/')
    # Strict check: must be /api/plans
    if len(parts) >= 2 and parts[0] == 'api' and parts[1] == 'plans':
        plan_id = parts[2] if len(parts) >= 3 else None
        action = parts[3] if len(parts) >= 4 else None
        return 'plans', plan_id, action
    return '', None, None


def _get_all_plans(limit: int = 50) -> list[dict]:
    """Scan tasks directory for plan.json files"""
    base_dir = default_base_dir()
    tasks_path = tasks_dir(base_dir)
    
    if not tasks_path.exists():
        return []
    
    plans = []
    for plan_dir in sorted(tasks_path.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not plan_dir.is_dir():
            continue
        
        plan_file = plan_dir / "plan.json"
        if not plan_file.exists():
            continue
        
        try:
            plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
            # Extract summary info
            summary = {
                "planId": plan_data.get("planId"),
                "repo": plan_data.get("repo"),
                "title": plan_data.get("title"),
                "requestedBy": plan_data.get("requestedBy"),
                "requestedAt": plan_data.get("requestedAt"),
                "objective": plan_data.get("objective"),
                "subtaskCount": len(plan_data.get("subtasks", [])),
                "status": _get_plan_status(plan_dir),
            }
            plans.append(summary)
            
            if len(plans) >= limit:
                break
        except Exception:
            continue
    
    return plans


def _get_plan_status(plan_dir: Path) -> str:
    """Determine plan status from dispatch-state.json"""
    state_file = plan_dir / "dispatch-state.json"
    if not state_file.exists():
        return "pending"
    
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        dispatched = state.get("dispatched", {})
        if not dispatched:
            return "pending"
        
        # Check if all subtasks are dispatched
        total = len(dispatched)
        queued_count = sum(1 for v in dispatched.values() if v.get("state") == "queued")
        
        if queued_count == total:
            return "dispatched"
        elif queued_count > 0:
            return "partial"
        else:
            return "pending"
    except Exception:
        return "unknown"


def _build_dag(plan_data: dict, plan_dir: Path) -> dict:
    """Build DAG visualization from subtasks with status from registry"""
    try:
        # Get registry items for status
        registry_items = get_all_tasks(limit=1000)
    except Exception:
        registry_items = []
    
    # Build DAG using dag_renderer
    dag = build_dag_from_plan_and_registry(plan_data, registry_items)
    
    # Convert to dict format
    return {
        "nodes": [
            {
                "id": node.id,
                "title": node.title,
                "status": node.status.value,
                "agent": node.agent,
                "model": node.model,
            }
            for node in dag.nodes
        ],
        "edges": [
            {
                "from": edge.from_id,
                "to": edge.to_id,
            }
            for edge in dag.edges
        ],
    }




def _get_dag_response(plan_id: str, format_type: str = "json"):
    """Get DAG response in specified format"""
    base_dir = default_base_dir()
    tasks_path = tasks_dir(base_dir)
    plan_dir = tasks_path / plan_id
    plan_file = plan_dir / "plan.json"
    
    if not plan_file.exists():
        return _error_response(f"Plan not found: {plan_id}", 404)
    
    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return _error_response(f"Invalid plan JSON: {e}", 400)
    
    try:
        registry_items = get_all_tasks(limit=1000)
    except Exception:
        registry_items = []
    
    dag = build_dag_from_plan_and_registry(plan_data, registry_items)
    
    if format_type == "json" or format_type == "dag":
        renderer = DAGRenderer()
        dag_json = renderer.render_dag_json(dag)
        return _json_response({
            "success": True,
            "data": dag_json,
            "planId": plan_id,
        })
    elif format_type == "svg":
        renderer = DAGRenderer(format="svg")
        try:
            svg_content = renderer.render_dag(dag, title=plan_data.get("title"))
            if svg_content:
                return svg_content, 200, 'image/svg+xml'
            else:
                return _error_response(
                    "SVG generation requires graphviz binary. Install: apt-get install graphviz",
                    503
                )
        except RuntimeError as e:
            return _error_response(str(e), 503)
    elif format_type == "png":
        renderer = DAGRenderer(format="png")
        try:
            png_content = renderer.render_dag(dag, title=plan_data.get("title"))
            if png_content:
                return png_content, 200, 'image/png'
            else:
                return _error_response(
                    "PNG generation requires graphviz binary. Install: apt-get install graphviz",
                    503
                )
        except RuntimeError as e:
            return _error_response(str(e), 503)
    elif format_type == "dot":
        renderer = DAGRenderer()
        try:
            dot_content = renderer.render_dag_dot(dag, title=plan_data.get("title"))
            return dot_content.encode('utf-8'), 200, 'text/plain'
        except RuntimeError as e:
            return _error_response(str(e), 503)
    else:
        return _error_response(f"Unknown DAG format: {format_type}", 400)


class PlansAPIHandler:
    """Plans API request handler mixin"""
    
    def handle_get_plans(self, plan_id: Optional[str] = None):
        """Handle GET /api/plans or GET /api/plans/{plan_id}"""
        try:
            if plan_id:
                # Get single plan
                base_dir = default_base_dir()
                tasks_path = tasks_dir(base_dir)
                plan_dir = tasks_path / plan_id
                plan_file = plan_dir / "plan.json"
                
                if not plan_file.exists():
                    return _error_response(f"Plan not found: {plan_id}", 404)
                
                plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
                
                # Add DAG visualization with status from registry
                dag = _build_dag(plan_data, plan_dir)
                plan_data["dag"] = dag
                plan_data["status"] = _get_plan_status(plan_dir)
                
                return _json_response({"success": True, "data": plan_data})
            else:
                # Get all plans
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                limit = int(params.get('limit', ['50'])[0])
                
                plans = _get_all_plans(limit)
                
                return _json_response({
                    "success": True,
                    "data": plans,
                    "count": len(plans)
                })
        except Exception as e:
            return _error_response(f"Failed to get plans: {str(e)}", 500)
    
    def handle_dispatch_plan(self, plan_id: str):
        """Handle POST /api/plans/{plan_id}/dispatch"""
        try:
            if not plan_id:
                return _error_response("Plan ID is required", 400)
            
            base_dir = default_base_dir()
            tasks_path = tasks_dir(base_dir)
            plan_dir = tasks_path / plan_id
            plan_file = plan_dir / "plan.json"
            
            if not plan_file.exists():
                return _error_response(f"Plan not found: {plan_id}", 404)
            
            # Load and validate plan
            plan = load_plan(plan_file)
            
            # Preflight checks (daemon running, repo exists)
            try:
                preflight_dispatch(plan, base_dir)
            except Exception as e:
                return _error_response(f"Preflight check failed: {str(e)}", 400)
            
            # Get current registry items
            init_db()
            registry_items = get_all_tasks(limit=1000)
            
            # Dispatch ready subtasks
            queued_paths = dispatch_ready_subtasks(
                plan,
                base_dir=base_dir,
                registry_items=registry_items,
            )
            
            queued_task_ids = [p.stem for p in queued_paths]
            
            return _json_response({
                "success": True,
                "data": {
                    "planId": plan_id,
                    "queuedTasks": queued_task_ids,
                    "queuedCount": len(queued_task_ids),
                },
                "message": f"Dispatched {len(queued_task_ids)} subtasks for plan {plan_id}"
            }, 202)
        except Exception as e:
            return _error_response(f"Failed to dispatch plan: {str(e)}", 500)


def create_plans_handler(base_handler: type) -> type:
    """Factory to create a combined handler with plans API support"""
    
    class CombinedHandler(PlansAPIHandler, base_handler):
        def do_GET(self):
            # Check for DAG endpoints first
            path = self.path.split('?')[0]
            parts = path.strip('/').split('/')
            
            # Handle DAG endpoints: /api/plans/{plan_id}/dag, /api/plans/{plan_id}/dag/{format}
            if len(parts) >= 4 and parts[0] == 'api' and parts[1] == 'plans' and parts[3] == 'dag':
                plan_id = parts[2]
                format_type = parts[4] if len(parts) >= 5 else 'json'
                
                result = _get_dag_response(plan_id, format_type)
                if len(result) == 3:
                    body, status, content_type = result
                else:
                    # It's an error response tuple
                    body, status, content_type = result
                
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
                return
            
            # Handle regular plans endpoints
            resource, resource_id, action = _parse_path(self.path)
            if resource == 'plans' and action is None:
                body, status, content_type = self.handle_get_plans(resource_id)
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                # Delegate to base handler for other GETs
                super().do_GET()
        
        def do_POST(self):
            resource, resource_id, action = _parse_path(self.path)
            if resource == 'plans' and resource_id and action == 'dispatch':
                body, status, content_type = self.handle_dispatch_plan(resource_id)
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                # Delegate to base handler for other POSTs
                super().do_POST()
        
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
    
    return CombinedHandler
