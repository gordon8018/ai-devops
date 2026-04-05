# WebSocket API Documentation

## Overview

The WebSocket API provides real-time event streaming for task and plan status updates.

## Connection

**Endpoint:** `ws://host:8765/ws/events`

## Event Types

- `task_status` - Task status changes (queued, running, completed, failed)
- `plan_status` - Plan status changes (pending, dispatched, completed)
- `alert` - System alerts (info, warning, error, critical)
- `system` - System events (startup, shutdown)

## Client Protocol

### 1. Connect
```javascript
const ws = new WebSocket('ws://localhost:8765/ws/events');

ws.onopen = () => {
  console.log('Connected');
};
```

### 2. Welcome Message
Upon connection, you'll receive:
```json
{
  "type": "connected",
  "client_id": "client_1",
  "timestamp": 1712234567.89,
  "available_events": ["task_status", "plan_status", "alert", "system"]
}
```

### 3. Subscribe to Events
```javascript
// Subscribe to specific events
ws.send(JSON.stringify({
  "type": "subscribe",
  "events": ["task_status", "plan_status"]
}));

// Response:
{
  "type": "subscribed",
  "events": ["task_status", "plan_status"]
}
```

### 4. Heartbeat (Ping/Pong)
```javascript
// Client sends ping
ws.send(JSON.stringify({"type": "ping"}));

// Server responds with pong
{
  "type": "pong",
  "timestamp": 1712234567.89
}
```

## Event Format

All events follow this structure:
```json
{
  "type": "task_status",
  "data": {
    "task_id": "task_001",
    "status": "running",
    "details": {"progress": 50}
  },
  "timestamp": 1712234567.89,
  "source": "orchestrator"
}
```

## Example: JavaScript Client

```javascript
const ws = new WebSocket('ws://localhost:8765/ws/events');

ws.onopen = () => {
  // Subscribe to task and plan updates
  ws.send(JSON.stringify({
    type: 'subscribe',
    events: ['task_status', 'plan_status']
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch(data.type) {
    case 'task_status':
      console.log(`Task ${data.data.task_id}: ${data.data.status}`);
      break;
    case 'plan_status':
      console.log(`Plan ${data.data.plan_id}: ${data.data.status}`);
      break;
    case 'alert':
      console.log(`[${data.data.level}] ${data.data.message}`);
      break;
  }
};

// Heartbeat
setInterval(() => {
  ws.send(JSON.stringify({type: 'ping'}));
}, 30000);
```

## Example: Python Client

```python
import asyncio
import json
import websockets

async def listen():
    async with websockets.connect('ws://localhost:8765/ws/events') as ws:
        # Subscribe to events
        await ws.send(json.dumps({
            'type': 'subscribe',
            'events': ['task_status', 'plan_status']
        }))
        
        # Listen for events
        async for message in ws:
            data = json.loads(message)
            print(f"Event: {data['type']}", data.get('data', {}))

asyncio.run(listen())
```

## Publishing Events (Server-side)

From the API server:
```python
from orchestrator.api.server import APIServer

server = APIServer()
server.publish_event('task_status', {
    'task_id': 'task_001',
    'status': 'running',
    'details': {'progress': 50}
})
```

Or directly using EventManager:
```python
from orchestrator.api.events import get_event_manager

em = get_event_manager()
em.publish_task_status('task_001', 'running', {'progress': 50})
```

## Configuration

- **Default HTTP Port:** 8080
- **Default WebSocket Port:** 8765
- **Heartbeat Interval:** 30 seconds
- **Heartbeat Timeout:** 60 seconds
- **Max Clients:** 100

## Error Handling

```json
{
  "type": "error",
  "message": "Invalid JSON"
}
```
