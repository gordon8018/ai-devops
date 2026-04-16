"""
Tasks REST API

Endpoints:
- GET /api/tasks - Get task list
- GET /api/tasks/{task_id} - Get task details
- POST /api/tasks - Create new task
- DELETE /api/tasks/{task_id} - Delete task
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, parse_qs

import sys

# 添加 bin 目录到路径以导入 db 模块
bin_dir = Path(__file__).parent.parent / "bin"
if str(bin_dir) not in sys.path:
    sys.path.insert(0, str(bin_dir))

try:
    from db import (
        init_db,
        get_task,
        get_all_tasks,
        insert_task,
        delete_task,
        update_task,
    )
except ImportError:
    from orchestrator.bin.db import (
        init_db,
        get_task,
        get_all_tasks,
        insert_task,
        delete_task,
        update_task,
    )


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    """Generate JSON response"""
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode('utf-8'), status, 'application/json'


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    """Generate error response"""
    return _json_response({"error": message, "success": False}, status)


def _parse_path(path: str) -> tuple[str, Optional[str]]:
    """Parse API path to extract resource and ID"""
    parts = path.split('?', 1)[0].strip('/').split('/')
    # Strict check: must be /api/tasks
    if len(parts) >= 2 and parts[0] == 'api' and parts[1] == 'tasks':
        task_id = parts[2] if len(parts) >= 3 else None
        return 'tasks', task_id
    return '', None


class TasksAPIHandler:
    """Tasks API request handler mixin"""
    
    def handle_get_tasks(self, task_id: Optional[str] = None):
        """Handle GET /api/tasks or GET /api/tasks/{task_id}"""
        try:
            init_db()
            
            if task_id:
                # Get single task
                task = get_task(task_id)
                if not task:
                    return _error_response(f"Task not found: {task_id}", 404)
                
                # Convert sqlite3.Row to dict and clean up
                result = dict(task) if hasattr(task, 'keys') else task
                return _json_response({"success": True, "data": result})
            else:
                # Get all tasks with optional limit
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                limit = int(params.get('limit', ['50'])[0])
                
                tasks = get_all_tasks(limit)
                
                # Convert to list of dicts
                result = [dict(t) if hasattr(t, 'keys') else t for t in tasks]
                return _json_response({
                    "success": True,
                    "data": result,
                    "count": len(result)
                })
        except Exception as e:
            return _error_response(f"Failed to get tasks: {str(e)}", 500)
    
    def handle_post_tasks(self):
        """Handle POST /api/tasks"""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return _error_response("Request body is required", 400)
            
            body = self.rfile.read(content_length)
            task_data = json.loads(body.decode('utf-8'))
            
            # Validate required fields
            if 'id' not in task_data:
                return _error_response("Field 'id' is required", 400)
            if 'repo' not in task_data:
                return _error_response("Field 'repo' is required", 400)
            
            # Set defaults
            task_data.setdefault('title', '')
            task_data.setdefault('status', 'queued')
            task_data.setdefault('agent', 'codex')
            task_data.setdefault('model', 'gpt-5.3-codex')
            task_data.setdefault('effort', 'medium')
            task_data.setdefault('attempts', 0)
            task_data.setdefault('maxAttempts', 3)
            task_data.setdefault('created_at', int(time.time() * 1000))
            
            # Initialize DB and insert
            init_db()
            insert_task(task_data)
            
            return _json_response({
                "success": True,
                "data": {"id": task_data['id']},
                "message": f"Task {task_data['id']} created"
            }, 201)
        except json.JSONDecodeError:
            return _error_response("Invalid JSON", 400)
        except Exception as e:
            return _error_response(f"Failed to create task: {str(e)}", 500)
    
    def handle_delete_tasks(self, task_id: str):
        """Handle DELETE /api/tasks/{task_id}"""
        try:
            if not task_id:
                return _error_response("Task ID is required", 400)
            
            init_db()
            
            # Check if task exists
            task = get_task(task_id)
            if not task:
                return _error_response(f"Task not found: {task_id}", 404)
            
            delete_task(task_id)
            
            return _json_response({
                "success": True,
                "message": f"Task {task_id} deleted"
            })
        except Exception as e:
            return _error_response(f"Failed to delete task: {str(e)}", 500)


def create_tasks_handler(base_handler: type) -> type:
    """Factory to create a combined handler with tasks API support"""
    
    class CombinedHandler(TasksAPIHandler, base_handler):
        def do_GET(self):
            resource, resource_id = _parse_path(self.path)
            if resource == 'tasks':
                body, status, content_type = self.handle_get_tasks(resource_id)
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()
        
        def do_POST(self):
            resource, resource_id = _parse_path(self.path)
            if resource == 'tasks' and not resource_id:
                body, status, content_type = self.handle_post_tasks()
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                # Delegate to base handler for other POSTs
                super().do_POST()
        
        def do_DELETE(self):
            resource, resource_id = _parse_path(self.path)
            if resource == 'tasks' and resource_id:
                body, status, content_type = self.handle_delete_tasks(resource_id)
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_DELETE()
        
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
    
    return CombinedHandler
