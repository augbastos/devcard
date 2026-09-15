"""Tests for install.py.

Nothing here touches Cloudflare. The pure helpers are tested directly, and the
whole wizard is run end to end against a fake `run` that answers the way npm,
Node and Wrangler do — which is what lets the ordering guarantees (checks
before changes, the secret before its local copy) and the re-run path be pinned
without an account.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "hook"))

import install  # noqa: E402 — imported from the repository root added above

TEMPLATE = os.path.join(ROOT, "worker", "wrangler.example.jsonc")
CI_WORKFLOW = os.path.join(ROOT, ".github", "workflows", "ci.yml")
DB_ID = "3f2a9c1e-8b7d-4e6f-a5c4-1d2e3f4a5b6c"


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TestFolderInput(unittest.TestCase):
    """Paths with spaces.

    `paths.split()` turned `C:\\My Projects\\api` into two folders that do not
    exist, and the git hook was then installed nowhere with no error.
    """

    def _ask(self, answers):
        it = iter(answers)
        return mock.patch.object(install, "ask", side_effect=lambda _prompt: next(it))

    def test_accepts_a_path_containing_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = os.path.join(tmp, "My Code Projects")
            os.makedirs(spaced)
            with self._ask([spaced, ""]):
                self.assertEqual(install.ask_folders(), [spaced])

    def test_accepts_several_folders_one_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a b")
            b = os.path.join(tmp, "c d")
            os.makedirs(a)
            os.makedirs(b)
            with self._ask([a, b, ""]):
                self.assertEqual(install.ask_folders(), [a, b])

    def test_strips_quotes_a_shell_paste_leaves_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            spaced = os.path.join(tmp, "My Projects")
            os.makedirs(spaced)
            with self._ask([f'"{spaced}"', ""]):
                self.assertEqual(install.ask_folders(), [spaced])

    def test_rejects_a_folder_that_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self._ask([os.path.join(tmp, "nope"), ""]):
                self.assertEqual(install.ask_folders(), [])

    def test_blank_answer_means_skip(self):
        with self._ask([""]):
            self.assertEqual(install.ask_folders(), [])


class TestRenderConfig(unittest.TestCase):
    """The deployment config is rendered from the tracked template, never edited in place."""

    def setUp(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            self.template = f.read()

    def test_fills_the_three_deployment_values(self):
        out = install.render_config(self.template, DB_ID, "octo-cat", "America/Argentina/Buenos_Aires")
        self.assertIn(f'"database_id": "{DB_ID}"', out)
        self.assertIn('"GITHUB_USERNAME": "octo-cat"', out)
        self.assertIn('"TIMEZONE": "America/Argentina/Buenos_Aires"', out)

    def test_keeps_everything_else_from_the_template(self):
        out = install.render_config(self.template, DB_ID, "octo-cat", "UTC")
        for kept in ('"name": "card"', '"compatibility_date"', '"crons"', '"binding": "DB"'):
            self.assertIn(kept, out)

    def test_is_deterministic_so_a_rerun_changes_nothing(self):
        once = install.render_config(self.template, DB_ID, "octo-cat", "UTC")
        self.assertEqual(once, install.render_config(self.template, DB_ID, "octo-cat", "UTC"))

    def test_rejects_values_that_could_break_out_of_their_string(self):
        for db_id, user, zone in (
            ('x", "evil": "1', "octo", "UTC"),
            (DB_ID, 'octo", "x', "UTC"),
            (DB_ID, "octo", 'UTC"}'),
            (DB_ID, "-leading-hyphen", "UTC"),
        ):
            with self.assertRaises(SystemExit):
                install.render_config(self.template, db_id, user, zone)

    def test_dies_when_a_key_is_missing(self):
        # A silent no-op left the Worker pointed at somebody else's database.
        with self.assertRaises(SystemExit):
            install.render_config("{}", DB_ID, "octo", "UTC")

    def test_a_value_with_backslashes_is_not_reinterpreted(self):
        # re.sub treats \1 and \g<> in a replacement as group references.
        out = install.substitute('"k": "old"', r'"k"\s*:\s*"[^"]*"', r'"k": "a\1b"', "k")
        self.assertEqual(out, r'"k": "a\1b"')


class TestTemplateIsGeneric(unittest.TestCase):
    """The tracked template must never become somebody's deployment again."""

    def test_carries_placeholders_not_a_real_deployment(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            text = f.read()
        ids = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
        self.assertEqual(set(ids), {"00000000-0000-0000-0000-000000000000"})
        self.assertIn('"GITHUB_USERNAME": "your-github-username"', text)
        self.assertIn('"TIMEZONE": "UTC"', text)

    def test_the_rendered_config_is_gitignored(self):
        result = subprocess.run(
            ["git", "-C", ROOT, "check-ignore", "-q", "worker/wrangler.jsonc"], capture_output=True
        )
        self.assertEqual(result.returncode, 0, "worker/wrangler.jsonc must be gitignored")


class TestVersionFloors(unittest.TestCase):
    """One number each, and CI tests exactly that number."""

    def test_node_floor_comes_from_package_json(self):
        with open(os.path.join(ROOT, "worker", "package.json"), encoding="utf-8") as f:
            engines = json.load(f)["engines"]["node"]
        self.assertEqual(install.min_node(), int(re.search(r"\d+", engines).group(0)))

    def test_ci_runs_the_python_floor(self):
        with open(CI_WORKFLOW, encoding="utf-8") as f:
            ci = f.read()
        floor = ".".join(map(str, install.MIN_PYTHON))
        self.assertRegex(ci, rf'python-version:\s*\[?[^\]\n]*"{re.escape(floor)}"')

    def test_the_readme_states_the_same_floors(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        self.assertIn(f"Python {'.'.join(map(str, install.MIN_PYTHON))}+", readme)
        self.assertIn(f"Node {install.min_node()}+", readme)

    def test_ruff_targets_the_python_floor(self):
        with open(os.path.join(ROOT, "ruff.toml"), encoding="utf-8") as f:
            ruff = f.read()
        self.assertIn('target-version = "py{}{}"'.format(*install.MIN_PYTHON), ruff)

    def test_ci_runs_the_node_floor(self):
        with open(CI_WORKFLOW, encoding="utf-8") as f:
            ci = f.read()
        self.assertRegex(ci, rf'node-version:\s*\[?[^\]\n]*"{install.min_node()}"')


class TestNodeVersionGate(unittest.TestCase):
    def _node(self, stdout, returncode=0):
        return mock.patch.object(install, "run", return_value=_completed(stdout, returncode))

    def test_accepts_the_floor(self):
        with self._node("v22.11.0\n"):
            self.assertEqual(install.check_node_version("node", floor=22), "v22.11.0")

    def test_rejects_a_node_below_the_floor(self):
        with self._node("v20.19.0\n"), self.assertRaises(SystemExit):
            install.check_node_version("node", floor=22)

    def test_rejects_unreadable_output(self):
        with self._node("something else\n"), self.assertRaises(SystemExit):
            install.check_node_version("node", floor=22)

    def test_rejects_a_node_that_will_not_run(self):
        with self._node("", returncode=1), self.assertRaises(SystemExit):
            install.check_node_version("node", floor=22)


class TestDetectTimezone(unittest.TestCase):
    def test_uses_what_node_reports(self):
        with mock.patch.object(install, "run", return_value=_completed("Asia/Kolkata")):
            self.assertEqual(install.detect_timezone("node"), "Asia/Kolkata")

    def test_falls_back_to_utc_on_garbage_or_failure(self):
        for result in (_completed("not a zone; rm -rf"), _completed("", 1), _completed("")):
            with mock.patch.object(install, "run", return_value=result):
                self.assertEqual(install.detect_timezone("node"), "UTC")


class TestSecretFilePermissions(unittest.TestCase):
    def test_token_file_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "devcard", "token")
            install.write_private(path, "s3cret")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "s3cret")
            if os.name == "nt":
                acl = subprocess.run(["icacls", path], capture_output=True, text=True, errors="replace").stdout
                # "(I)" marks an inherited entry; none may survive.
                self.assertNotIn("(I)", acl)
                self.assertIn(os.environ["USERNAME"].lower(), acl.lower())
            else:
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode), 0o700)

    @unittest.skipIf(os.name == "nt", "POSIX mode bits")
    def test_a_rerun_tightens_a_file_that_was_left_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old")
            os.chmod(path, 0o640)  # readable by the group: looser than the installer allows
            install.write_private(path, "new")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_refuses_to_write_a_token_it_could_not_protect(self):
        # The Windows branch, forced so it runs on every platform: icacls failing
        # used to print a warning and write the secret anyway.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            with mock.patch.object(install, "restrict_to_owner_windows", return_value=False), \
                    mock.patch("builtins.print"), self.assertRaises(SystemExit):
                install.write_private(path, "s3cret", windows=True)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "")

    def test_preparing_keeps_an_existing_token(self):
        # prepare_private runs before the secret is rotated, so it must not
        # truncate the token a working installation still depends on.
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            install.write_private(path, "current")
            install.prepare_private(path)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "current")

    def test_overwrites_rather_than_appending_on_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "token")
            install.write_private(path, "first")
            install.write_private(path, "second")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "second")


