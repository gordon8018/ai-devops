#!/usr/bin/env python3
"""
Zoe Daemon - Queue consumer and agent spawner

Consumes tasks from queue/, creates worktrees, and spawns coding agents.
"""

import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional
import sys

try:
    from .config import ai_devops_home, queue_dir, repos_dir, worktrees_dir
except ImportError:
    from config import ai_devops_home, queue_dir, repos_dir, worktrees_dir

try:
    from .task_spec import constraint_path_list as _constraint_path_list
except ImportError:
    from task_spec import constraint_path_list as _constraint_path_list

# 导入 SQLite 跟踪模块
# 导入全局调度器
try:
    from .global_scheduler import get_global_scheduler, GlobalScheduler
except ImportError:
    from global_scheduler import get_global_scheduler, GlobalScheduler

try:
    from .db import configure_control_plane_dual_write, init_db, get_task, insert_task, get_running_tasks
    from .process_guardian import ProcessGuardian
    from .heartbeat import update_heartbeat
except ImportError:
    from db import configure_control_plane_dual_write, init_db, get_task, insert_task, get_running_tasks
    from process_guardian import ProcessGuardian
    from heartbeat import update_heartbeat

try:
    from orchestrator.api.events import get_event_manager
except ImportError:
    def get_event_manager():  # type: ignore[no-redef]
        return None


def _agent_runner_codex() -> Path:
    return Path(os.getenv("CODEX_RUNNER_PATH", str(ai_devops_home() / "agents" / "run-codex-agent.sh")))


def _agent_runner_claude() -> Path:
    return Path(os.getenv("CLAUDE_RUNNER_PATH", str(ai_devops_home() / "agents" / "run-claude-agent.sh")))


# Module-level aliases kept for test monkeypatching compatibility
WORKTREES = worktrees_dir()

# 导入提示词编译器（当 Zoe 未提供 prompt 时使用模板回退）
from prompt_compiler import compile_prompt  # type: ignore

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.release_worker.service import ReleaseWorker
from apps.incident_worker.service import IncidentWorker
from packages.kernel.runtime.services import AgentLauncher, QueueConsumer, RunStateRecorder, WorkspaceManager
from packages.kernel.services.work_items import MissingContextPackError, WorkItemService
from packages.shared.domain.runtime_state import configure_runtime_persistence


def sanitize_branch_component(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", "/") else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-_/") or "task"


def sh(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> str:
    r = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if check and r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n"
            f"CWD: {cwd}\n"
            f"STDOUT:\n{r.stdout}\n"
            f"STDERR:\n{r.stderr}\n"
        )
    return (r.stdout or "").strip()


def tmux_available() -> bool:
    return shutil.which("tmux") is not None


def tmux_has(session: str) -> bool:
    if not tmux_available():
        return False
    r = subprocess.run(["tmux", "has-session", "-t", session], capture_output=True, text=True)
    return r.returncode == 0


def ensure_repo(repo_name: str) -> Path:
    repo_root = repos_dir() / repo_name
    if not repo_root.exists():
        raise RuntimeError(
            f"Repo not found: {repo_root}\n"
            f"Clone it under ~/ai-devops/repos/{repo_name} first."
        )
    return repo_root


def _detect_default_branch(repo_root: Path) -> str:
    """Detect the remote default branch via git symbolic-ref.
    Falls back to 'origin/main' if detection fails."""
    ref = sh(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
        cwd=repo_root,
        check=False,
    ).strip()
    if ref and "/" in ref:
        return ref  # e.g. "origin/main" or "origin/develop"
    return "origin/main"


def create_worktree(repo_root: Path, branch: str) -> Path:
    """Create a worktree based on the detected remote default branch."""
    wt_base = worktrees_dir()
    wt_base.mkdir(parents=True, exist_ok=True)

    wt_dir = wt_base / branch.replace("/", "-")
    if wt_dir.exists():
        # 目录已存在时视为已完成预置，直接复用。
        return wt_dir

    sh(["git", "fetch", "origin"], cwd=repo_root)

    default_branch = _detect_default_branch(repo_root)
    sh(["git", "worktree", "add", str(wt_dir), "-b", branch, default_branch], cwd=repo_root)
    return wt_dir


