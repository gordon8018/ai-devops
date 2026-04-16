from __future__ import annotations

from packages.context.graph.service import ContextGraphBuilder
from packages.context.indexer.repository import RepositoryIndex


def test_context_graph_links_modules_to_tests_and_docs() -> None:
    index = RepositoryIndex(
        repo_root="/tmp/repo",
        files=("src/service.py", "src/other.py"),
        docs=("docs/service.md",),
        tests=("tests/test_service.py",),
        routes=("apps/api/routes.py",),
    )

    graph = ContextGraphBuilder().build(index)

    related = graph.related_paths(("src/service.py",))

    assert "tests/test_service.py" in related
    assert "docs/service.md" in related
