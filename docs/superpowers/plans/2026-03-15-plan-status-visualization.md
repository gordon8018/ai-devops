# Plan Status Visualization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `agent plan-status <plan-id>` command with a rich terminal TUI and a browser HTML dashboard that polls a local JSON API for live plan/subtask status.

**Architecture:** A data-aggregation module (`plan_status.py`) reads SQLite + archived JSON files to build a unified `PlanView`. A renderer (`plan_status_renderer.py`) displays it using `rich`. An HTTP server (`plan_status_server.py`) exposes the same data as JSON and serves an embedded HTML dashboard. The CLI (`agent.py`) wires it all together.

**Tech Stack:** Python 3.10+, `rich` (already a dependency), stdlib `http.server` / `threading` / `webbrowser`, SQLite via existing `db.py`.

---

## Chunk 1: Data Aggregation Layer

**Files:**
- Create: `orchestrator/bin/plan_status.py`
- Create: `tests/test_plan_status.py`

### Task 1: Define `PlanView` and `SubtaskView` dataclasses

**Files:**
- Create: `orchestrator/bin/plan_status.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_status.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status import SubtaskView, PlanView

def test_subtask_view_defaults():
    sv = SubtaskView(id="s1", title="Fix auth", status="queued")
    assert sv.id == "s1"
    assert sv.agent is None
    assert sv.pr_url is None
    assert sv.depends_on == ()

def test_plan_view_progress():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready"),
        SubtaskView(id="s2", title="B", status="running"),
        SubtaskView(id="s3", title="C", status="queued"),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    assert pv.completed_count == 1
    assert pv.total_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/gordonyang/workspace/myproject/ai-devops
python -m pytest tests/test_plan_status.py::test_subtask_view_defaults -v
```

Expected: `ModuleNotFoundError: No module named 'plan_status'`

- [ ] **Step 3: Implement `SubtaskView` and `PlanView`**

```python
# orchestrator/bin/plan_status.py
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Statuses considered "completed" for progress tracking
_COMPLETED_STATUSES = frozenset({"ready", "merged"})


@dataclass
class SubtaskView:
    id: str
    title: str
    status: str                         # from DB or dispatch archive
    agent: str | None = None
    model: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    attempts: int = 0
    note: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass
class PlanView:
    plan_id: str
    repo: str
    subtasks: list[SubtaskView]
    objective: str = ""
    requested_by: str = ""
    requested_at: int | None = None

    @property
    def completed_count(self) -> int:
        return sum(1 for s in self.subtasks if s.status in _COMPLETED_STATUSES)

    @property
    def total_count(self) -> int:
        return len(self.subtasks)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_plan_status.py::test_subtask_view_defaults tests/test_plan_status.py::test_plan_view_progress -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/plan_status.py tests/test_plan_status.py
git commit -m "feat: add PlanView/SubtaskView dataclasses for plan status aggregation"
```

---

### Task 2: Implement `load_plan_view` — aggregate DB + archive data

**Files:**
- Modify: `orchestrator/bin/plan_status.py`
- Modify: `tests/test_plan_status.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_plan_status.py`:

```python
import json
import sqlite3
import tempfile
import os

def _make_db(tmp: Path, tasks: list[dict]) -> Path:
    db_path = tmp / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE agent_tasks (
            id TEXT PRIMARY KEY, plan_id TEXT, repo TEXT, title TEXT,
            status TEXT, agent TEXT, model TEXT, pr_number INTEGER,
            pr_url TEXT, attempts INTEGER DEFAULT 0, note TEXT,
            metadata TEXT, created_at INTEGER, updated_at INTEGER
        )
    """)
    for t in tasks:
        conn.execute(
            "INSERT INTO agent_tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (t["id"], t.get("plan_id"), t["repo"], t["title"], t["status"],
             t.get("agent"), t.get("model"), t.get("pr_number"), t.get("pr_url"),
             t.get("attempts", 0), t.get("note"), None, 0, 0)
        )
    conn.commit()
    conn.close()
    return db_path


def _make_plan_archive(tmp: Path, plan_id: str, subtasks: list[dict], plan_meta: dict) -> None:
    plan_dir = tmp / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps(plan_meta))
    subtasks_dir = plan_dir / "subtasks"
    subtasks_dir.mkdir()
    for s in subtasks:
        (subtasks_dir / f"{s['id']}.json").write_text(json.dumps(s))


def test_load_plan_view_merges_db_and_archive(tmp_path, monkeypatch):
    plan_id = "feat-auth"
    _make_db(tmp_path, [
        {"id": "feat-auth-s1", "plan_id": plan_id, "repo": "org/repo",
         "title": "Schema", "status": "ready", "attempts": 0},
        {"id": "feat-auth-s2", "plan_id": plan_id, "repo": "org/repo",
         "title": "API", "status": "running", "attempts": 1},
    ])
    _make_plan_archive(tmp_path, plan_id, [
        {"id": "s1", "title": "Schema", "depends_on": []},
        {"id": "s2", "title": "API", "depends_on": ["s1"]},
    ], {"planId": plan_id, "repo": "org/repo", "objective": "Add auth",
        "requestedBy": "gordon", "requestedAt": 0})

    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    from plan_status import load_plan_view
    pv = load_plan_view(plan_id, base_dir=tmp_path)

    assert pv.plan_id == plan_id
    assert pv.repo == "org/repo"
    assert pv.objective == "Add auth"
    assert len(pv.subtasks) == 2

    s1 = next(s for s in pv.subtasks if s.id == "s1")
    s2 = next(s for s in pv.subtasks if s.id == "s2")
    assert s1.status == "ready"
    assert s2.status == "running"
    assert s2.depends_on == ("s1",)
    assert pv.completed_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_plan_status.py::test_load_plan_view_merges_db_and_archive -v
```

