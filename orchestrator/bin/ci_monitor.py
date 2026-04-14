#!/usr/bin/env python3
"""CI/CD Monitor - Tracks CI/CD pipeline status"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ralph_state import RalphState
except ImportError:
    from orchestrator.bin.ralph_state import RalphState

class CIMonitorError(Exception):
    pass

class CIMonitor:
    def __init__(self, db_path=None):
        self.state = RalphState(db_path)
        self.poll_interval = 30
        self.timeout = 3600

    def check_github_actions(self, branch: str) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["gh", "run", "list", "--branch", branch, "--limit", "5", "--json", "conclusion,status,name,databaseId,createdAt,displayTitle"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return {"platform": "github", "status": "error", "error": "Failed to fetch"}
            if not result.stdout.strip():
                return {"platform": "github", "status": "no_runs"}
            runs = json.loads(result.stdout)
            if not runs:
                return {"platform": "github", "status": "no_runs"}
            latest = runs[0]
            check_results = self._get_check_results(latest.get("databaseId"))
            return {
                "platform": "github",
                "status": latest.get("conclusion") or latest.get("status"),
                "all_passed": latest.get("conclusion") == "success",
                "run_id": latest.get("databaseId"),
                "run_name": latest.get("displayTitle"),
                "checks": check_results
            }
        except Exception as e:
            return {"platform": "github", "status": "error", "error": str(e)}

    def _get_check_results(self, run_id: int) -> List[Dict]:
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/checks"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return []
            data = json.loads(result.stdout)
            return [{"name": c.get("name"), "conclusion": c.get("conclusion"), "status": c.get("status")} for c in data.get("check_runs", [])]
        except:
            return []

def main():
    if len(sys.argv) < 2:
        print("Usage: ci_monitor.py check <branch>")
        sys.exit(0)
    monitor = CIMonitor()
    if sys.argv[1] == "check":
        result = monitor.check_github_actions(sys.argv[2])
        print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
