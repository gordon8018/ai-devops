"""Tmux 会话管理器 - 用于监控和恢复 ai-devops Agent 会话
SECURITY FIX: 修复命令注入漏洞 (P0)
"""
from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

try:
    from .config import agent_scripts_dir
except ImportError:
    from config import agent_scripts_dir


# ============================================================================
# 输入验证 - 白名单验证
# ============================================================================

ALLOWED_AGENTS = frozenset(["claude", "codex"])
ALLOWED_EFFORTS = frozenset(["low", "medium", "high"])
TASK_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')
SESSION_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_:-]{1,256}$')
PROMPT_FILENAME_PATTERN = re.compile(r'^[a-zA-Z0-9_./-]{1,512}$')


def validate_agent(agent: str) -> Tuple[bool, str]:
    if not agent:
        return (False, "agent cannot be empty")
    if agent not in ALLOWED_AGENTS:
        return (False, f"invalid agent: {agent}")
    return (True, "")


def validate_task_id(task_id: str) -> Tuple[bool, str]:
    if not task_id:
        return (False, "task_id cannot be empty")
    if not TASK_ID_PATTERN.match(task_id):
        return (False, "invalid task_id format")
    return (True, "")


def validate_effort(effort: str) -> Tuple[bool, str]:
    if not effort:
        return (False, "effort cannot be empty")
    if effort not in ALLOWED_EFFORTS:
        return (False, f"invalid effort: {effort}")
    return (True, "")


def validate_prompt_filename(filename: str) -> Tuple[bool, str]:
    if not filename:
        return (False, "prompt_filename cannot be empty")
    if not PROMPT_FILENAME_PATTERN.match(filename):
        return (False, "invalid prompt_filename format")
    if '..' in filename:
        return (False, "path traversal detected")
    return (True, "")


def validate_session_name(session_name: str) -> Tuple[bool, str]:
    if not session_name:
        return (False, "session_name cannot be empty")
    if not SESSION_NAME_PATTERN.match(session_name):
        return (False, "invalid session_name format")
    return (True, "")


