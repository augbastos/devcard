"""Offline transcript -> real SQLite -> machine JSON/dashboard/card boundaries."""
from copy import deepcopy
import json
from pathlib import Path
from unittest import mock

from devcard import config, data, publish, serve, usage
from devcard._hook import lib, usage as usage_hook

from .helpers import Home, TempDirTest, edit, git

NOW = 1760000000
PRIVATE = "private-project-secret-transcript-message"


def record(identity="one", model="claude-sonnet-4-5", tokens=1000):
    return {"type": "assistant", "timestamp": "2025-10-09T08:00:00Z",
            "requestId": PRIVATE + identity, "cwd": PRIVATE,
            "message": {"id": PRIVATE + identity, "model": model,
                        "content": PRIVATE, "usage": {"input_tokens": tokens, "output_tokens": 1000}}}


class UsageIntegrationTest(TempDirTest):
    def transcript(self):
        root = Path(self.tmp) / PRIVATE
        root.mkdir(exist_ok=True)
        path = root / "transcript.jsonl"
        path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
        return root, path

    def test_publish_scans_before_aggregate_and_published_bytes_are_private(self):
        root, path = self.transcript()
        remote = self.bare_remote()
        with Home(self.tmp, "home") as home, mock.patch.object(usage, "default_roots", return_value=(("claude", root),)):
            home.add_events([{**edit(NOW), "project_key": PRIVATE, "agent": "claude-code"}])
            cfg = {**config.DEFAULTS, "github_user": "octo-cat", "repo": "octo-cat/card",
                   "remote": remote, "avatar": False, "card": {"show_agents": True, "show_usage": True}}
            self.assertEqual(publish.publish(cfg, now=NOW, repo_count_fn=lambda _: 0), "published")
            source = lib.source_id()
            body = git(remote, "show", f"devcard-data:machines/{source}.json").encode()
            rows = json.loads(body)["usage"]
            self.assertEqual(rows[0]["estimated_cost_usd"], "0.018")
            self.assertEqual(rows[0]["input_tokens"], 1000)
            self.assertEqual(set(rows[0]), set(usage_hook.PUBLIC_FIELDS))
            activity = json.loads(body)
            self.assertEqual(activity["agents"]["claude-code"]["active_minutes"], 2)
            self.assertEqual(activity["active_minutes"], {"2025-10-09": {"claude-code": 2}})
            for forbidden in (PRIVATE, str(path), "content", "requestId", "call_key", "project_key", "salt"):
                self.assertNotIn(forbidden.encode(), body)
            # Scanner cursors avoid decoding unchanged transcripts.
            with mock.patch.object(usage_hook, "parse_claude", side_effect=AssertionError("reparsed")):
                self.assertEqual(publish.publish(cfg, now=NOW + 1000, repo_count_fn=lambda _: 0), "unchanged")
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(record("two", model=PRIVATE)) + "\n")
            agg = publish.local_aggregate(cfg, NOW + 2000, repo_count_fn=lambda _: 0)
            self.assertEqual(sum(row["input_tokens"] for row in agg["usage"]), 2000)
            self.assertEqual({row["model_family"] for row in agg["usage"]}, {"claude-sonnet", "unknown"})
            self.assertNotIn(PRIVATE.encode(), publish.encode_aggregate(agg))

    def test_default_publish_keeps_agents_and_usage_on_the_machine(self):
        # The owner's choice: with the card lines off, these aggregates are not published.
        root, _ = self.transcript()
        remote = self.bare_remote()
        with Home(self.tmp, "home") as home, mock.patch.object(usage, "default_roots", return_value=(("claude", root),)):
            home.add_events([{**edit(NOW), "agent": "claude-code"}])
            cfg = {**config.DEFAULTS, "github_user": "octo-cat", "repo": "octo-cat/card",
                   "remote": remote, "avatar": False}
            self.assertEqual(publish.publish(cfg, now=NOW, repo_count_fn=lambda _: 0), "published")
            body = json.loads(git(remote, "show", f"devcard-data:machines/{lib.source_id()}.json"))
            for key in ("usage", "agents", "active_minutes"):
                self.assertNotIn(key, body)

    def test_disabled_scan_does_not_discover_or_migrate(self):
        with Home(self.tmp, "home"):
            conn = lib.init_db()
            self.addCleanup(conn.close)
            with mock.patch.object(usage, "default_roots", side_effect=AssertionError("discovery")):
                usage.scan_local({"usage": False}, conn)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='usage_meta'").fetchone())

    def test_failure_never_stops_publish_and_error_log_has_no_exception_text(self):
        with Home(self.tmp, "home"), mock.patch.object(usage, "default_roots", side_effect=OSError(PRIVATE)):
            agg = publish.local_aggregate(config.DEFAULTS, NOW, repo_count_fn=lambda _: 0)
            self.assertEqual(agg["events"], 0)
            errors = Path(lib.ERROR_LOG_PATH).read_text(encoding="utf-8")
            self.assertIn("usage scan failed (OSError)", errors)
            self.assertNotIn(PRIVATE, errors)

    def test_serve_command_scans_existing_database_before_serving(self):
        root, _ = self.transcript()
        with Home(self.tmp, "home") as home:
            home.add_events([edit(NOW)])
            config.save({**config.DEFAULTS, "timezone": "UTC"})
            with mock.patch.object(usage, "default_roots", return_value=(("claude", root),)), \
                    mock.patch.object(serve.DashboardServer, "serve_forever", side_effect=KeyboardInterrupt):
                self.assertEqual(serve.cmd_serve(mock.Mock(port=0)), 0)
            dashboard = serve.Dashboard(cfg=config.load(), now=NOW)
            conn = dashboard.connect()
            try:
                self.assertEqual(dashboard.usage(conn)[0]["total_tokens"], 2000)
                self.assertFalse(dashboard.summary(conn)["usage_incomplete"])
            finally:
                conn.close()

    def test_default_roots_and_fresh_install_never_create_database(self):
        with mock.patch.dict("os.environ", {"CODEX_HOME": str(Path(self.tmp) / "codex")}), \
                mock.patch.object(Path, "home", return_value=Path(self.tmp)):
            roots = usage.default_roots()
        self.assertEqual(roots, (("claude", Path(self.tmp) / ".claude" / "projects"),
                                 ("codex", Path(self.tmp) / "codex" / "sessions"),
                                 ("codex", Path(self.tmp) / "codex" / "archived_sessions")))
        missing = Path(self.tmp) / "absent" / "events.db"
        usage.scan_local(config.DEFAULTS, db_path=missing)
        self.assertFalse(missing.parent.exists())

    def test_merge_sums_daily_tokens_and_propagates_unknown_cost(self):
        root, _ = self.transcript()
        with Home(self.tmp, "home"), mock.patch.object(usage, "default_roots", return_value=(("claude", root),)):
            first = publish.local_aggregate({**config.DEFAULTS, "card": {"show_usage": True}}, NOW,
                                            repo_count_fn=lambda _: 3)
        second = deepcopy(first)
        second["usage"][0]["estimated_cost_usd"] = "0.1"
        merged = data.merge([first, second], now=NOW)
        self.assertEqual(merged["repo_count"], 3)
        self.assertEqual(merged["usage"][0]["input_tokens"], 2000)
        self.assertEqual(merged["usage"][0]["estimated_cost_usd"], "0.118")
        second["usage"][0]["estimated_cost_usd"] = None
        self.assertIsNone(data.merge([first, second], now=NOW)["usage"][0]["estimated_cost_usd"])
        for key, bad in (("agent", PRIVATE), ("model_family", PRIVATE), ("date", PRIVATE), ("input_tokens", -1),
                         ("estimated_cost_usd", "NaN")):
            invalid = deepcopy(first)
            invalid["usage"][0][key] = bad
            with self.subTest(key=key), self.assertWarns(RuntimeWarning):
                self.assertEqual(data.merge([invalid], now=NOW)["usage"], [])

    def test_agent_totals_use_column_and_reject_free_form_labels(self):
        with Home(self.tmp, "home") as home:
            home.add_events([edit(NOW), edit(NOW)])
            conn = lib.init_db()
            try:
                conn.execute("PRAGMA ignore_check_constraints=ON")  # Simulate a corrupted/legacy database.
                conn.execute("UPDATE events SET agent=CASE WHEN id=1 THEN 'claude-code' ELSE ? END", (PRIVATE,))
                conn.commit()
                agg = data.aggregate(conn, NOW, tz="UTC")
            finally:
                conn.close()
        self.assertEqual(set(agg["agents"]), {"claude-code", "unknown"})
        self.assertNotIn(PRIVATE.encode(), publish.encode_aggregate(agg))
        merged = data.merge([agg, agg], now=NOW)
        self.assertEqual(merged["agents"]["claude-code"]["lines_added"], 20)
        self.assertEqual(merged["agents"]["claude-code"]["active_minutes"], 4)
        self.assertEqual(merged["active_minutes"]["2025-10-09"]["claude-code"], 4)

    def test_config_roundtrip_keeps_scan_and_card_flags(self):
        with Home(self.tmp, "home"):
            config.save({**config.DEFAULTS, "usage": False, "card": {"show_agents": True, "show_usage": True}})
            cfg = config.load()
        self.assertIs(cfg["usage"], False)
        self.assertEqual(cfg["card"], {"show_agents": True, "show_usage": True})