Expected: `ImportError: cannot import name 'load_plan_view'`

- [ ] **Step 3: Implement `load_plan_view`**

Append to `orchestrator/bin/plan_status.py`:

```python
def _load_archive_subtasks(plan_dir: Path) -> dict[str, dict[str, Any]]:
    """Return {subtask_id: archive_dict} from tasks/<plan-id>/subtasks/*.json."""
    result: dict[str, dict[str, Any]] = {}
    subtasks_dir = plan_dir / "subtasks"
    if not subtasks_dir.exists():
        return result
    for path in subtasks_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sid = data.get("id")
            if sid:
                result[sid] = data
        except (OSError, json.JSONDecodeError):
            pass
    return result


def _load_plan_meta(plan_dir: Path) -> dict[str, Any]:
    plan_file = plan_dir / "plan.json"
    if not plan_file.exists():
        return {}
    try:
        return json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_plan_view(plan_id: str, base_dir: Path | None = None) -> PlanView:
    """Build a PlanView by merging the DB task records with the archived plan structure."""
    from config import ai_devops_home
    root = base_dir or ai_devops_home()
    plan_dir = root / "tasks" / plan_id

    # --- archive ---
    archive_subtasks = _load_archive_subtasks(plan_dir)
    plan_meta = _load_plan_meta(plan_dir)

    # --- DB ---
    import sqlite3 as _sqlite3
    import os as _os
    db_path = root / ".clawdbot" / "agent_tasks.db"
    db_tasks: dict[str, dict[str, Any]] = {}
    if db_path.exists():
        conn = _sqlite3.connect(str(db_path))
        conn.row_factory = _sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM agent_tasks WHERE plan_id = ? ORDER BY id",
            (plan_id,),
        )
        for row in cursor.fetchall():
            row_dict = dict(row)
            # DB id format: "<plan_id>-<subtask_id>" — extract subtask_id suffix
            raw_id = row_dict["id"]
            prefix = f"{plan_id}-"
            subtask_id = raw_id[len(prefix):] if raw_id.startswith(prefix) else raw_id
            db_tasks[subtask_id] = row_dict
        conn.close()

    # --- merge: archive defines structure, DB provides live status ---
    subtask_views: list[SubtaskView] = []
    for sid, arc in archive_subtasks.items():
        db = db_tasks.get(sid, {})
        depends_on = tuple(arc.get("depends_on") or arc.get("dependsOn") or [])
        status = db.get("status") or arc.get("dispatch", {}).get("state") or "planned"
        subtask_views.append(SubtaskView(
            id=sid,
            title=arc.get("title") or db.get("title") or sid,
            status=status,
            agent=db.get("agent") or arc.get("agent"),
            model=db.get("model") or arc.get("model"),
            pr_number=db.get("pr_number"),
            pr_url=db.get("pr_url"),
            attempts=int(db.get("attempts") or 0),
            note=db.get("note"),
            depends_on=depends_on,
        ))

    return PlanView(
        plan_id=plan_id,
        repo=plan_meta.get("repo") or "",
        subtasks=subtask_views,
        objective=plan_meta.get("objective") or "",
        requested_by=plan_meta.get("requestedBy") or "",
        requested_at=plan_meta.get("requestedAt"),
    )


def list_plan_views(base_dir: Path | None = None, limit: int = 10) -> list[PlanView]:
    """Return recent PlanViews sorted by most recently modified dispatch-state."""
    from config import ai_devops_home
    root = base_dir or ai_devops_home()
    tasks_dir = root / "tasks"
    if not tasks_dir.exists():
        return []

    plan_dirs = sorted(
        [d for d in tasks_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )[:limit]

    views = []
    for d in plan_dirs:
        try:
            views.append(load_plan_view(d.name, base_dir=root))
        except Exception:
            pass
    return views
```

- [ ] **Step 4: Run all plan_status tests**

```bash
python -m pytest tests/test_plan_status.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/plan_status.py tests/test_plan_status.py
git commit -m "feat: implement load_plan_view data aggregation"
```

---

## Chunk 2: Terminal TUI Renderer

**Files:**
- Create: `orchestrator/bin/plan_status_renderer.py`
- Create: `tests/test_plan_status_renderer.py`