def runner_for_agent(agent: str) -> Path:
    if agent == "codex":
        return _agent_runner_codex()
    if agent == "claude":
        return _agent_runner_claude()
    raise RuntimeError(f"Unsupported agent: {agent}")




def _repo_relative_constraint_path(path: str, repo_root: Path) -> str | None:
    text = str(path).strip()
    if not text:
        return None
    candidate = Path(text)
    try:
        repo_resolved = repo_root.resolve()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            try:
                rel = resolved.relative_to(repo_resolved)
                text = str(rel)
            except ValueError:
                return None
        return text.replace('\\', '/').lstrip('./') or None
    except OSError:
        return None


def _scope_patterns_from_task_spec(task_spec: dict, repo_root: Path) -> list[str]:
    patterns: list[str] = []
    for item in _constraint_path_list(task_spec, 'allowedPaths', 'mustTouch', 'requiredTouchedPaths'):
        rel = _repo_relative_constraint_path(item, repo_root)
        if not rel:
            continue
        patterns.append(rel)
        if rel.endswith('/**'):
            patterns.append(rel[:-3])
        if '*' not in rel and '?' not in rel and '[' not in rel:
            p = Path(rel)
            if p.suffix:
                patterns.append(str(p.parent).replace('\\', '/'))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in patterns:
        normalized = item.rstrip('/') or item
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _write_scope_manifest(wt_dir: Path, repo_root: Path, task_spec: dict) -> Path:
    contract_dir = wt_dir / '.task-contract'
    contract_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        'repoRoot': str(repo_root),
        'worktree': str(wt_dir),
        'allowedPaths': _constraint_path_list(task_spec, 'allowedPaths'),
        'forbiddenPaths': _constraint_path_list(task_spec, 'forbiddenPaths', 'blockedPaths'),
        'mustTouch': _constraint_path_list(task_spec, 'mustTouch', 'requiredTouchedPaths'),
        'sparsePatterns': _scope_patterns_from_task_spec(task_spec, repo_root),
    }
    target = contract_dir / 'scope-manifest.json'
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def _apply_sparse_checkout_if_scoped(repo_root: Path, wt_dir: Path, task_spec: dict) -> bool:
    patterns = _scope_patterns_from_task_spec(task_spec, repo_root)
    if not patterns:
        return False
    sh(['git', 'sparse-checkout', 'init', '--no-cone'], cwd=wt_dir)
    cmd = ['git', 'sparse-checkout', 'set', '--no-cone', *patterns]
    sh(cmd, cwd=wt_dir)
    return True


def resolve_branch(task: dict) -> str:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    worktree_strategy = metadata.get("worktreeStrategy")
    if worktree_strategy == "shared" and metadata.get("planId"):
        return f"plan/{sanitize_branch_component(str(metadata['planId']))}"
    return f"feat/{sanitize_branch_component(task['id'])}"


