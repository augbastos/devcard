"""M2 attribution, migration, session estimates and serialized privacy checks."""
import io
import json
import os
import sqlite3
import struct
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_activity as activity
import devcard_capture as capture
import devcard_git_hook as githook
import devcard_lib as lib


def ts(hour=12, minute=0, *, day=1):
    return datetime(2026, 1, day, hour, minute, tzinfo=timezone.utc).timestamp()


def event(timestamp=None, agent="claude-code", event_type="edit"):
    return {"ts": ts() if timestamp is None else timestamp, "agent": agent,
            "language": "Python", "lines_added": 3, "lines_removed": 1,
            "bytes_added": 9, "event_type": event_type, "project_key": "/private/project"}


def dst_zone():
    """A tiny TZif fixture with two 2026 transitions, independent of host tzdata."""
    spring = int(datetime(2026, 3, 29, 1, tzinfo=timezone.utc).timestamp())
    autumn = int(datetime(2026, 10, 25, 1, tzinfo=timezone.utc).timestamp())
    header = b"TZif\0" + bytes(15) + struct.pack(">6l", 0, 0, 0, 2, 2, 8)
    transitions = struct.pack(">2l", spring, autumn) + bytes((1, 0))
    types = struct.pack(">lBB", 0, 0, 0) + struct.pack(">lBB", 3600, 1, 4)
    return ZoneInfo.from_file(io.BytesIO(header + transitions + types + b"STD\0DST\0"))


