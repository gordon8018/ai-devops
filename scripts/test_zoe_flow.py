#!/usr/bin/env python3
"""
Zoe 完整流程测试脚本

测试目标:
1. 验证 plan_and_dispatch_task 完整流程
2. 验证规划引擎生成正确的子任务
3. 验证依赖感知分发
4. 验证队列文件生成

运行方式:
    python scripts/test_zoe_flow.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.bin.config import ai_devops_home
from orchestrator.bin.db import init_db, get_all_tasks, delete_task
from orchestrator.bin.dispatch import (
    dispatch_ready_subtasks,
    load_dispatch_state,
    tasks_dir,
    _dispatch_queue_dir,
)
from orchestrator.bin.plan_schema import load_plan
from orchestrator.bin.planner_engine import ZoePlannerEngine
from orchestrator.bin.zoe_tools import (
    build_plan_request,
    generate_plan_id,
    save_plan,
    list_plans,
    task_status,
)


def setup_environment():
    base = ai_devops_home()
    print(f"[SETUP] AI_DEVOPS_HOME = {base}")

    init_db()
    print("[SETUP] 数据库初始化完成")

    queue_dir = _dispatch_queue_dir(base)
    queue_dir.mkdir(parents=True, exist_ok=True)
    print(f"[SETUP] 队列目录 = {queue_dir}")

    return base


def test_task_1_simple_implementation():
    """测试1: 简单实现任务 - 应生成单个子任务"""
    print("\n" + "=" * 60)
    print("测试1: 简单实现任务")
    print("=" * 60)

    base = ai_devops_home()
    planner = ZoePlannerEngine()

    task_input = {
        "repo": "test-org/test-repo",
        "title": "Add hello function",
        "description": "Add a simple hello function to main.py",
        "requested_by": "test-user",
        "requested_at": int(1e13),
    }

    request = build_plan_request(task_input, base_dir=base)
    print(f"[INPUT] planId = {request['planId']}")
    print(f"[INPUT] repo = {request['repo']}")
    print(f"[INPUT] title = {request['title']}")

    plan = planner.plan(request)
    plan_path = save_plan(plan, base_dir=base)

    print(f"\n[OUTPUT] plan.json = {plan_path}")
    print(f"[OUTPUT] 子任务数量 = {len(plan.subtasks)}")

    for i, subtask in enumerate(plan.subtasks, 1):
        print(f"  [{i}] {subtask.id}: {subtask.title}")
        print(f"      dependsOn = {list(subtask.depends_on)}")
        print(f"      filesHint = {list(subtask.files_hint)[:3]}...")

    dispatch_state = load_dispatch_state(plan, base)
    queued = dispatch_ready_subtasks(plan, base_dir=base)

    print(f"\n[DISPATCH] 入队文件数 = {len(queued)}")
    if queued:
        queue_payload = json.loads(queued[0].read_text())
        print(f"[DISPATCH] 队列文件 = {queued[0].name}")
        print(f"[DISPATCH] metadata.planId = {queue_payload['metadata']['planId']}")
        print(
            f"[DISPATCH] metadata.subtaskId = {queue_payload['metadata']['subtaskId']}"
        )

    return {
        "test": "simple_implementation",
        "plan_id": plan.plan_id,
        "subtask_count": len(plan.subtasks),
        "queued_count": len(queued),
        "success": len(plan.subtasks) >= 1 and len(queued) >= 1,
    }


def test_task_2_complex_refactor():
    """测试2: 复杂重构任务 - 应生成多个子任务 (foundation + impl + validation)"""
    print("\n" + "=" * 60)
    print("测试2: 复杂重构任务 (多阶段)")
    print("=" * 60)

    base = ai_devops_home()
    planner = ZoePlannerEngine()

    task_input = {
        "repo": "test-org/test-repo",
        "title": "Refactor and migrate authentication system",
        "description": """Refactor the authentication module and migrate to new session handling.
        This involves restructuring the core auth logic and updating the session management.""",
        "requested_by": "test-user",
        "requested_at": int(1e13) + 1,
    }

    request = build_plan_request(task_input, base_dir=base)
    print(f"[INPUT] planId = {request['planId']}")

    plan = planner.plan(request)
    plan_path = save_plan(plan, base_dir=base)

    print(f"\n[OUTPUT] 子任务数量 = {len(plan.subtasks)}")

    for i, subtask in enumerate(plan.subtasks, 1):
        print(f"  [{i}] {subtask.id}: {subtask.title}")
        print(f"      dependsOn = {list(subtask.depends_on)}")

    has_foundation = any(
        "foundation" in s.title.lower() or "Prepare" in s.title for s in plan.subtasks
    )
    has_validation = any(
        "validation" in s.title.lower() or "test" in s.title.lower()
        for s in plan.subtasks
    )

    print(f"\n[ANALYSIS] 包含 Foundation 阶段 = {has_foundation}")
    print(f"[ANALYSIS] 包含 Validation 阶段 = {has_validation}")

    queued = dispatch_ready_subtasks(plan, base_dir=base)
    print(f"[DISPATCH] 入队文件数 = {len(queued)}")

    return {
        "test": "complex_refactor",
        "plan_id": plan.plan_id,
        "subtask_count": len(plan.subtasks),
        "has_foundation": has_foundation,
        "has_validation": has_validation,
        "queued_count": len(queued),
        "success": len(plan.subtasks) >= 2 and (has_foundation or has_validation),
    }


def test_task_3_docs_only():
    """测试3: 文档任务 - 验证文档阶段存在"""
    print("\n" + "=" * 60)
    print("测试3: 文档任务 (验证文档阶段)")
    print("=" * 60)

    base = ai_devops_home()
    planner = ZoePlannerEngine()

    task_input = {
        "repo": "test-org/test-repo",
        "title": "Update README documentation",
        "description": "Update the README and add documentation for the new features.",
        "requested_by": "test-user",
        "requested_at": int(1e13) + 2,
    }

    request = build_plan_request(task_input, base_dir=base)
    plan = planner.plan(request)
    plan_path = save_plan(plan, base_dir=base)

    print(f"[OUTPUT] 子任务数量 = {len(plan.subtasks)}")
    for subtask in plan.subtasks:
        print(f"  - {subtask.id}: {subtask.title}")

    has_docs_phase = any(
        "doc" in s.title.lower() or "documentation" in s.title.lower()
        for s in plan.subtasks
    )
    print(f"[ANALYSIS] 包含文档阶段 = {has_docs_phase}")

    return {
        "test": "docs_task",
        "plan_id": plan.plan_id,
        "subtask_count": len(plan.subtasks),
        "has_docs_phase": has_docs_phase,
        "success": has_docs_phase,
    }


def test_task_4_scoped_constraint():
    """测试4: 范围约束任务 - 验证 allowedPaths/mustTouch 约束"""
    print("\n" + "=" * 60)
    print("测试4: 范围约束任务")
    print("=" * 60)

    base = ai_devops_home()
    planner = ZoePlannerEngine()

    task_input = {
        "repo": "test-org/test-repo",
        "title": "Scoped fix",
        "description": "Fix only the specified file",
        "requested_by": "test-user",
        "requested_at": int(1e13) + 3,
        "taskSpec": {
            "repo": "test-org/test-repo",
            "title": "Scoped fix",
            "goal": "Fix only the specified file within allowed paths",
            "workingRoot": "/tmp/test-work",
            "allowedPaths": ["src/**"],
            "forbiddenPaths": ["tests/**"],
            "mustTouch": ["src/main.py"],
            "definitionOfDone": ["Stay within allowed paths", "Run tests"],
            "validation": ["Run targeted tests"],
            "firstStepRequirement": "List exact files before editing",
            "failureRules": ["Stop on out-of-scope edits"],
        },
    }

    request = build_plan_request(task_input, base_dir=base)
    print(f"[INPUT] allowedPaths = {request['constraints'].get('allowedPaths')}")
    print(f"[INPUT] mustTouch = {request['constraints'].get('mustTouch')}")

    plan = planner.plan(request)
    plan_path = save_plan(plan, base_dir=base)

    task_spec = plan.context.get("taskSpec", {})
    print(f"\n[OUTPUT] taskSpec.allowedPaths = {task_spec.get('allowedPaths')}")
    print(f"[OUTPUT] taskSpec.mustTouch = {task_spec.get('mustTouch')}")

    for subtask in plan.subtasks:
        prompt = subtask.prompt
        if "ALLOWED PATHS" in prompt:
            print(f"[VALIDATE] {subtask.id} prompt 包含 ALLOWED PATHS 边界")
        if "REQUIRED TARGET FILES" in prompt:
            print(f"[VALIDATE] {subtask.id} prompt 包含 REQUIRED TARGET FILES")

    has_constraints = (
        "allowedPaths" in request["constraints"]
        or "mustTouch" in request["constraints"]
    )
    prompt_has_boundary = any("ALLOWED PATHS" in s.prompt for s in plan.subtasks)

    return {
        "test": "scoped_constraint",
        "plan_id": plan.plan_id,
        "has_constraints": has_constraints,
        "prompt_has_boundary": prompt_has_boundary,
        "success": has_constraints and prompt_has_boundary,
    }

    request = build_plan_request(task_input, base_dir=base)
    print(f"[INPUT] allowedPaths = {request['constraints'].get('allowedPaths')}")
    print(f"[INPUT] mustTouch = {request['constraints'].get('mustTouch')}")

    plan = planner.plan(request)
    plan_path = save_plan(plan, base_dir=base)

    task_spec = plan.context.get("taskSpec", {})
    print(f"\n[OUTPUT] taskSpec.allowedPaths = {task_spec.get('allowedPaths')}")
    print(f"[OUTPUT] taskSpec.mustTouch = {task_spec.get('mustTouch')}")

    for subtask in plan.subtasks:
        prompt = subtask.prompt
        if "ALLOWED PATHS" in prompt:
            print(f"[VALIDATE] S{subtask.id} prompt 包含 ALLOWED PATHS 边界")
        if "REQUIRED TARGET FILES" in prompt:
            print(f"[VALIDATE] S{subtask.id} prompt 包含 REQUIRED TARGET FILES")

    has_constraints = (
        "allowedPaths" in request["constraints"]
        or "mustTouch" in request["constraints"]
    )

    return {
        "test": "scoped_constraint",
        "plan_id": plan.plan_id,
        "has_constraints": has_constraints,
        "success": has_constraints,
    }


def test_list_and_status():
    """测试5: list_plans 和 task_status API"""
    print("\n" + "=" * 60)
    print("测试5: list_plans 和 task_status API")
    print("=" * 60)

    base = ai_devops_home()

    plans = list_plans(base_dir=base, limit=10)
    print(f"[LIST] 计划数量 = {len(plans['plans'])}")

    for p in plans["plans"][:5]:
        print(f"  - {p['planId']}: {p['title']} ({p['subtaskCount']} subtasks)")

    if plans["plans"]:
        first_plan_id = plans["plans"][0]["planId"]
        status = task_status(plan_id=first_plan_id, base_dir=base)
        print(f"\n[STATUS] plan_id = {first_plan_id}")
        print(f"[STATUS] tasks 数量 = {len(status.get('tasks', []))}")

    return {
        "test": "list_and_status",
        "plans_count": len(plans["plans"]),
        "success": len(plans["plans"]) >= 3,
    }


def main():
    print("=" * 60)
    print("Zoe 完整流程测试")
    print("=" * 60)

    base = setup_environment()

    results = []

    try:
        results.append(test_task_1_simple_implementation())
    except Exception as e:
        print(f"[ERROR] 测试1失败: {e}")
        results.append(
            {"test": "simple_implementation", "success": False, "error": str(e)}
        )

    try:
        results.append(test_task_2_complex_refactor())
    except Exception as e:
        print(f"[ERROR] 测试2失败: {e}")
        results.append({"test": "complex_refactor", "success": False, "error": str(e)})

    try:
        results.append(test_task_3_docs_only())
    except Exception as e:
        print(f"[ERROR] 测试3失败: {e}")
        results.append({"test": "docs_only", "success": False, "error": str(e)})

    try:
        results.append(test_task_4_scoped_constraint())
    except Exception as e:
        print(f"[ERROR] 测试4失败: {e}")
        results.append({"test": "scoped_constraint", "success": False, "error": str(e)})

    try:
        results.append(test_list_and_status())
    except Exception as e:
        print(f"[ERROR] 测试5失败: {e}")
        results.append({"test": "list_and_status", "success": False, "error": str(e)})

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = sum(1 for r in results if r.get("success"))
    total = len(results)

    for r in results:
        status = "PASS" if r.get("success") else "FAIL"
        print(f"  [{status}] {r['test']}")

    print(f"\n总计: {passed}/{total} 通过")

    if passed == total:
        print("\n[SUCCESS] 所有测试通过!")
        return 0
    else:
        print("\n[FAILED] 部分测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
