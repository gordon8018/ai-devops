from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class RepositoryIndex:
    repo_root: str
    files: tuple[str, ...]
    docs: tuple[str, ...]
    tests: tuple[str, ...]
    routes: tuple[str, ...]


class RepositoryIndexer:
    """Build a lightweight repository index for context packing."""

    def index(self, repo_root: Path) -> RepositoryIndex:
        root = repo_root.resolve()
        files: list[str] = []
        docs: list[str] = []
        tests: list[str] = []
        routes: list[str] = []

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if ".git/" in rel or rel.startswith(".git/"):
                continue
            files.append(rel)
            lower = rel.lower()
            if lower.endswith(".md") or "/docs/" in f"/{lower}":
                docs.append(rel)
            if (
                lower.startswith("tests/")
                or "/tests/" in f"/{lower}"
                or path.name.startswith("test_")
                or path.name.endswith("_test.py")
            ):
                tests.append(rel)
            if any(token in lower for token in ("route", "router", "api", "server")):
                routes.append(rel)

        return RepositoryIndex(
            repo_root=str(root),
            files=tuple(files),
            docs=tuple(docs),
            tests=tuple(tests),
            routes=tuple(routes),
        )
