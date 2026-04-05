# Orchestrator REST API

See individual module files for endpoint details.

## Quick Start

1. API starts automatically with zoe-daemon.py
2. Default port: 8080 (configurable via ZOE_API_PORT env var)

## Endpoints

### Health
- GET /api/health - System health status
- GET /api/health/services - Detailed service status

### Tasks
- GET /api/tasks - List tasks
- GET /api/tasks/{task_id} - Get task details
- POST /api/tasks - Create task
- DELETE /api/tasks/{task_id} - Delete task

### Plans
- GET /api/plans - List plans
- GET /api/plans/{plan_id} - Get plan details with DAG
- POST /api/plans/{plan_id}/dispatch - Dispatch plan subtasks

## Testing

curl http://localhost:8080/api/health
