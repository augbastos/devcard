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

    def test_publish_command_reports_failure_with_exit_1(self):
        with Home(self.tmp, "a"), contextlib.redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(cli.main(["publish", "--force"]), 1)
        self.assertIn("devcard init", buf.getvalue())


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
        env = {**inherited, "HOME": home, "USERPROFILE": home, "DEVCARD_WORKER_URL": "",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
               "XDG_CONFIG_HOME": os.path.join(home, ".config")}
        subprocess.run(["git", "-C", project, "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", project, "commit", "-q", "-m", "x"], check=True, env=env)
        hook = os.path.join(ROOT, "hook", "devcard_git_hook.py")
        subprocess.run([sys.executable, "-S", hook], cwd=project, env=env, check=True, timeout=120)

        card = git(remote, "show", f"{publish.BRANCH}:card.svg")
        self.assertIn(">3<", card)
        machines = git(remote, "ls-tree", "--name-only", f"{publish.BRANCH}:machines")
        self.assertRegex(machines, re.compile(r"^[0-9a-f]{32}\.json$"))
        errors = os.path.join(devcard_home, "errors.log")
        if os.path.exists(errors):
            with open(errors, encoding="utf-8") as f:
                self.assertNotIn("publish", f.read())


if __name__ == "__main__":
    unittest.main()
