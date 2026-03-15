#!/usr/bin/env python3
import argparse
import fnmatch
import json
import os
import sys as _sys
import time
from pathlib import Path
from typing import Tuple

try:
    from .config import ai_devops_home, logs_dir
except ImportError:
    from config import ai_devops_home, logs_dir

try:
    from .db import init_db, get_running_tasks, update_task
except ImportError:
    _sys.path.insert(0, str(Path(__file__).parent))
    from db import init_db, get_running_tasks, update_task

try:
    from .monitor_helpers import (
        sh,
        tmux_available,
        tmux_alive,
        process_alive,
        exit_status_path,
        load_exit_status,
        log_file_stale,
        task_elapsed_minutes,
        pr_info,
        merge_clean,
        analyze_checks,
        latest_run_failure,
        restart_agent,
    )
except ImportError:
    from monitor_helpers import (
        sh,
        tmux_available,
        tmux_alive,
        process_alive,
        exit_status_path,
        load_exit_status,
        log_file_stale,
        task_elapsed_minutes,
        pr_info,
        merge_clean,
        analyze_checks,
        latest_run_failure,
        restart_agent,
    )

try:
    from notify import notify
except ImportError:
    def notify(msg: str) -> None:
        print(f"[NOTIFY] {msg}")

try:
    from obsidian_client import ObsidianClient
except ImportError:
    ObsidianClient = None  # type: ignore

try:
    from reviewer import review_pr
except ImportError:
    def review_pr(task_id, pr_number, repo_dir):  # type: ignore[misc]
        print(f"[WARN] reviewer module not available, skipping review for PR #{pr_number}")


def _obsidian_search(query: str) -> list[dict]:
    """搜索知识库上下文。未配置或不可达时返回空列表。"""
    token = os.getenv("OBSIDIAN_API_TOKEN", "")
    if not token or ObsidianClient is None:
        return []
    client = ObsidianClient.from_env()
    return client.search(query, limit=2)


def _constraint_path_list(raw: dict | None, *keys: str) -> list[str]:
    if not isinstance(raw, dict):
        return []
    values: list[str] = []
    for key in keys:
        items = raw.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            text = str(item).strip()
            if text:
                values.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _git_touched_files(worktree: Path) -> list[str]:
    if not worktree.exists():
        return []
    output = sh(["git", "status", "--short"], cwd=worktree)
    if not output:
        return []
    ignored_runtime_paths = {
        'prompt.txt',
        'task-spec.json',
    }
    ignored_prefixes = (
        '.task-contract/',
        'task-contract/',
    )
    touched: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip() if len(line) >= 4 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path:
            continue
        normalized = path.replace('\\', '/').lstrip('./')
        if normalized in ignored_runtime_paths:
            continue
        if any(normalized.startswith(prefix) for prefix in ignored_prefixes):
            continue
        touched.append(normalized)
    return touched


def _path_matches_constraint(path: str, rule: str, worktree: Path) -> bool:
    normalized = path.replace('\\', '/').lstrip('./')
    candidate_paths = {normalized}
    try:
        abs_path = (worktree / normalized).resolve()
        candidate_paths.add(str(abs_path).replace('\\', '/'))
    except OSError:
        pass

    normalized_rule = rule.replace('\\', '/').rstrip('/')
    if not normalized_rule:
        return False
    if any(ch in normalized_rule for ch in '*?['):
        patterns = {normalized_rule}
        if normalized_rule.endswith('/**'):
            patterns.add(normalized_rule[:-3])
            patterns.add(normalized_rule[:-3] + '/*')
        return any(any(fnmatch.fnmatch(candidate, pat) for pat in patterns) for candidate in candidate_paths)

    return any(
        candidate == normalized_rule
        or candidate.startswith(normalized_rule + '/')
        for candidate in candidate_paths
    )


