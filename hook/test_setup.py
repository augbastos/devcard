"""Tests for the setup wizard's pure helpers.

Nothing here provisions anything: the network- and account-touching steps of
`setup.py` are not unit-testable without a Cloudflare account. What IS tested
is the part that silently corrupted installs — argument parsing, version
gates, config substitution and secret-file permissions.
"""
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import setup as wizard


class TestFolderInput(unittest.TestCase):
    """Paths with spaces.

    `paths.split()` turned `C:\\My Projects\\api` into two folders that do not
    exist, and the git hook was then installed nowhere with no error.
    """

    def _ask(self, answers):
        it = iter(answers)
        return mock.patch.object(wizard, "ask", side_effect=lambda _prompt: next(it))

    def test_accepts_a_path_containing_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = os.path.join(tmp, "My Code Projects")
            os.makedirs(spaced)
            with self._ask([spaced, ""]):
                self.assertEqual(wizard.ask_folders(), [spaced])

    def test_accepts_several_folders_one_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a b")
            b = os.path.join(tmp, "c d")
            os.makedirs(a)
            os.makedirs(b)
            with self._ask([a, b, ""]):
                self.assertEqual(wizard.ask_folders(), [a, b])

    def test_strips_quotes_a_shell_paste_leaves_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = os.path.join(tmp, "My Projects")
            os.makedirs(spaced)
            with self._ask([f'"{spaced}"', ""]):
                self.assertEqual(wizard.ask_folders(), [spaced])

    def test_rejects_a_folder_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope")
            with self._ask([missing, ""]):
                self.assertEqual(wizard.ask_folders(), [])

    def test_blank_answer_means_skip(self):
        with self._ask([""]):
            self.assertEqual(wizard.ask_folders(), [])


class TestSubstitute(unittest.TestCase):
    """Config rewriting that fails loudly instead of silently doing nothing."""

    def test_replaces_the_database_id(self):
        toml = 'database_id = "old-value"\n'
        out = wizard.substitute(toml, r'database_id\s*=\s*"[^"]*"',
                                'database_id = "new-value"', "database_id")
        self.assertIn('database_id = "new-value"', out)

    def test_dies_when_the_key_is_missing(self):
        # A silent no-op left the Worker pointed at somebody else's database.
        with self.assertRaises(SystemExit):
            wizard.substitute("nothing here\n", r'database_id\s*=\s*"[^"]*"',
                              'database_id = "x"', "database_id")

    def test_a_value_with_backslashes_is_not_reinterpreted(self):
        # re.sub treats \1 and \g<> in the replacement as group references.
        out = wizard.substitute('GITHUB_USERNAME = "old"\n', r'GITHUB_USERNAME\s*=\s*"[^"]*"',
                                r'GITHUB_USERNAME = "a\1b"', "GITHUB_USERNAME")
        self.assertIn(r'a\1b', out)

    def test_is_idempotent_on_a_second_run(self):
        toml = 'database_id = "old"\n'
        once = wizard.substitute(toml, r'database_id\s*=\s*"[^"]*"',
                                 'database_id = "new"', "database_id")
        twice = wizard.substitute(once, r'database_id\s*=\s*"[^"]*"',
                                  'database_id = "new"', "database_id")
        self.assertEqual(once, twice)


class TestNodeVersionGate(unittest.TestCase):
    def _node(self, stdout, returncode=0):
        return mock.patch.object(
            wizard, "run",
            return_value=mock.Mock(returncode=returncode, stdout=stdout, stderr=""),
        )

    def test_accepts_a_supported_node(self):
        with self._node("v20.11.1\n"):
            self.assertEqual(wizard.check_node_version("node"), "v20.11.1")

    def test_rejects_a_node_below_the_minimum(self):
        with self._node("v16.20.0\n"), self.assertRaises(SystemExit):
            wizard.check_node_version("node")

    def test_rejects_unreadable_output(self):
        with self._node("something else\n"), self.assertRaises(SystemExit):
            wizard.check_node_version("node")

    def test_rejects_a_node_that_will_not_run(self):
        with self._node("", returncode=1), self.assertRaises(SystemExit):
            wizard.check_node_version("node")


class TestSecretFilePermissions(unittest.TestCase):
    def test_token_file_is_owner_only_on_posix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            wizard.write_private(path, "s3cret")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "s3cret")
            if os.name != "nt":
                mode = stat.S_IMODE(os.stat(path).st_mode)
                self.assertEqual(mode, 0o600)

    def test_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "deeper", "token")
            wizard.write_private(path, "x")
            self.assertTrue(os.path.exists(path))

    def test_overwrites_rather_than_appending_on_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            wizard.write_private(path, "first")
            wizard.write_private(path, "second")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "second")


class TestRunIsNotShellInterpreted(unittest.TestCase):
    def test_a_missing_binary_is_reported_not_raised(self):
        result = wizard.run(["definitely-not-a-real-binary-9f2b"])
        self.assertNotEqual(result.returncode, 0)

    def test_arguments_are_passed_as_a_list(self):
        # Shell metacharacters in a folder name must reach the child verbatim.
        out = wizard.run([sys.executable, "-c", "import sys; print(sys.argv[1])", "a & b | c"])
        self.assertEqual(out.stdout.strip(), "a & b | c")


class TestWorkerUrlConfig(unittest.TestCase):
    """The hook's endpoint is local config now, not an edit to tracked source."""

    def setUp(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hook"))

    def test_env_var_wins(self):
        import devcard_lib as lib
        with mock.patch.dict(os.environ, {"DEVCARD_WORKER_URL": "https://env.example/ingest"}):
            self.assertEqual(lib._load_worker_url(), "https://env.example/ingest")

    def test_config_file_is_used_when_there_is_no_env_var(self):
        import devcard_lib as lib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "worker-url")
            with open(path, "w", encoding="utf-8") as f:
                f.write("https://file.example/ingest\n")
            with mock.patch.dict(os.environ, {}, clear=False), \
                    mock.patch.object(lib, "WORKER_URL_PATH", path):
                os.environ.pop("DEVCARD_WORKER_URL", None)
                self.assertEqual(lib._load_worker_url(), "https://file.example/ingest")

    def test_falls_back_to_the_compiled_in_default(self):
        import devcard_lib as lib
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(lib, "WORKER_URL_PATH", os.path.join(tmp, "absent")):
                os.environ.pop("DEVCARD_WORKER_URL", None)
                self.assertEqual(lib._load_worker_url(), lib.DEFAULT_INGEST_URL)


if __name__ == "__main__":
    unittest.main()