class TestRunIsNotShellInterpreted(unittest.TestCase):
    def test_a_missing_binary_is_reported_not_raised(self):
        self.assertNotEqual(install.run(["definitely-not-a-real-binary-9f2b"]).returncode, 0)

    def test_arguments_are_passed_as_a_list(self):
        # Shell metacharacters in a folder name must reach the child verbatim.
        out = install.run([sys.executable, "-c", "import sys; print(sys.argv[1])", "a & b | c"])
        self.assertEqual(out.stdout.strip(), "a & b | c")


class TestRegisterClaudeHook(unittest.TestCase):
    CMD = '"/usr/bin/python3" "/src/devcard/hook/devcard_capture.py"'

    def _settings(self, tmp, content=None):
        path = os.path.join(tmp, ".claude", "settings.json")
        if content is not None:
            os.makedirs(os.path.dirname(path))
            with open(path, "w", encoding="utf-8") as f:
                json.dump(content, f)
        return path

    def _entries(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)["hooks"]["PostToolUse"]

    def test_registers_into_a_missing_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp)
            self.assertEqual(install.register_claude_hook(path, self.CMD), "registered")
            self.assertEqual(self._entries(path)[0]["hooks"][0]["command"], self.CMD)

    def test_keeps_other_hooks_and_settings(self):
        other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {"model": "x", "hooks": {"PostToolUse": [other]}})
            install.register_claude_hook(path, self.CMD)
            with open(path, encoding="utf-8") as f:
                settings = json.load(f)
            self.assertEqual(settings["model"], "x")
            self.assertEqual(settings["hooks"]["PostToolUse"][0], other)
            self.assertEqual(len(settings["hooks"]["PostToolUse"]), 2)

    def test_a_second_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {})
            install.register_claude_hook(path, self.CMD)
            with open(path, encoding="utf-8") as f:
                before = f.read()
            self.assertEqual(install.register_claude_hook(path, self.CMD), "unchanged")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), before)

    def test_a_moved_clone_repoints_the_entry_instead_of_adding_one(self):
        # The old path would otherwise stay registered and fail silently.
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {})
            install.register_claude_hook(path, '"python" "/old/place/hook/devcard_capture.py"')
            self.assertEqual(install.register_claude_hook(path, self.CMD), "updated")
            entries = self._entries(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["hooks"][0]["command"], self.CMD)

    def test_keeps_the_first_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._settings(tmp, {"original": True})
            install.register_claude_hook(path, '"python" "/a/devcard_capture.py"')
            install.register_claude_hook(path, self.CMD)
            with open(path + ".devcard-backup", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"original": True})