class TmuxManager:
    """管理 tmux 会话的生命周期，包括健康检查和重建"""
    
    def __init__(self, session_name: str, worktree: Path, runner_script: str):
        valid, err = validate_session_name(session_name)
        if not valid:
            raise ValueError(f"Invalid session_name: {err}")
        
        self.session_name = session_name
        self.worktree = worktree
        self.runner_script = runner_script
        self._last_check_time: float = 0
        self._last_health_status: bool = False
    
    @property
    def session_exists(self) -> bool:
        return self.check_session_exists()
    
    @property
    def is_healthy(self) -> bool:
        now = time.time()
        if now - self._last_check_time < 5:
            return self._last_health_status
        self._last_check_time = now
        self._last_health_status = self.check_health()
        return self._last_health_status
    
    def check_session_exists(self) -> bool:
        if not self._tmux_available():
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True, text=True, shell=False
        )
        return result.returncode == 0
    
    def _tmux_available(self) -> bool:
        result = subprocess.run(
            ["which", "tmux"],
            capture_output=True, text=True, shell=False
        )
        return result.returncode == 0
    
    def check_health(self) -> bool:
        if not self._tmux_available():
            return False
        if not self.check_session_exists():
            return False
        result = subprocess.run(
            ["tmux", "list-windows", "-t", self.session_name, "-F", "#W"],
            capture_output=True, text=True, shell=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        result = subprocess.run(
            ["tmux", "list-panes", "-t", self.session_name, "-F", "#S:#W.#P"],
            capture_output=True, text=True, shell=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        return True
    
    def get_session_info(self) -> Optional[dict]:
        if not self._tmux_available():
            return None
        if not self.check_session_exists():
            return None
        result = subprocess.run(
            ["tmux", "list-panels", "-t", self.session_name, "-F", 
             "window_name=#W,pane_pid=#P,pane_current_path=#{pane_current_path},pane_active=#{pane_active}"],
            capture_output=True, text=True, shell=False
        )
        if result.returncode != 0:
            return None
        panels = []
        for line in result.stdout.strip().split(chr(10)):
            if not line.strip():
                continue
            panel_info = {}
            for part in line.split(','):
                if '=' in part:
                    key, value = part.split('=', 1)
                    panel_info[key] = value
            panels.append(panel_info)
        return {"session_name": self.session_name, "panels": panels, "is_healthy": self.is_healthy}
    
    def create_session(self, cmd_args: Optional[List[str]] = None) -> bool:
        """创建新的 tmux 会话
        
        SECURITY FIX: 接收命令参数列表，而不是字符串
        """
        if not self._tmux_available():
            return False
        if self.check_session_exists():
            self.destroy_session()
        
        base_cmd = ["tmux", "new-session", "-d", "-s", self.session_name]
        
        if cmd_args:
            base_cmd.extend(cmd_args)
        
        result = subprocess.run(
            base_cmd, capture_output=True, text=True, shell=False
        )
        if result.returncode != 0:
            return False
        time.sleep(0.5)
        return self.check_session_exists()
    
    def destroy_session(self) -> bool:
        if not self._tmux_available():
            return False
        if not self.check_session_exists():
            return True
        result = subprocess.run(
            ["tmux", "kill-session", "-t", self.session_name],
            capture_output=True, text=True, shell=False
        )
        if result.returncode != 0:
            return False
        time.sleep(0.5)
        return not self.check_session_exists()
    
    def attach_session(self) -> bool:
        if not self._tmux_available():
            return False
        if not self.check_session_exists():
            return False
        result = subprocess.run(
            ["tmux", "attach-session", "-t", self.session_name],
            capture_output=True, text=True, shell=False
        )
        return result.returncode == 0
    
    def list_sessions(self) -> list[str]:
        if not self._tmux_available():
            return []
        result = subprocess.run(
            ["tmux", "list-sessions", "-F", "#S"],
            capture_output=True, text=True, shell=False
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.strip().split(chr(10)) if line.strip()]
    
    def run_command_in_session(self, cmd: str, window: Optional[str] = None) -> Tuple[bool, str, str]:
        if not self._tmux_available():
            return (False, "", "tmux not available")
        if not self.check_session_exists():
            return (False, "", f"session '{self.session_name}' does not exist")
        target = self.session_name
        if window:
            if not re.match(r'^[a-zA-Z0-9_-]{1,64}$', window):
                return (False, "", f"invalid window name: {window}")
            target = f"{self.session_name}:{window}"
        
        full_cmd = ["tmux", "send-keys", "-t", target, cmd, "Enter"]
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, shell=False
        )
        if result.returncode != 0:
            return (False, "", result.stderr)
        time.sleep(0.5)
        output_result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p"],
            capture_output=True, text=True, shell=False
        )
        return (True, output_result.stdout, output_result.stderr)
    
    def rebuild_session(self, agent: str, task_id: str, model: str, effort: str, prompt_filename: str) -> bool:
        """重建 tmux 会话
        
        SECURITY FIX: 
        - 所有外部参数使用 shlex.quote() 转义
        - 使用白名单验证输入参数
        - 使用列表形式传递命令，避免 shell 注入
        """
        # ========== 输入验证 ==========
        valid, err = validate_agent(agent)
        if not valid:
            raise ValueError(f"Invalid agent: {err}")
        
        valid, err = validate_task_id(task_id)
        if not valid:
            raise ValueError(f"Invalid task_id: {err}")
        
        valid, err = validate_effort(effort)
        if not valid:
            raise ValueError(f"Invalid effort: {err}")
        
        valid, err = validate_prompt_filename(prompt_filename)
        if not valid:
            raise ValueError(f"Invalid prompt_filename: {err}")
        
        # ========== 确定 runner 脚本 ==========
        if agent == "claude":
            runner = str(agent_scripts_dir() / "run-claude-agent.sh")
            default_model = "claude-sonnet-4"
        else:  # agent == "codex"
            runner = str(agent_scripts_dir() / "run-codex-agent.sh")
            default_model = "gpt-5.3-codex"
        
        runner_path = Path(runner)
        if not runner_path.exists():
            raise RuntimeError(f"Runner not found for agent {agent}: {runner}")
        
        model = model or default_model
        
        if self.check_session_exists():
            self.destroy_session()
        
        # ========== SECURITY FIX: 构建安全的命令 ==========
        # 使用 shlex.quote() 转义所有外部参数
        safe_runner = shlex.quote(runner)
        safe_task_id = shlex.quote(task_id)
        safe_model = shlex.quote(model)
        safe_effort = shlex.quote(effort)
        safe_worktree = shlex.quote(str(self.worktree))
        safe_prompt_filename = shlex.quote(prompt_filename)
        
        # 构建安全的命令字符串
        safe_cmd_string = f"{safe_runner} {safe_task_id} {safe_model} {safe_effort} {safe_worktree} {safe_prompt_filename}"
        
        # 使用 sh -c 执行转义后的命令
        cmd_args = ["sh", "-c", safe_cmd_string]
        
        return self.create_session(cmd_args)
    
    def safe_rebuild(self, agent: str, task_id: str, model: str, effort: str, prompt_filename: str) -> Tuple[bool, str]:
        """安全的重建方法，捕获所有异常"""
        try:
            if not self._tmux_available():
                return (False, "tmux not available on this system")
            current_info = self.get_session_info()
            if current_info and current_info.get("is_healthy"):
                return (True, "session already healthy")
            success = self.rebuild_session(agent, task_id, model, effort, prompt_filename)
            if success:
                return (True, "session rebuilt successfully")
            else:
                return (False, "failed to rebuild session")
        except ValueError as e:
            return (False, f"validation error: {str(e)}")
        except Exception as e:
            return (False, f"exception during rebuild: {str(e)}")


