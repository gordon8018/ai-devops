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

    def get_depth(sid: str, visiting: set[str] | None = None) -> int:
        if sid in depth:
            return depth[sid]
        if visiting is None:
            visiting = set()
        if sid in visiting:
            depth[sid] = 0
            return 0
        visiting.add(sid)
        s = id_map.get(sid)
        if not s or not s.depends_on:
            depth[sid] = 0
            return 0
        d = 1 + max(get_depth(dep, visiting) for dep in s.depends_on)
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
    if dag and any(line.strip() for line in dag):
        lines.append("Dependency Graph:")
        lines.extend(f"  {l}" for l in dag)
        lines.append("")

    # Table header — use fixed PR column width, not URL length
    cols = ["Subtask", "Status", "Agent", "PR", "Note"]
    field_names = ["id", "status", "agent", "pr_number", "note"]
    widths = []
    for col, fname in zip(cols, field_names):
        col_w = len(col)
        for s in pv.subtasks:
            val = getattr(s, fname, None)
            if fname == "pr_number":
                cell = f"#{val}" if val else "—"
            else:
                cell = str(val or "")
            col_w = max(col_w, len(cell))
        widths.append(col_w)
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
                    tmp = _Console(record=True)
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