class TestSmokeTest(unittest.TestCase):
    def _capture(self, status=200, raises=None):
        captured = {}
        resp = mock.MagicMock(status=status)
        resp.__enter__.return_value = resp

        def fake(req, timeout=None):
            if raises:
                raise raises
            captured["req"] = req
            return resp

        return captured, mock.patch("urllib.request.urlopen", side_effect=fake)

    def test_sends_no_repo_count_so_a_rerun_cannot_reset_the_card(self):
        captured, patch = self._capture()
        with patch:
            ok, _ = install.smoke_test("https://card.example", "tok")
        self.assertTrue(ok)
        self.assertEqual(json.loads(captured["req"].data), {"events": []})
        self.assertEqual(captured["req"].get_header("X-devcard-token"), "tok")

    def test_a_failure_is_reported_not_raised(self):
        _, patch = self._capture(raises=OSError("down"))
        with patch:
            ok, detail = install.smoke_test("https://card.example", "tok")
        self.assertFalse(ok)
        self.assertIn("down", detail)


class TestWorkerUrlConfig(unittest.TestCase):
    """The hook's endpoint is local config, and there is no built-in fallback."""

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
            with mock.patch.dict(os.environ, {"DEVCARD_WORKER_URL": ""}), \
                    mock.patch.object(lib, "WORKER_URL_PATH", path):
                self.assertEqual(lib._load_worker_url(), "https://file.example/ingest")

    def test_unconfigured_means_empty_not_somebody_elses_worker(self):
        import devcard_lib as lib
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"DEVCARD_WORKER_URL": ""}), \
                    mock.patch.object(lib, "WORKER_URL_PATH", os.path.join(tmp, "absent")):
                self.assertEqual(lib._load_worker_url(), "")


