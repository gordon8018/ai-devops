from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any, Mapping

from .errors import InvalidPlan
from .plan_schema import Plan

CODE_CHANGE_TERMS = (
    "implement",
    "fix",
    "build",
    "create",
    "add",
    "update",
    "refactor",
    "migrate",
    "wire",
    "integrate",
    "repair",
    "ship",
    "support",
    "修复",
    "实现",
    "新增",
    "重构",
)
FOUNDATION_SPLIT_TERMS = (
    "refactor",
    "migrate",
    "extract",
    "restructure",
    "integrate",
    "wire",
    "multi-step",
    "重构",
    "迁移",
    "拆分",
)
DOC_ACTION_TERMS = (
    "document",
    "documenter",
    "write docs",
    "update docs",
    "update documentation",
    "add docs",
    "refresh readme",
    "readme",
    "changelog",
    "guide",
    "manual",
    "更新文档",
    "补充文档",
    "完善文档",
    "撰写文档",
    "文档更新",
    "说明文档",
    "操作手册",
)
ANALYSIS_TERMS = (
    "investigate",
    "analyze",
    "audit",
    "review",
    "triage",
    "inspect",
    "understand",
    "progress",
    "status",
    "read",
    "current state",
    "confirm",
    "survey",
    "assess",
    "inventory",
    "分析",
    "审查",
    "排查",
    "进度",
    "阅读",
    "确认",
    "现状",
    "调研",
    "盘点",
)
FOUNDATION_FILE_TERMS = (
    "core",
    "base",
    "schema",
    "model",
    "service",
    "helper",
    "lib",
    "utils",
    "session",
    "client",
    "adapter",
)
IMPLEMENTATION_FILE_TERMS = (
    "route",
    "handler",
    "controller",
    "api",
    "auth",
    "view",
    "screen",
    "component",
    "feature",
    "flow",
)
DOC_FILE_TERMS = (
    "readme",
    "docs",
    "guide",
    "manual",
    "runbook",
    "changelog",
)
REPO_SCAN_ROOTS = (
    "",
    "src",
    "app",
    "server",
    "backend",
    "frontend",
    "scripts",
    "docs",
    "prisma",
    "tests",
)
REPO_SCAN_PRIORITIES = (
    "readme.md",
    "package.json",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "cargo.toml",
    "go.mod",
    "tsconfig.json",
    "next.config.js",
    "prisma/schema.prisma",
    "src/",
    "app/",
    "server/",
    "scripts/",
    "tests/",
    "docs/",
)
CODE_FILE_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".cs",
    ".sql",
    ".prisma",
    ".sh",
)
CONFIG_FALLBACK_FILES = (
    "package.json",
    "pyproject.toml",
    "go.mod",
    "cargo.toml",
    "tsconfig.json",
    "next.config.js",
    "prisma/schema.prisma",
)


def _coerce_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def _keyword_tokens(text: str) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text.lower())
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return tuple(result)


def _partition_files(files_hint: list[str]) -> tuple[list[str], list[str], list[str]]:
    impl: list[str] = []
    tests: list[str] = []
    docs: list[str] = []
    for item in files_hint:
        lowered = item.lower()
        if (
            "tests/" in lowered
            or lowered.startswith("tests")
            or "test_" in lowered
            or lowered.endswith("_test.py")
            or "/spec" in lowered
            or "__tests__" in lowered
        ):
            tests.append(item)
        elif (
            lowered == "readme.md"
            or lowered.startswith("docs/")
            or lowered.endswith(".md")
            or "changelog" in lowered
        ):
            docs.append(item)
        else:
            impl.append(item)
    return impl, tests, docs


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _ranked_file_subset(
    candidates: list[str],
    *,
    preferred_terms: tuple[str, ...],
    context_terms: tuple[str, ...],
    fallback: list[str],
    max_items: int = 4,
) -> list[str]:
    if not candidates:
        return _dedupe(fallback)[:max_items]

    scored: list[tuple[int, int, str]] = []
    for index, path in enumerate(candidates):
        lowered = path.lower()
        score = 0
        score += sum(4 for term in preferred_terms if term in lowered)
        score += sum(1 for term in context_terms if term in lowered)
        scored.append((score, -index, path))

    scored.sort(reverse=True)
    chosen = [path for score, _, path in scored if score > 0][:max_items]
    if not chosen:
        chosen = candidates[:max_items]
    return _dedupe(chosen + fallback)[:max_items]


