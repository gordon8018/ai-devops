import json
from pathlib import Path

def compile_prompt(task: dict, repo_root: Path) -> str:
    """
    MVP: 先用模板 prompt 跑通。
    后续：如果 Zoe planner 没有提供 prompt，再在这里补更强的本地编译逻辑。
    """
    title = task["title"]
    desc = task["description"]

    # 你可以在 repo 里放一个 CONTEXT.md / SPEC.md，供 prompt 自动引用
    context_files = ["SPEC.md", "CONTEXT.md", "README.md"]
    existing = [f for f in context_files if (repo_root / f).exists()]

    context_hint = ""
    if existing:
        context_hint = "Useful context files:\n" + "\n".join([f"- {f}" for f in existing])

    return f"""You are a senior engineer working in this repository.

TASK TITLE:
{title}

TASK DESCRIPTION:
{desc}

DEFINITION OF DONE:
- Implement the change
- Add/adjust tests if relevant
- Run local checks (lint/typecheck/unit) if available
- Create commits with clear messages
- Push branch and create a PR via `gh pr create --fill`

CONSTRAINTS:
- Prefer minimal, safe changes
- Do not change unrelated formatting
- If uncertain, search within repo first, then decide

{context_hint}

FIRST STEP:
- Identify relevant files and write a short plan.
"""

if __name__ == "__main__":
    import sys
    task_path = Path(sys.argv[1])
    repo_root = Path(sys.argv[2])
    task = json.loads(task_path.read_text(encoding="utf-8"))
    print(compile_prompt(task, repo_root))
