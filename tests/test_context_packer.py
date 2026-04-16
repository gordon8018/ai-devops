from __future__ import annotations

from pathlib import Path

from packages.context.adapters.git import GitContextAdapter
from packages.context.adapters.obsidian import ObsidianContextAdapter
from packages.context.graph.service import ContextGraphBuilder
from packages.context.indexer.repository import RepositoryIndexer
from packages.context.packer.service import ContextPackAssembler
from packages.shared.domain.models import WorkItem, WorkItemPriority, WorkItemStatus, WorkItemType


class FakeGitAdapter(GitContextAdapter):
    def recent_changes(self, repo_root, limit: int = 5):  # type: ignore[override]
        return ("commit:abc123 Add guardrails",)


class FakeObsidianAdapter(ObsidianContextAdapter):
    def __init__(self) -> None:
        pass

    def search(self, query: str, limit: int = 3):  # type: ignore[override]
        return ("notes/guardrails.md",)

    def failure_excerpts(self, query: str, limit: int = 3):  # type: ignore[override]
        return ("previous rollout exceeded error threshold",)


def test_context_pack_assembler_uses_index_graph_and_adapters(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "tests").mkdir()
    (repo_root / "docs").mkdir()
    (repo_root / "src" / "rollout.py").write_text("def rollout():\n    return True\n", encoding="utf-8")
    (repo_root / "tests" / "test_rollout.py").write_text("def test_rollout():\n    assert True\n", encoding="utf-8")
    (repo_root / "docs" / "rollout.md").write_text("# Rollout\n", encoding="utf-8")

    work_item = WorkItem(
        work_item_id="wi_001",
        type=WorkItemType.FEATURE,
        title="Add rollout guardrails",
        goal="Improve release safety",
        priority=WorkItemPriority.HIGH,
        status=WorkItemStatus.PLANNING,
        repo="acme/platform",
        constraints={"allowedPaths": ["src/rollout.py"]},
    )
    assembler = ContextPackAssembler(
        repo_indexer=RepositoryIndexer(),
        graph_builder=ContextGraphBuilder(),
        git_adapter=FakeGitAdapter(),
        obsidian_adapter=FakeObsidianAdapter(),
        repo_locator=lambda repo: repo_root,
    )

    pack = assembler.build(
        work_item,
        legacy_task_input={
            "context": {
                "filesHint": ["src/rollout.py"],
                "acceptanceCriteria": ["Guardrail checks are captured"],
            }
        },
    )

    assert "src/rollout.py" in pack.repo_scope
    assert "tests/test_rollout.py" in pack.repo_scope
    assert "docs/rollout.md" in pack.docs
    assert "notes/guardrails.md" in pack.docs
    assert pack.recent_changes == ("commit:abc123 Add guardrails",)
    assert "previous rollout exceeded error threshold" in pack.known_failures