def _repo_root(repo: str) -> Path:
    base_dir = Path(os.getenv("AI_DEVOPS_HOME", str(Path.home() / "ai-devops")))
    return base_dir / "repos" / repo


def _priority_score(path: str) -> int:
    lowered = path.lower()
    score = 0
    for index, marker in enumerate(REPO_SCAN_PRIORITIES):
        if marker.endswith("/"):
            if lowered.startswith(marker):
                score += 100 - index
        elif lowered == marker:
            score += 120 - index
        elif marker in lowered:
            score += 40 - index
    if lowered.endswith((".md", ".txt")):
        score -= 5
    return score


def _discover_repo_file_hints(repo: str, *, max_items: int = 6) -> list[str]:
    repo_root = _repo_root(repo)
    if not repo_root.exists() or not repo_root.is_dir():
        return []

    candidates: list[str] = []
    for relative_root in REPO_SCAN_ROOTS:
        root = repo_root / relative_root if relative_root else repo_root
        if not root.exists() or not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                nested: list[Path] = []
                try:
                    nested = sorted(entry.iterdir(), key=lambda item: item.name.lower())[:4]
                except OSError:
                    nested = []
                for child in nested:
                    if child.name.startswith(".") or child.is_dir():
                        continue
                    candidates.append(str(child.relative_to(repo_root)))
            elif entry.is_file():
                candidates.append(str(entry.relative_to(repo_root)))

    unique = _dedupe(candidates)
    ranked = sorted(unique, key=lambda path: (-_priority_score(path), path.lower()))
    return ranked[:max_items]


def _code_priority_score(path: str) -> int:
    lowered = path.lower()
    if ".bak" in lowered or lowered.endswith(("~", ".tmp", ".orig")):
        return -100
    if lowered.endswith((".md", ".txt", ".css", ".scss", ".sass")):
        return -50
    if "test" in lowered or "spec" in lowered:
        return -20
    score = 0
    if lowered.startswith(("src/lib/", "src/app/", "src/components/")):
        score += 95
    elif lowered.startswith(("src/", "app/", "server/", "backend/", "frontend/")):
        score += 75
    elif lowered.startswith(("scripts/", "prisma/")):
        score += 50
    if lowered.endswith(CODE_FILE_EXTENSIONS):
        score += 35
    if lowered in CONFIG_FALLBACK_FILES:
        score += 10
    score += sum(6 for term in IMPLEMENTATION_FILE_TERMS if term in lowered)
    score += sum(4 for term in FOUNDATION_FILE_TERMS if term in lowered)
    return score


def _test_priority_score(path: str) -> int:
    lowered = path.lower()
    if ".bak" in lowered or lowered.endswith(("~", ".tmp", ".orig")):
        return -100
    if lowered.endswith((".md", ".txt", ".json", ".css", ".scss", ".sass")):
        return -100
    score = 0
    is_test_like = False
    if "tests/" in lowered or lowered.startswith("tests"):
        score += 90
        is_test_like = True
    if "test_" in lowered or lowered.endswith(("_test.py", ".spec.ts", ".spec.js", ".test.ts", ".test.js")):
        score += 70
        is_test_like = True
    if "__tests__" in lowered or "/spec" in lowered:
        score += 60
        is_test_like = True
    if not is_test_like:
        return 0
    if lowered.endswith(CODE_FILE_EXTENSIONS):
        score += 15
    return score