def launch_agent_process(
    runner: Path,
    task: dict,
    wt_dir: Path,
    prompt_txt: Path,
    task_spec_file: Path | None = None,
) -> tuple[str, str | None, int | None]:
    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")
    session = f"agent-{task['id']}"

    child_env = os.environ.copy()
    if task_spec_file is not None:
        child_env["TASK_SPEC_FILE"] = str(task_spec_file)
        child_env["TASK_SPEC_REQUIRED"] = "1"
    scope_manifest_file = wt_dir / ".task-contract" / "scope-manifest.json"
    if scope_manifest_file.exists():
        child_env["SCOPE_MANIFEST_FILE"] = str(scope_manifest_file)

    if tmux_available():
        if tmux_has(session):
            raise RuntimeError(f"tmux session already exists: {session}")
        env_prefix = ""
        if task_spec_file is not None:
            env_prefix = (
                f"TASK_SPEC_FILE={shlex.quote(str(task_spec_file))} "
                f"TASK_SPEC_REQUIRED=1 "
            )
        scope_manifest_file = wt_dir / ".task-contract" / "scope-manifest.json"
        if scope_manifest_file.exists():
            env_prefix += f"SCOPE_MANIFEST_FILE={shlex.quote(str(scope_manifest_file))} "
        cmd = (
            f"{env_prefix}{shlex.quote(str(runner))} {shlex.quote(task['id'])} {shlex.quote(model)}"
            f" {shlex.quote(effort)} {shlex.quote(str(wt_dir))} {shlex.quote(prompt_txt.name)}"
        )
        sh(["tmux", "new-session", "-d", "-s", session, "-c", str(wt_dir), cmd])
        return ("tmux", session, None)

    process = subprocess.Popen(
        [str(runner), task["id"], model, effort, str(wt_dir), prompt_txt.name],
        cwd=str(wt_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=child_env,
    )
    return ("process", None, process.pid)


def spawn_agent(task: dict) -> dict:
    task = _enrich_task_with_execution_session(task)
    repo_name = task["repo"]
    agent = str(task.get("agent", "codex"))

    # 分支 / worktree 命名
    branch = resolve_branch(task)
    repo_root = ensure_repo(repo_name)
    wt_dir = create_worktree(repo_root, branch)

    # 生成提示词
    prompt = task.get("prompt") or compile_prompt(task, wt_dir)
    workspace_manager = WorkspaceManager(
        ensure_repo_fn=ensure_repo,
        create_worktree_fn=create_worktree,
        write_scope_manifest_fn=_write_scope_manifest,
        apply_sparse_checkout_fn=_apply_sparse_checkout_if_scoped,
    )
    prepared = workspace_manager.prepare_workspace(
        {**task, "prompt": prompt},
        branch=branch,
    )

    model = task.get("model", "gpt-5.3-codex")
    effort = task.get("effort", "high")

    agent_launcher = AgentLauncher(
        runner_for_agent_fn=runner_for_agent,
        launch_process_fn=launch_agent_process,
    )
    launched = agent_launcher.launch(
        task,
        worktree=prepared.worktree,
        prompt_file=prepared.prompt_file,
        task_spec_file=prepared.task_spec_file,
    )
    recorder = RunStateRecorder()
    return recorder.build_running_task_record(
        task=task,
        branch=branch,
        worktree=prepared.worktree,
        execution_mode=launched.execution_mode,
        tmux_session=launched.tmux_session,
        process_id=launched.process_id,
        prompt_file=prepared.prompt_file,
        task_spec_file=prepared.task_spec_file,
        scope_manifest_file=prepared.scope_manifest_file,
        sparse_checkout_applied=prepared.sparse_checkout_applied,
        agent=agent,
        model=model,
        effort=effort,
    )


def _enrich_task_with_execution_session(task: dict) -> dict:
    service = WorkItemService()
    session = service.create_legacy_session(task, base_dir=ai_devops_home())
    agent_run = service.prepare_agent_run(
        work_item=session.work_item,
        context_pack=session.context_pack,
        agent=str(task.get("agent", "codex")),
        model=str(task.get("model", "gpt-5.3-codex")),
    )
    metadata = dict(task.get("metadata") or {}) if isinstance(task.get("metadata"), dict) else {}
    metadata.update(
        {
            "workItem": session.work_item.to_dict(),
            "contextPack": session.context_pack.to_dict(),
            "planRequest": session.plan_request,
            "agentRun": agent_run.to_dict(),
        }
    )
    return {
        **task,
        "metadata": metadata,
    }


def _dead_letter_task(queue_file: Path, exc: Exception) -> None:
    dead_dir = queue_file.parent / "dead"
    dead_dir.mkdir(parents=True, exist_ok=True)
    dead_file = dead_dir / queue_file.name
    err_file = dead_dir / f"{queue_file.stem}.err"
    shutil.move(str(queue_file), str(dead_file))
    err_file.write_text(f"{exc.__class__.__name__}: {exc}\n", encoding="utf-8")


def _is_dead_letter_error(exc: Exception) -> bool:
    if isinstance(exc, (json.JSONDecodeError, MissingContextPackError, ValueError)):
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc)
        return message.startswith("Invalid task JSON") or message.startswith("Invalid queue payload")
    return False



