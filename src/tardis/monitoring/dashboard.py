"""
Real-Time Web Dashboard for TARDIS Monitoring

Provides a lightweight HTTP server with real-time monitoring data,
anomaly alerts, and trace visualization.

SECURITY:
- Localhost-only binding by default (no network exposure)
- No authentication (intended for local dev use only)
- Read-only API endpoints (no state mutation via HTTP)
"""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TARDIS Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, system-ui, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
h1 { color: #58a6ff; margin-bottom: 20px; }
h2 { color: #8b949e; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
.card .value { font-size: 28px; font-weight: 600; color: #f0f6fc; }
.card .label { font-size: 12px; color: #8b949e; margin-top: 4px; }
.card.ok { border-left: 3px solid #3fb950; }
.card.warn { border-left: 3px solid #d29922; }
.card.err { border-left: 3px solid #f85149; }
table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
th { text-align: left; padding: 8px 12px; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 12px; text-transform: uppercase; }
td { padding: 8px 12px; border-bottom: 1px solid #21262d; font-size: 13px; }
.alert { background: #161b22; border: 1px solid #f85149; border-radius: 6px; padding: 12px; margin-bottom: 8px; }
.alert .type { color: #f85149; font-weight: 600; }
.alert .msg { color: #c9d1d9; margin-top: 4px; }
.alert .time { color: #8b949e; font-size: 11px; margin-top: 4px; }
.refresh { color: #8b949e; font-size: 12px; margin-bottom: 20px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.badge.ok { background: #3fb95022; color: #3fb950; }
.badge.warn { background: #d2992222; color: #d29922; }
.badge.err { background: #f8514922; color: #f85149; }
</style>
</head>
<body>
<h1>&#x1F6F8; TARDIS Dashboard</h1>
<div class="refresh">Last updated: <span id="updated">-</span> | Auto-refresh every 5s</div>
<div class="grid" id="metrics"></div>
<h2>Recent Anomaly Alerts</h2>
<div id="alerts"></div>
<h2>Active Traces</h2>
<div id="traces"><p>No active traces.</p></div>
<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    document.getElementById('updated').textContent = new Date().toLocaleTimeString();
    renderMetrics(d.metrics || {});
    renderAlerts((d.alerts || {}).recent || []);
    renderTraces(d.traces || []);
  } catch(e) {
    document.getElementById('updated').textContent = 'Offline';
  }
}
function renderMetrics(m) {
  const cards = [
    { v: m.total_steps ?? 0, l: 'Total Steps', cls: 'ok' },
    { v: (m.total_tokens ?? 0).toLocaleString(), l: 'Total Tokens', cls: 'ok' },
    { v: '$' + (m.total_cost ?? 0).toFixed(4), l: 'Total Cost', cls: 'ok' },
    { v: m.error_count ?? 0, l: 'Errors', cls: (m.error_count || 0) > 0 ? 'err' : 'ok' },
    { v: m.errors_per_step ? (m.errors_per_step * 100).toFixed(1) + '%' : '0%', l: 'Error Rate', cls: (m.errors_per_step || 0) > 0.1 ? 'err' : 'ok' },
  ];
  document.getElementById('metrics').innerHTML = cards.map(c =>
    `<div class="card ${c.cls}"><div class="value">${c.v}</div><div class="label">${c.l}</div></div>`
  ).join('');
}
function renderAlerts(alerts) {
  const el = document.getElementById('alerts');
  if (!alerts.length) { el.innerHTML = '<p style="color:#8b949e">No recent alerts.</p>'; return; }
  el.innerHTML = alerts.slice(-5).reverse().map(a =>
    `<div class="alert"><div class="type">${a.type ?? 'unknown'}</div><div class="msg">${(a.description || '').slice(0, 200)}</div><div class="time">${a.timestamp || ''}</div></div>`
  ).join('');
}
function renderTraces(traces) {
  const el = document.getElementById('traces');
  if (!traces || !traces.length) { el.innerHTML = '<p style="color:#8b949e">No active traces.</p>'; return; }
  el.innerHTML = '<table><thead><tr><th>Trace ID</th><th>Status</th></tr></thead><tbody>' +
    traces.map(t => `<tr><td>${t}</td><td><span class="badge ok">active</span></td></tr>`).join('') +
    '</tbody></table>';
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the TARDIS dashboard."""

    def __init__(self, *args, **kwargs):
        self.dashboard = kwargs.pop("dashboard")
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/status":
            self._serve_json(self.dashboard.get_status_data())
        elif self.path == "/api/health":
            self._serve_json({"status": "ok", "timestamp": datetime.now().isoformat()})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(_DASHBOARD_HTML.encode("utf-8"))

    def _serve_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        # Only reflect localhost origins. The dashboard binds to localhost, so
        # cross-origin access from arbitrary hosts must not be allowed via a
        # wildcard header.
        origin = self.headers.get("Origin")
        if origin and origin.startswith(("http://localhost", "http://127.0.0.1")):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode("utf-8"))


class DashboardServer:
    """Lightweight HTTP dashboard server for real-time TARDIS monitoring.

    Binds to localhost only by default (no network exposure).
    Provides read-only API at /api/status and /api/health.

    Usage:
        monitor = LiveMonitor(config).start()
        dashboard = DashboardServer(monitor=monitor, port=9090)
        dashboard.start()
        # ... later ...
        dashboard.stop()

    SECURITY: Localhost-only binding. No authentication. Read-only endpoints.
    """

    def __init__(
        self,
        monitor: Any = None,
        host: str = "127.0.0.1",
        port: int = 9090,
    ):
        self.monitor = monitor
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

        if host != "127.0.0.1":
            import warnings

            warnings.warn(
                "TARDIS dashboard bound to non-loopback address. "
                "This exposes monitoring data on the network. "
                "Only use this in trusted environments."
            )

    def start(self):
        """Start the dashboard HTTP server in a background thread."""
        if self._server is not None:
            return

        server_ref = self

        class Handler(DashboardHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, dashboard=server_ref, **kwargs)

        self._server = HTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="tardis-dashboard",
        )
        self._thread.start()

    def stop(self):
        """Stop the dashboard HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_status_data(self) -> dict[str, Any]:
        """Get current dashboard status data."""
        data = {
            "status": {"running": True, "uptime_seconds": 0},
            "metrics": {
                "total_steps": 0,
                "total_tokens": 0,
                "total_cost": 0.0,
                "error_count": 0,
                "errors_per_step": 0.0,
            },
            "anomalies": {"total": 0, "recent": []},
            "alerts": {"total": 0, "recent": []},
            "traces": [],
        }

        if self.monitor and hasattr(self.monitor, "get_dashboard_data"):
            try:
                data = self.monitor.get_dashboard_data()
            except Exception:
                pass

        return data

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"
