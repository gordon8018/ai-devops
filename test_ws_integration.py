#!/usr/bin/env python3
"""
Integration test for WebSocket server

This test starts the WebSocket server and tests basic connectivity.
"""

import asyncio
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.api.events import get_event_manager, EventType
from orchestrator.api.websocket import get_websocket_handler, WEBSOCKETS_AVAILABLE


async def test_websocket_connection():
    """Test WebSocket server connectivity"""
    if not WEBSOCKETS_AVAILABLE:
        print("⚠ websockets library not installed, skipping")
        return True
    
    print("Testing WebSocket connection...")
    
    import websockets
    
    ws_handler = get_websocket_handler()
    event_manager = get_event_manager()
    
    # Start server
    server_task = asyncio.create_task(
        ws_handler.start_server('localhost', 18765)
    )
    
    # Wait for server to start
    await asyncio.sleep(0.5)
    
    try:
        # Connect as client
        async with websockets.connect('ws://localhost:18765') as ws:
            print("  ✓ Connected to WebSocket server")
            
            # Receive welcome message
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            print(f"  ✓ Received: {data['type']}")
            assert data['type'] == 'connected'
            
            # Test ping/pong
            await ws.send(json.dumps({'type': 'ping'}))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            print(f"  ✓ Ping/pong: {data['type']}")
            assert data['type'] == 'pong'
            
            # Test subscription
            await ws.send(json.dumps({
                'type': 'subscribe',
                'events': ['task_status', 'plan_status']
            }))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            print(f"  ✓ Subscribed to: {data['events']}")
            assert data['type'] == 'subscribed'
            
            # Publish event and receive
            await asyncio.sleep(0.1)
            event_manager.publish_task_status('test_task', 'running', {'progress': 50})
            
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            print(f"  ✓ Received event: {data['type']}")
            assert data['type'] == 'task_status'
            assert data['data']['task_id'] == 'test_task'
            
        print("✓ WebSocket integration test passed!\n")
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
    
    finally:
        # Stop server
        ws_handler.stop_server()
        server_task.cancel()


if __name__ == "__main__":
    success = asyncio.run(test_websocket_connection())
    sys.exit(0 if success else 1)