def start_api_server(port: int = 8080):
    """Start REST API server in daemon thread"""
    try:
        import sys
        api_dir = Path(__file__).parent.parent / "api"
        if str(api_dir) not in sys.path:
            sys.path.insert(0, str(api_dir.parent))
        
        # Import and inject resources handler
        from orchestrator.api import server as api_server_module
        from orchestrator.api.resources import create_resources_handler
        from orchestrator.api.server import BaseAPIHandler, APIServer
        
        # Monkey patch create_combined_handler to include resources
        original_create_combined_handler = api_server_module.create_combined_handler
        
        def create_combined_handler_with_resources() -> type:
            handler = original_create_combined_handler()
            handler = create_resources_handler(handler)
            return handler
        
        api_server_module.create_combined_handler = create_combined_handler_with_resources
        
        server = APIServer(port=port)
        server.start(daemon=True)
        
        # Print resources API endpoints
        print(f"[API]   - GET    /api/resources")
        print(f"[API]   - GET    /api/resources/cpu")
        print(f"[API]   - GET    /api/resources/memory")
        print(f"[API]   - GET    /api/resources/disk")
        
        print(f"[API] REST API server started on port {port}")
        return server
    except Exception as e:
        print(f"[API] Failed to start API server: {e}")
        import traceback
        traceback.print_exc()
        return None