def _discover_repo_phase_hints(
    repo: str,
    *,
    max_implementation: int = 6,
    max_tests: int = 4,
    max_docs: int = 3,
) -> dict[str, list[str]]:
    repo_root = _repo_root(repo)
    if not repo_root.exists() or not repo_root.is_dir():
        return {"implementation": [], "tests": [], "docs": []}

    candidates: list[str] = []
    for relative_root in REPO_SCAN_ROOTS:
        root = repo_root / relative_root if relative_root else repo_root
        if not root.exists() or not root.is_dir():
            continue
        try:
            for child in root.rglob("*"):
                if not child.is_file():
                    continue
                if any(part.startswith(".") for part in child.relative_to(repo_root).parts):
                    continue
                depth = len(child.relative_to(root).parts)
                if depth > 3:
                    continue
                candidates.append(str(child.relative_to(repo_root)))
        except OSError:
            continue

    unique = _dedupe(candidates)
    docs = [path for path in unique if path.lower().endswith(".md") or path.lower().startswith("docs/")]
    tests = [path for path in unique if _test_priority_score(path) > 0]
    implementation = [path for path in unique if _code_priority_score(path) > 0 and path not in tests]
    config_fallback = [path for path in unique if path.lower() in CONFIG_FALLBACK_FILES]

    implementation = sorted(implementation, key=lambda path: (-_code_priority_score(path), path.lower()))
    tests = sorted(tests, key=lambda path: (-_test_priority_score(path), path.lower()))
    docs = sorted(docs, key=lambda path: (-_priority_score(path), path.lower()))
    implementation = _dedupe(implementation + config_fallback)

    return {
        "implementation": implementation[:max_implementation],
        "tests": tests[:max_tests],
        "docs": docs[:max_docs],
    }


def _default_definition_of_done(task_input: Mapping[str, Any]) -> list[str]:
    constraints = task_input.get("constraints")
    dod: list[str] = [
        "Implement the requested outcome end-to-end for this subtask.",
        "Preserve unrelated behavior and formatting.",
        "Run the most relevant local validation available before finishing.",
    ]
    if isinstance(constraints, dict):
        explicit = constraints.get("definitionOfDone")
        if isinstance(explicit, list):
            dod.extend(str(item).strip() for item in explicit if str(item).strip())
    return _dedupe(dod)


def _merge_definition_of_done(phase_items: list[str], global_items: list[str]) -> list[str]:
    return _dedupe(phase_items + global_items)


def _build_prompt(
    *,
    repo: str,
    plan_title: str,
    objective: str,
    subtask_id: str,
    subtask_title: str,
    description: str,
    constraints: Mapping[str, Any],
    definition_of_done: list[str],
    files_hint: list[str],
    depends_on: list[str],
    phase_boundary: str,
) -> str:
    lines = [
        "You are Zoe executing one subtask from a multi-step repository plan.",
        "",
        f"REPOSITORY: {repo}",
        f"PLAN TITLE: {plan_title}",
        f"SUBTASK: {subtask_id} - {subtask_title}",
        "",
        "PLAN OBJECTIVE:",
        objective,
        "",
        "SUBTASK SCOPE:",
        description,
    ]
    if depends_on:
        lines.extend(
            [
                "",
                "UPSTREAM DEPENDENCIES:",
                *[f"- {dep} is already completed and should be treated as the starting point." for dep in depends_on],
            ]
        )
    lines.extend(["", "DEFINITION OF DONE:"])
    lines.extend(f"- {item}" for item in definition_of_done)
    lines.extend(
        [
            "",
            "BOUNDARIES:",
            "- Do not access or print secrets, environment variables, or credentials.",
            "- Do not make unrelated refactors.",
            "- Keep changes scoped to this subtask and avoid absorbing later subtasks unless required to keep the repo healthy.",
            f"- {phase_boundary}",
        ]
    )
    if constraints:
        lines.append("- Respect the explicit constraints attached to this plan.")
    if files_hint:
        lines.extend(["", "FILES TO CHECK FIRST:"])
        lines.extend(f"- {item}" for item in files_hint)
    lines.extend(
        [
            "",
            "FIRST STEP:",
            "- Inspect the referenced files, write a short execution plan, then implement only this subtask.",
        ]
    )
    return "\n".join(lines)


@dataclass(slots=True, frozen=True)
class TaskProfile:
    files_hint: tuple[str, ...]
    implementation_files: tuple[str, ...]
    test_files: tuple[str, ...]
    doc_files: tuple[str, ...]
    docs_requested: bool
    tests_requested: bool
    docs_only: bool
    analysis_only: bool
    requires_foundation_split: bool


