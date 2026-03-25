from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .scanner import scan_project


def derive_reviewers(report: dict) -> list[dict]:
    scores: dict[str, int] = {}
    for item in report.get("files", []):
        weight = max(item.get("hotspot_score", 0), 1)
        for owner in item.get("owners", []):
            scores[owner] = scores.get(owner, 0) + weight + 3
        for author in item.get("authors", []):
            if author in {"Not Committed Yet", "Unknown"}:
                continue
            scores[author] = scores.get(author, 0) + weight
    return [
        {"candidate": candidate, "score": score}
        for candidate, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def render_dashboard(root: str) -> str:
    report = scan_project(root).to_dict()
    report["reviewers"] = derive_reviewers(report)
    payload = json.dumps(report)
    insight_cards = "".join(f"<li>{html.escape(item)}</li>" for item in report["insights"])
    owner_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['owner'])}</td>"
        f"<td>{item['files']}</td>"
        "</tr>"
        for item in report.get("owners", [])[:10]
    )
    author_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['author'])}</td>"
        f"<td>{item['files']}</td>"
        "</tr>"
        for item in report.get("authors", [])[:10]
    )
    reviewer_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['candidate'])}</td>"
        f"<td>{item['score']}</td>"
        "</tr>"
        for item in report.get("reviewers", [])[:10]
    )
    risk_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['kind'])}</td>"
        f"<td>{html.escape(item['path'])}:{item['line']}</td>"
        f"<td>{html.escape(item['message'])}</td>"
        "</tr>"
        for item in report.get("security_findings", [])[:12]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CodeAtlas</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: rgba(15, 23, 42, 0.72);
      --panel-2: rgba(30, 41, 59, 0.92);
      --line: rgba(148, 163, 184, 0.18);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #f59e0b;
      --accent-2: #22c55e;
      --danger: #fb7185;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(245, 158, 11, 0.25), transparent 28%),
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.18), transparent 24%),
        linear-gradient(145deg, #020617 0%, #111827 52%, #0f172a 100%);
    }}
    .shell {{
      width: min(1240px, calc(100vw - 32px));
      margin: 24px auto 48px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      backdrop-filter: blur(14px);
      box-shadow: 0 20px 80px rgba(15, 23, 42, 0.45);
      overflow: hidden;
    }}
    .hero-copy {{
      padding: 28px;
    }}
    h1 {{
      font-size: clamp(2rem, 4vw, 3.6rem);
      line-height: 0.95;
      margin: 0 0 12px;
      letter-spacing: -0.05em;
    }}
    .lede, .meta {{
      color: var(--muted);
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}
    .stat {{
      padding: 16px;
      background: var(--panel-2);
      border-radius: 16px;
      border: 1px solid var(--line);
    }}
    .stat strong {{
      display: block;
      font-size: 1.7rem;
    }}
    .insights {{
      padding: 28px;
      background:
        linear-gradient(180deg, rgba(245, 158, 11, 0.16), transparent),
        var(--panel);
    }}
    .content {{
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 16px;
    }}
    .owners-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-top: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .table-wrap, .graph-wrap {{
      padding: 18px;
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1.2fr 0.6fr;
      gap: 10px;
      margin: 12px 0 16px;
    }}
    .graph {{
      min-height: 420px;
      position: relative;
    }}
    .legend {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .pill {{
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.03);
    }}
    svg {{ width: 100%; height: 420px; display: block; }}
    .footer {{
      color: var(--muted);
      padding: 14px 2px 0;
      font-size: 0.92rem;
    }}
    .viewer {{
      margin-top: 16px;
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 16px;
    }}
    .viewer-controls {{
      padding: 18px;
    }}
    .viewer pre {{
      margin: 0;
      padding: 18px;
      overflow: auto;
      min-height: 360px;
      background: rgba(2, 6, 23, 0.9);
      color: #cbd5e1;
      font-family: "IBM Plex Mono", "Fira Code", monospace;
      font-size: 0.9rem;
      line-height: 1.45;
    }}
    input, select, button {{
      width: 100%;
      padding: 12px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.05);
      color: var(--text);
      margin-top: 10px;
    }}
    @media (max-width: 960px) {{
      .hero, .content, .owners-grid, .controls {{ grid-template-columns: 1fr; }}
      .stats {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .viewer {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="panel hero-copy">
        <div class="meta">Repository intelligence workbench</div>
        <h1>CodeAtlas</h1>
        <div class="lede">Map dependencies, hotspots, TODO pressure, and documentation drift from a local repository without external services.</div>
        <div class="stats">
          <div class="stat"><span>Files</span><strong>{report["summary"]["total_files"]}</strong></div>
          <div class="stat"><span>Lines</span><strong>{report["summary"]["total_lines"]}</strong></div>
          <div class="stat"><span>TODOs</span><strong>{report["summary"]["todo_count"]}</strong></div>
          <div class="stat"><span>Warnings</span><strong>{report["summary"]["warning_count"]}</strong></div>
        </div>
      </div>
      <div class="panel insights">
        <h2>Signals</h2>
        <ul>{insight_cards}</ul>
      </div>
    </section>

    <section class="content">
      <div class="panel table-wrap">
        <h2>Hotspots</h2>
        <div class="controls">
          <input id="hotspot-filter" placeholder="Filter files by path or owner">
          <select id="hotspot-limit">
            <option value="12">12 rows</option>
            <option value="25">25 rows</option>
            <option value="50">50 rows</option>
            <option value="999">All rows</option>
          </select>
        </div>
        <table>
          <thead>
            <tr><th>Path</th><th>Lang</th><th>Owners</th><th>Lines</th><th>Deps</th><th>TODOs</th><th>Health</th><th>Score</th></tr>
          </thead>
          <tbody id="hotspot-body"></tbody>
        </table>
      </div>
      <div class="panel table-wrap">
        <h2>TODO Feed</h2>
        <div class="controls">
          <input id="todo-filter" placeholder="Filter TODOs by path or text">
          <select id="todo-limit">
            <option value="12">12 rows</option>
            <option value="25">25 rows</option>
            <option value="50">50 rows</option>
            <option value="999">All rows</option>
          </select>
        </div>
        <table>
          <thead>
            <tr><th>Type</th><th>Location</th><th>Detail</th></tr>
          </thead>
          <tbody id="todo-body"></tbody>
        </table>
      </div>
    </section>

    <section class="owners-grid">
      <div class="panel table-wrap">
        <h2>Ownership Load</h2>
        <table>
          <thead>
            <tr><th>Owner</th><th>Files</th></tr>
          </thead>
          <tbody>{owner_rows or '<tr><td colspan="2">No CODEOWNERS file detected.</td></tr>'}</tbody>
        </table>
      </div>
      <div class="panel table-wrap">
        <h2>Review Angle</h2>
        <div class="meta">Pair hotspot rank with ownership to see who is likely to review or absorb risk.</div>
        <div class="meta" id="rules-summary" style="margin-top:12px;"></div>
        <table style="margin-top:16px;">
          <thead>
            <tr><th>Reviewer</th><th>Score</th></tr>
          </thead>
          <tbody>{reviewer_rows or '<tr><td colspan="2">Use the `reviewers` CLI for changed-surface suggestions.</td></tr>'}</tbody>
        </table>
      </div>
    </section>

    <section class="owners-grid">
      <div class="panel table-wrap">
        <h2>Blame Authors</h2>
        <table>
          <thead>
            <tr><th>Author</th><th>Files</th></tr>
          </thead>
          <tbody>{author_rows or '<tr><td colspan="2">No blame data available.</td></tr>'}</tbody>
        </table>
      </div>
      <div class="panel table-wrap">
        <h2>Security Feed</h2>
        <table>
          <thead>
            <tr><th>Kind</th><th>Location</th><th>Detail</th></tr>
          </thead>
          <tbody>{risk_rows or '<tr><td colspan="3">No security or manifest risks detected.</td></tr>'}</tbody>
        </table>
      </div>
    </section>

    <section class="panel graph-wrap" style="margin-top:16px;">
      <h2>Dependency Sketch</h2>
      <div class="legend">
        <span class="pill">Amber: Python</span>
        <span class="pill">Green: JavaScript / TypeScript</span>
        <span class="pill">Rose: Markdown / Docs</span>
      </div>
      <div class="controls">
        <input id="graph-filter" placeholder="Filter graph nodes by path">
        <select id="graph-limit">
          <option value="28">28 nodes</option>
          <option value="60">60 nodes</option>
          <option value="120">120 nodes</option>
          <option value="999">All nodes</option>
        </select>
      </div>
      <div class="graph"><svg id="graph" viewBox="0 0 900 420" preserveAspectRatio="xMidYMid meet"></svg></div>
    </section>

    <section class="viewer">
      <div class="panel viewer-controls">
        <h2>File Drilldown</h2>
        <div class="meta">Inspect source without leaving the dashboard.</div>
        <select id="file-picker"></select>
        <button id="load-file">Load File</button>
      </div>
      <div class="panel"><pre id="file-content">Select a file to preview its contents.</pre></div>
    </section>

    <div class="footer">Target: {html.escape(str(Path(root).resolve()))}</div>
  </div>
  <script>
    const report = {payload};
    const svg = document.getElementById("graph");
    const ns = "http://www.w3.org/2000/svg";
    const byId = (id) => document.getElementById(id);
    const colorFor = (language) => {{
      if (language === "Python") return "#f59e0b";
      if (language === "JavaScript" || language === "TypeScript") return "#22c55e";
      if (language === "Markdown") return "#fb7185";
      return "#93c5fd";
    }};
    const picker = byId("file-picker");
    const output = byId("file-content");
    const renderHotspots = () => {{
      const filter = byId("hotspot-filter").value.toLowerCase();
      const limit = Number(byId("hotspot-limit").value);
      const rows = report.files
        .filter(item => !filter || item.path.toLowerCase().includes(filter) || (item.owners || []).join(" ").toLowerCase().includes(filter))
        .slice(0, limit)
        .map(item => `<tr><td>${{item.path}}</td><td>${{item.language}}</td><td>${{(item.owners || []).join(", ") || "unowned"}}</td><td>${{item.lines}}</td><td>${{item.outgoing_dependencies.length}}</td><td>${{item.todos.length}}</td><td>${{item.code_health_score ?? 100}}</td><td>${{item.hotspot_score}}</td></tr>`)
        .join("");
      byId("hotspot-body").innerHTML = rows || '<tr><td colspan="8">No files match the filter.</td></tr>';
    }};
    const renderTodos = () => {{
      const filter = byId("todo-filter").value.toLowerCase();
      const limit = Number(byId("todo-limit").value);
      const rows = report.todos
        .filter(item => !filter || item.path.toLowerCase().includes(filter) || item.text.toLowerCase().includes(filter))
        .slice(0, limit)
        .map(item => `<tr><td>${{item.label}}</td><td>${{item.path}}:${{item.line}}</td><td>${{item.text}}</td></tr>`)
        .join("");
      byId("todo-body").innerHTML = rows || '<tr><td colspan="3">No TODO markers found.</td></tr>';
    }};
    const renderPicker = () => {{
      const current = picker.value;
      picker.innerHTML = report.files
        .map(item => `<option value="${{item.path}}">${{item.path}}</option>`)
        .join("");
      if (current) picker.value = current;
    }};
    const renderGraph = () => {{
      svg.innerHTML = "";
      const filter = byId("graph-filter").value.toLowerCase();
      const limit = Number(byId("graph-limit").value);
      const nodes = report.graph.nodes
        .filter(node => !filter || node.id.toLowerCase().includes(filter))
        .slice(0, limit);
      const edges = report.graph.edges.filter(edge =>
        nodes.some(node => node.id === edge.source) && nodes.some(node => node.id === edge.target)
      );
      const cx = 450, cy = 210, radius = Math.max(120, 180 - Math.min(nodes.length, 80));
      const nodePos = new Map();
      nodes.forEach((node, index) => {{
        const angle = (Math.PI * 2 * index) / Math.max(nodes.length, 1);
        const wobble = 22 * Math.sin(index * 1.7);
        const x = cx + Math.cos(angle) * (radius + wobble);
        const y = cy + Math.sin(angle) * (radius - wobble);
        nodePos.set(node.id, {{ x, y }});
      }});
      edges.forEach(edge => {{
        const a = nodePos.get(edge.source);
        const b = nodePos.get(edge.target);
        if (!a || !b) return;
        const line = document.createElementNS(ns, "line");
        line.setAttribute("x1", a.x);
        line.setAttribute("y1", a.y);
        line.setAttribute("x2", b.x);
        line.setAttribute("y2", b.y);
        line.setAttribute("stroke", "rgba(148,163,184,0.28)");
        line.setAttribute("stroke-width", "1.3");
        svg.appendChild(line);
      }});
      nodes.forEach(node => {{
        const pos = nodePos.get(node.id);
        const group = document.createElementNS(ns, "g");
        const circle = document.createElementNS(ns, "circle");
        circle.setAttribute("cx", pos.x);
        circle.setAttribute("cy", pos.y);
        circle.setAttribute("r", 9);
        circle.setAttribute("fill", colorFor(node.language));
        const label = document.createElementNS(ns, "text");
        label.setAttribute("x", pos.x + 12);
        label.setAttribute("y", pos.y + 4);
        label.setAttribute("fill", "#e2e8f0");
        label.setAttribute("font-size", "10");
        label.textContent = node.id.split("/").slice(-2).join("/");
        group.appendChild(circle);
        group.appendChild(label);
        svg.appendChild(group);
      }});
    }};
    byId("rules-summary").textContent = `Rules: ${{report.rule_violations.length}} violations, cycles: ${{report.cycles.length}}, risks: ${{(report.security_findings || []).length}}.`;
    const loadFile = async () => {{
      const path = picker.value;
      if (!path) return;
      output.textContent = "Loading " + path + "...";
      const response = await fetch("/api/file?path=" + encodeURIComponent(path));
      output.textContent = await response.text();
    }};
    ["hotspot-filter", "hotspot-limit"].forEach(id => byId(id).addEventListener("input", renderHotspots));
    ["todo-filter", "todo-limit"].forEach(id => byId(id).addEventListener("input", renderTodos));
    ["graph-filter", "graph-limit"].forEach(id => byId(id).addEventListener("input", renderGraph));
    byId("load-file").addEventListener("click", loadFile);
    renderHotspots();
    renderTodos();
    renderPicker();
    renderGraph();
    if (picker.value) loadFile();
  </script>
</body>
</html>"""


def make_handler(root: str):
    class Handler(BaseHTTPRequestHandler):
        def _send_bytes(self, payload: bytes, content_type: str, head_only: bool = False) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)

        def _route(self, head_only: bool = False) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/report":
                report = scan_project(root).to_dict()
                payload = json.dumps(report).encode("utf-8")
                self._send_bytes(payload, "application/json; charset=utf-8", head_only=head_only)
                return

            if parsed.path == "/api/file":
                target = parse_qs(parsed.query).get("path", [""])[0]
                full = (Path(root) / target).resolve()
                if not str(full).startswith(str(Path(root).resolve())) or not full.exists():
                    self.send_error(404, "File not found")
                    return
                payload = full.read_text(encoding="utf-8", errors="ignore").encode("utf-8")
                self._send_bytes(payload, "text/plain; charset=utf-8", head_only=head_only)
                return

            html_doc = render_dashboard(root).encode("utf-8")
            self._send_bytes(html_doc, "text/html; charset=utf-8", head_only=head_only)

        def do_GET(self) -> None:
            self._route(head_only=False)

        def do_HEAD(self) -> None:
            self._route(head_only=True)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def serve(root: str, host: str = "127.0.0.1", port: int = 8123) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(root))
    print(f"CodeAtlas serving {Path(root).resolve()} at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