### Task 3: Implement rich TUI renderer

**Files:**
- Create: `orchestrator/bin/plan_status_renderer.py`
- Create: `tests/test_plan_status_renderer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plan_status_renderer.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status import PlanView, SubtaskView
from plan_status_renderer import status_icon, build_dag_lines, render_plan_view

def test_status_icon_known():
    assert "✅" in status_icon("ready")
    assert "🔄" in status_icon("running")
    assert "❌" in status_icon("blocked")
    assert "⏳" in status_icon("queued")

def test_status_icon_unknown_does_not_crash():
    result = status_icon("some_future_status")
    assert isinstance(result, str)

def test_build_dag_lines_no_deps():
    subtasks = [SubtaskView(id="s1", title="A", status="ready")]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    lines = build_dag_lines(pv)
    assert isinstance(lines, list)
    # single node with no deps — should produce at least one line
    assert len(lines) >= 1

def test_build_dag_lines_with_chain():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready"),
        SubtaskView(id="s2", title="B", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks)
    lines = build_dag_lines(pv)
    combined = " ".join(lines)
    assert "s1" in combined or "A" in combined
    assert "s2" in combined or "B" in combined
    assert "──→" in combined or "-->" in combined

def test_render_plan_view_returns_string():
    subtasks = [
        SubtaskView(id="s1", title="Schema", status="ready"),
        SubtaskView(id="s2", title="API", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="feat-auth", repo="org/repo", subtasks=subtasks,
                  objective="Add auth")
    result = render_plan_view(pv)
    assert isinstance(result, str)
    assert "feat-auth" in result
    assert "org/repo" in result

def test_watch_plan_once_does_not_crash(tmp_path, monkeypatch):
    """Smoke test: watch_plan with once=True completes without error."""
    import json, sqlite3
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT, plan_id TEXT, repo TEXT, title TEXT, status TEXT,
        agent TEXT, model TEXT, pr_number INTEGER, pr_url TEXT,
        attempts INTEGER, note TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    plan_dir = tmp_path / "tasks" / "smoke-plan"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps(
        {"planId": "smoke-plan", "repo": "org/r", "objective": "", "requestedBy": "", "requestedAt": 0}
    ))
    (plan_dir / "subtasks").mkdir()
    (plan_dir / "subtasks" / "s1.json").write_text(json.dumps(
        {"id": "s1", "title": "T", "depends_on": []}
    ))
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))
    watch_plan("smoke-plan", once=True, base_dir=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_plan_status_renderer.py -v
```

Expected: `ModuleNotFoundError: No module named 'plan_status_renderer'`

- [ ] **Step 3: Implement `plan_status_renderer.py`**