def _build_task_profile(
    *,
    title: str,
    objective: str,
    files_hint: list[str],
    has_explicit_files_hint: bool,
    constraints: Mapping[str, Any],
) -> TaskProfile:
    combined = f"{title}\n{objective}"
    impl_files, test_files, doc_files = _partition_files(files_hint)

    docs_requested = _contains_any(combined, DOC_ACTION_TERMS) or (has_explicit_files_hint and bool(doc_files))
    code_requested = _contains_any(combined, CODE_CHANGE_TERMS) or (has_explicit_files_hint and bool(impl_files))
    analysis_requested = _contains_any(combined, ANALYSIS_TERMS)
    docs_only = docs_requested and not analysis_requested and not code_requested and not bool(test_files)
    analysis_only = analysis_requested and not code_requested and not docs_requested

    complexity_score = 0
    if len(objective) >= 140:
        complexity_score += 1
    if len(files_hint) >= 3:
        complexity_score += 1
    if constraints:
        complexity_score += 1
    if _contains_any(combined, FOUNDATION_SPLIT_TERMS):
        complexity_score += 1
    if any(token in combined.lower() for token in (" and ", " then ", " also ", " plus ", "以及", "并且")):
        complexity_score += 1

    tests_requested = not docs_only and not analysis_only
    requires_foundation_split = (
        not docs_only
        and not analysis_only
        and (complexity_score >= 3 or _contains_any(combined, FOUNDATION_SPLIT_TERMS))
    )

    return TaskProfile(
        files_hint=tuple(files_hint),
        implementation_files=tuple(impl_files),
        test_files=tuple(test_files),
        doc_files=tuple(doc_files),
        docs_requested=docs_requested,
        tests_requested=tests_requested,
        docs_only=docs_only,
        analysis_only=analysis_only,
        requires_foundation_split=requires_foundation_split,
    )


def _phase_files(
    *,
    repo: str,
    title: str,
    objective: str,
    profile: TaskProfile,
    has_explicit_files_hint: bool,
) -> dict[str, list[str]]:
    context_terms = _keyword_tokens(f"{title} {objective}")
    discovered = _discover_repo_phase_hints(repo)
    if has_explicit_files_hint:
        implementation_files = list(profile.implementation_files) or discovered["implementation"]
        test_files = list(profile.test_files) or discovered["tests"]
        doc_files = list(profile.doc_files) or discovered["docs"]
    else:
        implementation_files = discovered["implementation"]
        test_files = discovered["tests"]
        doc_files = discovered["docs"]

    foundation_files = _ranked_file_subset(
        implementation_files,
        preferred_terms=FOUNDATION_FILE_TERMS,
        context_terms=context_terms,
        fallback=implementation_files[:2] or list(profile.files_hint[:2]),
    )
    primary_impl_files = _ranked_file_subset(
        implementation_files,
        preferred_terms=IMPLEMENTATION_FILE_TERMS,
        context_terms=context_terms,
        fallback=implementation_files[:3] or foundation_files,
    )
    validation_files = _ranked_file_subset(
        test_files or implementation_files,
        preferred_terms=("test", "spec", "fixture", "integration", "e2e"),
        context_terms=context_terms,
        fallback=(test_files[:2] + primary_impl_files[:2]) or ["tests/"],
    )
    documentation_files = _ranked_file_subset(
        doc_files or list(profile.files_hint),
        preferred_terms=DOC_FILE_TERMS,
        context_terms=context_terms,
        fallback=doc_files[:2] or ["README.md", "docs/"],
    )

    return {
        "foundation": foundation_files,
        "implementation": primary_impl_files,
        "validation": validation_files,
        "documentation": documentation_files,
    }


def _subtask_payload(
    *,
    subtask_id: str,
    title: str,
    description: str,
    agent: str,
    model: str,
    effort: str,
    depends_on: list[str],
    files_hint: list[str],
    definition_of_done: list[str],
    prompt: str,
) -> dict[str, Any]:
    return {
        "id": subtask_id,
        "title": title,
        "description": description,
        "agent": agent,
        "model": model,
        "effort": effort,
        "worktreeStrategy": "isolated",
        "dependsOn": depends_on,
        "filesHint": files_hint,
        "prompt": prompt,
        "definitionOfDone": definition_of_done,
    }


