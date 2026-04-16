from __future__ import annotations

from pathlib import Path

from packages.context.indexer.repository import RepositoryIndexer


def test_repository_indexer_categorizes_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    (repo_root / "src").mkdir(parents=True)
    (repo_root / "tests").mkdir()
    (repo_root / "docs").mkdir()
    (repo_root / "apps" / "api").mkdir(parents=True)
    (repo_root / "src" / "service.py").write_text("def run():\n    return True\n", encoding="utf-8")
    (repo_root / "tests" / "test_service.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    (repo_root / "docs" / "service.md").write_text("# Service\n", encoding="utf-8")
    (repo_root / "apps" / "api" / "routes.py").write_text("ROUTES = []\n", encoding="utf-8")

    index = RepositoryIndexer().index(repo_root)

    assert "src/service.py" in index.files
    assert "tests/test_service.py" in index.tests
    assert "docs/service.md" in index.docs
    assert "apps/api/routes.py" in index.routes
