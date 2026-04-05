"""
API Server - Unified HTTP Server for all REST APIs

Combines tasks, plans, and health APIs into a single HTTP server.
Now includes WebSocket support for real-time event streaming.
"""

from __future__ import annotations

import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Optional
import sys

# Import API handlers
try:
    from .tasks import create_tasks_handler
    from .plans import create_plans_handler
    from .health import create_health_handler
except ImportError:
    from tasks import create_tasks_handler
    from plans import create_plans_handler
    from health import create_health_handler

# Import WebSocket and Events
try:
    from .websocket import get_websocket_handler, WEBSOCKETS_AVAILABLE
    from .events import get_event_manager, EventType
except ImportError:
    from websocket import get_websocket_handler, WEBSOCKETS_AVAILABLE
    from events import get_event_manager, EventType


class BaseAPIHandler(BaseHTTPRequestHandler):
    """Base request handler with common functionality"""
    
    def log_message(self, format: str, *args) -> None:
        """Override to suppress default logging or customize"""
        pass
    
    def _send_404(self):
        """Send 404 Not Found"""
        body = json.dumps({"error": "Not Found", "success": False}).encode('utf-8')
        self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        """Handle GET requests - route to appropriate handler"""
        self._send_404()
    
    def do_POST(self):
        """Handle POST requests - route to appropriate handler"""
        self._send_404()
    
    def do_DELETE(self):
        """Handle DELETE requests - route to appropriate handler"""
        self._send_404()
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


def create_combined_handler() -> type:
    """Create a combined handler with all API routes"""
    handler = BaseAPIHandler
    handler = create_tasks_handler(handler)
    handler = create_plans_handler(handler)
    handler = create_health_handler(handler)
    return handler


class WebSocketServerThread(threading.Thread):
    """Thread to run WebSocket server"""
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8765):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.ws_handler = get_websocket_handler()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event = threading.Event()
    
    def run(self):
        """Run WebSocket server in its own event loop"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        try:
            self.loop.run_until_complete(
                self.ws_handler.start_server(self.host, self.port)
            )
            # Keep running until stopped
            self.loop.run_forever()
        except Exception as e:
            print(f"[WebSocket] Server error: {e}")
        finally:
            self.loop.close()
    
    def stop(self):
        """Stop WebSocket server"""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.ws_handler.stop_server)
            self.loop.call_soon_threadsafe(self.loop.stop)


class APIServer:
    """HTTP server for orchestrator REST APIs with WebSocket support"""
    
    def __init__(self, port: int = 8080, host: str = '0.0.0.0', ws_port: int = 8765):
        self.port = port
        self.host = host
        self.ws_port = ws_port
        self.server: Optional[HTTPServer] = None
        self.ws_thread: Optional[WebSocketServerThread] = None
        self.event_manager = get_event_manager()
    
    def start(self, daemon: bool = True):
        """Start the API server and WebSocket server"""
        handler_class = create_combined_handler()
        self.server = HTTPServer((self.host, self.port), handler_class)
        
        print(f"[API] Server starting on http://{self.host}:{self.port}")
        print(f"[API] REST Endpoints:")
        print(f"[API]   - GET    /api/health")
        print(f"[API]   - GET    /api/health/services")
        print(f"[API]   - GET    /api/tasks")
        print(f"[API]   - GET    /api/tasks/{{task_id}}")
        print(f"[API]   - POST   /api/tasks")
        print(f"[API]   - DELETE /api/tasks/{{task_id}}")
        print(f"[API]   - GET    /api/plans")
        print(f"[API]   - GET    /api/plans/{{plan_id}}")
        print(f"[API]   - POST   /api/plans/{{plan_id}}/dispatch")
        
        # Start WebSocket server if available
        if WEBSOCKETS_AVAILABLE:
            self.ws_thread = WebSocketServerThread(self.host, self.ws_port)
            self.ws_thread.start()
            print(f"[API] WebSocket: ws://{self.host}:{self.ws_port}/ws/events")
            print(f"[API] Event types: {', '.join([e.value for e in EventType])}")
        else:
            print("[API] WebSocket: not available (install 'websockets' package)")
        
        if daemon:
            thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            thread.start()
            return thread
        else:
            self.server.serve_forever()
    
    def stop(self):
        """Stop the API server and WebSocket server"""
        if self.server:
            self.server.shutdown()
            print("[API] HTTP server stopped")
        
        if self.ws_thread:
            self.ws_thread.stop()
            print("[API] WebSocket server stopped")
    
    def publish_event(self, event_type: str, data: dict, source: Optional[str] = None):
        """
        Publish an event to WebSocket clients
        
        Args:
            event_type: Event type (task_status, plan_status, alert)
            data: Event data
            source: Event source identifier
        """
        try:
            et = EventType(event_type)
            from .events import Event
            event = Event(event_type=et, data=data, source=source)
            self.event_manager.publish(event)
        except ValueError:
            print(f"[API] Unknown event type: {event_type}")


def run_server(port: int = 8080, ws_port: int = 8765):
    """Run API server in foreground"""
    server = APIServer(port=port, ws_port=ws_port)
    try:
        server.start(daemon=False)
    except KeyboardInterrupt:
        print("\n[API] Shutting down...")
        server.stop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Orchestrator REST API Server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP server port (default: 8080)")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket server port (default: 8765)")
    
    args = parser.parse_args()
    
    run_server(port=args.port, ws_port=args.ws_port)
