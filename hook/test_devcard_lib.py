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


class TestCountsAsCommit(unittest.TestCase):
    def test_plain_commit(self):
        self.assertTrue(lib.counts_as_commit('git commit -m "x"'))

    def test_commit_after_a_shell_separator(self):
        self.assertTrue(lib.counts_as_commit('git add -A && git commit -m "x"'))

    def test_commit_with_leading_flags(self):
        self.assertTrue(lib.counts_as_commit("git -C /repo commit -m x"))
        self.assertTrue(lib.counts_as_commit("git --no-pager commit -m x"))

    def test_amend_does_not_count(self):
        # rewrites a commit that was already counted
        self.assertFalse(lib.counts_as_commit('git commit --amend -m "x"'))

    def test_quoted_mention_does_not_count(self):
        self.assertFalse(lib.counts_as_commit('git log --grep="git commit"'))

    def test_unrelated_command(self):
        self.assertFalse(lib.counts_as_commit("git status"))
        self.assertFalse(lib.counts_as_commit(""))


class TestToolFailed(unittest.TestCase):
    def test_missing_response_is_not_a_failure(self):
        # PostToolUse generally fires on success; absence must not drop events
        self.assertFalse(lib.tool_failed({}))
        self.assertFalse(lib.tool_failed({"tool_response": None}))
        self.assertFalse(lib.tool_failed({"tool_response": "some string"}))

    def test_explicit_failure_is_detected(self):
        self.assertTrue(lib.tool_failed({"tool_response": {"success": False}}))
        self.assertTrue(lib.tool_failed({"tool_response": {"is_error": True}}))

    def test_success_is_not_a_failure(self):
        self.assertFalse(lib.tool_failed({"tool_response": {"success": True}}))

    def test_failed_commit_is_not_recorded(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "x"'},
            "cwd": "/repo",
            "tool_response": {"success": False},
        }
        self.assertIsNone(lib.parse_event(payload))

    def test_successful_commit_is_recorded(self):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "x"'},
            "cwd": "/repo",
            "tool_response": {"success": True},
        }
        self.assertEqual(lib.parse_event(payload)["event_type"], "commit")


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "events.db")
        self.conn = lib.init_db(self.db_path)

    def tearDown(self):
        self.conn.close()

    def _known_repos(self):
        return self.conn.execute("SELECT COUNT(*) FROM known_repos").fetchone()[0]

    def test_insert_records_distinct_projects(self):
        # Records the cwd it saw; turning those cwds into a published number is
        # repo_count's job, and it deliberately does not equal this row count.
        event = {
            "ts": 1000, "language": "Python", "lines_added": 5,
            "lines_removed": 1, "event_type": "edit", "project_key": "/repo/a",
        }
        lib.insert_event(self.conn, event)
        self.assertEqual(self._known_repos(), 1)
        lib.insert_event(self.conn, event)  # same project again
        self.assertEqual(self._known_repos(), 1)
        event["project_key"] = "/repo/b"
        lib.insert_event(self.conn, event)
        self.assertEqual(self._known_repos(), 2)

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

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ok = lib.send_to_worker([{"id": 1}], 3, url="https://example.test/ingest", token="tok")
        self.assertTrue(ok)
        self.assertEqual(captured["request"].get_header("User-agent"), "devcard-hook/1.0")

    def test_failure_is_swallowed(self):
        # log_error is stubbed so the failure path can't append fake entries to
        # the owner's real ~/.claude/devcard/errors.log — that file is the
        # documented starting point for debugging a silent hook.
        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")), \
                mock.patch.object(lib, "log_error") as logged:
            ok = lib.send_to_worker([{"id": 1}], 3, url="https://example.test/ingest", token="tok")
        self.assertFalse(ok)
        logged.assert_called_once()


class TestIsTrackableProject(unittest.TestCase):
    def test_plain_repo_path_is_trackable(self):
        self.assertTrue(lib.is_trackable_project(os.path.join("C:", "IA", "wavr")))

    def test_scratchpad_is_rejected(self):
        path = os.path.join("C:", "Temp", "claude", "abc", "scratchpad", "site")
        self.assertFalse(lib.is_trackable_project(path))

    def test_dependency_tree_is_rejected(self):
        self.assertFalse(
            lib.is_trackable_project(os.path.join("C:", "IA", "app", "node_modules", "next"))
        )

    def test_anything_under_the_temp_root_is_rejected(self):
        temp = os.path.normcase(os.path.join("C:", "tmp-root"))
        with mock.patch.object(lib, "TEMP_ROOT", temp):
            self.assertFalse(lib.is_trackable_project(os.path.join(temp, "scpe-demo")))
            self.assertFalse(lib.is_trackable_project(temp))
            self.assertTrue(lib.is_trackable_project(os.path.join("C:", "IA", "wavr")))

    def test_temp_root_only_matches_on_a_separator_boundary(self):
        temp = os.path.normcase(os.path.join("C:", "Users", "x", "Temp"))
        with mock.patch.object(lib, "TEMP_ROOT", temp):
            # a sibling directory that merely shares the prefix is still real work
            self.assertTrue(
                lib.is_trackable_project(os.path.join("C:", "Users", "x", "Temperature-app"))
            )

    def test_forward_slashes_are_normalized(self):
        self.assertFalse(lib.is_trackable_project("C:/Users/x/AppData/Local/Temp/scratchpad"))

    def test_empty_path_is_rejected(self):
        self.assertFalse(lib.is_trackable_project(""))


class TestGitRoot(unittest.TestCase):
    def test_finds_root_from_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.realpath(tmp)
            os.makedirs(os.path.join(root, ".git"))
            nested = os.path.join(root, "src", "deep")
            os.makedirs(nested)
            self.assertEqual(lib.git_root(nested), os.path.normcase(root))

    def test_returns_none_outside_a_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(lib.git_root(os.path.join(tmp, "plain")))


