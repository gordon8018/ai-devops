#!/usr/bin/env python3
"""
Agent CLI - AI DevOps 统一命令入口

Usage:
    agent spawn --repo <repo> --title <title> [--agent codex] [--model gpt-5.3-codex]
    agent list [--status running] [--limit 10]
    agent status <task-id>
    agent send <task-id> <message>
    agent kill <task-id>
    agent plan --repo <repo> --title <title> --description <desc>
    agent dispatch --plan <plan-file>
    agent retry <task-id>
"""

import argparse
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# 路径初始化
SCRIPT_DIR = Path(__file__).parent.absolute()

# 添加 orchestrator 到导入路径
sys.path.insert(0, str(SCRIPT_DIR))

from db import (
    init_db,
    insert_task,
    get_task,
    get_running_tasks,
    get_all_tasks,
    update_task,
    update_task_status,
    delete_task,
    count_running_tasks,
)
from agent_utils import (
    base_dir,
    queue_root,
    generate_task_id,
    print_table,
    format_timestamp,
    print_task_detail,
)

# 导入消息总线
try:
    from message_bus import get_message_bus, Message
except ImportError:
    from orchestrator.bin.message_bus import get_message_bus, Message


# 延迟导入 zoe_tools（仅在 plan/dispatch 命令需要）
def get_zoe_tools():
    import zoe_tools
    return zoe_tools


# Lazy import — only needed for plan-status/plans commands
def _get_plan_status_modules():
    import plan_status as _ps
    import plan_status_renderer as _psr
    import plan_status_server as _pss
    return _ps, _psr, _pss


# ============================================================================
# 命令实现
# ============================================================================

def cmd_init(args):
    """初始化数据库"""
    init_db()
    print("✓ Database initialized")
    print(f"  Location: {base_dir() / '.clawdbot' / 'agent_tasks.db'}")


def cmd_spawn(args):
    """创建新任务"""
    init_db()
    
    task_id = generate_task_id(args.repo, args.title)
    task = {
        "id": task_id,
        "repo": args.repo,
        "title": args.title,
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
        "status": "queued",
        "metadata": {
            "description": args.description or "",
            "files_hint": args.files.split(",") if args.files else [],
        }
    }
    
    insert_task(task)
    
    # 写入队列
    queue_dir = queue_root()
    queue_dir.mkdir(parents=True, exist_ok=True)
    queue_path = queue_dir / f"{task_id}.json"
    queue_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
    
    print(f"✓ Task spawned: {task_id}")
    print(f"  Repo: {args.repo}")
    print(f"  Title: {args.title}")
    print(f"  Agent: {task['agent']} ({task['model']})")
    print(f"  Queue: {queue_path}")


def cmd_list(args):
    """列出任务"""
    init_db()
    
    if args.status == "running":
        tasks = get_running_tasks()
    elif args.status == "queued":
        # 排队任务位于 queue/*.json
        queue_dir = queue_root()
        tasks = []
        if queue_dir.exists():
            for p in queue_dir.glob("*.json"):
                try:
                    task = json.loads(p.read_text())
                    tasks.append(task)
                except Exception:
                    pass
    elif args.status == "all":
        tasks = get_all_tasks(limit=args.limit)
    else:
        tasks = get_all_tasks(limit=args.limit)
    
    print(f"\n{'='*60}")
    print(f"Tasks ({len(tasks)} found)")
    print(f"{'='*60}\n")
    
    if args.json:
        print(json.dumps(tasks, indent=2))
    else:
        print_table(tasks, columns=["id", "status", "repo", "title", "agent", "started_at"])


def cmd_status(args):
    """查看任务状态"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if args.json:
        print(json.dumps(task, indent=2))
    else:
        print_task_detail(task)


def cmd_send(args):
    """通过会话管理工具向运行中的任务发送消息"""
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    session = task.get("tmux_session") or task.get("tmuxSession")
    if not session:
        print(f"✗ Cannot send: no tmux session for {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if not shutil.which("tmux"):
        print("✗ tmux not found", file=sys.stderr)
        sys.exit(1)
    
    # 向 tmux 会话发送按键
    subprocess.run(["tmux", "send-keys", "-t", session, args.message, "Enter"])
    print(f"✓ Message sent to {args.task_id} (tmux: {session})")


def cmd_kill(args):
    """终止运行中的任务"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    status = task.get("status")
    if status not in ("running", "pr_created", "retrying"):
        print(f"⚠ Task is not running (status: {status})")
    
    # 结束 tmux 会话
    session = task.get("tmux_session") or task.get("tmuxSession")
    if session and shutil.which("tmux"):
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True)
        print(f"✓ tmux session killed: {session}")
    
    # 结束进程：先发 SIGTERM，等待 3 秒后若进程仍存活再发 SIGKILL
    process_id = task.get("process_id") or task.get("processId")
    if isinstance(process_id, int) and process_id > 0:
        try:
            os.kill(process_id, signal.SIGTERM)
            time.sleep(3)
            try:
                os.kill(process_id, 0)  # 检查进程是否仍存活
                os.kill(process_id, signal.SIGKILL)
            except OSError:
                pass  # SIGTERM 后已退出
            print(f"✓ Process killed: {process_id}")
        except OSError as e:
            print(f"⚠ Process already dead: {e}")
    
    # 更新状态
    update_task_status(args.task_id, "killed", "killed by user")
    print(f"✓ Task killed: {args.task_id}")