def _scope_violation(task: dict, worktree: Path, *, enforce_must_touch: bool = False) -> tuple[str, str, list[str]] | None:
    metadata = task.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    task_spec = metadata.get("taskSpec") if isinstance(metadata.get("taskSpec"), dict) else {}
    constraints = metadata.get("constraints") if isinstance(metadata.get("constraints"), dict) else {}
    allowed = _constraint_path_list(constraints, "allowedPaths")
    forbidden = _constraint_path_list(constraints, "forbiddenPaths", "blockedPaths")
    must_touch = _constraint_path_list(constraints, "mustTouch", "requiredTouchedPaths")
    if task_spec:
        allowed = _constraint_path_list(task_spec, "allowedPaths") or allowed
        forbidden = _constraint_path_list(task_spec, "forbiddenPaths", "blockedPaths") or forbidden
        must_touch = _constraint_path_list(task_spec, "mustTouch", "requiredTouchedPaths") or must_touch
    touched = _git_touched_files(worktree)
    if not touched:
        if enforce_must_touch and (allowed or must_touch):
            return ("execution_contract_breach", "no scoped repository edits detected before completion", touched)
        return None

    forbidden_hits = [path for path in touched if any(_path_matches_constraint(path, rule, worktree) for rule in forbidden)]
    if forbidden_hits:
        return ("execution_contract_breach", f"forbidden paths touched: {', '.join(forbidden_hits[:5])}", touched)

    if allowed:
        outside = [path for path in touched if not any(_path_matches_constraint(path, rule, worktree) for rule in allowed)]
        if outside:
            return ("execution_contract_breach", f"touched files outside allowed paths: {', '.join(outside[:5])}", touched)

    if enforce_must_touch and must_touch and not any(any(_path_matches_constraint(path, rule, worktree) for rule in must_touch) for path in touched):
        return ("required_target_not_touched", f"required target paths not touched yet: expected one of {', '.join(must_touch[:5])}", touched)

    if enforce_must_touch and task_spec:
        files_hint = _constraint_path_list(task_spec, "filesHint")
        if files_hint and not any(
            any(_path_matches_constraint(path, rule, worktree) for rule in files_hint)
            for path in touched
        ):
            return ("execution_contract_breach", f"touched files do not overlap taskSpec filesHint: expected one of {', '.join(files_hint[:5])}", touched)

    return None


def _write_failure_log(repo: str, task_id: str, fail_summary: str, ci_detail: str) -> None:
    """将结构化失败记录写入失败日志目录。"""
    log_dir = ai_devops_home() / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    log_file = log_dir / f"{task_id}-{timestamp}.json"
    log_file.write_text(
        json.dumps({
            "taskId": task_id,
            "repo": repo,
            "failSummary": fail_summary,
            "ciDetail": ci_detail[:2000] if ci_detail else "",
            "timestamp": timestamp,
        }, indent=2),
        encoding="utf-8",
    )


def _load_failure_logs(repo: str, limit: int = 2) -> str:
    """加载仓库最近的失败日志摘要。"""
    log_dir = ai_devops_home() / ".clawdbot" / "failure-logs" / repo.replace("/", "_")
    if not log_dir.exists():
        return ""
    logs = sorted(log_dir.glob("*.json"), reverse=True)[:limit]
    excerpts = []
    for log in logs:
        try:
            data = json.loads(log.read_text(encoding="utf-8"))
            excerpts.append(f"- [{data.get('taskId','')}] {data.get('failSummary','')} — {data.get('ciDetail','')[:200]}")
        except Exception:
            continue
    return "\n".join(excerpts)