def _plan_analysis_task(
    *,
    repo: str,
    title: str,
    objective: str,
    constraints: Mapping[str, Any],
    profile: TaskProfile,
    agent: str,
    model: str,
    effort: str,
    global_dod: list[str],
) -> list[dict[str, Any]]:
    phase_dod = _merge_definition_of_done(
        [
            "Summarize the current implementation state with concrete file-level findings.",
            "Capture recommended next actions in a checked-in note or report file when no existing artifact is provided.",
        ],
        global_dod,
    )
    files_hint = list(profile.files_hint)
    prompt = _build_prompt(
        repo=repo,
        plan_title=title,
        objective=objective,
        subtask_id="S1",
        subtask_title="Analyze the current state",
        description="Inspect the relevant code and document the current state, blockers, and recommended next steps.",
        constraints=constraints,
        definition_of_done=phase_dod,
        files_hint=files_hint,
        depends_on=[],
        phase_boundary="Focus on analysis and reporting. Do not implement speculative code changes unless they are required to make the report accurate.",
    )
    return [
        _subtask_payload(
            subtask_id="S1",
            title="Analyze the current state",
            description="Inspect the relevant code and document the current state, blockers, and recommended next steps.",
            agent=agent,
            model=model,
            effort=effort,
            depends_on=[],
            files_hint=files_hint,
            definition_of_done=phase_dod,
            prompt=prompt,
        )
    ]


def _plan_docs_only_task(
    *,
    repo: str,
    title: str,
    objective: str,
    constraints: Mapping[str, Any],
    profile: TaskProfile,
    agent: str,
    model: str,
    effort: str,
    global_dod: list[str],
) -> list[dict[str, Any]]:
    files_hint = list(profile.doc_files) or ["README.md", "docs/"]
    phase_dod = _merge_definition_of_done(
        [
            "Update the requested documentation or written guidance.",
            "Keep examples, command snippets, and terminology internally consistent.",
        ],
        global_dod,
    )
    prompt = _build_prompt(
        repo=repo,
        plan_title=title,
        objective=objective,
        subtask_id="S1",
        subtask_title="Update documentation",
        description="Make the requested documentation changes and keep the written guidance consistent with the current repository behavior.",
        constraints=constraints,
        definition_of_done=phase_dod,
        files_hint=files_hint,
        depends_on=[],
        phase_boundary="Stay within docs, examples, and text-based guidance unless a tiny supporting code snippet must be corrected for accuracy.",
    )
    return [
        _subtask_payload(
            subtask_id="S1",
            title="Update documentation",
            description="Make the requested documentation changes and keep the written guidance consistent with the current repository behavior.",
            agent=agent,
            model=model,
            effort=effort,
            depends_on=[],
            files_hint=files_hint,
            definition_of_done=phase_dod,
            prompt=prompt,
        )
    ]


