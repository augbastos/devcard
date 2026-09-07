"""Tests for event identity, sync draining and the privacy of the wire payload.

The assertions here are deliberately about bytes and rows rather than about
intentions: "no project path leaves the machine" is the product's central
promise, so it is checked against the JSON that would actually be POSTed.
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
    """Point every devcard path at a throwaway directory for this whole module.

    Without this the suite READS the developer's real
    `~/.claude/devcard/source-id` — which exists here and does not exist on a CI
    runner, so `insert_event` would stamp rows locally and leave them NULL in
    CI, and tests would pass on one machine and fail on the other. It also
    guarantees nothing here can write to the owner's live data.
    """
    global _MODULE_TMP
    _MODULE_TMP = tempfile.mkdtemp(prefix="devcard-sync-tests-")
    for attr, name in (
        ("DB_PATH", "events.db"),
        ("ERROR_LOG_PATH", "errors.log"),
        ("SOURCE_ID_PATH", "source-id"),
        ("GITHUB_CACHE_PATH", "github-repos.json"),
    ):
        patcher = mock.patch.object(lib, attr, os.path.join(_MODULE_TMP, name))
        patcher.start()
        _PATCHERS.append(patcher)
    # A normal installation has an id by the time it captures anything (the
    # first sync creates one). Tests that need the no-id case redirect
    # SOURCE_ID_PATH themselves.
    lib.source_id()


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


class TestSourceId(unittest.TestCase):
    """The installation identity that makes ingest idempotent across machines."""

    def test_generates_and_persists_an_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "source-id")
            first = lib.source_id(path)
            self.assertRegex(first, r"^[0-9a-f]{32}$")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), first)

    def test_is_stable_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "source-id")
            self.assertEqual(lib.source_id(path), lib.source_id(path))

    def test_two_installations_get_different_ids(self):
        # The whole point: machine A and machine B must not share a namespace,
        # or B's event 1 is dropped as a duplicate of A's.
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertNotEqual(
                lib.source_id(os.path.join(a, "source-id")),
                lib.source_id(os.path.join(b, "source-id")),
            )

    def test_survives_recreating_the_local_database(self):
        # Deleting events.db restarts the rowid sequence. The source id lives in
        # a different file precisely so that the new sequence lands in the same
        # namespace and old rows are not re-counted.
        with tempfile.TemporaryDirectory() as tmp:
            source_path = os.path.join(tmp, "source-id")
            db_path = os.path.join(tmp, "events.db")
            before = lib.source_id(source_path)
            lib.init_db(db_path).close()
            os.remove(db_path)
            lib.init_db(db_path).close()
            self.assertEqual(lib.source_id(source_path), before)

    def test_carries_no_identifying_information(self):
        # It must be random, never derived from anything about the machine.
        with tempfile.TemporaryDirectory() as tmp:
            value = lib.source_id(os.path.join(tmp, "source-id"))
        candidates = [
            os.environ.get("USERNAME", ""),
            os.environ.get("USER", ""),
            os.environ.get("COMPUTERNAME", ""),
            os.environ.get("HOSTNAME", ""),
            os.path.basename(os.path.expanduser("~")),
        ]
        for secret in candidates:
            if len(secret) >= 3:
                self.assertNotIn(secret.lower(), value.lower())

    def test_matches_what_the_worker_accepts(self):
        # The Worker rejects anything outside [A-Za-z0-9_-]{4,64} with a 400,
        # which would stall the sync queue.
        with tempfile.TemporaryDirectory() as tmp:
            value = lib.source_id(os.path.join(tmp, "source-id"))
        self.assertTrue(lib._SOURCE_ID_RE.match(value))
        self.assertLessEqual(len(value), 64)
        self.assertGreaterEqual(len(value), 4)

    def test_rejects_a_corrupt_file_rather_than_sending_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "source-id")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not a valid id!!")
            # The file exists, so the exclusive create loses. Reporting "" is
            # what stops the corrupt value reaching the Worker, which would
            # answer 400 and stall the queue behind it.
            self.assertEqual(lib.source_id(path), "")

    def test_read_source_id_never_creates_the_file(self):
        # insert_event runs on the Claude Code hot path and calls this. It must
        # not create directories, and it must not log on every tool call.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "source-id")
            with mock.patch.object(lib, "log_error") as logged:
                self.assertEqual(lib.read_source_id(path), "")
            self.assertFalse(os.path.exists(os.path.dirname(path)))
            logged.assert_not_called()

    def test_unwritable_location_reports_failure_instead_of_a_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            # A directory where a file should be: every open() fails.
            path = os.path.join(tmp, "source-id")
            os.makedirs(path)
            with mock.patch.object(lib, "log_error"):
                self.assertEqual(lib.source_id(path), "")

    def test_send_to_worker_includes_the_source_id(self):
        req = _capture_request(
            lambda: lib.send_to_worker(
                [{"id": 1}], 3, url="https://example.test/ingest", token="tok", source="deadbeef"
            )
        )
        self.assertEqual(json.loads(req.data.decode("utf-8"))["source_id"], "deadbeef")

    def test_send_to_worker_refuses_to_send_without_a_source_id(self):
        # It used to omit the field, which made the Worker file the events under
        # the shared `legacy` namespace — silently undoing multi-machine
        # identity for that installation. Now nothing is sent at all.
        sent = []
        with mock.patch.object(lib, "log_error") as logged, \
                mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: sent.append(a)):
            ok = lib.send_to_worker(
                [{"id": 1}], 3, url="https://example.test/ingest", token="tok", source=""
            )
        self.assertFalse(ok)
        self.assertEqual(sent, [], "no request may be made without an installation id")
        logged.assert_called_once()


class TestSyncPayloadPrivacy(unittest.TestCase):
    """The product's central promise, asserted on the bytes that leave the box."""

    def _payload_for(self, project_key):
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                lib.insert_event(conn, {
                    "ts": 1750000000, "language": "Python", "lines_added": 5,
                    "lines_removed": 1, "bytes_added": 50, "event_type": "edit",
                    "project_key": project_key,
                })
                unsynced = lib.get_unsynced_events(conn)
            finally:
                conn.close()

        req = _capture_request(
            lambda: lib.send_to_worker(
                unsynced, 40, url="https://example.test/ingest", token="tok", source="abcdef01"
            )
        )
        return req.data.decode("utf-8")

    def test_project_path_never_appears_in_the_payload(self):
        raw = self._payload_for("C:/IA/a-private-client-project/src")
        self.assertNotIn("a-private-client-project", raw)
        self.assertNotIn("project_key", raw)
        self.assertNotIn("C:/IA", raw)

    def test_payload_carries_only_the_documented_fields(self):
        body = json.loads(self._payload_for("C:/IA/whatever"))
        self.assertEqual(set(body), {"events", "repo_count", "source_id"})
        self.assertEqual(
            set(body["events"][0]),
            {"id", "ts", "language", "lines_added", "lines_removed", "bytes_added",
             "event_type", "source_id"},
        )

    def test_the_unsynced_projection_cannot_select_a_project(self):
        # Belt and braces: the SQL itself has no project column in it, so a
        # future change to the payload builder cannot leak one by accident.
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                lib.insert_event(conn, {
                    "ts": 1, "language": "Python", "lines_added": 1, "lines_removed": 0,
                    "bytes_added": 1, "event_type": "edit", "project_key": "C:/IA/secret",
                })
                rows = lib.get_unsynced_events(conn)
            finally:
                conn.close()
        self.assertNotIn("project_key", rows[0])
        self.assertNotIn("C:/IA/secret", json.dumps(rows))

    def test_the_token_is_a_header_never_the_body_or_the_url(self):
        req = _capture_request(
            lambda: lib.send_to_worker(
                [{"id": 1}], 1, url="https://example.test/ingest",
                token="s3cret-token", source="abcdef01"
            )
        )
        self.assertNotIn("s3cret-token", req.data.decode("utf-8"))
        self.assertNotIn("s3cret-token", req.full_url)
        self.assertEqual(req.get_header("X-devcard-token"), "s3cret-token")

    def test_a_failure_is_logged_without_the_token(self):
        logged = []
        with mock.patch.object(lib, "log_error", side_effect=lambda m: logged.append(m)), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            lib.send_to_worker([{"id": 1}], 1, url="https://example.test/ingest",
                               token="s3cret-token", source="abcdef01")
        self.assertTrue(logged)
        for message in logged:
            self.assertNotIn("s3cret-token", message)


