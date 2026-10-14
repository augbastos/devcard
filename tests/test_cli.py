"""`devcard init`, `render`, `status`, the version floors, and a hook publishing on its own."""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import unittest
from unittest import mock

from devcard import cli, config, publish
from devcard._hook import lib

from .helpers import Home, TempDirTest, edit, git

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fake_run(cmd):
    """No gh on this pretend machine; git is real."""
    if os.path.basename(cmd[0]).startswith("gh"):
        return subprocess.CompletedProcess(cmd, 1, "", "not logged in")
    return cli._run(cmd)


def init(argv, answers=()):
    args = cli.build_parser().parse_args(["init", *argv])
    it = iter(answers)
    lines = []
    code = cli.Init(args, ask=lambda _p: next(it), run=fake_run, out=lines.append).main()
    return code, "\n".join(lines)


class InitTest(TempDirTest):
    def capture(self, mode):
        args = cli.build_parser().parse_args(["init", "--yes", "--mode", mode])
        return cli.Init(args, out=lambda _line: None).capture()

    def test_switch_claude_to_git_removes_only_the_claude_capture_hook(self):
        with Home(self.tmp, "a"):
            other = {"matcher": "Edit", "hooks": [{"type": "command", "command": "other-hook"}]}
            with open(cli.SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump({"hooks": {"PostToolUse": [other]}, "other-setting": True}, f)
            self.capture("claude")
            self.capture("git")
            with open(cli.SETTINGS_PATH, encoding="utf-8") as f:
                settings = json.load(f)
            self.assertEqual(settings["hooks"]["PostToolUse"], [other])
            self.assertTrue(settings["other-setting"])

    def test_switch_git_to_claude_reactivates_one_capture_hook_and_silences_git(self):
        import devcard_git_hook as githook

        with Home(self.tmp, "a"), mock.patch.object(githook, "MODE_PATH", cli.MODE_PATH):
            # Round trip: the old Claude entry must be removed, then installed once.
            self.capture("claude")
            self.capture("git")
            with open(cli.SETTINGS_PATH, encoding="utf-8") as f:
                self.assertNotIn("devcard_capture", f.read())
            self.capture("claude")
            self.assertEqual(githook.capture_mode(), "claude")
            with mock.patch.object(githook.lib, "init_db") as db:
                githook.main()
                db.assert_not_called()
            with open(cli.SETTINGS_PATH, encoding="utf-8") as f:
                settings = json.load(f)
            commands = [h["command"] for e in settings["hooks"]["PostToolUse"] for h in e["hooks"]]
            self.assertEqual(sum("devcard_capture" in c for c in commands), 1)

    def test_claude_mode_end_to_end(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a") as home:
            home.add_events([edit(int(time.time()) - 60, "Python", 42)])
            code, out = init(["--yes", "--user", "octo-cat", "--repo", "octo-cat/octo-cat",
                              "--remote", remote, "--mode", "claude"])
            self.assertEqual(code, 0)
            with open(cli.SETTINGS_PATH, encoding="utf-8") as f:
                settings = json.load(f)
            with open(cli.MODE_PATH, encoding="utf-8") as f:
                self.assertEqual(f.read(), "claude")
            saved = config.load()
        command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertIn("devcard_capture.py", command)
        self.assertTrue(os.path.exists(command.split('"')[3]))
        self.assertEqual(saved["repo"], "octo-cat/octo-cat")
        self.assertEqual(saved["remote"], remote)
        self.assertIn('srcset="https://raw.githubusercontent.com/octo-cat/octo-cat/devcard-data/card-dark.svg"', out)
        self.assertIn('src="https://raw.githubusercontent.com/octo-cat/octo-cat/devcard-data/card.svg"', out)
        self.assertIn(">42<", git(remote, "show", f"{publish.BRANCH}:card.svg"))

    def test_git_mode_installs_the_post_commit_hook(self):
        project = os.path.join(self.tmp, "project")
        subprocess.run(["git", "init", "-q", project], check=True)
        with Home(self.tmp, "a"):
            code, _ = init(["--yes", "--user", "octo-cat", "--repo", "octo-cat/cards", "--remote",
                            self.bare_remote(), "--mode", "git", "--git-folder", project])
            self.assertEqual(code, 0)
        hook = os.path.join(project, ".git", "hooks", "post-commit")
        with open(hook, encoding="utf-8") as f:
            self.assertIn("devcard_git_hook.py", f.read())

    def test_interactive_answers(self):
        with Home(self.tmp, "a"):
            code, out = init(["--remote", self.bare_remote()],
                             answers=["octo-cat", "", "1", "n"])
            self.assertEqual(code, 0)
            self.assertEqual(config.load()["repo"], "octo-cat/octo-cat")  # the profile repo default
        self.assertNotIn("published", out)

    def test_rejects_a_bad_repository_name(self):
        with Home(self.tmp, "a"), self.assertRaises(SystemExit):
            init(["--yes", "--user", "octo-cat", "--repo", "not a repo", "--mode", "claude"])


class CommandsTest(TempDirTest):
    def test_render_command(self):
        out = os.path.join(self.tmp, "out")
        with Home(self.tmp, "a") as home, contextlib.redirect_stdout(io.StringIO()):
            home.add_events([edit(int(time.time()) - 60)])
            with mock.patch.object(lib, "repo_count", lambda _c: 1):
                self.assertEqual(cli.main(["render", "--out", out, "--user", "octo-cat", "--layout", "wide"]), 0)
        with open(os.path.join(out, "card.svg"), encoding="utf-8") as f:
            self.assertIn('width="840"', f.read())

    def test_status_without_config(self):
        with Home(self.tmp, "a"), contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cli.main(["status"]), 1)
        self.assertIn("devcard init", buf.getvalue())

    def test_the_waiter_exits_quietly_without_a_config(self):
        with Home(self.tmp, "a"):
            self.assertEqual(cli.main(["publish", "--when-due"]), 0)
            self.assertFalse(os.path.exists(config.pending_path()))

    def test_publish_command_reports_failure_with_exit_1(self):
        with Home(self.tmp, "a"), contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cli.main(["publish", "--force"]), 1)
        self.assertIn("devcard init", buf.getvalue())