class TestActiveMinutes(unittest.TestCase):
    def calculate(self, events, **kwargs):
        return activity.active_minutes(events, timezone=timezone.utc, **kwargs)

    def test_empty_and_single_event(self):
        self.assertEqual(self.calculate([]), {})
        self.assertEqual(self.calculate([event()]), {"2026-01-01": {"claude-code": 2}})

    def test_sort_duplicate_timestamps_and_input_immutability(self):
        events = [event(ts(12, 10)), event(), event(), event(ts(12, 5))]
        before = json.dumps(events)
        self.assertEqual(self.calculate(iter(events)), {"2026-01-01": {"claude-code": 12}})
        self.assertEqual(json.dumps(events), before)

    def test_idle_gap_and_strict_boundary(self):
        # Exactly 15 minutes stays in the session. 16 minutes starts another.
        events = [event(ts()), event(ts(12, 15)), event(ts(12, 31)), event(ts(12, 36))]
        self.assertEqual(self.calculate(events), {"2026-01-01": {"claude-code": 24}})

    def test_interleaved_agents_do_not_bridge_each_others_idle_gaps(self):
        events = [event(ts()), event(ts(12, 10), "codex"), event(ts(12, 20)),
                  event(ts(12, 25), "codex"), event(ts(12, 25), "git")]
        self.assertEqual(self.calculate(events), {
            "2026-01-01": {"claude-code": 4, "codex": 17, "git": 2},
        })

    def test_concurrent_agent_durations_are_independent(self):
        events = [event(ts(), agent) for agent in ("claude-code", "codex")]
        events += [event(ts(12, 10), agent) for agent in ("claude-code", "codex")]
        self.assertEqual(self.calculate(events), {
            "2026-01-01": {"claude-code": 12, "codex": 12},
        })

    def test_session_and_tail_cross_midnight(self):
        self.assertEqual(self.calculate([event(ts(23, 55)), event(ts(0, 5, day=2))]), {
            "2026-01-01": {"claude-code": 5}, "2026-01-02": {"claude-code": 7},
        })
        self.assertEqual(self.calculate([event(ts(23, 59), "git")]), {
            "2026-01-01": {"git": 1}, "2026-01-02": {"git": 1},
        })

    def test_explicit_timezone_controls_date_boundary(self):
        self.assertEqual(activity.active_minutes([event(ts(23, 59))],
                                               timezone=timezone(timedelta(hours=2))), {
            "2026-01-02": {"claude-code": 2},
        })

    def test_configurable_gap_and_tail(self):
        events = [event(ts()), event(ts(12, 5))]
        self.assertEqual(self.calculate(events, idle_minutes=4, tail_minutes=0.5), {
            "2026-01-01": {"claude-code": 1},
        })
        self.assertEqual(self.calculate(events, tail_minutes=0), {
            "2026-01-01": {"claude-code": 5},
        })
        self.assertEqual(self.calculate([event()], tail_minutes=0), {})

    def test_dst_sessions_use_elapsed_seconds_and_local_days(self):
        zone = dst_zone()
        for month, day in ((3, 29), (10, 25)):
            start = datetime(2026, month, day, 0, 55, tzinfo=timezone.utc).timestamp()
            with self.subTest(month=month):
                self.assertEqual(activity.active_minutes([event(start), event(start + 600)],
                                                        timezone=zone), {
                    f"2026-{month:02d}-{day:02d}": {"claude-code": 12},
                })
        # The spring day is 23 hours and the autumn day is 25 hours.
        for start, minutes, day in (
            (datetime(2026, 3, 29, tzinfo=timezone.utc), 1380, "2026-03-29"),
            (datetime(2026, 10, 24, 23, tzinfo=timezone.utc), 1500, "2026-10-25"),
        ):
            self.assertEqual(activity.active_minutes([event(start.timestamp())],
                                                    timezone=zone, tail_minutes=minutes), {
                day: {"claude-code": minutes},
            })

    def test_long_tail_is_split_over_all_days(self):
        self.assertEqual(self.calculate([event(ts(23, 59))], tail_minutes=1443), {
            "2026-01-01": {"claude-code": 1}, "2026-01-02": {"claude-code": 1440},
            "2026-01-03": {"claude-code": 2},
        })

    def test_legacy_and_unrecognized_agents_read_as_unknown(self):
        events = [event(agent=None), event(agent="/private/arbitrary-agent"),
                  {"ts": ts()}]
        self.assertEqual(self.calculate(events), {"2026-01-01": {"unknown": 2}})

    def test_timezone_is_required_and_parameters_are_validated(self):
        with self.assertRaises(TypeError):
            activity.active_minutes([])
        for value in (None, "", 0):
            with self.subTest(timezone=value), self.assertRaises((ValueError, KeyError)):
                activity.active_minutes([], timezone=value)
        for value in (-1, float("inf"), float("nan"), "15", True):
            for parameter in ("idle_minutes", "tail_minutes"):
                with self.subTest(value=value, parameter=parameter), self.assertRaises(ValueError):
                    self.calculate([], **{parameter: value})
        for value in (float("inf"), float("nan"), "now", True):
            with self.subTest(timestamp=value), self.assertRaises(ValueError):
                self.calculate([event(value)])


class LocalDatabaseCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="devcard-m2-")
        self.addCleanup(tmp.cleanup)
        self.base = tmp.name
        for attr, name in (("DB_PATH", "events.db"), ("SOURCE_ID_PATH", "source-id"),
                           ("ERROR_LOG_PATH", "errors.log"), ("GITHUB_CACHE_PATH", "repos.json"),
                           ("MODE_PATH", "mode")):
            patcher = mock.patch.object(lib, attr, os.path.join(self.base, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(githook, "MODE_PATH", lib.MODE_PATH)
        patcher.start()
        self.addCleanup(patcher.stop)

    def database(self):
        conn = lib.init_db()
        self.addCleanup(conn.close)
        return conn

    def set_mode(self, mode):
        with open(lib.MODE_PATH, "w", encoding="utf-8") as f:
            f.write(mode)

    def legacy_database(self):
        conn = sqlite3.connect(lib.DB_PATH)
        conn.execute("""CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, language TEXT,
            lines_added INTEGER NOT NULL DEFAULT 0, lines_removed INTEGER NOT NULL DEFAULT 0,
            bytes_added INTEGER NOT NULL DEFAULT 0, event_type TEXT NOT NULL,
            project_key TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0, source_id TEXT
        )""")
        for kind in ("edit", "write", "diff", "commit"):
            conn.execute("""INSERT INTO events
                (ts, language, lines_added, event_type, project_key, synced, source_id)
                VALUES (?, 'Python', 7, ?, '/private/old', 1, 'namespace-old')""", (ts(), kind))
        conn.commit()
        conn.close()


class TestAttributionAndMigration(LocalDatabaseCase):
    def test_legacy_upgrade_preserves_rows_and_is_idempotent(self):
        self.legacy_database()
        conn = self.database()
        before = conn.execute("SELECT id, ts, lines_added, event_type, project_key, synced, source_id FROM events").fetchall()
        self.assertEqual(conn.execute("SELECT agent FROM events").fetchall(), [(None,)] * 4)
        new_id = lib.insert_event(conn, event(agent="codex"))
        self.assertEqual(new_id, 5)
        again = self.database()
        self.assertEqual(again.execute("SELECT id, ts, lines_added, event_type, project_key, synced, source_id FROM events WHERE id < 5").fetchall(), before)
        self.assertEqual(again.execute("SELECT agent FROM events").fetchall(), [(None,)] * 4 + [("codex",)])
        exported = json.loads(activity.export_aggregate(again, timezone=timezone.utc))
        self.assertEqual(exported["agents"]["unknown"]["events"], 4)
        self.assertEqual(exported["agents"]["unknown"]["lines_added"], 28)

    def test_concurrent_upgrades_add_one_column(self):
        self.legacy_database()

        def upgrade(_):
            # Test the M2 migration's serialization, allowing slow disk fsyncs
            # without changing the production hook's bounded SQLite timeout.
            conn = sqlite3.connect(lib.DB_PATH, timeout=30)
            try:
                lib._add_agent_column(conn)
                return [row[1] for row in conn.execute("PRAGMA table_info(events)")].count("agent")
            finally:
                conn.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(upgrade, range(2))), [1, 1])
        self.assertEqual(self.database().execute("SELECT COUNT(*) FROM events").fetchone()[0], 4)

    def test_failed_migration_closes_connection_and_can_retry(self):
        self.legacy_database()
        connection = sqlite3.connect(lib.DB_PATH)
        with mock.patch.object(lib.sqlite3, "connect", return_value=connection), \
                mock.patch.object(lib, "_add_agent_column", side_effect=sqlite3.OperationalError("blocked")), \
                self.assertRaises(sqlite3.OperationalError):
            lib.init_db(lib.DB_PATH)
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")
        self.assertEqual(self.database().execute("SELECT agent FROM events").fetchall(), [(None,)] * 4)

    def test_allowlist_is_enforced_by_insert_and_sqlite(self):
        conn = self.database()
        for agent in activity.AGENTS + (None,):
            lib.insert_event(conn, event(agent=agent))
        for agent in ("other-agent", "/private/project", "", ["codex"]):
            with self.subTest(agent=agent), self.assertRaises(ValueError):
                lib.insert_event(conn, event(agent=agent))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE events SET agent = 'untrusted'")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 5)

    def test_claude_payload_cannot_override_origin(self):
        for tool, inputs in (("Edit", {"file_path": "a.py", "new_string": "x"}),
                             ("Write", {"file_path": "a.py", "content": "x"}),
                             ("Bash", {"command": "git commit -m test"})):
            payload = {"tool_name": tool, "tool_input": inputs, "cwd": "/private/project", "agent": "codex"}
            self.assertEqual(lib.parse_event(payload)["agent"], "claude-code")

    def test_claude_entrypoint_attributes_and_respects_mode(self):
        payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "a.py", "new_string": "x"}})
        self.set_mode("claude")
        with mock.patch.object(sys, "stdin", io.StringIO(payload)), mock.patch.object(capture, "maybe_spawn_sync"):
            capture.main()
        self.assertEqual(self.database().execute("SELECT agent FROM events").fetchall(), [("claude-code",)])
        for mode in ("git", "codex", "unexpected"):
            self.set_mode(mode)
            with mock.patch.object(sys, "stdin", io.StringIO(payload)), mock.patch.object(lib, "init_db") as opened:
                capture.main()
            opened.assert_not_called()

    def test_git_entrypoint_attributes_all_rows(self):
        self.set_mode("git")
        with mock.patch.object(githook, "_git", return_value=SimpleNamespace(returncode=0, stdout=self.base)), \
                mock.patch.object(githook, "head_parents", return_value=[]), \
                mock.patch.object(githook, "collect", return_value=({"Python": (3, 1)}, {"Python": 9})), \
                mock.patch.object(lib, "sync_pending"):
            githook.main()
        self.assertEqual(self.database().execute("SELECT event_type, agent FROM events ORDER BY id").fetchall(),
                         [("diff", "git"), ("commit", "git")])

    def test_git_suppressed_for_agent_and_unrecognized_modes(self):
        for mode in ("claude", "codex", "unexpected"):
            self.set_mode(mode)
            with mock.patch.object(githook, "_git") as invoked:
                githook.main()
            invoked.assert_not_called()

    def test_missing_mode_keeps_legacy_default_and_io_error_fails_closed(self):
        self.assertIsNone(lib.capture_mode())
        for entrypoint in (capture.main, githook.main):
            with mock.patch.object(lib, "capture_mode", side_effect=PermissionError("blocked")), \
                    mock.patch.object(sys, "stdin", io.StringIO("{}")), \
                    mock.patch.object(lib, "init_db") as opened, \
                    mock.patch.object(lib, "log_error") as logged:
                entrypoint()
            opened.assert_not_called()
            logged.assert_called_once()


