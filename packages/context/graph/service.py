from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.context.indexer.repository import RepositoryIndex


def _stem_tokens(path: str) -> set[str]:
    name = Path(path).stem.lower().replace("test_", "").replace("_test", "")
    parts = {name}
    parts.update(part for part in name.replace("-", "_").split("_") if part)
    return {part for part in parts if part}


@dataclass(slots=True, frozen=True)
class ContextGraph:
    module_links: dict[str, tuple[str, ...]]

    def related_paths(self, seeds: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        related: list[str] = []
        for seed in seeds:
            for candidate in self.module_links.get(seed, ()):
                if candidate in seen:
                    continue
                seen.add(candidate)
                related.append(candidate)
        return tuple(related)


class ContextGraphBuilder:
    """Link indexed files to adjacent tests and docs."""

    def build(self, index: RepositoryIndex) -> ContextGraph:
        docs_by_token: dict[str, list[str]] = {}
        tests_by_token: dict[str, list[str]] = {}

        for doc in index.docs:
            for token in _stem_tokens(doc):
                docs_by_token.setdefault(token, []).append(doc)
        for test in index.tests:
            for token in _stem_tokens(test):
                tests_by_token.setdefault(token, []).append(test)

        module_links: dict[str, tuple[str, ...]] = {}
        for file_path in index.files:
            related: list[str] = []
            for token in _stem_tokens(file_path):
                related.extend(tests_by_token.get(token, ()))
                related.extend(docs_by_token.get(token, ()))
            deduped: list[str] = []
            seen: set[str] = set()
            for item in related:
                if item == file_path or item in seen:
                    continue
                seen.add(item)
                deduped.append(item)
            module_links[file_path] = tuple(deduped)

        return ContextGraph(module_links=module_links)
