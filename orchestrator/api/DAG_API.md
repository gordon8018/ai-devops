# DAG Visualization API

## Overview

The DAG (Directed Acyclic Graph) Visualization API provides endpoints for rendering plan dependency graphs in multiple formats.

## Endpoints

### GET /api/plans/{plan_id}/dag
Get DAG data in JSON format (default).

### GET /api/plans/{plan_id}/dag/json
Same as /dag - returns JSON format for frontend rendering.

### GET /api/plans/{plan_id}/dag/svg
Returns SVG diagram of the DAG. Requires graphviz binary.

### GET /api/plans/{plan_id}/dag/png
Returns PNG diagram of the DAG. Requires graphviz binary.

### GET /api/plans/{plan_id}/dag/dot
Returns DOT source code for the DAG.

## Node Status Colors

| Status   | Color   | Hex Code |
|----------|---------|----------|
| pending  | Gray    | #B0BEC5  |
| running  | Blue    | #42A5F5  |
| completed| Green   | #66BB6A  |
| failed   | Red     | #EF5350  |
| blocked  | Orange  | #FFA726  |

## Requirements

- Python Package: graphviz (installed in .venv)
- Binary Tool: graphviz (optional, for SVG/PNG output)

Install: sudo apt-get install graphviz

## Testing

Run tests: python3 test_dag_api.py