def _save_success_pattern(
    *, repo: str, task_id: str, title: str, worktree: Path, attempts: int
) -> None:
    """保存成功提示词模板，供后续规划参考。

    说明：同一 slug（repo+title）仅保留一个文件，会覆盖旧版本，
    因此始终保存最近一次成功提示词。
    """
    import re as _re
    prompt_path = worktree / "prompt.txt"
    if not prompt_path.exists():
        return
    content = prompt_path.read_text(encoding="utf-8")

    templates_dir = ai_devops_home() / ".clawdbot" / "prompt-templates" / repo.replace("/", "_")
    templates_dir.mkdir(parents=True, exist_ok=True)

    slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    if not slug:
        slug = f"task-{task_id}"[:48]
    timestamp = int(time.time() * 1000)
    out_file = templates_dir / f"{slug}.md"
    out_file.write_text(
        f"<!-- attempts={attempts} timestamp={timestamp} repo={repo} -->\n{content}",
        encoding="utf-8",
    )


def _build_retry_prompt(task: dict, retry_n: int, fail_summary: str, ci_detail: str) -> Path:
    """
    Build and write prompt.retryN.txt for a task.
    Injects Obsidian business context and past failure history.
    Returns path to the written file.
    """
    worktree = Path(task.get("worktree", ""))
    base_prompt_path = worktree / "prompt.txt"
    base_prompt = base_prompt_path.read_text(encoding="utf-8") if base_prompt_path.exists() else ""

    # 知识库上下文（Obsidian）
    query = f"{task.get('title', '')} {task.get('repo', '')}"
    obsidian_results = _obsidian_search(query)
    obsidian_section = ""
    if obsidian_results:
        excerpts = "\n".join(f"- [{r['path']}]: {r['excerpt']}" for r in obsidian_results)
        obsidian_section = f"\nBUSINESS CONTEXT (from Obsidian):\n{excerpts}\n"

    # 历史失败记录
    past_failures = _load_failure_logs(task.get("repo", ""))
    failures_section = ""
    if past_failures:
        failures_section = f"\nPAST FAILURES FOR THIS REPO:\n{past_failures}\n"

    retry_prompt = (
        base_prompt
        + obsidian_section
        + failures_section
        + "\n\n"
        + f"RERUN DIRECTIVE (Retry #{retry_n}):\n"
        + "CI is failing. Your ONLY priority is to make CI green.\n"
        + f"Failed checks summary: {fail_summary}\n\n"
        + (ci_detail + "\n\n" if ci_detail else "")
        + "Instructions:\n"
        + "- Read failing logs and identify root cause.\n"
        + "- Apply minimal fix.\n"
        + "- Run local equivalent checks/tests if available.\n"
        + "- Push commits to the SAME branch and update the PR.\n"
    )

    retry_prompt_path = worktree / f"prompt.retry{retry_n}.txt"
    retry_prompt_path.write_text(retry_prompt, encoding="utf-8")
    return retry_prompt_path