class FakeToolchain:
    """Answers `run` the way node, npm, git and Wrangler do, and records calls."""

    def __init__(self, token_path, db_exists=False, node_version="v22.11.0", logged_in=True,
                 secret_put_fails=False):
        self.calls = []
        self.token_path = token_path
        self.db_exists = db_exists
        self.node_version = node_version
        self.secret_put_saw_local_token = None
        self.logged_in = logged_in
        self.secret_put_fails = secret_put_fails

    def __call__(self, cmd, cwd=None, capture=True, input_text=None):
        self.calls.append(list(cmd))
        args = cmd[2:] if len(cmd) > 1 and cmd[1] == install.WRANGLER_JS else None
        if cmd[:2] == ["node", "--version"]:
            return _completed(self.node_version + "\n")
        if cmd[:2] == ["node", "-e"]:
            return _completed("Asia/Tokyo")
        if args is None:
            return _completed()  # npm ci, git --version, icacls
        if args == ["whoami", "--json"]:
            return _completed('{"loggedIn": true}', 0 if self.logged_in else 1)
        if args == ["login"]:
            self.logged_in = True
            return _completed()
        if args[:2] == ["d1", "create"]:
            if self.db_exists:
                return _completed("", 1, "A database with that name already exists")
            return _completed(f'{{"d1_databases": [{{"database_id": "{DB_ID}"}}]}}')
        if args[:2] == ["d1", "list"]:
            return _completed(json.dumps([{"name": "devcard", "uuid": DB_ID}]))
        if args == ["deploy"]:
            return _completed("Deployed card\n  https://card.someone.workers.dev\n")
        if args[:2] == ["secret", "put"]:
            self.secret_put_saw_local_token = os.path.exists(self.token_path) and open(
                self.token_path, encoding="utf-8").read()
            self.secret = input_text
            return _completed("", 1, "boom") if self.secret_put_fails else _completed()
        return _completed()