class TestSyncDraining(unittest.TestCase):
    """The retry behaviour that keeps events from being lost or double-sent."""

    def _db(self, tmp, n):
        conn = lib.init_db(os.path.join(tmp, "events.db"))
        for i in range(n):
            lib.insert_event(conn, {
                "ts": 1750000000 + i, "language": "Python", "lines_added": 1,
                "lines_removed": 0, "bytes_added": 10, "event_type": "edit",
                "project_key": "C:/IA/repo",
            })
        return conn

    def test_a_failed_send_leaves_events_unsynced_for_the_next_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp, 3)
            try:
                unsynced = lib.get_unsynced_events(conn)
                with mock.patch.object(lib, "log_error"), \
                        mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
                    ok = lib.send_to_worker(unsynced, 1, url="https://example.test/ingest",
                                            token="t", source="abcdef01")
                self.assertFalse(ok)
                # Nothing was marked: the caller only marks on success.
                self.assertEqual(len(lib.get_unsynced_events(conn)), 3)
            finally:
                conn.close()

    def test_a_non_2xx_response_is_treated_as_a_failure(self):
        resp = _mock_response()
        resp.status = 500
        with mock.patch("urllib.request.urlopen", return_value=resp):
            ok = lib.send_to_worker([{"id": 1}], 1, url="https://example.test/ingest",
                                    token="t", source="abcdef01")
        self.assertFalse(ok)

    def test_marking_synced_is_idempotent_and_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp, 4)
            try:
                ids = [e["id"] for e in lib.get_unsynced_events(conn)]
                lib.mark_synced(conn, ids[:2])
                lib.mark_synced(conn, ids[:2])  # a concurrent syncer repeating itself
                self.assertEqual([e["id"] for e in lib.get_unsynced_events(conn)], ids[2:])
            finally:
                conn.close()

    def test_events_are_drained_oldest_first_in_bounded_batches(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp, 7)
            try:
                batch = lib.get_unsynced_events(conn, limit=3)
                self.assertEqual(len(batch), 3)
                self.assertEqual([e["ts"] for e in batch], sorted(e["ts"] for e in batch))
                self.assertEqual(batch[0]["ts"], 1750000000)
            finally:
                conn.close()

    def test_batches_never_exceed_the_worker_limit(self):
        # The Worker rejects a batch over 100 outright; a default that exceeded
        # it would deadlock the queue instead of draining it.
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp, 120)
            try:
                self.assertLessEqual(len(lib.get_unsynced_events(conn)), 100)
            finally:
                conn.close()

    def test_mark_synced_with_no_ids_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self._db(tmp, 1)
            try:
                lib.mark_synced(conn, [])
                self.assertEqual(len(lib.get_unsynced_events(conn)), 1)
            finally:
                conn.close()

    def test_surrogates_in_content_do_not_break_the_encode(self):
        # A lone surrogate from a weird file encoding used to raise inside
        # json.dumps and silently stop the sync.
        req = _capture_request(
            lambda: lib.send_to_worker(
                [{"id": 1, "language": "Python\ud800"}], 1,
                url="https://example.test/ingest", token="t", source="abcdef01"
            )
        )
        self.assertIsInstance(req.data, bytes)