def _process_task(t: dict, notified_ready: set) -> None:
    """在一次监控周期中处理单个任务。"""
    status = t.get("status")
    if status not in ("running", "pr_created", "retrying"):
        return

    # 基础字段（db 使用 snake_case）
    session = t.get("tmuxSession") or t.get("tmux_session")
    process_id = t.get("processId") or t.get("process_id")
    execution_mode = t.get("executionMode") or t.get("execution_mode", "tmux")
    worktree = Path(t.get("worktree", ""))
    branch = t.get("branch", "")
    task_id = t.get("id")

    if not task_id or not worktree.exists() or not branch:
        update_task(task_id, {"status": "blocked", "note": "invalid task record (missing id/worktree/branch)"})
        t["status"] = "blocked"
        return

    if execution_mode == "process":
        alive = process_alive(process_id)
    else:
        alive = bool(session) and tmux_alive(session)

    scope_violation = _scope_violation(t, worktree, enforce_must_touch=False)
    if scope_violation:
        breach_code, note, touched = scope_violation
        update_task(task_id, {"status": "blocked", "note": f"{breach_code}: {note}"})
        t["status"] = "blocked"
        notify(
            f"🛑 Scope violation: `{task_id}` touched wrong files. {breach_code}: {note}\n"
            f"Touched: {', '.join(touched[:8])}"
        )
        return

    # 1) PR info
    pr = pr_info(worktree, branch)

    if pr and t.get("status") == "running":
        update_task(task_id, {
            "status": "pr_created",
            "pr_number": pr.get("number"),
            "pr_url": pr.get("url"),
        })
        t["status"] = "pr_created"
        t["pr"] = pr.get("number")
        t["prUrl"] = pr.get("url")

        # 异步触发 PR 评审（非阻塞）
        worktree_path = Path(t.get("worktree", ""))
        if worktree_path.exists() and pr.get("number"):
            review_pr(task_id, pr["number"], worktree_path)

    if not pr:
        exit_info = load_exit_status(task_id)
        if t.get("status") == "running" and exit_info:
            exit_code = exit_info.get("exitCode")
            completed_at = exit_info.get("finishedAt")
            if not isinstance(completed_at, int):
                completed_at = int(time.time() * 1000)
            terminal_scope_violation = _scope_violation(t, worktree, enforce_must_touch=True)
            if terminal_scope_violation:
                breach_code, note, touched = terminal_scope_violation
                update_task(task_id, {
                    "status": "blocked",
                    "completed_at": completed_at,
                    "note": f"{breach_code}: {note}",
                })
                t["status"] = "blocked"
                notify(
                    f"🛑 Scope violation after agent exit: `{task_id}`. {breach_code}: {note}\n"
                    f"Touched: {', '.join(touched[:8])}"
                )
            elif exit_code == 0:
                update_task(task_id, {
                    "status": "agent_exited",
                    "completed_at": completed_at,
                    "note": "agent process exited cleanly before opening a PR",
                })
                t["status"] = "agent_exited"
            else:
                update_task(task_id, {
                    "status": "agent_failed",
                    "completed_at": completed_at,
                    "note": f"agent exited with code {exit_code}",
                })
                t["status"] = "agent_failed"
                notify(
                    f"⚠️ Agent exited: `{task_id}` with code {exit_code}. Check logs."
                )
            return

        # 在 PR 生成前才依赖运行时存活判断。
        if not alive and t.get("status") == "running":
            note = (
                "background process not found"
                if execution_mode == "process"
                else "tmux session not found"
            )
            update_task(task_id, {"status": "agent_dead", "note": note})
            t["status"] = "agent_dead"
            runtime_ref = (
                f"pid={process_id}" if execution_mode == "process" else session
            )
            notify(
                f"⚠️ Agent session dead: `{task_id}` ({runtime_ref}). Check logs."
            )
        return

    # 3) Only handle OPEN PRs for checks/retry
    if (pr.get("state") or "").upper() != "OPEN":
        return

    passed, fail_summary, pending = analyze_checks(pr)

    # 检查仍在进行：不做处理
    if pending:
        return

    # 就绪条件：检查通过且可干净合并
    if passed and merge_clean(pr):
        terminal_scope_violation = _scope_violation(t, worktree, enforce_must_touch=True)
        if terminal_scope_violation:
            breach_code, note, touched = terminal_scope_violation
            update_task(task_id, {
                "status": "blocked",
                "completed_at": int(time.time() * 1000),
                "note": f"{breach_code}: {note}",
            })
            t["status"] = "blocked"
            notify(
                f"🛑 Scope violation before ready: `{task_id}`. {breach_code}: {note}\n"
                f"Touched: {', '.join(touched[:8])}"
            )
            return
        if task_id not in notified_ready:
            notified_ready.add(task_id)
            update_task(task_id, {
                "status": "ready",
                "completed_at": int(time.time() * 1000),
                "note": "checks passed and mergeable clean",
            })
            t["status"] = "ready"
            _save_success_pattern(
                repo=t.get("repo", ""),
                task_id=task_id,
                title=t.get("title", task_id),
                worktree=worktree,
                attempts=int(t.get("attempts", 0)),
            )
            notify(f"✅ PR ready: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')} (checks✅ + merge✅)")
        return

    # 检查通过但无法干净合并 -> 通知人工处理
    if passed and not merge_clean(pr):
        # 避免刷屏：仅在状态变化时通知一次
        if t.get("status") != "needs_rebase":
            note = f"merge not clean: mergeable={pr.get('mergeable')} state={pr.get('mergeStateStatus')}"
            update_task(task_id, {"status": "needs_rebase", "note": note})
            t["status"] = "needs_rebase"
            notify(
                f"⚠️ PR checks passed but merge not clean: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
                f"mergeable={pr.get('mergeable')} mergeStateStatus={pr.get('mergeStateStatus')}"
            )
        return

    # 4) 检查失败 -> Ralph Loop v2 自动重试
    if fail_summary:
        attempts = int(t.get("attempts", 0))
        max_attempts = int(t.get("maxAttempts") or t.get("max_attempts", 3))

        update_task(task_id, {"last_failure": fail_summary})

        if attempts >= max_attempts:
            if t.get("status") != "blocked":
                update_task(task_id, {"status": "blocked", "note": "max retries reached"})
                t["status"] = "blocked"
                notify(
                    f"🛑 CI failed and max retries reached: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
                    f"Fail: {fail_summary}"
                )
            return

        retry_n = attempts + 1

        # 尽可能拉取更多 CI 失败细节
        ci_detail = latest_run_failure(worktree, branch) or ""

        # 写入失败日志
        _write_failure_log(t.get("repo", ""), task_id, fail_summary, ci_detail)

        # 构建带 Obsidian 上下文的重试提示词
        retry_prompt_path = _build_retry_prompt(t, retry_n, fail_summary, ci_detail)

        # 使用重试提示词重启 agent
        try:
            restart_agent(t, worktree, retry_prompt_path.name)
        except Exception as e:
            update_task(task_id, {"status": "blocked", "note": f"failed to restart agent: {e}"})
            t["status"] = "blocked"
            notify(f"🛑 Failed to restart agent for `{task_id}`: {e}")
            return

        update_task(task_id, {
            "attempts": retry_n,
            "status": "running",
            "note": f"retry #{retry_n} triggered",
        })
        t["attempts"] = retry_n
        t["status"] = "running"

        notify(
            f"🔁 Retry #{retry_n} triggered: `{task_id}` {t.get('prUrl') or t.get('pr_url', '')}\n"
            f"Fail: {fail_summary}"
        )


