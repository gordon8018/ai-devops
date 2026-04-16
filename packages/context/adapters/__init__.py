"""Context adapters for Git, Obsidian, and other external sources."""

from .git import GitContextAdapter
from .obsidian import ObsidianContextAdapter

__all__ = ["GitContextAdapter", "ObsidianContextAdapter"]
