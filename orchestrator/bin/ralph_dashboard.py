#!/usr/bin/env python3
"""Dashboard API for Ralph - REST endpoints for task monitoring"""

import json
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List
from urllib.parse import urlparse, parse_qs

try:
    from ralph_state import RalphState
except ImportError:
    from orchestrator.bin.ralph_state import RalphState

class RalphDashboardAPI:
    """REST API handler for ralph dashboard"""
    
    def __init__(self, state=None):
        self.state = state or RalphState()
    
    def handle_request(self, method: str, path: str, query: Dict, body: Dict = None) -> tuple:
        """Handle API request and return (status_code, response_dict)"""
        if path == "/ralph/tasks":
            if method == "GET":
                return self.get_tasks(query)
            else:
                return 405, {"error": "Method not allowed"}
        
        elif path.startswith("/ralph/tasks/"):
            task_id = path[len("/ralph/tasks/"):]
            if method == "GET":
                return self.get_task(task_id)
            else:
                return 405, {"error": "Method not allowed"}
        
        elif path == "/ralph/stats":
            if method == "GET":
                return self.get_stats()
            else:
                return 405, {"error": "Method not allowed"}
        
        else:
            return 404, {"error": "Not found"}
    
    def get_tasks(self, query: Dict) -> tuple:
        """GET /ralph/tasks - List all tasks"""
        status_filter = query.get("status", [None])[0]
        limit = int(query.get("limit", [50])[0])
        
        tasks = self.state.list(status=status_filter, limit=limit)
        
        return 200, {
            "tasks": tasks,
            "count": len(tasks),
            "status_filter": status_filter
        }
    
    def get_task(self, task_id: str) -> tuple:
        """GET /ralph/tasks/{id} - Get task details"""
        task = self.state.get(task_id)
        
        if task is None:
            return 404, {"error": "Task not found", "task_id": task_id}
        
        return 200, task
    
    def get_stats(self) -> tuple:
        """GET /ralph/stats - Get statistics"""
        all_tasks = self.state.list(limit=1000)
        
        total = len(all_tasks)
        by_status = {}
        by_status_counts = {}
        
        for task in all_tasks:
            status = task["status"]
            by_status[status] = by_status.get(status, 0) + 1
        
        # Calculate success rate
        completed = by_status.get("completed", 0) + by_status.get("quality_passed", 0)
        failed = by_status.get("failed", 0) + by_status.get("ci_failed", 0) + by_status.get("review_failed", 0)
        success_rate = (completed / total * 100) if total > 0 else 0
        
        # Average iterations
        total_iterations = 0
        iteration_count = 0
        for task in all_tasks:
            iterations = task["metadata"].get("review_attempts", 0)
            if iterations > 0:
                total_iterations += iterations
                iteration_count += 1
        avg_iterations = (total_iterations / iteration_count) if iteration_count > 0 else 0
        
        return 200, {
            "total_tasks": total,
            "by_status": by_status,
            "success_rate": round(success_rate, 2),
            "average_iterations": round(avg_iterations, 2),
            "completed": completed,
            "failed": failed,
            "running": by_status.get("running", 0),
            "queued": by_status.get("queued", 0)
        }

def create_dashboard_handler(base_handler_class):
    """Decorator to add ralph dashboard routes to existing API handler"""
    dashboard = RalphDashboardAPI()
    
    class RalphDashboardHandler(base_handler_class):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            
            if parsed.path.startswith("/ralph/"):
                status_code, response = dashboard.handle_request("GET", parsed.path, query)
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())
            else:
                super().do_GET()
    
    return RalphDashboardHandler

def main():
    dashboard = RalphDashboardAPI()
    
    if len(sys.argv) < 2:
        print("Ralph Dashboard API CLI")
        print("Usage:")
        print("  ralph_dashboard.py tasks [--status completed] [--limit 50]")
        print("  ralph_dashboard.py task <task_id>")
        print("  ralph_dashboard.py stats")
        sys.exit(0)
    
    command = sys.argv[1]
    
    if command == "tasks":
        status = None
        limit = 50
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--status" and i + 1 < len(sys.argv):
                status = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--limit" and i + 1 < len(sys.argv):
                limit = int(sys.argv[i + 1])
                i += 2
            else:
                i += 1
        status_code, response = dashboard.get_tasks({"status": [status], "limit": [limit]})
        print(json.dumps(response, indent=2))
    
    elif command == "task":
        task_id = sys.argv[2]
        status_code, response = dashboard.get_task(task_id)
        print(json.dumps(response, indent=2))
    
    elif command == "stats":
        status_code, response = dashboard.get_stats()
        print(json.dumps(response, indent=2))
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

if __name__ == "__main__":
    main()
