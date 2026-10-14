"""The real loopback server, using only a temporary SQLite fixture."""
import contextlib
import csv
import hashlib
import http.client
import io
import json
from pathlib import Path
import socket
import sqlite3
import threading
import unittest
from unittest import mock

from devcard import cli, config, data, serve
from devcard.render import render

from .helpers import TempDirTest

NOW = 1760000000
TODAY = "2025-10-09"
PRIVATE = "/private/customer/project/source.py"


class ServerTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.db_path = Path(self.tmp) / "events.db"
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE events (ts INTEGER, language TEXT, lines_added INTEGER,
                    lines_removed INTEGER, bytes_added INTEGER, event_type TEXT,
                    project_key TEXT, agent TEXT);
                CREATE TABLE known_repos (project_key TEXT PRIMARY KEY, first_seen INTEGER);
            """)
            conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (NOW - 10, "Python", 10, 2, 100, "edit", PRIVATE, "claude-code"),
                (NOW - 20, "Python", 5, 1, 40, "write", PRIVATE, "codex"),
                (NOW - 86400, "Rust", 7, 3, 70, "diff", PRIVATE, "manual"),
                (NOW - 86400, None, 0, 0, 0, "commit", PRIVATE, None),
                (NOW - 400 * 86400, "Go", 4, 0, 20, "diff", PRIVATE, ""),
            ])
            conn.executemany("INSERT INTO known_repos VALUES (?, ?)", [(PRIVATE, NOW), ("another-private-project", NOW)])
        self.dashboard = serve.Dashboard(self.db_path, {**config.DEFAULTS, "timezone": "UTC"}, now=NOW)
        self.server = serve.DashboardServer(self.dashboard, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive())

    def request(self, path, headers=None, method="GET"):
        client = http.client.HTTPConnection(*self.server.server_address, timeout=10)
        try:
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def get_json(self, path):
        status, headers, body = self.request(path)
        self.assertEqual(status, 200, body)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertNotIn(PRIVATE.encode(), body)
        self.assertNotIn(b"project_key", body)
        return json.loads(body)

    def test_summary_matches_card_aggregates(self):
        result = self.get_json("/api/summary")
        self.assertEqual(result["totals"], {"lines_added": 26, "bytes_added": 230, "events": 5,
                         "commits": 1, "actions": 2, "diffs": 2, "repo_count": 2})
        self.assertEqual(result["streak"], 2)
        self.assertEqual(result["languages"], [{"language": "Python", "lines_added": 15},
                                             {"language": "Rust", "lines_added": 7},
                                             {"language": "Go", "lines_added": 4}])
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            card = data.card_data(data.merge([data.aggregate(conn, NOW, tz="UTC", repo_count=2)]), "devcard", NOW, tz="UTC")
        self.assertEqual(result["streak"], card.streak)
        self.assertEqual(result["heatmap"], [[{"day": c.day, "lines": c.lines, "level": c.level} for c in w] for w in card.heat_weeks])
        self.assertEqual((len(result["heatmap"]), len(result["heatmap"][0])), (16, 7))

    def test_days_are_per_language_with_inclusive_bounds(self):
        rows = self.get_json(f"/api/days?from={TODAY}&to={TODAY}")
        self.assertEqual(rows, [{"day": TODAY, "language": "Python", "lines_added": 15,
                                "lines_removed": 3, "bytes_added": 140, "events": 2}])
        yesterday = self.get_json("/api/days?from=2025-10-08&to=2025-10-08")
        self.assertEqual(len(yesterday), 2)
        self.assertEqual(yesterday[0]["language"], None)
        self.assertEqual(yesterday[1]["lines_added"], 7)
        self.assertEqual(sum(row["lines_added"] for row in self.get_json("/api/days")), 22)

    def test_day_boundaries_follow_configuration(self):
        self.dashboard.to_day = data.day_fn("Asia/Tokyo")
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DELETE FROM events")
            conn.execute("INSERT INTO events VALUES (?, 'Rust', 3, 0, 90, 'edit', ?, 'codex')", (1759966200, PRIVATE))
        rows = self.get_json(f"/api/days?from={TODAY}&to={TODAY}")
        self.assertEqual(rows[0]["lines_added"], 3)

    def test_agents_sum_to_all_event_totals(self):
        rows = self.get_json("/api/agents")
        self.assertEqual(rows[0], {"agent": "claude-code", "lines_added": 10, "lines_removed": 2, "bytes_added": 100, "events": 1})
        self.assertEqual(sum(row["lines_added"] for row in rows), 26)
        self.assertEqual(sum(row["events"] for row in rows), 5)
        unknown = next(row for row in rows if row["agent"] == "unknown")
        self.assertEqual(unknown["events"], 2)

    def test_old_schema_and_missing_optional_tables(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("ALTER TABLE events DROP COLUMN agent")
        self.assertEqual(self.get_json("/api/agents"), [])
        self.assertEqual(self.get_json("/api/usage"), [])
        self.assertEqual(self.get_json("/api/summary")["totals"]["events"], 5)

    def test_usage_sums_tokens_and_cost_without_inventing_unknown_prices(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE usage (agent TEXT, model TEXT, input_tokens INTEGER,
                    output_tokens INTEGER, cached_input_tokens INTEGER, total_tokens INTEGER, cost_usd REAL);
                INSERT INTO usage VALUES ('codex', 'test-model', 100, 20, 40, 120, 0.2);
                INSERT INTO usage VALUES ('codex', 'test-model', 200, 40, 80, 240, 0.4);
                INSERT INTO usage VALUES ('claude-code', 'unknown-model', 20, 5, 0, 25, NULL);
            """)
        rows = self.get_json("/api/usage")
        self.assertIsNone(rows[0]["cost_usd"])
        self.assertEqual(rows[1]["total_tokens"], 360)
        self.assertEqual(rows[1]["cached_input_tokens"], 120)
        self.assertAlmostEqual(rows[1]["cost_usd"], 0.6)
        # A missing price in a group makes its cost unavailable, not a partial bill.
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO usage VALUES ('codex', 'test-model', 0, 0, 0, 0, NULL)")
        self.assertIsNone(self.get_json("/api/usage")[1]["cost_usd"])

    def test_usage_raw_aliases_and_no_double_counting_rollups(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE usage_events (agent TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
                    cache_read_input_tokens INTEGER, cache_creation_input_tokens INTEGER, estimated_cost_usd REAL);
                INSERT INTO usage_events VALUES ('claude-code', 'model', 10, 5, 20, 3, 0.01);
                CREATE TABLE usage_daily AS SELECT * FROM usage_events;
            """)
        rows = self.get_json("/api/usage")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_tokens"], 38)
        self.assertEqual(rows[0]["cache_write_input_tokens"], 3)
        self.assertEqual(rows[0]["cost_usd"], 0.01)

    def test_unrecognized_usage_schema_is_empty(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("CREATE TABLE usage (unrelated TEXT)")
        self.assertEqual(self.get_json("/api/usage"), [])

    def test_fresh_install_does_not_create_database(self):
        path = Path(self.tmp) / "not-created" / "events.db"
        self.dashboard.db_path = path
        self.assertEqual(self.get_json("/api/summary")["totals"]["events"], 0)
        self.assertEqual(self.get_json("/api/days"), [])
        self.assertEqual(self.get_json("/api/agents"), [])
        self.assertEqual(self.get_json("/api/usage"), [])
        self.assertEqual(self.request("/api/card.svg")[0], 200)
        self.assertFalse(path.parent.exists())

    def test_database_is_opened_read_only_and_responses_do_not_modify_it(self):
        before = hashlib.sha256(self.db_path.read_bytes()).digest()
        conn = self.dashboard.connect()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM events")
        finally:
            conn.close()
        for path in ("/api/summary", "/api/days", "/api/agents", "/api/usage", "/api/card.svg", "/api/export.csv", "/api/export.json"):
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(before, hashlib.sha256(self.db_path.read_bytes()).digest())

    def test_new_hook_writes_are_visible_without_restart(self):
        self.assertEqual(self.get_json("/api/summary")["totals"]["events"], 5)
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO events VALUES (?, 'Python', 2, 0, 60, 'edit', ?, 'codex')", (NOW, PRIVATE))
        self.assertEqual(self.get_json("/api/summary")["totals"]["lines_added"], 28)

    def test_preview_uses_the_existing_renderer(self):
        status, headers, body = self.request("/api/card.svg?theme=dark")
        conn = self.dashboard.connect()
        try:
            expected = render(self.dashboard.card(self.dashboard.aggregate(conn)), theme="dark", now=NOW)
        finally:
            conn.close()
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/svg+xml; charset=utf-8")
        self.assertEqual(body.decode(), expected)
        self.assertNotIn(PRIVATE.encode(), body)

    def test_exports_reproduce_summary_totals_and_filter_days(self):
        result = self.get_json("/api/export.json")
        self.assertEqual(sum(row["lines_added"] for row in result["days"]), result["summary"]["totals"]["lines_added"])
        self.assertEqual(sum(row["bytes_added"] for row in result["days"]), result["summary"]["totals"]["bytes_added"])
        self.assertEqual(result["cost_label"], serve.COST_LABEL)
        status, headers, body = self.request("/api/export.csv")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/csv"))
        rows = list(csv.DictReader(io.StringIO(body.decode())))
        self.assertEqual(sum(int(row["lines_added"]) for row in rows), 26)
        selected = self.get_json(f"/api/export.json?from={TODAY}&to={TODAY}")
        self.assertEqual(len(selected["days"]), 1)

    def test_csv_escapes_spreadsheet_formula_labels(self):
        with contextlib.closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO events VALUES (?, '=SUM(1)', 1, 0, 1, 'edit', ?, 'codex')", (NOW, PRIVATE))
        body = self.request("/api/export.csv")[2].decode()
        self.assertIn("'=SUM(1)", body)

    def test_only_loopback_bind_and_exclusive_port(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.assertFalse(self.server.allow_reuse_address)
        self.assertFalse(self.server.allow_reuse_port)
        self.assertEqual(self.server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR), 0)
        with self.assertRaises(OSError):
            serve.DashboardServer(self.dashboard, self.server.server_address[1])

    def test_startup_does_not_use_dns(self):
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("DNS lookup")):
            with serve.DashboardServer(self.dashboard, port=0) as server:
                self.assertEqual(server.server_name, "localhost")

    def test_access_errors_are_not_reported_as_empty_data(self):
        with mock.patch.object(Path, "stat", side_effect=PermissionError("private path")):
            status, _, body = self.request("/api/summary")
        self.assertEqual(status, 503)
        self.assertNotIn(b"private path", body)

    def test_host_header_and_origin_guards(self):
        port = self.server.server_address[1]
        self.assertEqual(self.request("/api/summary", {"Host": f"localhost:{port}"})[0], 200)
        for host in ("attacker.invalid", f"127.0.0.1.attacker.invalid:{port}", "0.0.0.0", f"localhost:{port + 1}", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertEqual(self.request("/api/summary", {"Host": host})[0], 403)
        self.assertEqual(self.request("/api/summary", {"Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/summary", {"Origin": f"http://127.0.0.1:{port}"})[0], 200)

    def test_duplicate_and_missing_host_headers_are_rejected(self):
        for hosts in ([], ["127.0.0.1", "attacker.invalid"]):
            client = http.client.HTTPConnection(*self.server.server_address, timeout=10)
            try:
                client.putrequest("GET", "/api/summary", skip_host=True)
                for host in hosts:
                    client.putheader("Host", host)
                client.endheaders()
                response = client.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
            finally:
                client.close()

    def test_invalid_dates_queries_and_remote_request_paths(self):
        for query in ("from=bad", "from=2025-02-30", "from=20251009", "from=2025-10-10&to=2025-10-01",
                      "from=", "from=2025-10-01&from=2025-10-02", "secret=value"):
            with self.subTest(query=query):
                self.assertEqual(self.request("/api/days?" + query)[0], 400)
        # http.client otherwise replaces Host with the absolute URL's host,
        # which correctly hits the 403 Host guard before path validation.
        host = f"127.0.0.1:{self.server.server_address[1]}"
        self.assertEqual(self.request("http://attacker.invalid/api/summary", {"Host": host})[0], 400)
        self.assertEqual(self.request("/api/card.svg?theme=constructor")[0], 400)

    def test_static_assets_security_headers_and_no_file_traversal(self):
        for path in ("/", "/dashboard.css", "/dashboard.js"):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        for path in ("/../devcard/serve.py", "/%2e%2e/serve.py", "/.env", "/api/nope"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/", method="HEAD")[2], b"")

    def test_database_errors_do_not_expose_paths(self):
        self.dashboard.db_path = Path(self.tmp)
        status, _, body = self.request("/api/summary")
        self.assertEqual(status, 503)
        self.assertNotIn(self.tmp.encode(), body)


class CommandTest(unittest.TestCase):
    def test_cli_registration_default_and_override(self):
        args = cli.build_parser().parse_args(["serve"])
        self.assertEqual(args.port, 47811)
        self.assertIs(args.func, serve.cmd_serve)
        self.assertEqual(cli.build_parser().parse_args(["serve", "--port", "47999"]).port, 47999)

    def test_command_handles_taken_port_and_bad_port(self):
        with mock.patch.object(config, "load", return_value=None), mock.patch.object(serve, "Dashboard"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            with mock.patch.object(serve.DashboardServer, "serve_forever", side_effect=KeyboardInterrupt):
                self.assertEqual(cli.main(["serve", "--port", "0"]), 0)
            self.assertEqual(cli.main(["serve", "--port", "65536"]), 1)
            with mock.patch.object(serve, "DashboardServer", side_effect=OSError("private-path")):
                self.assertEqual(cli.main(["serve"]), 1)
        self.assertIn("http://127.0.0.1:", out.getvalue())
        self.assertNotIn("private-path", out.getvalue())


if __name__ == "__main__":
    unittest.main()