```python
# orchestrator/bin/plan_status_renderer.py
from __future__ import annotations

import time
from collections import defaultdict

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TextColumn
    from rich import print as rprint
    _RICH = True
except ImportError:
    _RICH = False

try:
    from .plan_status import PlanView, SubtaskView
except ImportError:
    from plan_status import PlanView, SubtaskView

_STATUS_ICONS: dict[str, tuple[str, str]] = {
    "planned":     ("📋", "dim"),
    "queued":      ("⏳", "yellow"),
    "running":     ("🔄", "cyan"),
    "retrying":    ("🔄", "cyan"),
    "pr_created":  ("🔀", "blue"),
    "ready":       ("✅", "green"),
    "merged":      ("🎉", "bold green"),
    "blocked":     ("❌", "red"),
    "agent_failed":("❌", "red"),
    "agent_dead":  ("❌", "red"),
    "needs_rebase":("⚠️",  "yellow"),
}
_DEFAULT_ICON = ("❓", "white")


def status_icon(status: str) -> str:
    icon, _ = _STATUS_ICONS.get(status, _DEFAULT_ICON)
    return f"{icon} {status}"


def _status_color(status: str) -> str:
    _, color = _STATUS_ICONS.get(status, _DEFAULT_ICON)
    return color


def _topo_layers(pv: PlanView) -> list[list[SubtaskView]]:
    """Return subtasks grouped into topological layers (depth 0, 1, 2…)."""
    id_map = {s.id: s for s in pv.subtasks}
    depth: dict[str, int] = {}

    def get_depth(sid: str) -> int:
        if sid in depth:
            return depth[sid]
        s = id_map.get(sid)
        if not s or not s.depends_on:
            depth[sid] = 0
            return 0
        d = 1 + max(get_depth(dep) for dep in s.depends_on)
        depth[sid] = d
        return d

    for s in pv.subtasks:
        get_depth(s.id)

    max_depth = max(depth.values(), default=0)
    layers: list[list[SubtaskView]] = [[] for _ in range(max_depth + 1)]
    for s in pv.subtasks:
        layers[depth[s.id]].append(s)
    return layers


DAG_COLLAPSE_THRESHOLD = 6


def build_dag_lines(pv: PlanView) -> list[str]:
    """Return ASCII DAG lines. Falls back to empty list if > threshold nodes."""
    if len(pv.subtasks) > DAG_COLLAPSE_THRESHOLD:
        return []

    layers = _topo_layers(pv)
    lines: list[str] = []

    for layer_idx, layer in enumerate(layers):
        nodes = [f"[{status_icon(s.status)} {s.id}]" for s in layer]
        row = "  ".join(nodes)
        if layer_idx < len(layers) - 1:
            # Draw arrows from each node in this layer to its children in the next
            next_ids = {s.id for s in layers[layer_idx + 1]}
            arrows = []
            for s in layer:
                children = [c for c in pv.subtasks if s.id in c.depends_on and c.id in next_ids]
                if children:
                    arrows.append(f"  {s.id} ──→ " + ", ".join(c.id for c in children))
            lines.append(row)
            lines.extend(arrows)
        else:
            lines.append(row)

    return lines


def render_plan_view(pv: PlanView) -> str:
    """Render PlanView as a plain-text string (used in tests and non-rich fallback)."""
    lines: list[str] = []
    lines.append(f"Plan: {pv.plan_id}  [repo: {pv.repo}]  Progress: {pv.completed_count}/{pv.total_count}")
    if pv.objective:
        lines.append(f"Objective: {pv.objective}")
    if pv.requested_by:
        lines.append(f"Requested by: {pv.requested_by}")
    lines.append("")

    dag = build_dag_lines(pv)
    if dag:
        lines.append("Dependency Graph:")
        lines.extend(f"  {l}" for l in dag)
        lines.append("")

    # Table header
    cols = ["Subtask", "Status", "Agent", "PR", "Note"]
    widths = [max(len(c), max((len(getattr(s, f, "") or "") for s in pv.subtasks), default=0))
              for c, f in zip(cols, ["id", "status", "agent", "pr_url", "note"])]
    widths[0] = max(widths[0], 8)
    widths[1] = max(widths[1] + 3, 12)  # icon adds chars

    def row(vals: list[str]) -> str:
        return "  ".join(v.ljust(w) for v, w in zip(vals, widths))

    lines.append(row(cols))
    lines.append("-" * sum(w + 2 for w in widths))
    for s in pv.subtasks:
        pr = f"#{s.pr_number}" if s.pr_number else "—"
        lines.append(row([s.id, status_icon(s.status), s.agent or "—", pr, s.note or ""]))

    return "\n".join(lines)


def print_plan_view(pv: PlanView, console: "Console | None" = None) -> None:
    """Print PlanView to terminal using rich if available, else plain text."""
    if not _RICH:
        print(render_plan_view(pv))
        return

    from rich.console import Console as _Console
    from rich.table import Table as _Table
    from rich.panel import Panel as _Panel
    from rich.text import Text

    con = console or _Console()

    # Header panel
    header_lines = [f"[bold]repo:[/bold] {pv.repo}"]
    if pv.objective:
        header_lines.append(f"[bold]Objective:[/bold] {pv.objective}")
    if pv.requested_by:
        header_lines.append(f"[bold]Requested by:[/bold] {pv.requested_by}")
    progress_bar = "█" * pv.completed_count + "░" * (pv.total_count - pv.completed_count)
    title = f"Plan: [bold cyan]{pv.plan_id}[/bold cyan]  [{progress_bar}] {pv.completed_count}/{pv.total_count}"
    con.print(_Panel("\n".join(header_lines), title=title))

    # DAG
    dag = build_dag_lines(pv)
    if dag:
        con.print("[bold]Dependency Graph:[/bold]")
        for line in dag:
            con.print(f"  {line}")
        con.print()
    elif len(pv.subtasks) > DAG_COLLAPSE_THRESHOLD:
        con.print("[dim](DAG hidden: too many nodes — see Depends On column)[/dim]")
        con.print()

    # Table
    table = _Table(show_header=True, header_style="bold")
    table.add_column("Subtask", style="cyan")
    table.add_column("Status")
    table.add_column("Agent")
    table.add_column("PR")
    table.add_column("Note", style="dim")
    if len(pv.subtasks) > DAG_COLLAPSE_THRESHOLD:
        table.add_column("Depends On", style="dim")

    for s in pv.subtasks:
        icon, color = _STATUS_ICONS.get(s.status, _DEFAULT_ICON)
        status_cell = f"[{color}]{icon} {s.status}[/{color}]"
        pr_cell = f"[link={s.pr_url}]#{s.pr_number}[/link]" if s.pr_url else "—"
        row_vals = [s.id, status_cell, s.agent or "—", pr_cell, s.note or ""]
        if len(pv.subtasks) > DAG_COLLAPSE_THRESHOLD:
            row_vals.append(", ".join(s.depends_on) if s.depends_on else "—")
        table.add_row(*row_vals)

    con.print(table)


def watch_plan(
    plan_id: str,
    *,
    interval: int = 5,
    base_dir=None,
    once: bool = False,
) -> None:
    """Watch loop: refresh TUI every `interval` seconds. Ctrl+C to exit."""
    try:
        from .plan_status import load_plan_view
    except ImportError:
        from plan_status import load_plan_view

    if _RICH:
        from rich.console import Console as _Console
        from rich.live import Live

        con = _Console()
        with Live(console=con, refresh_per_second=1) as live:
            while True:
                try:
                    pv = load_plan_view(plan_id, base_dir=base_dir)
                    from rich.console import Console as _C
                    tmp = _C(record=True)
                    print_plan_view(pv, console=tmp)
                    text = tmp.export_text()
                except Exception as exc:
                    text = f"[red]Error loading plan: {exc}[/red]"
                if once:
                    live.update(text)
                    break
                footer = f"\n[dim][Auto-refresh in {interval}s | Ctrl+C to exit][/dim]"
                live.update(text + footer)
                time.sleep(interval)
    else:
        while True:
            try:
                pv = load_plan_view(plan_id, base_dir=base_dir)
                print(render_plan_view(pv))
            except Exception as exc:
                print(f"Error: {exc}")
            if once:
                break
            time.sleep(interval)
```