def _plan_code_change_tasks(
    *,
    repo: str,
    title: str,
    objective: str,
    constraints: Mapping[str, Any],
    profile: TaskProfile,
    agent: str,
    model: str,
    effort: str,
    global_dod: list[str],
    has_explicit_files_hint: bool,
) -> list[dict[str, Any]]:
    subtasks: list[dict[str, Any]] = []
    dependency_chain: list[str] = []
    phase_files = _phase_files(
        repo=repo,
        title=title,
        objective=objective,
        profile=profile,
        has_explicit_files_hint=has_explicit_files_hint,
    )
    impl_files = phase_files["implementation"] or list(profile.implementation_files) or list(profile.files_hint)
    foundation_files = phase_files["foundation"] or impl_files
    test_files = phase_files["validation"] or list(profile.test_files) or ["tests/"]
    doc_files = phase_files["documentation"] or list(profile.doc_files) or ["README.md", "docs/"]

    if profile.requires_foundation_split:
        foundation_id = "S1"
        foundation_dod = _merge_definition_of_done(
            [
                "Extract or reshape the core implementation surface needed for the requested change.",
                "Leave the codebase in a stable state that the follow-up implementation step can build on directly.",
            ],
            global_dod,
        )
        foundation_prompt = _build_prompt(
            repo=repo,
            plan_title=title,
            objective=objective,
            subtask_id=foundation_id,
            subtask_title="Prepare the implementation surface",
            description="Make the structural or foundational code changes required before the main behavior update lands.",
            constraints=constraints,
            definition_of_done=foundation_dod,
            files_hint=foundation_files,
            depends_on=[],
            phase_boundary="Focus on foundation work only. Do not absorb the follow-up validation or documentation work into this step.",
        )
        subtasks.append(
            _subtask_payload(
                subtask_id=foundation_id,
                title="Prepare the implementation surface",
                description="Make the structural or foundational code changes required before the main behavior update lands.",
                agent=agent,
                model=model,
                effort=effort,
                depends_on=[],
                files_hint=foundation_files,
                definition_of_done=foundation_dod,
                prompt=foundation_prompt,
            )
        )
        dependency_chain = [foundation_id]

    implementation_id = f"S{len(subtasks) + 1}"
    implementation_dod = _merge_definition_of_done(
        [
            "Complete the primary behavior change requested by the objective.",
            "Keep the implementation scoped to the affected feature area.",
        ],
        global_dod,
    )
    implementation_prompt = _build_prompt(
        repo=repo,
        plan_title=title,
        objective=objective,
        subtask_id=implementation_id,
        subtask_title="Land the primary implementation",
        description=f"Implement the main repository change for '{title}' and wire it through the affected code paths.",
        constraints=constraints,
        definition_of_done=implementation_dod,
        files_hint=impl_files,
        depends_on=dependency_chain,
        phase_boundary="Focus on the code path changes. Defer dedicated validation and docs work to later subtasks unless a minimal adjustment is required to keep the change correct.",
    )
    subtasks.append(
        _subtask_payload(
            subtask_id=implementation_id,
            title="Land the primary implementation",
            description=f"Implement the main repository change for '{title}' and wire it through the affected code paths.",
            agent=agent,
            model=model,
            effort=effort,
            depends_on=list(dependency_chain),
            files_hint=impl_files,
            definition_of_done=implementation_dod,
            prompt=implementation_prompt,
        )
    )
    dependency_chain = [implementation_id]

    if profile.tests_requested:
        validation_id = f"S{len(subtasks) + 1}"
        validation_dod = _merge_definition_of_done(
            [
                "Add or update focused validation that proves the requested behavior.",
                "Make sure the relevant tests or checks would fail without the implementation change.",
            ],
            global_dod,
        )
        validation_prompt = _build_prompt(
            repo=repo,
            plan_title=title,
            objective=objective,
            subtask_id=validation_id,
            subtask_title="Add validation and regression coverage",
            description="Add or adjust the most relevant tests, checks, or validation artifacts for the preceding implementation change.",
            constraints=constraints,
            definition_of_done=validation_dod,
            files_hint=test_files,
            depends_on=dependency_chain,
            phase_boundary="Stay focused on tests, checks, and validation. Do not reopen broad implementation work unless the earlier subtask left a small correctness gap.",
        )
        subtasks.append(
            _subtask_payload(
                subtask_id=validation_id,
                title="Add validation and regression coverage",
                description="Add or adjust the most relevant tests, checks, or validation artifacts for the preceding implementation change.",
                agent=agent,
                model=model,
                effort=effort,
                depends_on=list(dependency_chain),
                files_hint=test_files,
                definition_of_done=validation_dod,
                prompt=validation_prompt,
            )
        )
        dependency_chain = [validation_id]

    if profile.docs_requested:
        docs_id = f"S{len(subtasks) + 1}"
        docs_dod = _merge_definition_of_done(
            [
                "Update documentation or operator guidance affected by the change.",
                "Keep docs aligned with the behavior and commands introduced by earlier subtasks.",
            ],
            global_dod,
        )
        docs_prompt = _build_prompt(
            repo=repo,
            plan_title=title,
            objective=objective,
            subtask_id=docs_id,
            subtask_title="Update documentation and handoff notes",
            description="Update the repository documentation, README, or handoff notes that should change after the implementation and validation work.",
            constraints=constraints,
            definition_of_done=docs_dod,
            files_hint=doc_files,
            depends_on=dependency_chain,
            phase_boundary="Stay within docs and handoff artifacts. Do not introduce fresh feature work in this subtask.",
        )
        subtasks.append(
            _subtask_payload(
                subtask_id=docs_id,
                title="Update documentation and handoff notes",
                description="Update the repository documentation, README, or handoff notes that should change after the implementation and validation work.",
                agent=agent,
                model=model,
                effort=effort,
                depends_on=list(dependency_chain),
                files_hint=doc_files,
                definition_of_done=docs_dod,
                prompt=docs_prompt,
            )
        )

    return subtasks


