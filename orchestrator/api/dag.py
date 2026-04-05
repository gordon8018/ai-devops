"""
DAG Visualization REST API

Endpoints:
- GET /api/plans/{plan_id}/dag - Get plan DAG data
- GET /api/plans/{plan_id}/dag/svg - Get DAG SVG diagram
- GET /api/plans/{plan_id}/dag/png - Get DAG PNG diagram
- GET /api/plans/{plan_id}/dag/dot - Get DAG DOT source
- GET /api/plans/{plan_id}/dag/json - Get DAG JSON data (for frontend rendering)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs
import sys

bin_dir = Path(__file__).parent.parent / "bin"
if str(bin_dir) not in sys.path:
    sys.path.insert(0, str(bin_dir))

try:
    from plan_schema import load_plan
    from db import get_all_tasks
    from dag_renderer import (
        DAGRenderer,
        build_dag_from_plan,
        build_dag_from_plan_and_registry,
    )
    from dispatch import default_base_dir, tasks_dir
except ImportError:
    from orchestrator.bin.plan_schema import load_plan
    from orchestrator.bin.db import get_all_tasks
    from orchestrator.bin.dag_renderer import (
        DAGRenderer,
        build_dag_from_plan,
        build_dag_from_plan_and_registry,
    )
    from orchestrator.bin.dispatch import default_base_dir, tasks_dir


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode('utf-8'), status, 'application/json'


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    return _json_response({"error": message, "success": False}, status)


def _svg_response(svg_content: bytes, status: int = 200) -> tuple[bytes, int, str]:
    return svg_content, status, 'image/svg+xml'


def _png_response(png_content: bytes, status: int = 200) -> tuple[bytes, int, str]:
    return png_content, status, 'image/png'


def _text_response(text: str, status: int = 200) -> tuple[bytes, int, str]:
    return text.encode('utf-8'), status, 'text/plain'


def _load_plan_and_registry(plan_id: str):
    base_dir = default_base_dir()
    tasks_path = tasks_dir(base_dir)
    plan_dir = tasks_path / plan_id
    plan_file = plan_dir / "plan.json"
    
    if not plan_file.exists():
        return None, None, f"Plan not found: {plan_id}"
    
    try:
        plan_data = json.loads(plan_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return None, None, f"Invalid plan JSON: {e}"
    
    try:
        registry_items = get_all_tasks(limit=1000)
    except Exception:
        registry_items = []
    
    return plan_data, registry_items, None


class DAGAPIHandler:
    """DAG API request handler mixin"""
    
    def handle_get_dag(self, plan_id: str):
        """Handle GET /api/plans/{plan_id}/dag - Get DAG data (default: JSON)"""
        plan_data, registry_items, error = _load_plan_and_registry(plan_id)
        if error:
            return _error_response(error, 404)
        
        dag = build_dag_from_plan_and_registry(plan_data, registry_items)
        renderer = DAGRenderer()
        dag_json = renderer.render_dag_json(dag)
        
        return _json_response({
            "success": True,
            "data": dag_json,
            "planId": plan_id,
        })
    
    def handle_get_dag_svg(self, plan_id: str):
        """Handle GET /api/plans/{plan_id}/dag/svg - Get DAG SVG diagram"""
        plan_data, registry_items, error = _load_plan_and_registry(plan_id)
        if error:
            return _error_response(error, 404)
        
        dag = build_dag_from_plan_and_registry(plan_data, registry_items)
        renderer = DAGRenderer(format="svg")
        
        try:
            svg_content = renderer.render_dag(dag, title=plan_data.get("title"))
            if svg_content:
                return _svg_response(svg_content)
            else:
                # Fallback to DOT if graphviz binary not available
                dot_content = renderer.render_dag_dot(dag, title=plan_data.get("title"))
                return _error_response(
                    "SVG generation requires graphviz binary (dot command). Install with: apt-get install graphviz",
                    503
                )
        except RuntimeError as e:
            return _error_response(str(e), 503)
    
    def handle_get_dag_png(self, plan_id: str):
        """Handle GET /api/plans/{plan_id}/dag/png - Get DAG PNG diagram"""
        plan_data, registry_items, error = _load_plan_and_registry(plan_id)
        if error:
            return _error_response(error, 404)
        
        dag = build_dag_from_plan_and_registry(plan_data, registry_items)
        renderer = DAGRenderer(format="png")
        
        try:
            png_content = renderer.render_dag(dag, title=plan_data.get("title"))
            if png_content:
                return _png_response(png_content)
            else:
                return _error_response(
                    "PNG generation requires graphviz binary (dot command). Install with: apt-get install graphviz",
                    503
                )
        except RuntimeError as e:
            return _error_response(str(e), 503)
    
    def handle_get_dag_dot(self, plan_id: str):
        """Handle GET /api/plans/{plan_id}/dag/dot - Get DAG DOT source"""
        plan_data, registry_items, error = _load_plan_and_registry(plan_id)
        if error:
            return _error_response(error, 404)
        
        dag = build_dag_from_plan_and_registry(plan_data, registry_items)
        renderer = DAGRenderer()
        
        try:
            dot_content = renderer.render_dag_dot(dag, title=plan_data.get("title"))
            return _text_response(dot_content)
        except RuntimeError as e:
            return _error_response(str(e), 503)
    
    def handle_get_dag_json(self, plan_id: str):
        """Handle GET /api/plans/{plan_id}/dag/json - Get DAG JSON data"""
        plan_data, registry_items, error = _load_plan_and_registry(plan_id)
        if error:
            return _error_response(error, 404)
        
        dag = build_dag_from_plan_and_registry(plan_data, registry_items)
        renderer = DAGRenderer()
        dag_json = renderer.render_dag_json(dag)
        
        return _json_response({
            "success": True,
            "data": dag_json,
            "planId": plan_id,
        })


def create_dag_handler(base_handler: type) -> type:
    """Factory to create a combined handler with DAG API support"""
    
    class CombinedHandler(DAGAPIHandler, base_handler):
        def do_GET(self):
            path = self.path.split('?')[0]
            parts = path.strip('/').split('/')
            
            # Check for DAG endpoints
            if len(parts) >= 4 and parts[0] == 'api' and parts[1] == 'plans' and parts[3] == 'dag':
                plan_id = parts[2]
                
                if len(parts) == 4:
                    # GET /api/plans/{plan_id}/dag
                    body, status, content_type = self.handle_get_dag(plan_id)
                elif len(parts) == 5:
                    format_type = parts[4]
                    if format_type == 'svg':
                        body, status, content_type = self.handle_get_dag_svg(plan_id)
                    elif format_type == 'png':
                        body, status, content_type = self.handle_get_dag_png(plan_id)
                    elif format_type == 'dot':
                        body, status, content_type = self.handle_get_dag_dot(plan_id)
                    elif format_type == 'json':
                        body, status, content_type = self.handle_get_dag_json(plan_id)
                    else:
                        body, status, content_type = _error_response(f"Unknown DAG format: {format_type}", 400)
                else:
                    body, status, content_type = _error_response("Invalid DAG endpoint", 400)
                
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
                return
            
            # Delegate to base handler for other GETs
            super().do_GET()
    
    return CombinedHandler