class TestRepoCount(unittest.TestCase):
    def _db_with_projects(self, tmp, keys):
        conn = lib.init_db(os.path.join(tmp, "events.db"))
        for key in keys:
            conn.execute(
                "INSERT OR IGNORE INTO known_repos (project_key, first_seen) VALUES (?, 0)",
                (key,),
            )
        conn.commit()
        return conn

    def test_local_count_collapses_subdirs_and_drops_junk(self):
        # The scratch dirs below live under the OS temp root, which the real
        # filter rejects wholesale — point TEMP_ROOT elsewhere so this exercises
        # the git-root collapsing rather than the temp rule.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(lib, "TEMP_ROOT", os.path.normcase(os.path.join("C:", "nowhere"))):
            repo = os.path.join(tmp, "repo")
            os.makedirs(os.path.join(repo, ".git"))
            os.makedirs(os.path.join(repo, "site"))
            os.makedirs(os.path.join(repo, "tests"))
            loose = os.path.join(tmp, "not-a-repo")
            os.makedirs(loose)
            conn = self._db_with_projects(tmp, [
                repo,                                  # the repo itself
                os.path.join(repo, "site"),            # subdir of the same repo
                os.path.join(repo, "tests"),           # subdir of the same repo
                loose,                                 # not in any repo
                os.path.join(tmp, "scratchpad", "x"),  # junk
            ])
            try:
                self.assertEqual(lib.local_repo_count(conn), 1)
            finally:
                conn.close()

    def test_insert_event_skips_untrackable_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                lib.insert_event(conn, {
                    "ts": 1, "language": "Python", "lines_added": 1, "lines_removed": 0,
                    "bytes_added": 1, "event_type": "write",
                    "project_key": os.path.join(tmp, "scratchpad", "x"),
                })
                # the event still counts; only the "project" is not recorded
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM known_repos").fetchone()[0], 0)
            finally:
                conn.close()

    def test_github_count_wins_over_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                with mock.patch.object(lib, "github_repo_count", return_value=40):
                    self.assertEqual(lib.repo_count(conn), 40)
            finally:
                conn.close()

    def test_falls_back_to_local_when_github_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = lib.init_db(os.path.join(tmp, "events.db"))
            try:
                with mock.patch.object(lib, "github_repo_count", return_value=None), \
                        mock.patch.object(lib, "local_repo_count", return_value=19):
                    self.assertEqual(lib.repo_count(conn), 19)
            finally:
                conn.close()


class TestGithubRepoCount(unittest.TestCase):
    def test_fresh_cache_is_used_without_shelling_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "github-repos.json")
            with open(cache, "w", encoding="utf-8") as f:
                f.write('{"count": 40, "fetched_at": 1000}')
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", cache), \
                    mock.patch("shutil.which", side_effect=AssertionError("must not shell out")):
                self.assertEqual(lib.github_repo_count(now=1001), 40)

    def test_stale_cache_triggers_a_refetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "github-repos.json")
            with open(cache, "w", encoding="utf-8") as f:
                f.write('{"count": 3, "fetched_at": 0}')
            proc = mock.Mock(returncode=0, stdout='{"public":12,"private":28}')
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", cache), \
                    mock.patch("shutil.which", return_value="gh"), \
                    mock.patch("subprocess.run", return_value=proc):
                self.assertEqual(lib.github_repo_count(now=lib.GITHUB_CACHE_TTL + 1), 40)

    def test_returns_none_without_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", os.path.join(tmp, "none.json")), \
                    mock.patch("shutil.which", return_value=None):
                self.assertIsNone(lib.github_repo_count(now=0))

    def test_returns_none_when_gh_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = mock.Mock(returncode=1, stdout="")
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", os.path.join(tmp, "none.json")), \
                    mock.patch.object(lib, "log_error"), \
                    mock.patch("shutil.which", return_value="gh"), \
                    mock.patch("subprocess.run", return_value=proc):
                self.assertIsNone(lib.github_repo_count(now=0))

    def test_a_recent_failure_is_not_retried_or_relogged(self):
        # The syncer runs every ~20s; without a negative cache a logged-out gh
        # would be re-spawned and re-logged each time, burying errors.log.
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "github-repos.json")
            proc = mock.Mock(returncode=1, stdout="")
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", cache), \
                    mock.patch.object(lib, "log_error") as logged, \
                    mock.patch("shutil.which", return_value="gh"), \
                    mock.patch("subprocess.run", return_value=proc) as ran:
                self.assertIsNone(lib.github_repo_count(now=0))
                self.assertIsNone(lib.github_repo_count(now=1))
                self.assertIsNone(lib.github_repo_count(now=lib.GITHUB_FAILURE_TTL - 1))
            self.assertEqual(ran.call_count, 1)
            self.assertEqual(logged.call_count, 1)

    def test_failure_cache_expires_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "github-repos.json")
            failing = mock.Mock(returncode=1, stdout="")
            ok = mock.Mock(returncode=0, stdout='{"public":12,"private":28}')
            with mock.patch.object(lib, "GITHUB_CACHE_PATH", cache), \
                    mock.patch.object(lib, "log_error"), \
                    mock.patch("shutil.which", return_value="gh"):
                with mock.patch("subprocess.run", return_value=failing):
                    self.assertIsNone(lib.github_repo_count(now=0))
                with mock.patch("subprocess.run", return_value=ok):
                    self.assertEqual(
                        lib.github_repo_count(now=lib.GITHUB_FAILURE_TTL + 1), 40
                    )


if __name__ == "__main__":
    unittest.main()
