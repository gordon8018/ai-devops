#!/usr/bin/env python3
"""
GitHub Webhook Receiver for AI DevOps

Receives GitHub webhook events (check_run, workflow_run, pull_request)
and triggers monitor to check task status.

Usage:
    python webhook_server.py --port 8080 --secret <webhook-secret>
    python webhook_server.py --port 8080 --secret <secret> --daemon

Environment:
    GITHUB_WEBHOOK_SECRET: Webhook secret (alternative to --secret)
    AI_DEVOPS_HOME: AI DevOps home directory (default: ~/ai-devops)
"""

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, Dict, Any


def base_dir() -> Path:
    return Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))


def log_dir() -> Path:
    return base_dir() / "logs"


def monitor_script_path() -> Path:
    return base_dir() / "orchestrator" / "bin" / "monitor.py"


MONITOR_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="webhook-monitor")

# Add orchestrator to path
sys.path.insert(0, str(base_dir() / "orchestrator" / "bin"))

# Import database
try:
    from db import init_db, get_task_by_branch, update_task
except ImportError:
    from orchestrator.bin.db import init_db, get_task_by_branch, update_task


WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "").encode()


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature"""
    if not WEBHOOK_SECRET:
        print("[ERROR] No webhook secret configured; rejecting webhook request")
        return False
    
    if not signature:
        return False
    
    # GitHub sends sha256=<hash>
    if not signature.startswith("sha256="):
        return False
    
    expected_hash = signature[7:]  # Remove "sha256=" prefix
    computed_hash = hmac.new(WEBHOOK_SECRET, payload, hashlib.sha256).hexdigest()
    
    return hmac.compare_digest(computed_hash, expected_hash)


def log_event(event_type: str, action: str, data: Dict[str, Any]) -> None:
    """Log webhook event to file"""
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    log_file = logs / "webhook.log"
    
    log_entry = {
        "timestamp": int(time.time() * 1000),
        "event": event_type,
        "action": action,
        "data": data,
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(log_entry) + "\n")


def _run_monitor_once() -> None:
    """Run monitor.py --once synchronously."""
    monitor_script = monitor_script_path()
    
    if not monitor_script.exists():
        print(f"[ERROR] Monitor script not found: {monitor_script}")
        return
    
    try:
        # Run monitor in --once mode
        subprocess.run(
            ["python3", str(monitor_script), "--once"],
            cwd=str(base_dir()),
            capture_output=True,
            text=True,
            timeout=60,
        )
        print("[INFO] Monitor triggered successfully")
    except subprocess.TimeoutExpired:
        print("[WARN] Monitor timed out")
    except Exception as e:
        print(f"[ERROR] Failed to trigger monitor: {e}")


def trigger_monitor() -> None:
    """Queue monitor execution without blocking the webhook HTTP response."""
    MONITOR_EXECUTOR.submit(_run_monitor_once)


def handle_check_run(payload: Dict[str, Any]) -> None:
    """
    Handle check_run event
    
    Event: check_run.completed
    Action: Update task status if checks passed/failed
    """
    check_run = payload.get("check_run", {})
    action = payload.get("action", "")
    conclusion = check_run.get("conclusion", "")
    status = check_run.get("status", "")
    head_branch = check_run.get("head_branch", "")
    check_name = check_run.get("name", "")
    html_url = check_run.get("html_url", "")
    
    print(f"[INFO] check_run.{action}: {check_name} on {head_branch} - {conclusion}")
    
    log_event("check_run", action, {
        "branch": head_branch,
        "check_name": check_name,
        "conclusion": conclusion,
        "status": status,
        "url": html_url,
    })
    
    if action != "completed":
        return
    
    # Find task by branch
    task = get_task_by_branch(f"feat/{head_branch}") or get_task_by_branch(head_branch)
    if not task:
        print(f"[INFO] No task found for branch: {head_branch}")
        return
    
    task_id = task.get("id")
    print(f"[INFO] Found task: {task_id}")
    
    # Trigger monitor to check all tasks
    trigger_monitor()


def handle_workflow_run(payload: Dict[str, Any]) -> None:
    """
    Handle workflow_run event
    
    Event: workflow_run.completed
    Action: Update task status if workflow passed/failed
    """
    workflow_run = payload.get("workflow_run", {})
    action = payload.get("action", "")
    conclusion = workflow_run.get("conclusion", "")
    status = workflow_run.get("status", "")
    head_branch = workflow_run.get("head_branch", "")
    workflow_name = workflow_run.get("name", "")
    html_url = workflow_run.get("html_url", "")
    run_id = workflow_run.get("id", "")
    
    print(f"[INFO] workflow_run.{action}: {workflow_name} on {head_branch} - {conclusion}")
    
    log_event("workflow_run", action, {
        "branch": head_branch,
        "workflow_name": workflow_name,
        "conclusion": conclusion,
        "status": status,
        "run_id": run_id,
        "url": html_url,
    })
    
    if action != "completed":
        return
    
    # Find task by branch
    task = get_task_by_branch(f"feat/{head_branch}") or get_task_by_branch(head_branch)
    if not task:
        print(f"[INFO] No task found for branch: {head_branch}")
        return
    
    task_id = task.get("id")
    print(f"[INFO] Found task: {task_id}")
    
    # Trigger monitor to check all tasks
    trigger_monitor()


def handle_pull_request(payload: Dict[str, Any]) -> None:
    """
    Handle pull_request event
    
    Event: pull_request.opened, pull_request.closed, etc.
    Action: Update task PR info
    """
    pr = payload.get("pull_request", {})
    action = payload.get("action", "")
    head_branch = pr.get("head", {}).get("ref", "")
    pr_number = pr.get("number", "")
    pr_url = pr.get("html_url", "")
    state = pr.get("state", "")
    merged = pr.get("merged", False)
    
    print(f"[INFO] pull_request.{action}: #{pr_number} on {head_branch} - {state}")
    
    log_event("pull_request", action, {
        "branch": head_branch,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "state": state,
        "merged": merged,
    })
    
    # Find task by branch
    task = get_task_by_branch(f"feat/{head_branch}") or get_task_by_branch(head_branch)
    if not task:
        print(f"[INFO] No task found for branch: {head_branch}")
        return
    
    task_id = task.get("id")
    print(f"[INFO] Found task: {task_id}")
    
    # Update task with PR info
    if action == "opened":
        update_task(task_id, {
            "pr_number": pr_number,
            "pr_url": pr_url,
            "status": "pr_created",
        })
        print(f"[INFO] Updated task {task_id} with PR info")
    elif action == "closed":
        if merged:
            update_task(task_id, {
                "status": "merged",
                "note": f"PR #{pr_number} merged",
            })
            print(f"[INFO] Task {task_id} marked as merged")
        else:
            update_task(task_id, {
                "status": "pr_closed",
                "note": f"PR #{pr_number} closed without merge",
            })
            print(f"[INFO] Task {task_id} marked as PR closed")
    
    # Trigger monitor
    trigger_monitor()


class GitHubWebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for GitHub webhooks"""
    
    def do_POST(self):
        """Handle POST requests from GitHub"""
        # Get headers
        content_length = int(self.headers.get("Content-Length", 0))
        signature = self.headers.get("X-Hub-Signature-256", "")
        event_type = self.headers.get("X-GitHub-Event", "")
        
        # Read body
        body = self.rfile.read(content_length)
        
        # Verify signature
        if not verify_signature(body, signature):
            print(f"[WARN] Invalid signature from {self.client_address}")
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Invalid signature")
            return
        
        # Parse payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            self.send_response(400)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return
        
        # Route to handler
        print(f"[INFO] Received {event_type} event from {self.client_address}")
        
        try:
            if event_type == "check_run":
                handle_check_run(payload)
            elif event_type == "workflow_run":
                handle_workflow_run(payload)
            elif event_type == "pull_request":
                handle_pull_request(payload)
            else:
                print(f"[INFO] Ignoring event type: {event_type}")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            
        except Exception as e:
            print(f"[ERROR] Error handling event: {e}")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Internal error: {e}".encode())
    
    def do_GET(self):
        """Health check endpoint"""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = {
                "status": "healthy",
                "timestamp": int(time.time() * 1000),
                "base_dir": str(base_dir()),
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Not found")
    
    def log_message(self, format, *args):
        """Override to customize logging"""
        print(f"[HTTP] {self.client_address[0]} - {format % args}")


def run_server(port: int, daemon: bool = False) -> None:
    """Run the webhook server"""
    # Initialize database
    init_db()
    
    server = HTTPServer(("0.0.0.0", port), GitHubWebhookHandler)
    print(f"{'='*60}")
    print(f"GitHub Webhook Server")
    print(f"{'='*60}")
    print(f"Listening on: http://0.0.0.0:{port}")
    print(f"Base directory: {base_dir()}")
    print(f"Log file: {log_dir() / 'webhook.log'}")
    print(f"Secret configured: {'Yes' if WEBHOOK_SECRET else 'No'}")
    print(f"{'='*60}")
    print()
    print("Endpoints:")
    print(f"  POST / - GitHub webhook events")
    print(f"  GET  /health - Health check")
    print()
    print("Supported events:")
    print("  - check_run (completed)")
    print("  - workflow_run (completed)")
    print("  - pull_request (opened, closed)")
    print()
    
    if daemon:
        print("Running in daemon mode (background)...")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down server...")
        server.shutdown()


def main():
    parser = argparse.ArgumentParser(
        description="GitHub Webhook Receiver for AI DevOps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in foreground
  python webhook_server.py --port 8080 --secret my-secret

  # Run in background (daemon)
  python webhook_server.py --port 8080 --secret my-secret --daemon

  # Use environment variable for secret
  export GITHUB_WEBHOOK_SECRET=my-secret
  python webhook_server.py --port 8080

GitHub Configuration:
  1. Go to repository Settings → Webhooks → Add webhook
  2. Payload URL: http://<your-server>:8080/
  3. Content type: application/json
  4. Secret: <your-secret>
  5. Events: Select 'Check runs', 'Workflow runs', 'Pull requests'
  6. Click 'Add webhook'
        """
    )
    
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--secret", default="", help="Webhook secret (or use GITHUB_WEBHOOK_SECRET env)")
    parser.add_argument("--daemon", action="store_true", help="Run in background (daemon mode)")
    
    args = parser.parse_args()
    
    # Set secret from argument
    if args.secret:
        global WEBHOOK_SECRET
        WEBHOOK_SECRET = args.secret.encode()
    
    # Ensure log directory exists
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)

    if not WEBHOOK_SECRET:
        print("[ERROR] Webhook secret is required. Set --secret or GITHUB_WEBHOOK_SECRET.")
        sys.exit(2)
    
    # Run server
    run_server(args.port, daemon=args.daemon)


if __name__ == "__main__":
    main()