- [ ] **Step 4: Run all renderer tests**

```bash
python -m pytest tests/test_plan_status_renderer.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/plan_status_renderer.py tests/test_plan_status_renderer.py
git commit -m "feat: add rich TUI renderer for plan status"
```

---

## Chunk 3: HTTP Server and HTML Dashboard

**Files:**
- Create: `orchestrator/bin/plan_status_server.py`
- Create: `tests/test_plan_status_server.py`

### Task 4: Implement mini HTTP server with JSON API + embedded HTML

**Files:**
- Create: `orchestrator/bin/plan_status_server.py`
- Create: `tests/test_plan_status_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plan_status_server.py
import sys
import json
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "orchestrator" / "bin"))

from plan_status_server import PlanStatusServer, plan_view_to_dict
from plan_status import PlanView, SubtaskView


def test_plan_view_to_dict_shape():
    subtasks = [
        SubtaskView(id="s1", title="A", status="ready", pr_url="https://gh/1", pr_number=1),
        SubtaskView(id="s2", title="B", status="running", depends_on=("s1",)),
    ]
    pv = PlanView(plan_id="p1", repo="org/repo", subtasks=subtasks, objective="Test")
    d = plan_view_to_dict(pv)
    assert d["planId"] == "p1"
    assert d["repo"] == "org/repo"
    assert d["completedCount"] == 1
    assert d["totalCount"] == 2
    assert len(d["subtasks"]) == 2
    s2 = next(s for s in d["subtasks"] if s["id"] == "s2")
    assert s2["dependsOn"] == ["s1"]
    assert s2["prUrl"] is None


def test_server_serves_json_api(tmp_path, monkeypatch):
    plan_id = "test-plan"
    # minimal DB
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT PRIMARY KEY, plan_id TEXT, repo TEXT, title TEXT,
        status TEXT, agent TEXT, model TEXT, pr_number INTEGER,
        pr_url TEXT, attempts INTEGER DEFAULT 0, note TEXT,
        metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    # minimal plan archive
    plan_dir = tmp_path / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({
        "planId": plan_id, "repo": "org/repo", "objective": "Test", "requestedBy": "bot", "requestedAt": 0
    }))
    (plan_dir / "subtasks").mkdir()
    (plan_dir / "subtasks" / "s1.json").write_text(json.dumps(
        {"id": "s1", "title": "Task1", "depends_on": []}
    ))
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    server = PlanStatusServer(plan_id=plan_id, base_dir=tmp_path)
    server.start()
    time.sleep(0.2)

    try:
        url = f"http://localhost:{server.port}/api/plan/{plan_id}"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read())
        assert data["planId"] == plan_id
        assert "subtasks" in data
    finally:
        server.stop()


def test_server_serves_html_root(tmp_path, monkeypatch):
    plan_id = "test-plan"
    db_path = tmp_path / ".clawdbot" / "agent_tasks.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE agent_tasks (
        id TEXT, plan_id TEXT, repo TEXT, title TEXT, status TEXT,
        agent TEXT, model TEXT, pr_number INTEGER, pr_url TEXT,
        attempts INTEGER, note TEXT, metadata TEXT, created_at INTEGER, updated_at INTEGER)""")
    conn.commit(); conn.close()
    plan_dir = tmp_path / "tasks" / plan_id
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.json").write_text(json.dumps({"planId": plan_id, "repo": "r", "objective": "", "requestedBy": "", "requestedAt": 0}))
    (plan_dir / "subtasks").mkdir()
    monkeypatch.setenv("AI_DEVOPS_HOME", str(tmp_path))

    server = PlanStatusServer(plan_id=plan_id, base_dir=tmp_path)
    server.start()
    time.sleep(0.2)
    try:
        with urllib.request.urlopen(f"http://localhost:{server.port}/", timeout=3) as resp:
            html = resp.read().decode()
        assert "<!DOCTYPE html>" in html
        assert plan_id in html
    finally:
        server.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_plan_status_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'plan_status_server'`

- [ ] **Step 3: Implement `plan_status_server.py`**

