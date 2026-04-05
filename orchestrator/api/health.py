"""
Health REST API

Endpoints:
- GET /api/health - System health status
- GET /api/health/services - Service status details
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import sys

# 添加 bin 目录到路径以导入模块
bin_dir = Path(__file__).parent.parent / "bin"
if str(bin_dir) not in sys.path:
    sys.path.insert(0, str(bin_dir))

try:
    from db import init_db, count_running_tasks, get_all_tasks
    from config import ai_devops_home
except ImportError:
    from orchestrator.bin.db import init_db, count_running_tasks, get_all_tasks
    from orchestrator.bin.config import ai_devops_home


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    """Generate JSON response"""
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode('utf-8'), status, 'application/json'


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    """Generate error response"""
    return _json_response({"error": message, "success": False}, status)


def _check_daemon_running() -> bool:
    """Check if zoe-daemon.py is running"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "orchestrator/bin/zoe-daemon.py"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_db_healthy() -> dict:
    """Check database health"""
    try:
        init_db()
        running_count = count_running_tasks()
        return {
            "status": "healthy",
            "runningTasks": running_count,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


def _check_queue_healthy() -> dict:
    """Check queue directory health"""
    try:
        base_dir = ai_devops_home()
        queue_dir = base_dir / "orchestrator" / "queue"
        
        if not queue_dir.exists():
            return {
                "status": "healthy",
                "queuedTasks": 0,
                "message": "Queue directory not created yet",
            }
        
        queued_files = list(queue_dir.glob("*.json"))
        return {
            "status": "healthy",
            "queuedTasks": len(queued_files),
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


def _check_repos_healthy() -> dict:
    """Check repos directory"""
    try:
        base_dir = ai_devops_home()
        repos_dir = base_dir / "repos"
        
        if not repos_dir.exists():
            return {
                "status": "warning",
                "message": "Repos directory not found",
            }
        
        repos = [d.name for d in repos_dir.iterdir() if d.is_dir()]
        return {
            "status": "healthy",
            "repoCount": len(repos),
            "repos": repos[:10],  # List first 10 repos
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
        }


def _parse_path(path: str) -> tuple[str, Optional[str]]:
    """Parse API path to extract resource and action"""
    parts = path.strip('/').split('/')
    # Check for /api/health or /api/health/services
    if len(parts) >= 2 and parts[0] == 'api' and parts[1] == 'health':
        action = parts[2] if len(parts) >= 3 else None
        return 'health', action
    return '', None


class HealthAPIHandler:
    """Health API request handler mixin"""
    
    def handle_get_health(self):
        """Handle GET /api/health - Overall system health"""
        try:
            services = {}
            overall_status = "healthy"
            
            # Check daemon
            daemon_running = _check_daemon_running()
            services["daemon"] = {
                "status": "running" if daemon_running else "stopped",
            }
            if not daemon_running:
                overall_status = "degraded"
            
            # Check database
            db_health = _check_db_healthy()
            services["database"] = db_health
            if db_health["status"] != "healthy":
                overall_status = "unhealthy"
            
            # Check queue
            queue_health = _check_queue_healthy()
            services["queue"] = queue_health
            if queue_health["status"] == "unhealthy":
                overall_status = "unhealthy"
            
            return _json_response({
                "success": True,
                "data": {
                    "status": overall_status,
                    "timestamp": int(time.time() * 1000),
                    "services": services,
                }
            })
        except Exception as e:
            return _error_response(f"Health check failed: {str(e)}", 500)
    
    def handle_get_services(self):
        """Handle GET /api/health/services - Detailed service status"""
        try:
            services = {
                "daemon": {
                    "name": "Zoe Daemon",
                    "status": "running" if _check_daemon_running() else "stopped",
                    "description": "Task queue consumer and agent spawner",
                },
                "database": {
                    "name": "SQLite Database",
                    **_check_db_healthy(),
                    "description": "Task registry and state tracking",
                },
                "queue": {
                    "name": "Task Queue",
                    **_check_queue_healthy(),
                    "description": "Pending task storage",
                },
                "repos": {
                    "name": "Repository Storage",
                    **_check_repos_healthy(),
                    "description": "Cloned git repositories",
                },
            }
            
            # Calculate overall status
            statuses = [s.get("status", "unknown") for s in services.values()]
            if all(s == "healthy" or s == "running" for s in statuses):
                overall = "healthy"
            elif any(s == "unhealthy" or s == "stopped" for s in statuses):
                overall = "unhealthy"
            else:
                overall = "degraded"
            
            return _json_response({
                "success": True,
                "data": {
                    "overallStatus": overall,
                    "timestamp": int(time.time() * 1000),
                    "services": services,
                }
            })
        except Exception as e:
            return _error_response(f"Service check failed: {str(e)}", 500)


def create_health_handler(base_handler: type) -> type:
    """Factory to create a combined handler with health API support"""
    
    class CombinedHandler(HealthAPIHandler, base_handler):
        def do_GET(self):
            resource, action = _parse_path(self.path)
            if resource == 'health':
                if action == 'services':
                    body, status, content_type = self.handle_get_services()
                else:
                    body, status, content_type = self.handle_get_health()
                
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(body)
            else:
                # Delegate to base handler
                super().do_GET()
        
        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type')
            self.end_headers()
    
    return CombinedHandler
