#!/usr/bin/env python3
import sys, os, tempfile
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from ci_monitor import CIMonitor
except:
    from orchestrator.bin.ci_monitor import CIMonitor

def test_ci_monitor_init():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        monitor = CIMonitor(db_path)
        assert monitor.state is not None
        print("✓ test_ci_monitor_init passed")

def test_ci_monitor_check_github_actions():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        monitor = CIMonitor(db_path)
        result = monitor.check_github_actions("test-branch")
        assert "platform" in result
        print("✓ test_ci_monitor_check_github_actions passed")

def run_all_tests():
    print("Running ci_monitor tests...")
    print()
    test_ci_monitor_init()
    test_ci_monitor_check_github_actions()
    print()
    print("All ci_monitor tests passed!")

if __name__ == "__main__":
    run_all_tests()