```python
# orchestrator/bin/plan_status_server.py
from __future__ import annotations

import json
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    from .plan_status import PlanView, SubtaskView, load_plan_view
except ImportError:
    from plan_status import PlanView, SubtaskView, load_plan_view


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def plan_view_to_dict(pv: PlanView) -> dict[str, Any]:
    return {
        "planId": pv.plan_id,
        "repo": pv.repo,
        "objective": pv.objective,
        "requestedBy": pv.requested_by,
        "requestedAt": pv.requested_at,
        "completedCount": pv.completed_count,
        "totalCount": pv.total_count,
        "subtasks": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "agent": s.agent,
                "prNumber": s.pr_number,
                "prUrl": s.pr_url,
                "attempts": s.attempts,
                "note": s.note,
                "dependsOn": list(s.depends_on),
            }
            for s in pv.subtasks
        ],
    }


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Plan: {plan_id}</title>
<style>
  body {{ font-family: monospace; background: #0d1117; color: #c9d1d9; margin: 2em; }}
  h1 {{ color: #58a6ff; }}
  .progress-bar {{ background: #21262d; border-radius: 4px; height: 12px; width: 300px; display: inline-block; vertical-align: middle; }}
  .progress-fill {{ background: #238636; height: 100%; border-radius: 4px; transition: width 0.5s; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 1em; }}
  th {{ background: #161b22; text-align: left; padding: 6px 12px; border-bottom: 1px solid #30363d; }}
  td {{ padding: 5px 12px; border-bottom: 1px solid #21262d; }}
  a {{ color: #58a6ff; }}
  .status-ready {{ color: #3fb950; }}
  .status-running, .status-retrying {{ color: #79c0ff; }}
  .status-queued {{ color: #d29922; }}
  .status-blocked, .status-agent_failed, .status-agent_dead {{ color: #f85149; }}
  .status-needs_rebase {{ color: #d29922; }}
  .status-merged {{ color: #3fb950; font-weight: bold; }}
  .status-pr_created {{ color: #79c0ff; }}
  .status-planned {{ color: #6e7681; }}
  #refresh-note {{ color: #6e7681; font-size: 0.85em; margin-top: 0.5em; }}
  svg {{ margin: 1em 0; }}
  .dag-node {{ rx: 6; fill: #161b22; stroke: #30363d; }}
  .dag-label {{ fill: #c9d1d9; font-size: 12px; font-family: monospace; }}
  .dag-arrow {{ stroke: #58a6ff; stroke-width: 1.5; fill: none; marker-end: url(#arrowhead); }}
</style>
</head>
<body>
<h1>🤖 Plan: <span id="plan-id">{plan_id}</span></h1>
<p>
  <span id="repo">—</span> &nbsp;|&nbsp;
  by <span id="requested-by">—</span> &nbsp;|&nbsp;
  <span id="progress-text">0/0</span>
  <span class="progress-bar"><span class="progress-fill" id="progress-fill" style="width:0%"></span></span>
</p>
<div id="refresh-note">Refreshing in <span id="countdown">5</span>s</div>
<div id="dag-container"></div>
<table id="task-table">
  <thead><tr><th>Subtask</th><th>Status</th><th>Agent</th><th>PR</th><th>Attempts</th><th>Note</th></tr></thead>
  <tbody id="task-body"></tbody>
</table>
<script>
const PLAN_ID = "{plan_id}";
const INTERVAL = 5;
let countdown = INTERVAL;

const ICONS = {{
  planned:"📋", queued:"⏳", running:"🔄", retrying:"🔄",
  pr_created:"🔀", ready:"✅", merged:"🎉",
  blocked:"❌", agent_failed:"❌", agent_dead:"❌", needs_rebase:"⚠️"
}};

function icon(status) {{ return (ICONS[status] || "❓") + " " + status; }}

function renderTable(subtasks) {{
  const tbody = document.getElementById("task-body");
  tbody.innerHTML = "";
  subtasks.forEach(s => {{
    const pr = s.prUrl ? `<a href="${{s.prUrl}}" target="_blank">#${{s.prNumber}}</a>` : "—";
    const cls = "status-" + s.status;
    tbody.innerHTML += `<tr>
      <td>${{s.id}}</td>
      <td class="${{cls}}">${{icon(s.status)}}</td>
      <td>${{s.agent || "—"}}</td>
      <td>${{pr}}</td>
      <td>${{s.attempts}}</td>
      <td>${{s.note || ""}}</td>
    </tr>`;
  }});
}}