# ============================================================================
# 单元测试
# ============================================================================

def run_security_tests():
    """运行安全修复的单元测试"""
    print("=" * 70)
    print("TmuxManager Security Fix - Unit Tests")
    print("=" * 70)
    
    tests_passed = 0
    tests_failed = 0
    
    # 测试输入验证
    print("\n[TEST] Input Validation")
    
    # 测试 validate_agent
    test_cases = [
        ("claude", True),
        ("codex", True),
        ("", False),
        ("invalid", False),
        ("claude; rm -rf /", False),
    ]
    
    for agent, expected in test_cases:
        valid, _ = validate_agent(agent)
        if valid == expected:
            print(f"  PASS: validate_agent({repr(agent)})")
            tests_passed += 1
        else:
            print(f"  FAIL: validate_agent({repr(agent)}) - expected {expected}, got {valid}")
            tests_failed += 1
    
    # 测试 validate_task_id
    test_cases = [
        ("task-123", True),
        ("task_456", True),
        ("", False),
        ("task; rm -rf /", False),
        ("task$(whoami)", False),
        ("task`id`", False),
    ]
    
    for task_id, expected in test_cases:
        valid, _ = validate_task_id(task_id)
        if valid == expected:
            print(f"  PASS: validate_task_id({repr(task_id)})")
            tests_passed += 1
        else:
            print(f"  FAIL: validate_task_id({repr(task_id)}) - expected {expected}, got {valid}")
            tests_failed += 1
    
    # 测试 validate_effort
    test_cases = [
        ("low", True),
        ("medium", True),
        ("high", True),
        ("", False),
        ("extreme", False),
    ]
    
    for effort, expected in test_cases:
        valid, _ = validate_effort(effort)
        if valid == expected:
            print(f"  PASS: validate_effort({repr(effort)})")
            tests_passed += 1
        else:
            print(f"  FAIL: validate_effort({repr(effort)}) - expected {expected}, got {valid}")
            tests_failed += 1
    
    # 测试 validate_prompt_filename
    test_cases = [
        ("prompt.txt", True),
        ("prompts/task.md", True),
        ("", False),
        ("../../../etc/passwd", False),
    ]
    
    for filename, expected in test_cases:
        valid, _ = validate_prompt_filename(filename)
        if valid == expected:
            print(f"  PASS: validate_prompt_filename({repr(filename)})")
            tests_passed += 1
        else:
            print(f"  FAIL: validate_prompt_filename({repr(filename)}) - expected {expected}, got {valid}")
            tests_failed += 1
    
    # 测试 shlex.quote()
    print("\n[TEST] shlex.quote() Escaping")
    
    test_cases = [
        "normal",
        "task; rm -rf /",
        "task$(whoami)",
        "task`id`",
    ]
    
    for input_val in test_cases:
        quoted = shlex.quote(input_val)
        if "'" in quoted:
            print(f"  PASS: shlex.quote({repr(input_val)}) = {quoted}")
            tests_passed += 1
        else:
            print(f"  FAIL: shlex.quote({repr(input_val)}) = {quoted}")
            tests_failed += 1
    
    # 测试 TmuxManager 初始化
    print("\n[TEST] TmuxManager Initialization")
    
    import tempfile
    
    test_cases = [
        ("valid-session", True),
        ("session; rm -rf /", False),
        ("session$(whoami)", False),
    ]
    
    for session_name, expected_valid in test_cases:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                tm = TmuxManager(session_name, Path(tmpdir), "runner.sh")
                valid = True
        except ValueError:
            valid = False
        
        if valid == expected_valid:
            print(f"  PASS: TmuxManager(session_name={repr(session_name)})")
            tests_passed += 1
        else:
            print(f"  FAIL: TmuxManager(session_name={repr(session_name)}) - expected {expected_valid}, got {valid}")
            tests_failed += 1
    
    # 总结
    print("\n" + "=" * 70)
    print(f"Tests Passed: {tests_passed}")
    print(f"Tests Failed: {tests_failed}")
    print("=" * 70)
    
    return tests_failed == 0


if __name__ == "__main__":
    import sys
    success = run_security_tests()
    sys.exit(0 if success else 1)