def check_all_tasks(notified_ready: set) -> Tuple[bool, set]:
    """
    执行一次全量监控循环，返回 (changed, notified_ready)。
    当前 changed 固定为 False（状态即时更新），仅保留兼容字段。
    """
    items = get_running_tasks()
    for t in items:
        try:
            _process_task(t, notified_ready)
        except Exception as exc:
            task_id = t.get("id", "<unknown>")
            update_task(task_id, {"status": "blocked", "note": f"monitor error: {exc}"})
            print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
    return (False, notified_ready)


def run_once(notified_ready: set) -> None:
    """对所有活跃任务执行一次监控循环。"""
    try:
        items = get_running_tasks()
        for t in items:
            try:
                _process_task(t, notified_ready)
            except Exception as exc:
                task_id = t.get("id", "<unknown>")
                update_task(task_id, {"status": "blocked", "note": f"monitor error: {exc}"})
                print(f"[ERROR] Monitor failed for task {task_id}: {exc}")
    except Exception as exc:
        print(f"[ERROR] Monitor loop failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zoe task monitor")
    parser.add_argument("--once", action="store_true",
                        help="Run one monitoring cycle and exit")
    args = parser.parse_args()

    init_db()
    notified_ready: set = set()

    if args.once:
        run_once(notified_ready)
        return

    print("Monitor started.")
    while True:
        run_once(notified_ready)
        time.sleep(30)


if __name__ == "__main__":
    main()
