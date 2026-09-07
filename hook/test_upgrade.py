"""Event identity ACROSS an upgrade, and what happens when it cannot be obtained.

Two failure modes are pinned here, both about a local row outliving the
identity its installation had when the row was queued:

1. An old hook syncs local row 42 with no source_id, so the Worker stores it as
   `legacy/42`. The response is lost, so the row stays `synced = 0`. The user
   upgrades. The new hook re-sends row 42 under its brand-new installation id —
   and the Worker, told a different identity for the same work, counts it twice.

2. An installation that cannot persist an id falls back to `legacy`, silently
   merging its rowids with every other unidentified installation's and undoing
   the multi-machine identity the field exists to provide.
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

import devcard_lib as lib

_MODULE_TMP = None
_PATCHERS = []


def setUpModule():
    """Keep this module off the owner's real ~/.claude/devcard files.

    `insert_event` reads the installation's source id, so without this the
    suite's behaviour would depend on whether the developer happens to have one
    — passing locally and failing on a CI runner that does not.
    """
    global _MODULE_TMP
    _MODULE_TMP = tempfile.mkdtemp(prefix="devcard-upgrade-tests-")
    for attr, name in (
        ("DB_PATH", "events.db"),
        ("ERROR_LOG_PATH", "errors.log"),
        ("SOURCE_ID_PATH", "source-id"),
        ("GITHUB_CACHE_PATH", "github-repos.json"),
    ):
        patcher = mock.patch.object(lib, attr, os.path.join(_MODULE_TMP, name))
        patcher.start()
        _PATCHERS.append(patcher)


def tearDownModule():
    for patcher in _PATCHERS:
        patcher.stop()
    _PATCHERS.clear()
    if _MODULE_TMP:
        shutil.rmtree(_MODULE_TMP, ignore_errors=True)


def _mock_response():
    resp = mock.MagicMock()
    resp.status = 200
    resp.__enter__.return_value = resp
    return resp


def _capture_request(fn):
    """Run `fn`, returning the urllib Request it would have sent."""
    captured = {}
    resp = _mock_response()

    def fake_urlopen(req, timeout=None):
        captured["request"] = req
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        fn()
    return captured["request"]


def legacy_db(tmp, rows=3, synced=False):
    """A local database exactly as a pre-source_id version of devcard left it."""
    path = os.path.join(tmp, "events.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
        " language TEXT, lines_added INTEGER NOT NULL DEFAULT 0,"
        " lines_removed INTEGER NOT NULL DEFAULT 0, bytes_added INTEGER NOT NULL DEFAULT 0,"
        " event_type TEXT NOT NULL, project_key TEXT NOT NULL,"
        " synced INTEGER NOT NULL DEFAULT 0)"
    )
    for i in range(rows):
        conn.execute(
            "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added,"
            " event_type, project_key, synced) VALUES (?, 'Python', 10, 0, 100, 'edit',"
            " 'C:/IA/repo', ?)",
            (1750000000 + i, 1 if synced else 0),
        )
    conn.commit()
    conn.close()
    return path


class TestUpgradeAcrossSourceId(unittest.TestCase):
    """A local queue that predates the installation id."""

    def test_upgrading_stamps_the_pending_backlog_as_legacy(self):
        # Those rows may already be in D1 under `legacy` — an ACK can have been
        # lost. They have to go back under the identity they left under.
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp)
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                conn = lib.init_db(path)
                try:
                    sources = [r[0] for r in conn.execute("SELECT source_id FROM events ORDER BY id")]
                finally:
                    conn.close()
        self.assertEqual(sources, ["legacy", "legacy", "legacy"])

    def test_the_re_sent_backlog_keeps_the_legacy_namespace_on_the_wire(self):
        # The end of the scenario: what the upgraded hook actually POSTs.
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=1)
            source_path = os.path.join(tmp, "source-id")
            with mock.patch.object(lib, "SOURCE_ID_PATH", source_path):
                conn = lib.init_db(path)
                try:
                    new_id = lib.source_id()
                    lib.stamp_pending_source(conn, new_id)
                    unsynced = lib.get_unsynced_events(conn)
                finally:
                    conn.close()

            req = _capture_request(
                lambda: lib.send_to_worker(
                    unsynced, 1, url="https://example.test/ingest", token="t", source=new_id
                )
            )
        body = json.loads(req.data.decode("utf-8"))
        # The batch default is the new installation; the backlogged event
        # overrides it, so the Worker rebuilds the very key it already stored.
        self.assertEqual(body["source_id"], new_id)
        self.assertEqual(body["events"][0]["source_id"], "legacy")
        self.assertNotEqual(new_id, "legacy")

    def test_new_events_after_the_upgrade_use_the_new_source_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=1)
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                new_id = lib.source_id()
                conn = lib.init_db(path)
                try:
                    lib.insert_event(conn, {
                        "ts": 1750001000, "language": "Python", "lines_added": 4,
                        "lines_removed": 0, "bytes_added": 40, "event_type": "edit",
                        "project_key": "C:/IA/repo",
                    })
                    rows = dict(conn.execute("SELECT id, source_id FROM events ORDER BY id"))
                finally:
                    conn.close()
        self.assertEqual(rows[1], "legacy")  # queued before the upgrade
        self.assertEqual(rows[2], new_id)    # captured after it

    def test_one_batch_can_carry_both_namespaces(self):
        # The realistic first sync after an upgrade: backlog plus new work.
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=2)
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                new_id = lib.source_id()
                conn = lib.init_db(path)
                try:
                    lib.insert_event(conn, {
                        "ts": 1750002000, "language": "Rust", "lines_added": 7,
                        "lines_removed": 0, "bytes_added": 70, "event_type": "edit",
                        "project_key": "C:/IA/repo",
                    })
                    unsynced = lib.get_unsynced_events(conn)
                finally:
                    conn.close()
        self.assertEqual([e["source_id"] for e in unsynced], ["legacy", "legacy", new_id])

    def test_an_already_synced_backlog_is_not_re_sent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=3, synced=True)
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                conn = lib.init_db(path)
                try:
                    self.assertEqual(lib.get_unsynced_events(conn), [])
                finally:
                    conn.close()

    def test_the_backfill_runs_once_and_never_relabels_new_rows(self):
        # Re-running the backfill on every open would stamp `legacy` onto rows
        # that merely have not been given an id yet — the opposite error, and it
        # would file this machine's work in the shared namespace.
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=1)
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                lib.init_db(path).close()

                # A capture that happened before any id could be persisted.
                raw = sqlite3.connect(path)
                raw.execute(
                    "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added,"
                    " event_type, project_key, source_id) VALUES (1, 'Python', 1, 0, 1, 'edit',"
                    " 'C:/IA/repo', NULL)"
                )
                raw.commit()
                raw.close()

                conn = lib.init_db(path)  # opened again, as every hook run does
                try:
                    sources = [r[0] for r in conn.execute("SELECT source_id FROM events ORDER BY id")]
                finally:
                    conn.close()
        self.assertEqual(sources, ["legacy", None])

    def test_adding_the_column_and_stamping_it_are_atomic(self):
        # Apart, a process killed between the two would leave the column
        # present and every pre-existing row NULL — and the ALTER never runs
        # again, so the backfill never happens. Those rows would then look
        # "captured but not yet stamped", get the CURRENT installation id, and
        # any already sent as legacy with a lost response would be counted
        # twice. So the pair has to be one transaction.
        with tempfile.TemporaryDirectory() as tmp:
            path = legacy_db(tmp, rows=3)
            conn = sqlite3.connect(path)
            try:
                conn.execute("BEGIN")
                conn.execute("ALTER TABLE events ADD COLUMN source_id TEXT")
                conn.rollback()  # stand-in for dying before the UPDATE
                columns = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
                self.assertNotIn(
                    "source_id", columns,
                    "SQLite must roll the ALTER back, or the migration is not atomic",
                )
            finally:
                conn.close()

            # and the next run completes it properly
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                conn = lib.init_db(path)
                try:
                    sources = [r[0] for r in conn.execute("SELECT source_id FROM events")]
                finally:
                    conn.close()
        self.assertEqual(sources, ["legacy", "legacy", "legacy"])

    def test_the_backfill_does_not_depend_on_call_order(self):
        # A database with no source_id column was written by a version that sent
        # no source_id, so `legacy` is what D1 holds for it — whether or not an
        # id happens to have been created by the time init_db runs. An earlier
        # draft chose between the two based on the file existing, which made a
        # correctness property depend on the order two unrelated functions are
        # called in.
        for create_id_first in (False, True):
            with self.subTest(create_id_first=create_id_first):
                with tempfile.TemporaryDirectory() as tmp:
                    source_path = os.path.join(tmp, "source-id")
                    with mock.patch.object(lib, "SOURCE_ID_PATH", source_path):
                        if create_id_first:
                            lib.source_id()
                        path = legacy_db(tmp, rows=2)
                        conn = lib.init_db(path)
                        try:
                            sources = {r[0] for r in conn.execute("SELECT source_id FROM events")}
                        finally:
                            conn.close()
                self.assertEqual(sources, {"legacy"})

    def test_a_fresh_install_has_no_legacy_rows_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "SOURCE_ID_PATH", os.path.join(tmp, "source-id")):
                new_id = lib.source_id()
                conn = lib.init_db(os.path.join(tmp, "events.db"))
                try:
                    lib.insert_event(conn, {
                        "ts": 1, "language": "Python", "lines_added": 1, "lines_removed": 0,
                        "bytes_added": 1, "event_type": "edit", "project_key": "C:/IA/repo",
                    })
                    sources = {r[0] for r in conn.execute("SELECT source_id FROM events")}
                finally:
                    conn.close()
        self.assertEqual(sources, {new_id})


class TestFailClosedOnMissingSourceId(unittest.TestCase):
    """A failure to persist an id must never silently become `legacy`."""

    def _unwritable_source_path(self, tmp):
        # A directory where the file should be: every open() fails.
        path = os.path.join(tmp, "source-id")
        os.makedirs(path)
        return path

    def _db_with_events(self, tmp, n=3):
        conn = lib.init_db(os.path.join(tmp, "events.db"))
        for i in range(n):
            lib.insert_event(conn, {
                "ts": 1750000000 + i, "language": "Python", "lines_added": 1,
                "lines_removed": 0, "bytes_added": 10, "event_type": "edit",
                "project_key": "C:/IA/repo",
            })
        return conn

    def test_events_are_captured_even_when_no_id_can_be_persisted(self):
        # Capture must never lose work just because identity is unavailable.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "SOURCE_ID_PATH", self._unwritable_source_path(tmp)):
                conn = self._db_with_events(tmp)
                try:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 3)
                    self.assertEqual(lib.count_unstamped(conn), 3)
                finally:
                    conn.close()

    def test_unstamped_events_are_never_offered_for_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "SOURCE_ID_PATH", self._unwritable_source_path(tmp)):
                conn = self._db_with_events(tmp)
                try:
                    self.assertEqual(lib.get_unsynced_events(conn), [])
                finally:
                    conn.close()

    def test_sync_sends_nothing_and_keeps_the_events_for_later(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Own error-log directory: the throttle marker lives beside it, and
            # a marker left by another test would suppress the line this one
            # asserts.
            with mock.patch.object(lib, "SOURCE_ID_PATH", self._unwritable_source_path(tmp)), \
                    mock.patch.object(lib, "ERROR_LOG_PATH", os.path.join(tmp, "errors.log")):
                conn = self._db_with_events(tmp)
                try:
                    sent = []
                    with mock.patch.object(lib, "log_error") as logged, \
                            mock.patch("urllib.request.urlopen",
                                       side_effect=lambda *a, **k: sent.append(a)):
                        ok = lib.sync_pending(conn)
                    self.assertFalse(ok)
                    self.assertEqual(sent, [], "nothing may go on the wire")
                    self.assertEqual(logged.call_count, 1, "the failure is recorded locally")
                    self.assertEqual(lib.count_unstamped(conn), 3, "events are kept")
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM events WHERE synced = 1").fetchone()[0], 0
                    )
                finally:
                    conn.close()

    def test_nothing_is_ever_filed_under_legacy_by_accident(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "SOURCE_ID_PATH", self._unwritable_source_path(tmp)):
                conn = self._db_with_events(tmp)
                try:
                    with mock.patch.object(lib, "log_error"), mock.patch("urllib.request.urlopen"):
                        lib.sync_pending(conn)
                    sources = {r[0] for r in conn.execute("SELECT source_id FROM events")}
                finally:
                    conn.close()
        self.assertEqual(sources, {None})
        self.assertNotIn("legacy", sources)

    def test_a_hook_is_not_blocked_by_the_failure(self):
        # sync_pending returns; it does not raise into the caller, which is a
        # Claude Code tool call or a `git commit`.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "SOURCE_ID_PATH", self._unwritable_source_path(tmp)):
                conn = self._db_with_events(tmp, n=1)
                try:
                    with mock.patch.object(lib, "log_error"):
                        self.assertIs(lib.sync_pending(conn), False)
                finally:
                    conn.close()

    def test_recovers_once_an_id_can_be_persisted(self):
        # The retry the next capture triggers: the same events go out, once,
        # under a real namespace.
        with tempfile.TemporaryDirectory() as tmp:
            blocked = self._unwritable_source_path(tmp)
            with mock.patch.object(lib, "SOURCE_ID_PATH", blocked):
                conn = self._db_with_events(tmp)
                with mock.patch.object(lib, "log_error"):
                    self.assertFalse(lib.sync_pending(conn))

            # The obstruction clears (permissions fixed, disk freed, whatever).
            os.rmdir(blocked)
            captured = {}
            resp = _mock_response()

            def fake_urlopen(req, timeout=None):
                captured["body"] = json.loads(req.data.decode("utf-8"))
                return resp

            try:
                with mock.patch.object(lib, "SOURCE_ID_PATH", blocked), \
                        mock.patch.object(lib, "repo_count", return_value=1), \
                        mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    self.assertTrue(lib.sync_pending(conn))
                    self.assertEqual(lib.count_unstamped(conn), 0)
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM events WHERE synced = 0").fetchone()[0], 0
                    )
                new_id = lib.read_source_id(blocked)
            finally:
                conn.close()

        self.assertRegex(new_id, r"^[0-9a-f]{32}$")
        self.assertEqual(captured["body"]["source_id"], new_id)
        self.assertEqual({e["source_id"] for e in captured["body"]["events"]}, {new_id})
        self.assertEqual(len(captured["body"]["events"]), 3)

    def test_a_stamped_event_keeps_its_namespace_if_the_id_file_is_lost(self):
        # An event sent-but-unacked was sent under the id it carries. If the
        # file is lost and regenerated, the retry must still use the OLD one,
        # or the Worker sees a new event and counts the work twice.
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source-id")
            with mock.patch.object(lib, "SOURCE_ID_PATH", source_path):
                original = lib.source_id()
                conn = self._db_with_events(tmp, n=2)
                try:
                    os.remove(source_path)
                    regenerated = lib.source_id()
                    self.assertNotEqual(regenerated, original)
                    unsynced = lib.get_unsynced_events(conn)
                finally:
                    conn.close()
        self.assertEqual({e["source_id"] for e in unsynced}, {original})

    def test_a_corrupt_id_file_also_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source-id")
            with open(source_path, "w", encoding="utf-8") as f:
                f.write("!! not a valid id !!")
            with mock.patch.object(lib, "SOURCE_ID_PATH", source_path):
                conn = self._db_with_events(tmp, n=2)
                try:
                    sent = []
                    with mock.patch.object(lib, "log_error"), \
                            mock.patch("urllib.request.urlopen",
                                       side_effect=lambda *a, **k: sent.append(a)):
                        self.assertFalse(lib.sync_pending(conn))
                    self.assertEqual(sent, [])
                    self.assertEqual(lib.count_unstamped(conn), 2)
                finally:
                    conn.close()


class TestFailureLogThrottle(unittest.TestCase):
    """A persistent failure must not bury the log it writes to.

    The syncer runs roughly every 20 seconds, so an unthrottled line for a
    condition that lasts a day would be thousands of entries in the file that is
    documented as the place to start debugging a silent hook. The project has
    already been burnt by this once, with a logged-out `gh`.
    """

    def _tmp_log(self, tmp):
        return mock.patch.object(lib, "ERROR_LOG_PATH", os.path.join(tmp, "errors.log"))

    def test_logs_the_first_time_and_stays_quiet_after(self):
        with tempfile.TemporaryDirectory() as tmp, self._tmp_log(tmp):
            with mock.patch.object(lib, "log_error") as logged:
                self.assertTrue(lib._log_throttled("k", "boom", now=1000))
                self.assertFalse(lib._log_throttled("k", "boom", now=1001))
                self.assertFalse(lib._log_throttled("k", "boom", now=1000 + lib.LOG_THROTTLE_TTL - 1))
            self.assertEqual(logged.call_count, 1)

    def test_logs_again_once_the_window_passes(self):
        with tempfile.TemporaryDirectory() as tmp, self._tmp_log(tmp):
            with mock.patch.object(lib, "log_error") as logged:
                lib._log_throttled("k", "boom", now=1000)
                self.assertTrue(lib._log_throttled("k", "boom", now=1000 + lib.LOG_THROTTLE_TTL + 1))
            self.assertEqual(logged.call_count, 2)

    def test_different_conditions_do_not_silence_each_other(self):
        with tempfile.TemporaryDirectory() as tmp, self._tmp_log(tmp):
            with mock.patch.object(lib, "log_error") as logged:
                self.assertTrue(lib._log_throttled("one", "a", now=1000))
                self.assertTrue(lib._log_throttled("two", "b", now=1000))
            self.assertEqual(logged.call_count, 2)

    def test_a_repeated_sync_failure_produces_one_line_not_one_per_attempt(self):
        with tempfile.TemporaryDirectory() as tmp, self._tmp_log(tmp):
            blocked = os.path.join(tmp, "source-id")
            os.makedirs(blocked)
            with mock.patch.object(lib, "SOURCE_ID_PATH", blocked):
                conn = lib.init_db(os.path.join(tmp, "events.db"))
                try:
                    lib.insert_event(conn, {
                        "ts": 1, "language": "Python", "lines_added": 1, "lines_removed": 0,
                        "bytes_added": 1, "event_type": "edit", "project_key": "C:/IA/repo",
                    })
                    with mock.patch("urllib.request.urlopen"):
                        for _ in range(20):  # ~7 minutes of syncing
                            lib.sync_pending(conn)
                finally:
                    conn.close()
            with open(os.path.join(tmp, "errors.log"), encoding="utf-8") as f:
                lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("holding 1 event(s) unsynced", lines[0])


if __name__ == "__main__":
    unittest.main()
