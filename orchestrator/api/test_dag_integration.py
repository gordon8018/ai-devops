#!/usr/bin/env python3
"""
Integration test for DAG API endpoints

Tests the full API handler chain with mock requests.
"""

import json
import sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from io import BytesIO

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.api.plans import create_plans_handler


class MockRequest:
    """Mock HTTP request"""
    def __init__(self, path):
        self.path = path
        self.requestline = f"GET {path} HTTP/1.1"
        self.headers = {}


class MockHandler:
    """Mock base handler"""
    def do_GET(self):
        self.send_response(404)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"error": "Not found"}')


def test_dag_json_endpoint():
    """Test GET /api/plans/{plan_id}/dag endpoint"""
    print("\nTesting DAG JSON endpoint...")
    
    # Create handler
    handler_class = create_plans_handler(MockHandler)
    
    # Find a test plan
    tasks_dir = Path(__file__).parent.parent.parent / "tasks"
    if not tasks_dir.exists():
        print("⚠ No tasks directory found, skipping integration test")
        return
    
    plan_dirs = [d for d in tasks_dir.iterdir() if d.is_dir() and (d / "plan.json").exists()]
    if not plan_dirs:
        print("⚠ No plan.json files found, skipping integration test")
        return
    
    test_plan_id = plan_dirs[0].name
    print(f"Using test plan: {test_plan_id}")
    
    # Test DAG JSON endpoint
    request = MockRequest(f"/api/plans/{test_plan_id}/dag")
    
    # Create mock handler instance
    class TestHandler(handler_class):
        def __init__(self):
            self.path = request.path
            self._response_code = None
            self._headers = {}
            self._body = BytesIO()
        
        def send_response(self, code):
            self._response_code = code
        
        def send_header(self, key, value):
            self._headers[key] = value
        
        def end_headers(self):
            pass
        
        def wfile_write(self, data):
            self._body.write(data)
        
        @property
        def wfile(self):
            class WFile:
                def __init__(self, parent):
                    self.parent = parent
                def write(self, data):
                    self.parent._body.write(data)
            return WFile(self)
    
    handler = TestHandler()
    handler.do_GET()
    
    body = handler._body.getvalue().decode('utf-8')
    print(f"Response code: {handler._response_code}")
    print(f"Content-Type: {handler._headers.get('Content-Type')}")
    
    if handler._response_code == 200:
        data = json.loads(body)
        if data.get("success"):
            dag_data = data.get("data", {})
            print(f"Nodes: {len(dag_data.get('nodes', []))}")
            print(f"Edges: {len(dag_data.get('edges', []))}")
            print("✓ DAG JSON endpoint test passed")
        else:
            print(f"✗ API returned error: {data.get('error')}")
    else:
        print(f"✗ Unexpected response code: {handler._response_code}")


def test_dag_dot_endpoint():
    """Test GET /api/plans/{plan_id}/dag/dot endpoint"""
    print("\nTesting DAG DOT endpoint...")
    
    # Create handler
    handler_class = create_plans_handler(MockHandler)
    
    # Find a test plan
    tasks_dir = Path(__file__).parent.parent.parent / "tasks"
    if not tasks_dir.exists():
        print("⚠ No tasks directory found, skipping integration test")
        return
    
    plan_dirs = [d for d in tasks_dir.iterdir() if d.is_dir() and (d / "plan.json").exists()]
    if not plan_dirs:
        print("⚠ No plan.json files found, skipping integration test")
        return
    
    test_plan_id = plan_dirs[0].name
    
    # Test DAG DOT endpoint
    request = MockRequest(f"/api/plans/{test_plan_id}/dag/dot")
    
    class TestHandler(handler_class):
        def __init__(self):
            self.path = request.path
            self._response_code = None
            self._headers = {}
            self._body = BytesIO()
        
        def send_response(self, code):
            self._response_code = code
        
        def send_header(self, key, value):
            self._headers[key] = value
        
        def end_headers(self):
            pass
        
        def wfile_write(self, data):
            self._body.write(data)
        
        @property
        def wfile(self):
            class WFile:
                def __init__(self, parent):
                    self.parent = parent
                def write(self, data):
                    self.parent._body.write(data)
            return WFile(self)
    
    handler = TestHandler()
    handler.do_GET()
    
    body = handler._body.getvalue().decode('utf-8')
    print(f"Response code: {handler._response_code}")
    print(f"Content-Type: {handler._headers.get('Content-Type')}")
    
    if handler._response_code == 200:
        if "digraph" in body:
            print("✓ DAG DOT endpoint test passed")
            print(f"DOT content length: {len(body)} bytes")
        else:
            print("✗ Response doesn't contain digraph")
    else:
        print(f"✗ Unexpected response code: {handler._response_code}")


def run_integration_tests():
    """Run integration tests"""
    print("\n" + "=" * 60)
    print("DAG API Integration Tests")
    print("=" * 60)
    
    test_dag_json_endpoint()
    test_dag_dot_endpoint()
    
    print("\n" + "=" * 60)
    print("Integration tests completed")
    print("=" * 60)


if __name__ == "__main__":
    run_integration_tests()