def main() -> None:
    # 初始化 SQLite 数据库
    init_db()
    control_plane_store = configure_control_plane_dual_write()
    configure_runtime_persistence(store=control_plane_store)

    # 启动 REST API 服务器
    api_port = int(os.getenv("ZOE_API_PORT", "8080"))
    api_server = start_api_server(port=api_port)

    # 初始化进程守护
    def on_restart_callback(task_id: str, session_name: str) -> None:
        print(f"[GUARDIAN] Restarted task {task_id} in session {session_name}")

    def on_max_restarts_callback(task_id: str, restart_count: int) -> None:
        print(f"[GUARDIAN] Task {task_id} exceeded max restarts ({restart_count}), marked as failed")

    guardian = ProcessGuardian(
        on_restart=on_restart_callback,
        on_max_restarts=on_max_restarts_callback,
    )
    event_manager = get_event_manager()
    release_worker = ReleaseWorker(event_manager=event_manager) if event_manager is not None else None
    incident_worker = IncidentWorker(event_manager=event_manager) if event_manager is not None else None
    if release_worker is not None:
        release_worker.start()
    if incident_worker is not None:
        incident_worker.start()

    q = queue_dir()
    q.mkdir(parents=True, exist_ok=True)
    consumer = QueueConsumer(q)
    print(f"Zoe daemon started. Watching queue: {q}")
    print(f"ProcessGuardian initialized. Monitoring agent sessions...")

    # 资源监控（每 30 秒采集一次）
    try:
        from resource_monitor import get_resource_monitor
        resource_monitor = get_resource_monitor()
        resource_collect_interval = 30  # 30 秒
        last_resource_collect_time = 0
        print("[RESOURCE] Resource monitor initialized")
    except Exception as e:
        print(f"[RESOURCE-ERROR] Failed to initialize resource monitor: {e}")
        resource_monitor = None
        resource_collect_interval = 30
        last_resource_collect_time = 0

    # 心跳上报间隔（秒）
    heartbeat_interval = 300  # 5 分钟
    last_heartbeat_time = 0

    # 初始化全局调度器
    try:
        scheduler = get_global_scheduler()
        scheduling_interval = 60  # 60 秒
        last_scheduling_time = 0
        print("[SCHEDULER] Global scheduler initialized")
    except Exception as e:
        print(f"[SCHEDULER-ERROR] Failed to initialize scheduler: {e}")
        scheduler = None
        scheduling_interval = 60
        last_scheduling_time = 0
    
    while True:
        now = time.time()
        
        # 资源监控采集
        if resource_monitor and now - last_resource_collect_time >= resource_collect_interval:
            try:
                summary = resource_monitor.get_summary()
                cpu_pct = summary.get("cpu", {}).get("percent", 0)
                mem_pct = summary.get("memory", {}).get("percent", 0)
                disk_pct = summary.get("disk", {}).get("percent", 0)
                print(f"[RESOURCE] CPU: {cpu_pct}% | Memory: {mem_pct}% | Disk: {disk_pct}%")
                last_resource_collect_time = now
            except Exception as e:
                print(f"[RESOURCE-ERROR] Failed to collect resource data: {e}")
        
        # 心跳上报：为所有运行中的任务更新心跳
        if now - last_heartbeat_time >= heartbeat_interval:
            try:
                running_tasks = get_running_tasks()
                for task in running_tasks:
                    try:
                        update_heartbeat(task["id"])
                    except Exception as e:
                        print(f"[HEARTBEAT-ERROR] Failed to update heartbeat for {task['id']}: {e}")
                last_heartbeat_time = now
                if running_tasks:
                    print(f"[HEARTBEAT] Updated heartbeat for {len(running_tasks)} running tasks")
            except Exception as e:
                print(f"[HEARTBEAT-ERROR] Heartbeat update failed: {e}")
        
        # 全局调度器周期调度
        if scheduler and now - last_scheduling_time >= scheduling_interval:
            try:
                decisions = scheduler.schedule()
                if decisions:
                    dispatched = sum(1 for d in decisions if d.decision == "dispatched")
                    if dispatched > 0:
                        print(f"[SCHEDULER] Dispatched {dispatched} plans")
                last_scheduling_time = now
            except Exception as e:
                print(f"[SCHEDULER-ERROR] Scheduling cycle failed: {e}")

        
        # 进程守护检查
        try:
            report = guardian.check_all()
            for task_id, info in report.items():
                status = info.get("status", "unknown")
                detail = info.get("detail", "")
                if status in ("restarted", "max_restarts", "restart_failed"):
                    print(f"[GUARDIAN] Task {task_id}: {status} - {detail}")
        except Exception as e:
            print(f"[GUARDIAN-ERROR] Check failed: {e}")

        # 队列处理
        for p in consumer.list_queue_files():
            try:
                task = consumer.load_task(p)
                if "id" not in task or "repo" not in task:
                    raise RuntimeError(f"Invalid task JSON (missing id/repo): {p}")

                if get_task(task["id"]) is not None:
                    # 已存在跟踪记录时，删除队列项避免重复循环
                    p.unlink(missing_ok=True)
                    continue

                item = spawn_agent(task)
                insert_task(item)

                # 添加到进程守护监控
                if item.get("tmuxSession"):
                    guardian.add_task(item["id"], item["tmuxSession"])

                p.unlink(missing_ok=True)
                if item["executionMode"] == "tmux":
                    print(f"Spawned task {item['id']} in tmux {item['tmuxSession']}")
                else:
                    print(f"Spawned task {item['id']} as background process {item['processId']}")
            except Exception as e:
                if _is_dead_letter_error(e):
                    _dead_letter_task(p, e)
                    print(f"[DEAD-LETTER] Moved invalid task {p} to dead-letter: {e}")
                    continue
                # 不删除任务文件，保留用于排查与重试
                print(f"[ERROR] Failed processing {p}: {e}")

        time.sleep(2)


if __name__ == "__main__":
    main()