def cmd_plan(args):
    """仅规划任务，不下发执行"""
    init_db()
    
    task_input = {
        "repo": args.repo,
        "title": args.title,
        "description": args.description,
        "requested_by": args.user or "cli",
        "requested_at": int(time.time() * 1000),
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
    }
    
    if args.files:
        task_input["context"] = {"filesHint": args.files.split(",")}
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.plan_task(task_input)
        print(f"✓ Plan created: {result.plan.plan_id}")
        print(f"  Subtasks: {len(result.plan.subtasks)}")
        print(f"  Plan file: {result.plan_path}")
        
        if not args.quiet:
            print("\nSubtasks:")
            for i, subtask in enumerate(result.plan.subtasks):
                print(f"  {subtask.id}: {subtask.title}")
                if subtask.depends_on:
                    print(f"         Depends: {', '.join(subtask.depends_on)}")
    except Exception as e:
        print(f"✗ Plan failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_dispatch(args):
    """下发已存在的计划"""
    init_db()
    
    plan_path = Path(args.plan_file)
    if not plan_path.exists():
        print(f"✗ Plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.dispatch_plan(plan_path)
        print(f"✓ Dispatched: {len(result.queued_paths)} tasks queued")
        for path in result.queued_paths:
            print(f"  - {path}")
    except Exception as e:
        print(f"✗ Dispatch failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_plan_and_dispatch(args):
    """一步完成规划与下发"""
    init_db()
    
    task_input = {
        "repo": args.repo,
        "title": args.title,
        "description": args.description,
        "requested_by": args.user or "cli",
        "requested_at": int(time.time() * 1000),
        "agent": args.agent or "codex",
        "model": args.model or "gpt-5.3-codex",
        "effort": args.effort or "medium",
    }
    
    if args.files:
        task_input["context"] = {"filesHint": args.files.split(",")}
    
    try:
        zoe_tools = get_zoe_tools()
        result = zoe_tools.plan_and_dispatch_task(task_input)
        print(f"✓ Plan created: {result.plan.plan_id}")
        print(f"  Subtasks: {len(result.plan.subtasks)}")
        print(f"  Queued: {len(result.queued_paths)} tasks")
        for path in result.queued_paths:
            print(f"  - {path}")
    except Exception as e:
        print(f"✗ Failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_retry(args):
    """重试失败任务"""
    init_db()
    
    task = get_task(args.task_id)
    if not task:
        print(f"✗ Task not found: {args.task_id}", file=sys.stderr)
        sys.exit(1)
    
    if task.get("status") not in ("blocked", "agent_failed", "timeout", "log_stale"):
        print(f"⚠ Task status is {task.get('status')}, not a retry candidate")
        if not args.force:
            print("Use --force to retry anyway")
            sys.exit(1)
    
    # 重置状态与重试次数
    update_task(args.task_id, {
        "status": "queued",
        "attempts": 0,
        "note": "retried by user"
    })
    
    # 重新入队
    queue_dir = queue_root()
    queue_dir.mkdir(parents=True, exist_ok=True)
    
    task_data = {
        "id": task["id"],
        "repo": task["repo"],
        "title": task["title"],
        "agent": task.get("agent", "codex"),
        "model": task.get("model", "gpt-5.3-codex"),
        "effort": task.get("effort", "medium"),
        "status": "queued",
    }
    
    queue_path = queue_dir / f"{task['id']}.json"
    queue_path.write_text(json.dumps(task_data, indent=2), encoding="utf-8")
    
    print(f"✓ Task queued for retry: {args.task_id}")
    print(f"  Queue: {queue_path}")


def cmd_clean(args):
    """清理旧任务"""
    init_db()
    
    from db import get_db
    
    cutoff_days = args.days
    cutoff_ms = int((time.time() - cutoff_days * 86400) * 1000)
    
    _TERMINAL_STATUSES = (
        "ready", "killed", "agent_exited",
        "merged", "pr_closed", "needs_rebase",
        "blocked", "agent_dead", "agent_failed",
        "timeout", "log_stale",
    )
    placeholders = ",".join("?" * len(_TERMINAL_STATUSES))
    with get_db() as conn:
        cursor = conn.execute(
            f"SELECT id, status, created_at FROM agent_tasks "
            f"WHERE created_at < ? AND status IN ({placeholders})",
            (cutoff_ms, *_TERMINAL_STATUSES),
        )
        old_tasks = cursor.fetchall()
    
    if not old_tasks:
        print(f"No tasks older than {cutoff_days} days to clean")
        return
    
    print(f"Found {len(old_tasks)} tasks older than {cutoff_days} days:")
    for task_id, status, created_at in old_tasks:
        print(f"  {task_id} ({status})")
    
    if not args.dry_run:
        for task_id, _, _ in old_tasks:
            delete_task(task_id)
        print(f"✓ Deleted {len(old_tasks)} tasks")
    else:
        print(f"\nDry run - use without --dry-run to delete")


def cmd_plan_status(args):
    """Display plan status with rich TUI."""
    init_db()
    ps, psr, pss = _get_plan_status_modules()

    server = None
    if args.html:
        server = pss.PlanStatusServer(plan_id=args.plan_id)
        url = server.start(open_browser=True)
        print(f"✓ Dashboard: {url}")
        if args.no_tui:
            print("Press Ctrl+C to stop server.")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                server.stop()
                return

    try:
        psr.watch_plan(
            args.plan_id,
            interval=args.interval,
            once=not args.watch,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.stop()


def cmd_plans(args):
    """List recent plans with progress summary."""
    init_db()
    ps, psr, _ = _get_plan_status_modules()

    views = ps.list_plan_views(limit=args.limit)
    if not views:
        print("No plans found.")
        return

    from agent_utils import format_timestamp
    header = f"{'PLAN-ID':<35} {'PROGRESS':<10} {'STATUS':<12} {'REPO':<25} STARTED"
    print(header)
    print("-" * len(header))
    for pv in views:
        active_statuses = {s.status for s in pv.subtasks}
        if "running" in active_statuses or "retrying" in active_statuses:
            overall = "running"
        elif all(s.status in ("ready", "merged") for s in pv.subtasks) and pv.subtasks:
            overall = "done"
        elif any(s.status == "blocked" for s in pv.subtasks):
            overall = "blocked"
        else:
            overall = "partial"
        started = format_timestamp(pv.requested_at)[:16] if pv.requested_at else "—"
        print(
            f"{pv.plan_id:<35} {pv.completed_count}/{pv.total_count:<8} "
            f"{overall:<12} {pv.repo:<25} {started}"
        )




def cmd_message(args):
    """通过消息总线发送消息"""
    init_db()
    
    bus = get_message_bus()
    
    # 发送消息
    message_id = bus.send_message(
        from_agent=args.from_agent or "cli",
        to_agent=args.to_agent,
        content={"text": args.content},
        topic=args.topic
    )
    
    print(f"✓ Message sent: {message_id}")
    print(f"  From: {args.from_agent or 'cli'}")
    print(f"  To: {args.to_agent}")
    print(f"  Topic: {args.topic or 'N/A'}")
    print(f"  Content: {args.content}")


def cmd_messages(args):
    """接收消息"""
    init_db()
    
    bus = get_message_bus()
    agent_id = args.agent or "cli"
    
    # 接收消息
    messages = bus.receive_messages(agent_id, limit=args.limit)
    
    if not messages:
        print(f"No pending messages for {agent_id}")
        return
    
    print(f"\n{'='*60}")
    print(f"Messages for {agent_id} ({len(messages)} pending)")
    print(f"{'='*60}\n")
    
    for msg in messages:
        print(f"ID: {msg.message_id}")
        print(f"From: {msg.from_agent}")
        print(f"Topic: {msg.topic or 'N/A'}")
        print(f"Time: {format_timestamp(msg.timestamp)}")
        print(f"Content: {msg.content}")
        print("-" * 60)


def cmd_message_list(args):
    """列出所有消息"""
    init_db()
    
    from db import get_all_messages
    
    messages = get_all_messages(limit=args.limit)
    
    if not messages:
        print("No messages found.")
        return
    
    print(f"\n{'='*80}")
    print(f"Recent Messages ({len(messages)} found)")
    print(f"{'='*80}\n")
    
    for msg in messages:
        delivered = "✓" if msg.get("delivered") else "✗"
        print(f"[{delivered}] {msg['message_id']}")
        print(f"    {msg['from_agent']} -> {msg['to_agent']}")
        print(f"    Topic: {msg.get('topic') or 'N/A'}")
        print(f"    Time: {format_timestamp(msg['timestamp'])}")
        print(f"    Content: {msg.get('content')}")
        print()

# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog="agent",
        description="AI DevOps Agent CLI - Unified command interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agent spawn --repo my-repo --title "Fix auth bug"
  agent list --status running
  agent status 1234567890-my-repo-fix-auth-bug-S1
  agent send 1234567890-my-repo-fix-auth-bug-S1 "please check line 42"
  agent kill 1234567890-my-repo-fix-auth-bug-S1
  agent plan --repo my-repo --title "Add tests" --description "Add unit tests"
  agent dispatch --plan ~/ai-devops/tasks/xxx/plan.json
  agent retry 1234567890-my-repo-fix-auth-bug-S1
  agent clean --days 30 --dry-run
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")
    
    # 初始化
    p = subparsers.add_parser("init", help="Initialize the database")
    p.set_defaults(func=cmd_init)
    
    # 创建任务
    p = subparsers.add_parser("spawn", help="Spawn a new task")
    p.add_argument("--repo", required=True, help="Repository name")
    p.add_argument("--title", required=True, help="Task title")
    p.add_argument("--description", help="Task description")
    p.add_argument("--agent", default="codex", choices=["codex", "claude"])
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium", choices=["low", "medium", "high"])
    p.add_argument("--files", help="Comma-separated file hints")
    p.set_defaults(func=cmd_spawn)
    
    # 列表
    p = subparsers.add_parser("list", help="List tasks")
    p.add_argument("--status", default="all", choices=["all", "running", "queued", "ready", "blocked"])
    p.add_argument("--limit", type=int, default=20, help="Max tasks to show")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_list)
    
    # 状态
    p = subparsers.add_parser("status", help="Show task status")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_status)
    
    # 发送消息
    p = subparsers.add_parser("send", help="Send message to running agent")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("message", help="Message to send")
    p.set_defaults(func=cmd_send)
    
    # 终止任务
    p = subparsers.add_parser("kill", help="Kill running task")
    p.add_argument("task_id", help="Task ID")
    p.set_defaults(func=cmd_kill)
    
    # 规划
    p = subparsers.add_parser("plan", help="Plan a task without dispatching")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--user", default="cli")
    p.add_argument("--agent", default="codex")
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium")
    p.add_argument("--files", help="Comma-separated file hints")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_plan)
    
    # 下发
    p = subparsers.add_parser("dispatch", help="Dispatch existing plan")
    p.add_argument("--plan", dest="plan_file", required=True, help="Path to plan.json")
    p.set_defaults(func=cmd_dispatch)
    
    # 规划并下发
    p = subparsers.add_parser("plan-and-dispatch", help="Plan and dispatch in one command")
    p.add_argument("--repo", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--user", default="cli")
    p.add_argument("--agent", default="codex")
    p.add_argument("--model", default="gpt-5.3-codex")
    p.add_argument("--effort", default="medium")
    p.add_argument("--files", help="Comma-separated file hints")
    p.add_argument("--quiet", "-q", action="store_true")
    p.set_defaults(func=cmd_plan_and_dispatch)
    
    # 重试
    p = subparsers.add_parser("retry", help="Retry a failed task")
    p.add_argument("task_id", help="Task ID")
    p.add_argument("--force", "-f", action="store_true")
    p.set_defaults(func=cmd_retry)
    
    # 清理
    p = subparsers.add_parser("clean", help="Clean up old tasks")
    p.add_argument("--days", type=int, default=30, help="Delete tasks older than N days")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_clean)

    # plan 状态
    p = subparsers.add_parser("plan-status", help="Show plan execution status (TUI + optional browser)")
    p.add_argument("plan_id", help="Plan ID")
    p.add_argument("--watch", action="store_true", help="Auto-refresh TUI")
    p.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds")
    p.add_argument("--html", action="store_true", help="Open browser dashboard")
    p.add_argument("--no-tui", action="store_true", dest="no_tui", help="Skip terminal TUI (browser only)")
    p.set_defaults(func=cmd_plan_status)

    # 列出 plans
    p = subparsers.add_parser("plans", help="List recent plans with progress summary")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_plans)


    # 发送消息
    p = subparsers.add_parser("message", help="Send message to another agent")
    p.add_argument("to_agent", help="Target agent ID")
    p.add_argument("content", help="Message content")
    p.add_argument("--from", dest="from_agent", help="Sender agent ID (default: cli)")
    p.add_argument("--topic", help="Message topic")
    p.set_defaults(func=cmd_message)

    # 接收消息
    p = subparsers.add_parser("messages", help="Receive messages for an agent")
    p.add_argument("--agent", help="Agent ID (default: cli)")
    p.add_argument("--limit", type=int, default=10, help="Max messages to retrieve")
    p.set_defaults(func=cmd_messages)

    # 列出所有消息
    p = subparsers.add_parser("msg-list", help="List all recent messages")
    p.add_argument("--limit", type=int, default=20, help="Max messages to show")
    p.set_defaults(func=cmd_message_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
