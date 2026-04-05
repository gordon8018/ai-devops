"""
WebSocket Handler - Real-time event streaming

Provides:
- WebSocketHandler: Manages WebSocket connections
- Client connection management
- Message broadcasting
- Heartbeat/ping-pong mechanism
- Event subscription filtering
"""

from __future__ import annotations

import asyncio
import json
import time
import threading
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

try:
    import websockets
    from websockets.server import serve, WebSocketServerProtocol
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    WebSocketServerProtocol = Any

from .events import EventManager, get_event_manager, Event, EventType


@dataclass
class WebSocketClient:
    """Represents a connected WebSocket client"""
    websocket: Any
    client_id: str
    subscriptions: Set[EventType] = field(default_factory=set)
    last_ping: float = field(default_factory=lambda: time.time())
    connected_at: float = field(default_factory=lambda: time.time())
    
    def is_subscribed_to(self, event_type: EventType) -> bool:
        """Check if client is subscribed to an event type"""
        if not self.subscriptions:
            return True
        return event_type in self.subscriptions


class WebSocketHandler:
    """
    WebSocket connection handler with event streaming
    
    Features:
    - Client connection management
    - Event subscription filtering
    - Message broadcasting
    - Heartbeat/ping-pong
    - Graceful shutdown
    """
    
    _instance: Optional['WebSocketHandler'] = None
    _lock = threading.RLock()  # 使用 RLock 替代 Lock，避免 TOCTOU
    
    def __new__(cls) -> 'WebSocketHandler':
        """Singleton pattern for global handler"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, event_manager: Optional[EventManager] = None):
        """Initialize WebSocket handler"""
        if self._initialized:
            return
        
        self._initialized = True
        self.event_manager = event_manager or get_event_manager()
        self._clients: Dict[str, WebSocketClient] = {}
        self._client_counter = 0
        self._lock = threading.RLock()
        self._running = False
        self._server = None
        self._unsubscribe_event_manager = None
        
        self.heartbeat_interval = 30
        self.heartbeat_timeout = 60
        self.max_clients = 100
    
    @property
    def client_count(self) -> int:
        return len(self._clients)
    
    @property
    def is_running(self) -> bool:
        return self._running

    async def handle_client(self, websocket: WebSocketServerProtocol, path: str):
        """Handle a WebSocket client connection"""
        if not WEBSOCKETS_AVAILABLE:
            return
        
        # TOCTOU 修复：在单个锁操作中检查并添加客户端
        with self._lock:
            if len(self._clients) >= self.max_clients:
                await websocket.close(code=1013, reason="Max clients reached")
                return
            
            # 在同一个锁内完成计数器递增和客户端添加
            self._client_counter += 1
            client_id = f"client_{self._client_counter}"
            client = WebSocketClient(
                websocket=websocket,
                client_id=client_id,
            )
            self._clients[client_id] = client
        
        print(f"[WebSocket] Client connected: {client_id} (total: {len(self._clients)})")
        
        def on_event(event: Event):
            if client.is_subscribed_to(event.event_type):
                asyncio.create_task(self._send_event(client, event))
        
        unsubscribe = self.event_manager.subscribe(on_event)
        
        try:
            await self._send_message(client, {
                "type": "connected",
                "client_id": client_id,
                "timestamp": time.time(),
                "available_events": [e.value for e in EventType],
            })
            
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(client))
            
            async for message in websocket:
                await self._handle_message(client, message)
            
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            print(f"[WebSocket] Error handling client {client_id}: {e}")
        finally:
            unsubscribe()
            with self._lock:
                self._clients.pop(client_id, None)
            print(f"[WebSocket] Client disconnected: {client_id} (total: {len(self._clients)})")

    async def _handle_message(self, client: WebSocketClient, message: str):
        """Handle incoming message from client"""
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "ping":
                await self._send_message(client, {
                    "type": "pong",
                    "timestamp": time.time(),
                })
                client.last_ping = time.time()
            
            elif msg_type == "pong":
                client.last_ping = time.time()
            
            elif msg_type == "subscribe":
                event_types = data.get("events", [])
                client.subscriptions.clear()
                for et in event_types:
                    try:
                        client.subscriptions.add(EventType(et))
                    except ValueError:
                        pass
                await self._send_message(client, {
                    "type": "subscribed",
                    "events": [e.value for e in client.subscriptions],
                })
            
            elif msg_type == "unsubscribe":
                client.subscriptions.clear()
                await self._send_message(client, {
                    "type": "unsubscribed",
                })
            
            else:
                await self._send_message(client, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })
        
        except json.JSONDecodeError:
            await self._send_message(client, {
                "type": "error",
                "message": "Invalid JSON",
            })
        except Exception as e:
            print(f"[WebSocket] Error handling message: {e}")

    async def _send_message(self, client: WebSocketClient, data: Dict[str, Any]):
        """Send message to client"""
        if not WEBSOCKETS_AVAILABLE:
            return
        try:
            message = json.dumps(data, ensure_ascii=False)
            await client.websocket.send(message)
        except Exception as e:
            print(f"[WebSocket] Error sending message: {e}")

    async def _send_event(self, client: WebSocketClient, event: Event):
        """Send event to client"""
        await self._send_message(client, event.to_dict())

    async def _heartbeat_loop(self, client: WebSocketClient):
        """Send periodic heartbeats to client"""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                if time.time() - client.last_ping > self.heartbeat_timeout:
                    print(f"[WebSocket] Client {client.client_id} timed out")
                    await client.websocket.close(code=1001, reason="Heartbeat timeout")
                    break
                
                await self._send_message(client, {
                    "type": "ping",
                    "timestamp": time.time(),
                })
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WebSocket] Heartbeat error: {e}")
                break

    def broadcast(self, event: Event):
        """Broadcast event to all connected clients"""
        if not WEBSOCKETS_AVAILABLE or not self._running:
            return
        
        async def _broadcast():
            with self._lock:
                clients = list(self._clients.values())
            
            for client in clients:
                if client.is_subscribed_to(event.event_type):
                    try:
                        await self._send_event(client, event)
                    except Exception:
                        pass
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast())
        except RuntimeError:
            pass

    def get_client_info(self) -> List[Dict[str, Any]]:
        """Get information about connected clients"""
        with self._lock:
            return [
                {
                    "client_id": c.client_id,
                    "connected_at": c.connected_at,
                    "last_ping": c.last_ping,
                    "subscriptions": [e.value for e in c.subscriptions],
                }
                for c in self._clients.values()
            ]

    async def start_server(self, host: str = '0.0.0.0', port: int = 8765):
        """Start WebSocket server"""
        if not WEBSOCKETS_AVAILABLE:
            print("[WebSocket] websockets library not available")
            return
        
        if self._running:
            return
        
        self._running = True
        print(f"[WebSocket] Server starting on ws://{host}:{port}")
        print(f"[WebSocket] Endpoint: /ws/events")
        
        self._server = await serve(
            self.handle_client,
            host,
            port,
            subprotocols=["events"]
        )

    def stop_server(self):
        """Stop WebSocket server"""
        if self._server:
            self._server.close()
            self._running = False
            print("[WebSocket] Server stopped")


_websocket_handler: Optional[WebSocketHandler] = None


def get_websocket_handler() -> WebSocketHandler:
    """Get the global WebSocket handler instance"""
    global _websocket_handler
    if _websocket_handler is None:
        _websocket_handler = WebSocketHandler()
    return _websocket_handler
