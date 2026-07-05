import os
import tempfile
import unittest
from unittest import mock

import devcard_lib as lib


class TestLanguageForPath(unittest.TestCase):
    def test_known_extension(self):
        self.assertEqual(lib.language_for_path("foo/bar.py"), "Python")

    def test_unknown_extension(self):
        self.assertIsNone(lib.language_for_path("foo/bar.exe"))

    def test_case_insensitive(self):
        self.assertEqual(lib.language_for_path("FOO.PY"), "Python")


class TestCountLines(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(lib.count_lines(""), 0)

    def test_single_line(self):
        self.assertEqual(lib.count_lines("hello"), 1)

    def test_multi_line(self):
        self.assertEqual(lib.count_lines("a\nb\nc"), 3)


class TestParseEvent(unittest.TestCase):
    def test_write_known_language(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/main.py", "content": "a\nb\n"},
            "cwd": "/repo",
        }
        event = lib.parse_event(payload)
        self.assertEqual(event["language"], "Python")
        self.assertEqual(event["lines_added"], 3)
        self.assertEqual(event["lines_removed"], 0)
        self.assertEqual(event["event_type"], "write")
        self.assertEqual(event["project_key"], "/repo")

    def test_write_unknown_language_returns_none(self):
        payload = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/repo/image.png", "content": "binary"},
            "cwd": "/repo",
        }
        self.assertIsNone(lib.parse_event(payload))

    def test_edit_counts_both_sides(self):
        payload = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/repo/app.ts",
                "old_string": "a\nb",
                "new_string": "a\nb\nc\nd",
            },
            "cwd": "/repo",
        }
        event = lib.parse_event(payload)
        self.assertEqual(event["language"], "TypeScript")
        self.assertEqual(event["lines_added"], 4)
        self.assertEqual(event["lines_removed"], 2)

    def test_bash_git_commit_recorded(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'test'"},
            "cwd": "/repo",
        }
        event = lib.parse_event(payload)
        self.assertEqual(event["event_type"], "commit")
        self.assertIsNone(event["language"])

    def test_bash_other_command_ignored(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "cwd": "/repo",
        }
        self.assertIsNone(lib.parse_event(payload))

    def test_unknown_tool_ignored(self):
        payload = {"tool_name": "Grep", "tool_input": {}, "cwd": "/repo"}
        self.assertIsNone(lib.parse_event(payload))


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "events.db")
        self.conn = lib.init_db(self.db_path)

    def tearDown(self):
        self.conn.close()

    def test_insert_and_repo_count(self):
        event = {
            "ts": 1000, "language": "Python", "lines_added": 5,
            "lines_removed": 1, "event_type": "edit", "project_key": "/repo/a",
        }
        lib.insert_event(self.conn, event)
        self.assertEqual(lib.repo_count(self.conn), 1)
        event["project_key"] = "/repo/b"
        lib.insert_event(self.conn, event)
        self.assertEqual(lib.repo_count(self.conn), 2)

    def test_unsynced_events_and_mark_synced(self):
        event = {
            "ts": 1000, "language": "Python", "lines_added": 5,
            "lines_removed": 1, "event_type": "edit", "project_key": "/repo/a",
        }
        row_id = lib.insert_event(self.conn, event)
        unsynced = lib.get_unsynced_events(self.conn)
        self.assertEqual(len(unsynced), 1)
        self.assertEqual(unsynced[0]["id"], row_id)
        lib.mark_synced(self.conn, [row_id])
        self.assertEqual(lib.get_unsynced_events(self.conn), [])


class TestSendToWorker(unittest.TestCase):
    def test_success(self):
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["request"] = req
            return mock_resp

        with mock.patch("devcard_lib.urllib.request.urlopen", side_effect=fake_urlopen):
            ok = lib.send_to_worker([{"id": 1}], 3, url="https://example.test/ingest", token="tok")
        self.assertTrue(ok)
        self.assertEqual(captured["request"].get_header("User-agent"), "devcard-hook/1.0")

    def test_failure_is_swallowed(self):
        with mock.patch("devcard_lib.urllib.request.urlopen", side_effect=OSError("boom")):
            ok = lib.send_to_worker([{"id": 1}], 3, url="https://example.test/ingest", token="tok")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
