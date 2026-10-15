"""Read-only, offline dashboard. No publisher, hook initialization or network clients."""
import csv
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socket
from socketserver import TCPServer
import sqlite3
import time
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfoNotFoundError

from . import config, data, usage
from ._hook import lib, usage as usage_hook
from .render import render

DEFAULT_PORT = 47811
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
    "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
}
COST_LABEL = usage_hook.COST_LABEL


def _columns(conn, table):
    # Only fixed internal names reach this helper, never request parameters.
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


class Dashboard:
    def __init__(self, db_path=None, cfg=None, now=None):
        self.db_path = Path(lib.DB_PATH if db_path is None else db_path).resolve()
        self.cfg = dict(config.DEFAULTS if cfg is None else cfg)
        self.clock = time.time if now is None else lambda: now
        self.to_day = data.day_fn(self.cfg.get("timezone") or None)

    def connect(self):
        try:
            self.db_path.stat()
        except FileNotFoundError:
            return None  # A fresh installation is empty; never create the hook DB.
        conn = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only = ON")
        return conn

    def aggregate(self, conn):
        now = int(self.clock())
        if conn is None or not _columns(conn, "events"):
            return {"format": 1, "languages": {}, "event_types": {}, "days": {},
                    "bytes": 0, "events": 0, "first_ts": None, "repo_count": 0, "updated_at": now}
        repos = conn.execute("SELECT COUNT(*) FROM known_repos").fetchone()[0] if _columns(conn, "known_repos") else 0
        # Loopback data is local, not publication; consent does not hide it.
        return data.aggregate(conn, now, tz=self.cfg.get("timezone") or None, repo_count=repos,
                              consent=config.FULL_CONSENT, repo_count_private=True)

    def card(self, aggregate):
        return data.card_data(data.merge([aggregate]), self.cfg.get("github_user") or "devcard",
                              int(self.clock()), tz=self.cfg.get("timezone") or None, card=self.cfg.get("card"))

    def summary(self, conn):
        aggregate = self.aggregate(conn)
        card = self.card(aggregate)
        return {
            "totals": {"lines_added": card.total_lines, "bytes_added": card.total_bytes,
                       "events": card.total_events, "commits": card.total_commits,
                       "actions": card.total_actions, "diffs": card.total_diffs,
                       "repo_count": card.repo_count},
            "streak": card.streak,
            "languages": [{"language": s.language, "lines_added": s.total} for s in card.languages],
            "heatmap": [[asdict(cell) for cell in week] for week in card.heat_weeks],
            "today": self.to_day(int(self.clock())),
            "timezone": self.cfg.get("timezone") or "local",
            "first_ts": card.first_ts,
            "usage_timezone": self.cfg.get("timezone") or "UTC",
            "usage_incomplete": bool(conn is not None and _columns(conn, "usage_diagnostics")
                                     and conn.execute("SELECT 1 FROM usage_diagnostics LIMIT 1").fetchone()),
        }

    def days(self, conn, params):
        today = self.to_day(int(self.clock()))
        weeks, _, _ = data.build_heatmap({}, today, "en")
        start, end = params.get("from", [weeks[0][0].day])[0], params.get("to", [today])[0]
        for value in (start, end):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Use dates in YYYY-MM-DD format")
        if start > end:
            raise ValueError("from must be on or before to")
        if conn is None or not _columns(conn, "events"):
            return []
        rows = {}
        for bucket, language, added, removed, size, events in conn.execute(
            "SELECT (ts / 900) * 900 AS bucket, language, SUM(lines_added),"
            " SUM(lines_removed), SUM(bytes_added), COUNT(*) FROM events GROUP BY bucket, language"
        ):
            day = self.to_day(bucket)
            if not start <= day <= end:
                continue
            key = (day, language or None)
            row = rows.setdefault(key, {"day": day, "language": language or None,
                                       "lines_added": 0, "lines_removed": 0, "bytes_added": 0, "events": 0})
            for name, value in zip(("lines_added", "lines_removed", "bytes_added", "events"),
                                   (added, removed, size, events), strict=True):
                row[name] += int(value or 0)
        return sorted(rows.values(), key=lambda r: (r["day"], r["language"] or ""))

    def agents(self, conn):
        if conn is None or "agent" not in _columns(conn, "events"):
            return []
        exported = data.activity_rows(conn, self.cfg.get("timezone") or None)
        return [{"agent": agent, **row, "active_days": [
                    {"day": day, "active_minutes": agents[agent]}
                    for day, agents in exported["active_minutes"].items() if agent in agents]}
                for agent, row in sorted(exported["agents"].items(),
                                         key=lambda item: (-item[1]["lines_added"], item[0]))]

    def usage(self, conn):
        return [{**row, "total_tokens": sum(row[name] for name in usage_hook.TOKEN_FIELDS)}
                for row in usage.public_rows(conn)]

    def response(self, path, params):
        if path == "/favicon.ico":
            return b"", "image/x-icon"
        if path in ASSETS:
            name, content_type = ASSETS[path]
            return (Path(__file__).with_name("dashboard") / name).read_bytes(), content_type
        routes = {"/api/summary", "/api/days", "/api/agents", "/api/usage",
                  "/api/card.svg", "/api/export.json", "/api/export.csv"}
        if path not in routes:
            raise LookupError
        conn = self.connect()
        try:
            if conn is not None:
                conn.execute("BEGIN")  # A consistent snapshot per response while hooks write.
            if path == "/api/summary":
                payload = self.summary(conn)
            elif path == "/api/days":
                payload = self.days(conn, params)
            elif path == "/api/agents":
                payload = self.agents(conn)
            elif path == "/api/usage":
                payload = self.usage(conn)
            elif path == "/api/card.svg":
                theme = params.get("theme", ["light"])[0]
                if theme not in ("light", "dark"):
                    raise ValueError("theme must be light or dark")
                svg = render(self.card(self.aggregate(conn)), theme=theme, now=int(self.clock()))
                return svg.encode("utf-8"), "image/svg+xml; charset=utf-8"
            elif path == "/api/export.csv":
                output = io.StringIO(newline="")
                writer = csv.DictWriter(output, fieldnames=("day", "language", "lines_added", "lines_removed", "bytes_added", "events"))
                writer.writeheader()
                # The export defaults to the whole local history, unlike the chart.
                for row in self.days(conn, {"from": ["0001-01-01"], "to": ["9999-12-31"], **params}):
                    row = dict(row)
                    # Spreadsheet programs must not interpret labels as formulas.
                    if row["language"] and row["language"].startswith(("=", "+", "-", "@", "\t", "\r")):
                        row["language"] = "'" + row["language"]
                    writer.writerow(row)
                return output.getvalue().encode("utf-8"), "text/csv; charset=utf-8"
            else:
                payload = {"summary": self.summary(conn),
                           "days": self.days(conn, {"from": ["0001-01-01"], "to": ["9999-12-31"], **params}),
                           "agents": self.agents(conn), "usage": self.usage(conn), "cost_label": COST_LABEL}
            return json.dumps(payload, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8"
        finally:
            if conn is not None:
                conn.close()


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False
    allow_reuse_port = False

    def __init__(self, dashboard, port=DEFAULT_PORT):
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.dashboard = dashboard
        super().__init__(("127.0.0.1", port), DashboardHandler)

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind normally calls getfqdn(), which could consult
        # DNS. Local serving never needs a reverse lookup, even at startup.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "devcard"
    sys_version = ""

    def log_message(self, _format, *_args):
        pass  # Do not log arbitrary request strings or local data.

    def reply(self, status, payload, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content_type.startswith("image/svg+xml"):
            # The existing renderer uses embedded CSS. Permit it only in the
            # SVG document, which cannot execute scripts or fetch anything.
            policy = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"
        else:
            policy = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                      "img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header("Content-Security-Policy", policy)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # The browser closed this request; no response can reach it.

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed.update(("127.0.0.1", "localhost"))
        hosts = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if len(hosts) != 1 or hosts[0].lower() not in allowed or (
            origins and (len(origins) != 1 or origins[0].lower() not in {"http://" + h for h in allowed})
        ):
            self.reply(403, b'{"error":"Loopback Host and same-origin requests required"}')
            return
        try:
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment:
                raise ValueError("Use a local request path")
            params = parse_qs(url.query, keep_blank_values=True, max_num_fields=8)
            allowed_params = {"theme"} if url.path == "/api/card.svg" else {"from", "to"}
            if any(key not in allowed_params or len(values) != 1 for key, values in params.items()):
                raise ValueError("Invalid query parameters")
            payload, content_type = self.server.dashboard.response(url.path, params)
        except LookupError:
            self.reply(404, b'{"error":"Not found"}')
        except ValueError:
            self.reply(400, b'{"error":"Invalid query; use YYYY-MM-DD dates and from <= to"}')
        except (OSError, sqlite3.Error):
            self.reply(503, b'{"error":"Local dashboard data unavailable"}')
        else:
            self.reply(200, payload, content_type)


def cmd_serve(args):
    try:
        dashboard = Dashboard(cfg=config.load() or dict(config.DEFAULTS))
        usage.scan_local(dashboard.cfg, db_path=dashboard.db_path)
        with DashboardServer(dashboard, args.port) as server:
            print(f"devcard dashboard: http://127.0.0.1:{server.server_address[1]}/", flush=True)
            print("Read-only local data. Stop with Ctrl+C.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (OSError, ValueError, ZoneInfoNotFoundError) as exc:
        # Avoid exposing local paths from exceptions.
        detail = "port unavailable" if isinstance(exc, OSError) else "invalid port or timezone"
        print(f"devcard serve: {detail}; choose another --port or check the local configuration")
        return 1
    return 0
