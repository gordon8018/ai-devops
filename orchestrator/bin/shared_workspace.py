#!/usr/bin/env python3
"""Shared Workspace - 共享工作区管理"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    from .config import ai_devops_home
except ImportError:
    from config import ai_devops_home

logger = logging.getLogger(__name__)


@dataclass
class WorkspaceFile:
    """工作区文件元数据"""
    path: str
    agent_id: str
    created_at: int
    updated_at: int
    size: int = 0
    locked_by: Optional[str] = None
    locked_at: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "agentId": self.agent_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "size": self.size,
            "lockedBy": self.locked_by,
            "lockedAt": self.locked_at,
        }


class SharedWorkspace:
    """共享工作区管理"""
    
    def __init__(self, plan_id: str, base_dir: Optional[Path] = None):
        self.plan_id = plan_id
        self.base_dir = base_dir or ai_devops_home()
        self.workspace_dir = self.base_dir / "shared_workspaces" / plan_id
        self.metadata_file = self.workspace_dir / ".workspace_meta.json"
        self._lock_dir = self.workspace_dir / ".locks"
        self._initialized = False
        self._lock = threading.Lock()
    
    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self.workspace_dir.mkdir(parents=True, exist_ok=True)
            self._lock_dir.mkdir(parents=True, exist_ok=True)
            if not self.metadata_file.exists():
                self._save_meta({
                    "planId": self.plan_id,
                    "createdAt": int(time.time() * 1000),
                    "files": {},
                })
            self._initialized = True
    
    def _load_meta(self) -> dict:
        if not self.metadata_file.exists():
            return {"planId": self.plan_id, "files": {}}
        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"planId": self.plan_id, "files": {}}
    
    def _save_meta(self, meta: dict) -> None:
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.metadata_file, "w") as f:
            json.dump(meta, f, indent=2)
    def write_file(self, rel_path: str, content: str, agent_id: str) -> WorkspaceFile:
        self.initialize()
        file_path = self.workspace_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        now = int(time.time() * 1000)
        file_path.write_text(content, encoding="utf-8")
        size = len(content.encode("utf-8"))
        meta = self._load_meta()
        files = meta.get("files", {})
        files[rel_path] = {
            "path": rel_path,
            "agentId": agent_id,
            "createdAt": files.get(rel_path, {}).get("createdAt", now),
            "updatedAt": now,
            "size": size,
        }
        meta["files"] = files
        self._save_meta(meta)
        return WorkspaceFile(
            path=rel_path,
            agent_id=agent_id,
            created_at=files[rel_path]["createdAt"],
            updated_at=now,
            size=size,
        )
    
    def read_file(self, rel_path: str) -> Optional[str]:
        self.initialize()
        fp = self.workspace_dir / rel_path
        return fp.read_text("utf-8") if fp.exists() else None
    
    def delete_file(self, rel_path: str) -> bool:
        self.initialize()
        fp = self.workspace_dir / rel_path
        if not fp.exists():
            return False
        fp.unlink()
        meta = self._load_meta()
        files = meta.get("files", {})
        if rel_path in files:
            del files[rel_path]
            meta["files"] = files
            self._save_meta(meta)
        return True
    def acquire_lock(self, rel_path: str, agent_id: str, timeout: float = 10.0) -> bool:
        self.initialize()
        lock_file = self._lock_dir / f"{rel_path.replace('/', '_')}.lock"
        start = time.time()
        while time.time() - start < timeout:
            try:
                import os as _os
                fd = _os.open(str(lock_file), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY)
                _os.write(fd, f"{agent_id}\n{time.time()}".encode())
                _os.close(fd)
                return True
            except FileExistsError:
                try:
                    data = lock_file.read_text().strip().split("\n")
                    if len(data) >= 2 and time.time() - float(data[1]) > timeout * 2:
                        lock_file.unlink()
                        continue
                except (IOError, ValueError):
                    pass
                time.sleep(0.1)
        return False
    
    def release_lock(self, rel_path: str, agent_id: str) -> bool:
        self.initialize()
        lock_file = self._lock_dir / f"{rel_path.replace('/', '_')}.lock"
        if not lock_file.exists():
            return True
        try:
            data = lock_file.read_text().strip().split("\n")
            if data and data[0] == agent_id:
                lock_file.unlink()
                return True
        except (IOError, IndexError):
            pass
        return False
    
    def list_files(self) -> list[WorkspaceFile]:
        self.initialize()
        meta = self._load_meta()
        result = []
        for path, info in meta.get("files", {}).items():
            result.append(WorkspaceFile(
                path=info.get("path", path),
                agent_id=info.get("agentId", "unknown"),
                created_at=info.get("createdAt", 0),
                updated_at=info.get("updatedAt", 0),
                size=info.get("size", 0),
                locked_by=info.get("lockedBy"),
                locked_at=info.get("lockedAt"),
            ))
        return result
    def detect_conflicts(self) -> list[dict[str, Any]]:
        self.initialize()
        conflicts = []
        meta = self._load_meta()
        now = time.time() * 1000
        for path, info in meta.get("files", {}).items():
            if info.get("lockedBy") and info.get("lockedAt"):
                if now - info["lockedAt"] > 30 * 60 * 1000:
                    conflicts.append({
                        "type": "stale_lock",
                        "path": path,
                        "lockedBy": info["lockedBy"],
                        "lockedAt": info["lockedAt"],
                    })
        return conflicts
    
    def get_path(self) -> Path:
        self.initialize()
        return self.workspace_dir
    
    def export_context(self) -> dict[str, Any]:
        self.initialize()
        return {
            "planId": self.plan_id,
            "workspacePath": str(self.workspace_dir),
            "files": [f.to_dict() for f in self.list_files()],
            "conflicts": self.detect_conflicts(),
        }


# === 全局管理器 ===

import threading
_workspaces: dict[str, SharedWorkspace] = {}
_ws_lock = threading.Lock()

def get_workspace(plan_id: str) -> SharedWorkspace:
    with _ws_lock:
        if plan_id not in _workspaces:
            _workspaces[plan_id] = SharedWorkspace(plan_id)
            _workspaces[plan_id].initialize()
        return _workspaces[plan_id]

def clear_workspace(plan_id: str) -> bool:
    with _ws_lock:
        if plan_id in _workspaces:
            del _workspaces[plan_id]
            return True
        return False

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: shared_workspace.py <plan_id>")
        sys.exit(1)
    ws = get_workspace(sys.argv[1])
    print(f"Workspace: {ws.get_path()}")
