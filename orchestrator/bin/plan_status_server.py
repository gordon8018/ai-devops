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

  const idMap = {{}};
  subtasks.forEach(s => idMap[s.id] = s);

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

    def log_message(self, format: str, *args: Any) -> None:
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
