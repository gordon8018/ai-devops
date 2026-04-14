#!/usr/bin/env python3
"""WebSocket Server for Ralph - Real-time task status updates"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

try:
    import websockets
    from websockets.server import serve
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

try:
    from ralph_state import RalphState
except ImportError:
    from orchestrator.bin.ralph_state import RalphState

class RalphEventType(Enum):
    STATUS_CHANGE = "status_change"
    PROGRESS_UPDATE = "progress_update"
    LOG_APPEND = "log_append"
    TASK_COMPLETE = "task_complete"
    TASK_FAILED = "task_failed"

@dataclass
class RalphEvent:
    event_type: RalphEventType
    task_id: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=lambda: time.time())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type.value,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp
        }

class RalphWebSocketServer:
    """WebSocket server for broadcasting ralph task updates"""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8766):
        self.host = host
        self.port = port
        self.state = RalphState()
        self.clients: Set[Any] = set()
        self.server = None
        self._running = False
    
    async def handle_client(self, websocket, path):
        """Handle a WebSocket client connection"""
        self.clients.add(websocket)
        print(f"[RalphWS] Client connected (total: {len(self.clients)})")
        
        try:
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")
                
                if msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong", "timestamp": time.time()}))
                elif msg_type == "subscribe":
                    task_id = data.get("task_id")
                    if task_id:
                        task = self.state.get(task_id)
                        await websocket.send(json.dumps({
                            "type": "subscribed",
                            "task_id": task_id,
                            "task": task
                        }))
        except Exception as e:
            print(f"[RalphWS] Client error: {e}")
        finally:
            self.clients.remove(websocket)
            print(f"[RalphWS] Client disconnected (total: {len(self.clients)})")
    
    async def broadcast(self, event: RalphEvent):
        """Broadcast event to all connected clients"""
        if not self.clients:
            return
        
        message = json.dumps(event.to_dict())
        disconnected = set()
        
        for client in self.clients:
            try:
                await client.send(message)
            except Exception:
                disconnected.add(client)
        
        for client in disconnected:
            self.clients.discard(client)
    
    async def start(self):
        """Start the WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            print("[RalphWS] websockets library not available")
            return
        
        self._running = True
        self.server = await serve(self.handle_client, self.host, self.port)
        print(f"[RalphWS] Server started on ws://{self.host}:{self.port}")
    
    async def stop(self):
        """Stop the WebSocket server"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self._running = False
            print("[RalphWS] Server stopped")
    
    def publish_status_change(self, task_id: str, old_status: str, new_status: str):
        """Publish status change event"""
        event = RalphEvent(
            event_type=RalphEventType.STATUS_CHANGE,
            task_id=task_id,
            data={"old_status": old_status, "new_status": new_status}
        )
        asyncio.create_task(self.broadcast(event))
    
    def publish_progress_update(self, task_id: str, progress: int, message: str = ""):
        """Publish progress update event"""
        event = RalphEvent(
            event_type=RalphEventType.PROGRESS_UPDATE,
            task_id=task_id,
            data={"progress": progress, "message": message}
        )
        asyncio.create_task(self.broadcast(event))
    
    def publish_log_append(self, task_id: str, log_entry: str):
        """Publish log append event"""
        event = RalphEvent(
            event_type=RalphEventType.LOG_APPEND,
            task_id=task_id,
            data={"log": log_entry}
        )
        asyncio.create_task(self.broadcast(event))
    
    def publish_task_complete(self, task_id: str, result: Dict[str, Any]):
        """Publish task completion event"""
        event = RalphEvent(
            event_type=RalphEventType.TASK_COMPLETE,
            task_id=task_id,
            data=result
        )
        asyncio.create_task(self.broadcast(event))
    
    def publish_task_failed(self, task_id: str, error: str):
        """Publish task failure event"""
        event = RalphEvent(
            event_type=RalphEventType.TASK_FAILED,
            task_id=task_id,
            data={"error": error}
        )
        asyncio.create_task(self.broadcast(event))

# Global instance
_ws_server: Optional[RalphWebSocketServer] = None

def get_ws_server() -> RalphWebSocketServer:
    global _ws_server
    if _ws_server is None:
        _ws_server = RalphWebSocketServer()
    return _ws_server

def main():
    print("Ralph WebSocket Server")
    print("Usage: ralph_ws_server.py start [--port 8766]")
    print("       ralph_ws_server.py stop")

if __name__ == "__main__":
    main()