@dataclass(slots=True)
class ZoePlannerEngine:
    """
    Internal planning engine for Zoe.

    Zoe itself is the planning agent, so plan generation lives inside the
    orchestrator instead of calling an external planner service.
    """

    def plan(self, task_input: Mapping[str, Any]) -> Plan:
        repo = _coerce_text(task_input.get("repo"))
        title = _coerce_text(task_input.get("title"))
        objective = _coerce_text(task_input.get("objective") or task_input.get("description"))
        requested_by = _coerce_text(task_input.get("requestedBy"))
        version = _coerce_text(task_input.get("version"))
        plan_id = _coerce_text(task_input.get("planId"))

        if not repo or not title or not objective or not requested_by or not version or not plan_id:
            raise InvalidPlan("Planner request is missing required fields")

        requested_at = task_input.get("requestedAt")
        if not isinstance(requested_at, int):
            raise InvalidPlan("Planner request requestedAt must be an integer")

        routing = task_input.get("routing") if isinstance(task_input.get("routing"), dict) else {}
        constraints = dict(task_input.get("constraints")) if isinstance(task_input.get("constraints"), dict) else {}
        context = dict(task_input.get("context")) if isinstance(task_input.get("context"), dict) else {}
        explicit_files_hint = context.get("filesHint")
        if not isinstance(explicit_files_hint, list):
            explicit_files_hint = []
        explicit_files_hint = _dedupe(
            [str(item).strip() for item in explicit_files_hint if str(item).strip()]
        )
        has_explicit_files_hint = bool(explicit_files_hint)
        files_hint = explicit_files_hint or _discover_repo_file_hints(repo)

        agent = _coerce_text(routing.get("agent") or "codex")
        model = _coerce_text(routing.get("model") or "gpt-5.3-codex")
        effort = _coerce_text(routing.get("effort") or "medium")
        definition_of_done = _default_definition_of_done(task_input)
        profile = _build_task_profile(
            title=title,
            objective=objective,
            files_hint=files_hint,
            has_explicit_files_hint=has_explicit_files_hint,
            constraints=constraints,
        )

        if profile.analysis_only:
            subtasks = _plan_analysis_task(
                repo=repo,
                title=title,
                objective=objective,
                constraints=constraints,
                profile=profile,
                agent=agent,
                model=model,
                effort=effort,
                global_dod=definition_of_done,
            )
        elif profile.docs_only:
            subtasks = _plan_docs_only_task(
                repo=repo,
                title=title,
                objective=objective,
                constraints=constraints,
                profile=profile,
                agent=agent,
                model=model,
                effort=effort,
                global_dod=definition_of_done,
            )
        else:
            subtasks = _plan_code_change_tasks(
                repo=repo,
                title=title,
                objective=objective,
                constraints=constraints,
                profile=profile,
                agent=agent,
                model=model,
                effort=effort,
                global_dod=definition_of_done,
                has_explicit_files_hint=has_explicit_files_hint,
            )

        context.setdefault(
            "planner",
            {
                "strategy": "phased-v1",
                "docsRequested": profile.docs_requested,
                "testsRequested": profile.tests_requested,
                "docsOnly": profile.docs_only,
                "analysisOnly": profile.analysis_only,
                "requiresFoundationSplit": profile.requires_foundation_split,
                "subtaskCount": len(subtasks),
            },
        )

        payload = {
            "planId": plan_id,
            "repo": repo,
            "title": title,
            "requestedBy": requested_by,
            "requestedAt": requested_at,
            "objective": objective,
            "constraints": constraints,
            "context": context,
            "routing": routing,
            "version": version,
            "subtasks": subtasks,
        }
        return Plan.from_dict(payload)
