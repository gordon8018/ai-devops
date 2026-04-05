"""
Resources REST API

Endpoints:
- GET /api/resources - Resource usage summary
- GET /api/resources/cpu - CPU details
- GET /api/resources/memory - Memory details
- GET /api/resources/disk - Disk details
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
from dataclasses import asdict

bin_dir = Path(__file__).parent.parent / "bin"
if str(bin_dir) not in sys.path:
    sys.path.insert(0, str(bin_dir))

try:
    from resource_monitor import get_resource_monitor, ResourceMonitor
except ImportError:
    from orchestrator.bin.resource_monitor import get_resource_monitor, ResourceMonitor


def _json_response(data: Any, status: int = 200) -> tuple[bytes, int, str]:
    body = json.dumps(data, ensure_ascii=False, indent=2)
    return body.encode("utf-8"), status, "application/json"


def _error_response(message: str, status: int = 400) -> tuple[bytes, int, str]:
    return _json_response({"error": message, "success": False}, status)


def _parse_path(path: str) -> tuple[str, Optional[str]]:
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "api" and parts[1] == "resources":
        action = parts[2] if len(parts) >= 3 else None
        return "resources", action
    return "", None


class ResourcesAPIHandler:
    def handle_get_summary(self):
        try:
            monitor = get_resource_monitor()
            summary = monitor.get_summary_caching()
            return _json_response({"success": True, "data": summary})
        except Exception as e:
            return _error_response(f"Failed to get resource summary: {str(e)}", 500)

    def handle_get_cpu(self):
        try:
            monitor = get_resource_monitor()
            stats = monitor.get_cpu_stats()
            return _json_response({"success": True, "data": asdict(stats)})
        except Exception as e:
            return _error_response(f"Failed to get CPU stats: {str(e)}", 500)

    def handle_get_memory(self):
        try:
            monitor = get_resource_monitor()
            stats = monitor.get_memory_stats()
            return _json_response({"success": True, "data": asdict(stats)})
        except Exception as e:
            return _error_response(f"Failed to get memory stats: {str(e)}", 500)

    def handle_get_disk(self):
        try:
            monitor = get_resource_monitor()
            stats = monitor.get_disk_stats()
            return _json_response({"success": True, "data": asdict(stats)})
        except Exception as e:
            return _error_response(f"Failed to get disk stats: {str(e)}", 500)

    def handle_get_all(self):
        try:
            monitor = get_resource_monitor()
            stats = monitor.get_all_stats_caching()
            return _json_response({"success": True, "data": stats})
        except Exception as e:
            return _error_response(f"Failed to get all resource stats: {str(e)}", 500)


def create_resources_handler(base_handler: type) -> type:
    class CombinedHandler(ResourcesAPIHandler, base_handler):
        def do_GET(self):
            resource, action = _parse_path(self.path)
            if resource == "resources":
                if action == "cpu":
                    body, status, content_type = self.handle_get_cpu()
                elif action == "memory":
                    body, status, content_type = self.handle_get_memory()
                elif action == "disk":
                    body, status, content_type = self.handle_get_disk()
                elif action == "all":
                    body, status, content_type = self.handle_get_all()
                else:
                    body, status, content_type = self.handle_get_summary()
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            else:
                super().do_GET()

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

    return CombinedHandler


if __name__ == "__main__":
    monitor = get_resource_monitor()
    print("Summary:", json.dumps(monitor.get_summary(), indent=2))