function renderDag(subtasks) {{
  const container = document.getElementById("dag-container");
  if (subtasks.length > 6) {{ container.innerHTML = ""; return; }}

  // Build dependency map
  const idMap = {{}};
  subtasks.forEach(s => idMap[s.id] = s);

  // Topological layers
  const depth = {{}};
  function getDepth(id) {{
    if (depth[id] !== undefined) return depth[id];
    const s = idMap[id];
    if (!s || !s.dependsOn || s.dependsOn.length === 0) {{ depth[id] = 0; return 0; }}
    depth[id] = 1 + Math.max(...s.dependsOn.map(getDepth));
    return depth[id];
  }}
  subtasks.forEach(s => getDepth(s.id));
  const maxDepth = Math.max(...Object.values(depth));

  const layers = Array.from({{length: maxDepth + 1}}, () => []);
  subtasks.forEach(s => layers[depth[s.id]].push(s));

  const NODE_W = 140, NODE_H = 32, H_GAP = 40, V_GAP = 60;
  const svgW = (maxDepth + 1) * (NODE_W + H_GAP) + H_GAP;
  const svgH = Math.max(...layers.map(l => l.length)) * (NODE_H + V_GAP) + V_GAP;

  const pos = {{}};
  layers.forEach((layer, col) => {{
    layer.forEach((s, row) => {{
      pos[s.id] = {{
        x: H_GAP + col * (NODE_W + H_GAP),
        y: V_GAP + row * (NODE_H + V_GAP)
      }};
    }});
  }});

  let arrows = "";
  subtasks.forEach(s => {{
    (s.dependsOn || []).forEach(dep => {{
      if (!pos[dep] || !pos[s.id]) return;
      const x1 = pos[dep].x + NODE_W, y1 = pos[dep].y + NODE_H / 2;
      const x2 = pos[s.id].x, y2 = pos[s.id].y + NODE_H / 2;
      arrows += `<path class="dag-arrow" d="M${{x1}},${{y1}} C${{x1+20}},${{y1}} ${{x2-20}},${{y2}} ${{x2}},${{y2}}"/>`;
    }});
  }});

  let nodes = "";
  subtasks.forEach(s => {{
    const {{x, y}} = pos[s.id];
    const ico = ICONS[s.status] || "❓";
    nodes += `<rect class="dag-node" x="${{x}}" y="${{y}}" width="${{NODE_W}}" height="${{NODE_H}}"/>`;
    nodes += `<text class="dag-label" x="${{x+8}}" y="${{y+21}}">${{ico}} ${{s.id}}</text>`;
  }});

  container.innerHTML = `<svg width="${{svgW}}" height="${{svgH}}">
    <defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#58a6ff"/>
    </marker></defs>
    ${{arrows}}${{nodes}}
  </svg>`;
}}

function update() {{
  fetch("/api/plan/" + PLAN_ID)
    .then(r => r.json())
    .then(data => {{
      document.getElementById("repo").textContent = data.repo || "—";
      document.getElementById("requested-by").textContent = data.requestedBy || "—";
      const pct = data.totalCount ? Math.round(data.completedCount / data.totalCount * 100) : 0;
      document.getElementById("progress-text").textContent = data.completedCount + "/" + data.totalCount;
      document.getElementById("progress-fill").style.width = pct + "%";
      renderTable(data.subtasks || []);
      renderDag(data.subtasks || []);
      countdown = INTERVAL;
    }})
    .catch(err => console.error("fetch error", err));
}}

setInterval(() => {{
  countdown--;
  document.getElementById("countdown").textContent = countdown;
  if (countdown <= 0) update();
}}, 1000);

update();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    plan_id: str = ""
    base_dir: Path | None = None

    def log_message(self, format: str, *args: Any) -> None:  # silence access logs
        pass

    def do_GET(self) -> None:
        api_prefix = f"/api/plan/{self.plan_id}"
        if self.path == api_prefix or self.path.startswith(api_prefix + "?"):
            self._serve_json()
        else:
            self._serve_html()

    def _serve_json(self) -> None:
        try:
            pv = load_plan_view(self.plan_id, base_dir=self.base_dir)
            body = json.dumps(plan_view_to_dict(pv), ensure_ascii=False).encode()
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self) -> None:
        html = _HTML_TEMPLATE.format(plan_id=self.plan_id).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html)