class TestLocalSchema(unittest.TestCase):
    def test_unsynced_lookup_is_indexed(self):
        # The syncer asks this every ~20s and `events` only ever grows. Without
        # a partial index it is a full scan of the whole history.
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                plan = conn.execute(
                    "EXPLAIN QUERY PLAN SELECT id FROM events WHERE synced = 0 ORDER BY id ASC LIMIT 50"
                ).fetchall()
                self.assertIn("idx_events_unsynced", " ".join(str(r) for r in plan))
            finally:
                conn.close()

    def test_an_older_database_is_upgraded_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.db")
            legacy = sqlite3.connect(path)
            legacy.execute(
                "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL,"
                " language TEXT, lines_added INTEGER NOT NULL DEFAULT 0,"
                " lines_removed INTEGER NOT NULL DEFAULT 0, event_type TEXT NOT NULL,"
                " project_key TEXT NOT NULL, synced INTEGER NOT NULL DEFAULT 0)"
            )
            legacy.execute(
                "INSERT INTO events (ts, language, lines_added, lines_removed, event_type,"
                " project_key) VALUES (1, 'Python', 3, 0, 'edit', 'C:/IA/old')"
            )
            legacy.commit()
            legacy.close()

            conn = lib.init_db(path)
            try:
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )]
                self.assertIn("idx_events_unsynced", names)
                cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
                self.assertIn("bytes_added", cols)
                # and no event was lost on the way
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
            finally:
                conn.close()

    def test_init_db_uses_the_module_path_when_none_is_given(self):
        # Regression: the path used to be a default argument, bound at import,
        # so patching the module constant did nothing — and a test run wrote
        # into the owner's real events.db.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.db")
            with mock.patch.object(lib, "DB_PATH", path):
                conn = lib.init_db()
                conn.close()
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
