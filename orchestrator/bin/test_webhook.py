#!/usr/bin/env python3
"""
Test script for GitHub Webhook Server

Simulates GitHub webhook events for testing.

Usage:
    python test_webhook.py --port 8080 --event check_run
    python test_webhook.py --port 8080 --event workflow_run
    python test_webhook.py --port 8080 --event pull_request
"""

__test__ = False

import argparse
import hashlib
import hmac
import json
import urllib.request
import urllib.error
from pathlib import Path

# Default secret for testing
DEFAULT_SECRET = "test-secret"

# Sample payloads
CHECK_RUN_PAYLOAD = {
    "action": "completed",
    "check_run": {
        "name": "test",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "feat/test-branch",
        "html_url": "https://github.com/test/repo/runs/123",
    },
    "repository": {
        "name": "test-repo",
        "full_name": "test/test-repo",
    }
}

WORKFLOW_RUN_PAYLOAD = {
    "action": "completed",
    "workflow_run": {
        "name": "CI",
        "status": "completed",
        "conclusion": "failure",
        "head_branch": "feat/test-branch",
        "html_url": "https://github.com/test/repo/actions/runs/456",
        "id": 456,
    },
    "repository": {
        "name": "test-repo",
        "full_name": "test/test-repo",
    }
}

PULL_REQUEST_PAYLOAD = {
    "action": "opened",
    "pull_request": {
        "number": 42,
        "state": "open",
        "merged": False,
        "head": {
            "ref": "feat/test-branch",
        },
        "html_url": "https://github.com/test/repo/pull/42",
    },
    "repository": {
        "name": "test-repo",
        "full_name": "test/test-repo",
    }
}


def generate_signature(payload: bytes, secret: str) -> str:
    """Generate GitHub-style signature"""
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


def send_webhook(port: int, event_type: str, payload: dict, secret: str) -> dict:
    """Send webhook to server"""
    url = f"http://localhost:{port}/"
    body = json.dumps(payload).encode("utf-8")
    signature = generate_signature(body, secret)
    
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": event_type,
            "X-Hub-Signature-256": signature,
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return {
                "status": response.status,
                "body": response.read().decode("utf-8"),
            }
    except urllib.error.HTTPError as e:
        return {
            "status": e.code,
            "body": e.read().decode("utf-8"),
        }
    except urllib.error.URLError as e:
        return {
            "status": 0,
            "body": str(e.reason),
        }


def check_health(port: int) -> bool:
    """Test health endpoint"""
    url = f"http://localhost:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            print(f"✓ Health check: {data.get('status')}")
            return data.get("status") == "healthy"
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test GitHub Webhook Server")
    parser.add_argument("--port", type=int, default=8080, help="Webhook server port")
    parser.add_argument("--event", choices=["check_run", "workflow_run", "pull_request", "all"], default="all")
    parser.add_argument("--secret", default=DEFAULT_SECRET, help="Webhook secret")
    args = parser.parse_args()
    
    print("=" * 60)
    print("GitHub Webhook Server Test")
    print("=" * 60)
    print(f"Server: http://localhost:{args.port}")
    print(f"Secret: {args.secret}")
    print()
    
    # Test health
    print("1. Testing health endpoint...")
    if not check_health(args.port):
        print("✗ Server is not healthy, aborting tests")
        return
    print()
    
    # Test events
    events = []
    if args.event in ("check_run", "all"):
        events.append(("check_run", CHECK_RUN_PAYLOAD))
    if args.event in ("workflow_run", "all"):
        events.append(("workflow_run", WORKFLOW_RUN_PAYLOAD))
    if args.event in ("pull_request", "all"):
        events.append(("pull_request", PULL_REQUEST_PAYLOAD))
    
    for event_type, payload in events:
        print(f"2. Testing {event_type}...")
        result = send_webhook(args.port, event_type, payload, args.secret)
        
        if result["status"] == 200:
            print(f"   ✓ {event_type}: HTTP {result['status']} - {result['body']}")
        else:
            print(f"   ✗ {event_type}: HTTP {result['status']} - {result['body']}")
        print()
    
    print("=" * 60)
    print("Tests complete!")
    print("=" * 60)
    print()
    print("Check logs at:")
    print(f"  - {Path.home() / 'ai-devops' / 'logs' / 'webhook.log'}")


if __name__ == "__main__":
    main()