def _find_free_port(start: int = 8700, retries: int = 10) -> int:
    for port in range(start, start + retries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found")


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class PlanStatusServer:
    def __init__(self, plan_id: str, base_dir: Path | None = None) -> None:
        self.plan_id = plan_id
        self.base_dir = base_dir
        self.port = _find_free_port()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, open_browser: bool = False) -> str:
        handler = type(
            "_H",
            (_Handler,),
            {"plan_id": self.plan_id, "base_dir": self.base_dir},
        )
        self._server = HTTPServer(("127.0.0.1", self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        url = f"http://localhost:{self.port}/"
        if open_browser:
            webbrowser.open(url)
        return url

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
```

- [ ] **Step 4: Run server tests**

```bash
python -m pytest tests/test_plan_status_server.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add orchestrator/bin/plan_status_server.py tests/test_plan_status_server.py
git commit -m "feat: add mini HTTP server and embedded HTML dashboard for plan status"
```

---

## Chunk 4: CLI Integration

**Files:**
- Modify: `orchestrator/bin/agent.py`

### Task 5: Add `plan-status` and `plans` subcommands to `agent.py`

**Files:**
- Modify: `orchestrator/bin/agent.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_agent.py — append these cases:

import subprocess
import sys

def test_plan_status_command_help():
    """Smoke test: plan-status subcommand is registered."""
    result = subprocess.run(
        [sys.executable, "orchestrator/bin/agent.py", "plan-status", "--help"],
        capture_output=True, text=True,
        cwd="/home/gordonyang/workspace/myproject/ai-devops"
    )
    assert result.returncode == 0
    assert "plan-status" in result.stdout or "plan_id" in result.stdout

def test_plans_command_help():
    """Smoke test: plans subcommand is registered."""
    result = subprocess.run(
        [sys.executable, "orchestrator/bin/agent.py", "plans", "--help"],
        capture_output=True, text=True,
        cwd="/home/gordonyang/workspace/myproject/ai-devops"
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_agent.py::test_plan_status_command_help tests/test_agent.py::test_plans_command_help -v
```

Expected: both fail with non-zero returncode (subcommand not found)

- [ ] **Step 3: Add `cmd_plan_status` and `cmd_plans` to `agent.py`**

After the existing imports at the top of `agent.py`, add:

```python
# Lazy import — only needed for plan-status/plans commands
def _get_plan_status_modules():
    import plan_status as _ps
    import plan_status_renderer as _psr
    import plan_status_server as _pss
    return _ps, _psr, _pss
```

Add command implementations before `main()`:

```python
def cmd_plan_status(args):
    """Display plan status with rich TUI."""
    init_db()
    ps, psr, pss = _get_plan_status_modules()

    server = None
    if args.html:
        server = pss.PlanStatusServer(plan_id=args.plan_id)
        url = server.start(open_browser=True)
        print(f"✓ Dashboard: {url}")
        if args.no_tui:
            print("Press Ctrl+C to stop server.")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                server.stop()
                return

    try:
        psr.watch_plan(
            args.plan_id,
            interval=args.interval,
            once=not args.watch,
        )
    except KeyboardInterrupt:
        pass
    finally:
        if server:
            server.stop()


def cmd_plans(args):
    """List recent plans with progress summary."""
    init_db()
    ps, psr, _ = _get_plan_status_modules()

    views = ps.list_plan_views(limit=args.limit)
    if not views:
        print("No plans found.")
        return

    from agent_utils import format_timestamp
    header = f"{'PLAN-ID':<35} {'PROGRESS':<10} {'STATUS':<12} {'REPO':<25} STARTED"
    print(header)
    print("-" * len(header))
    for pv in views:
        active_statuses = {s.status for s in pv.subtasks}
        if "running" in active_statuses or "retrying" in active_statuses:
            overall = "running"
        elif all(s.status in ("ready", "merged") for s in pv.subtasks) and pv.subtasks:
            overall = "done"
        elif any(s.status == "blocked" for s in pv.subtasks):
            overall = "blocked"
        else:
            overall = "partial"
        started = format_timestamp(pv.requested_at)[:16] if pv.requested_at else "—"
        print(
            f"{pv.plan_id:<35} {pv.completed_count}/{pv.total_count:<8} "
            f"{overall:<12} {pv.repo:<25} {started}"
        )
```

In `main()`, add the new subparsers before the final `args = parser.parse_args()` call. Find the `# 清理` section and add after the `retry` parser block:

```python
    # plan 状态
    p = subparsers.add_parser("plan-status", help="Show plan execution status (TUI + optional browser)")
    p.add_argument("plan_id", help="Plan ID")
    p.add_argument("--watch", action="store_true", help="Auto-refresh TUI")
    p.add_argument("--interval", type=int, default=5, help="Refresh interval in seconds")
    p.add_argument("--html", action="store_true", help="Open browser dashboard")
    p.add_argument("--no-tui", action="store_true", dest="no_tui", help="Skip terminal TUI (browser only)")
    p.set_defaults(func=cmd_plan_status)

    # 列出 plans
    p = subparsers.add_parser("plans", help="List recent plans with progress summary")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_plans)
```

- [ ] **Step 4: Run CLI tests**

```bash
python -m pytest tests/test_agent.py::test_plan_status_command_help tests/test_agent.py::test_plans_command_help -v
```

Expected: `2 passed`

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add orchestrator/bin/agent.py tests/test_agent.py
git commit -m "feat: add plan-status and plans subcommands to agent CLI"
```

---

## Chunk 5: Smoke Test End-to-End

### Task 6: Manual smoke test and final verification

- [ ] **Step 1: Verify `agent plan-status --help`**

```bash
python orchestrator/bin/agent.py plan-status --help
```

Expected output includes `plan_id`, `--watch`, `--html`, `--interval`.

- [ ] **Step 2: Verify `agent plans --help`**

```bash
python orchestrator/bin/agent.py plans --help
```

Expected output includes `--limit`.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: all existing tests pass plus new tests in `test_plan_status.py`, `test_plan_status_renderer.py`, `test_plan_status_server.py`, `test_agent.py`.

- [ ] **Step 4: Final commit (if any fixups needed)**

```bash
git add -p
git commit -m "chore: finalize plan status visualization"
```