class TestAggregatePrivacy(LocalDatabaseCase):
    def test_export_bytes_include_only_allowlisted_totals_and_active_minutes(self):
        conn = self.database()
        secrets = ["private-repository-name", "private-file.py", "private-code-content",
                   "installation-identity", "private-language-label", "private-event-type"]
        data = event()
        data.update(project_key="/private/" + "/".join(secrets[:3]),
                    source_id=secrets[3], language=secrets[4])
        lib.insert_event(conn, data)
        data = event(ts(12, 5))
        data["event_type"] = secrets[5]
        lib.insert_event(conn, data)
        lib.insert_event(conn, event(ts(12, 10), "git", "diff"))
        lib.insert_event(conn, event(ts(12, 10), "git", "commit"))
        lib.insert_event(conn, event(ts(12, 20), "codex", "write"))
        lib.insert_event(conn, event(ts(12, 20), None))
        serialized = activity.export_aggregate(conn, timezone=timezone.utc)
        self.assertIsInstance(serialized, bytes)
        for value in secrets + ["project_key", "source_id", "language", "event_type", '"ts"', '"id"']:
            self.assertNotIn(value.encode(), serialized)
        exported = json.loads(serialized)
        self.assertEqual(set(exported), {"agents", "active_minutes"})
        self.assertEqual(set(exported["agents"]), set(activity.AGENTS))
        for totals in exported["agents"].values():
            self.assertEqual(set(totals), {"events", "commits", "code_edits", "lines_added",
                                           "lines_removed", "bytes_added", "active_minutes"})
        self.assertEqual(exported["agents"]["claude-code"]["active_minutes"], 7)
        self.assertEqual(exported["agents"]["git"]["code_edits"], 0)
        self.assertEqual(exported["agents"]["git"]["commits"], 1)
        for metric in ("lines_added", "lines_removed", "bytes_added"):
            actual = conn.execute(f"SELECT SUM({metric}) FROM events").fetchone()[0]
            self.assertEqual(sum(t[metric] for t in exported["agents"].values()), actual)
        self.assertEqual(sum(t["events"] for t in exported["agents"].values()), 6)
        self.assertEqual(sum(t["active_minutes"] for t in exported["agents"].values()),
                         sum(sum(day.values()) for day in exported["active_minutes"].values()))
        self.assertEqual(serialized, activity.export_aggregate(conn, timezone=timezone.utc))

    def test_empty_export(self):
        self.assertEqual(activity.export_aggregate(self.database(), timezone=timezone.utc),
                         b'{"active_minutes":{},"agents":{}}')


if __name__ == "__main__":
    unittest.main()