class TestInstallEndToEnd(unittest.TestCase):
    """The whole wizard against a fake toolchain, twice."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="devcard-install-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "devcard-home")
        self.settings = os.path.join(self.tmp, "claude", "settings.json")
        self.config = os.path.join(self.tmp, "wrangler.jsonc")
        wrangler_js = os.path.join(self.tmp, "wrangler.js")
        open(wrangler_js, "w").close()
        for attr, value in (
            ("DEVCARD_HOME", self.home), ("SETTINGS_PATH", self.settings),
            ("CONFIG_PATH", self.config), ("WRANGLER_JS", wrangler_js),
        ):
            patcher = mock.patch.object(install, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, kwargs in (
            ("shutil.which", {"side_effect": lambda name: name}),
            ("urllib.request.urlopen", {"side_effect": self._ok_response}),
        ):
            patcher = mock.patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _ok_response(req, timeout=None):
        resp = mock.MagicMock(status=200)
        resp.__enter__.return_value = resp
        return resp

    def _install(self, fake, answers=("octo-cat", "1")):
        it = iter(answers)
        with mock.patch.object(install, "run", side_effect=fake), \
                mock.patch.object(install, "ask", side_effect=lambda _p: next(it)), \
                mock.patch("builtins.print"):
            return install.main([])

    def _read(self, *parts):
        with open(os.path.join(*parts), encoding="utf-8") as f:
            return f.read()

    def test_provisions_everything_and_a_rerun_converges(self):
        token_path = os.path.join(self.home, "token")
        first = FakeToolchain(token_path)
        self.assertEqual(self._install(first), 0)

        config = self._read(self.config)
        self.assertIn(f'"database_id": "{DB_ID}"', config)
        self.assertIn('"GITHUB_USERNAME": "octo-cat"', config)
        self.assertIn('"TIMEZONE": "Asia/Tokyo"', config)
        self.assertEqual(self._read(self.home, "worker-url"), "https://card.someone.workers.dev/ingest\n")
        self.assertEqual(self._read(self.home, "mode"), "claude")
        self.assertEqual(self._read(token_path), first.secret)
        self.assertFalse(first.secret_put_saw_local_token, "the Worker secret must be set before the local copy")

        wrangler_steps = [c[2] for c in first.calls if len(c) > 2 and c[1] == install.WRANGLER_JS]
        self.assertLess(wrangler_steps.index("deploy"), wrangler_steps.index("secret"))

        # Re-run: the database already exists, the hook is already registered.
        with open(self.settings, encoding="utf-8") as f:
            settings_before = f.read()
        second = FakeToolchain(token_path, db_exists=True)
        self.assertEqual(self._install(second), 0)
        self.assertEqual(self._read(self.config), config)
        with open(self.settings, encoding="utf-8") as f:
            self.assertEqual(f.read(), settings_before)
        self.assertEqual(second.secret_put_saw_local_token, first.secret)
        self.assertEqual(self._read(token_path), second.secret)
        self.assertNotEqual(first.secret, second.secret)

    def test_a_failed_secret_rotation_keeps_the_working_token(self):
        token_path = os.path.join(self.home, "token")
        first = FakeToolchain(token_path)
        self._install(first)
        with self.assertRaises(SystemExit):
            self._install(FakeToolchain(token_path, db_exists=True, secret_put_fails=True))
        self.assertEqual(self._read(token_path), first.secret)

    def test_opens_the_login_when_wrangler_is_logged_out(self):
        fake = FakeToolchain(os.path.join(self.home, "token"), logged_in=False)
        self.assertEqual(self._install(fake), 0)
        wrangler_steps = [c[2:] for c in fake.calls if len(c) > 2 and c[1] == install.WRANGLER_JS]
        self.assertIn(["login"], wrangler_steps)

    def test_a_missing_prerequisite_changes_nothing(self):
        fake = FakeToolchain(os.path.join(self.home, "token"), node_version="v20.19.0")
        with self.assertRaises(SystemExit):
            self._install(fake)
        self.assertFalse(os.path.exists(self.home))
        self.assertFalse(os.path.exists(self.config))
        self.assertFalse(any(len(c) > 1 and c[1] == install.WRANGLER_JS for c in fake.calls))

    def test_the_token_has_exactly_one_local_copy(self):
        # It used to be written into worker/.dev.vars as well: a second
        # plaintext copy, inside the repository folder.
        fake = FakeToolchain(os.path.join(self.home, "token"))
        with mock.patch.object(install, "write_private", wraps=install.write_private) as spy:
            self._install(fake)
        self.assertEqual([c.args[0] for c in spy.call_args_list], [os.path.join(self.home, "token")])
        self.assertNotIn(fake.secret, self._read(self.config))


if __name__ == "__main__":
    unittest.main()