class DocumentationTest(unittest.TestCase):
    def test_serverless_freshness_uses_publish_cadence_and_raw_cache_only(self):
        for name in ("serverless.md", "limitations.md"):
            with self.subTest(name=name), open(os.path.join(ROOT, "docs", name), encoding="utf-8") as f:
                text = f.read()
                self.assertIn("15 minutes", text)
                self.assertIn("5 minutes", text)
                self.assertIn("max-age=300", text)
                self.assertNotIn("however long GitHub's image proxy", text)
                self.assertNotIn("renders README images through its image proxy", text)
                self.assertIn("not proxied", text)


class VersionFloorTest(unittest.TestCase):
    def test_every_python_floor_agrees(self):
        sys.path.insert(0, ROOT)
        import install

        self.assertEqual(cli.MIN_PYTHON, install.MIN_PYTHON)
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            project = tomllib.load(f)["project"]
        self.assertEqual(project["requires-python"], ">={}.{}".format(*cli.MIN_PYTHON))

    def test_the_package_ships_every_hook_module(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            modules = set(tomllib.load(f)["tool"]["setuptools"]["py-modules"])
        on_disk = {name[:-3] for name in os.listdir(os.path.join(ROOT, "hook"))
                   if name.endswith(".py") and not name.startswith("test_")}
        self.assertEqual(modules, on_disk)

    def test_the_package_ships_the_data_files_it_reads(self):
        # prices.json (usage cost) and the dashboard page are read at run time; a pipx
        # install only has them if package-data names them.
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            patterns = tomllib.load(f)["tool"]["setuptools"]["package-data"]["devcard"]
        self.assertIn("prices.json", patterns)
        self.assertIn("dashboard/*", patterns)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "devcard", "prices.json")))
        self.assertTrue(os.path.exists(os.path.join(ROOT, "devcard", "dashboard", "index.html")))


class HookPublishesTest(TempDirTest):
    """A real commit, a real git hook process started with `-S`, a real push."""

    def test_a_commit_publishes_the_card(self):
        remote = self.bare_remote()
        home = os.path.join(self.tmp, "home")
        devcard_home = os.path.join(home, ".claude", "devcard")
        os.makedirs(devcard_home)
        with open(os.path.join(devcard_home, "config.json"), "w", encoding="utf-8") as f:
            json.dump({**config.DEFAULTS, "github_user": "octo-cat", "repo": "octo-cat/octo-cat",
                       "remote": remote, "avatar": False}, f)
        project = os.path.join(self.tmp, "project")
        subprocess.run(["git", "init", "-q", project], check=True)
        with open(os.path.join(project, "app.py"), "w", encoding="utf-8") as f:
            f.write("print(1)\nprint(2)\nprint(3)\n")
        # No GitHub token reaches the hook: `gh` must fail offline, not ask the API.
        inherited = {k: v for k, v in os.environ.items() if not k.startswith(("GH_", "GITHUB_"))}
        # What git exports to a post-commit hook. Publishing must not follow it
        # into the project: it works in its own bare repository.
        git_dir = os.path.join(project, ".git")
        env = {**inherited, "HOME": home, "USERPROFILE": home, "DEVCARD_WORKER_URL": "",
               "GIT_DIR": git_dir, "GIT_INDEX_FILE": os.path.join(git_dir, "index"),
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
               "XDG_CONFIG_HOME": os.path.join(home, ".config")}
        subprocess.run(["git", "-C", project, "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", project, "commit", "-q", "-m", "x"], check=True, env=env)
        project_refs = git(project, "for-each-ref")
        hook = os.path.join(ROOT, "hook", "devcard_git_hook.py")
        subprocess.run([sys.executable, "-S", hook], cwd=project, env=env, check=True, timeout=120)

        card = git(remote, "show", f"{publish.BRANCH}:card.svg")
        self.assertIn(">3<", card)
        self.assertEqual(git(project, "for-each-ref"), project_refs)
        self.assertEqual(git(project, "remote"), "")
        machines = git(remote, "ls-tree", "--name-only", f"{publish.BRANCH}:machines")
        self.assertRegex(machines, re.compile(r"^[0-9a-f]{32}\.json$"))
        errors = os.path.join(devcard_home, "errors.log")
        if os.path.exists(errors):
            with open(errors, encoding="utf-8") as f:
                self.assertNotIn("publish", f.read())


if __name__ == "__main__":
    unittest.main()
