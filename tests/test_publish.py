"""`devcard render` and `devcard publish`, against temporary local bare repositories only."""
import getpass
import json
import os
import socket
import time
import unittest
from unittest import mock

from devcard import config, publish
from devcard._hook import lib

from .helpers import PROJECT, Home, TempDirTest, edit, git

NOW = 1760000000
REAL_FETCH_AVATAR = publish.fetch_avatar  # Home() stubs it out; these tests exercise it


def cfg_for(remote, **extra):
    return {**config.DEFAULTS, "github_user": "octo-cat", "repo": "octo-cat/octo-cat",
            "remote": remote, "avatar": False, **extra}


def run(cfg, now=NOW, force=False):
    return publish.publish(cfg, now=now, force=force, repo_count_fn=lambda _conn: 9)


class RenderTest(TempDirTest):
    def test_render_writes_a_light_and_a_dark_file(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 3600, "Python", 120), edit(NOW - 7200, "Rust", 30)])
            out = os.path.join(self.tmp, "out")
            paths = publish.render_local(cfg_for(""), out, now=NOW, repo_count_fn=lambda _c: 9)
        self.assertEqual(sorted(os.path.basename(p) for p in paths), ["card-dark.svg", "card.svg"])
        with open(os.path.join(out, "card.svg"), encoding="utf-8") as f:
            light = f.read()
        with open(os.path.join(out, "card-dark.svg"), encoding="utf-8") as f:
            dark = f.read()
        for svg in (light, dark):
            self.assertTrue(svg.startswith("<svg"))
            self.assertIn(">150<", svg)
            self.assertIn("9 repos", svg)
            # One look per file: GitHub's <picture> chooses, not the viewer's OS.
            self.assertNotIn("prefers-color-scheme", svg)
            # A static file cannot say "5min ago" truthfully for long.
            self.assertNotIn(" ago", svg)
            self.assertIn("updated 2025-10-09", svg)
            self.assertNotIn("acme-secret-client", svg)
        self.assertIn(".bg{fill:#ffffff}", light)
        self.assertIn(".bg{fill:#0f1117}", dark)


class PublishTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.remote = self.bare_remote()

    def tree(self):
        return sorted(git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH).splitlines())

    def show(self, name):
        return git(self.remote, "show", f"{publish.BRANCH}:{name}")

    def test_first_publish_creates_the_orphan_branch(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 40)])
            self.assertEqual(run(cfg_for(self.remote), force=True), "published")
            machine = lib.read_source_id()
        self.assertEqual(self.tree(), ["README.md", "card-dark.svg", "card.svg", f"machines/{machine}.json"])
        # One root commit, made under devcard's own identity — never user@hostname.
        self.assertEqual(git(self.remote, "rev-list", "--count", publish.BRANCH), "1")
        self.assertEqual(git(self.remote, "log", "-1", "--format=%P", publish.BRANCH), "")
        self.assertEqual(git(self.remote, "log", "-1", "--format=%an <%ae>", publish.BRANCH),
                         "devcard <devcard@devcard.invalid>")
        self.assertIn(">40<", self.show("card.svg"))

    def test_a_fresh_machine_keeps_one_file(self):
        """The first publish creates the database; that must not cost the machine its id."""
        with Home(self.tmp, "fresh") as home:
            run(cfg_for(self.remote), force=True)
            home.add_events([edit(NOW + 10)])
            run(cfg_for(self.remote), now=NOW + 60, force=True)
            machine = lib.read_source_id()
        self.assertEqual([n for n in self.tree() if n.startswith("machines/")], [f"machines/{machine}.json"])

    def test_debounced_unchanged_and_republished(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60)])
            cfg = cfg_for(self.remote)
            self.assertEqual(run(cfg, force=True), "published")
            head = git(self.remote, "rev-parse", publish.BRANCH)

            self.assertEqual(run(cfg, now=NOW + 60), "skipped")
            self.assertEqual(run(cfg, now=NOW + 120, force=True), "unchanged")
            self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

            home.add_events([edit(NOW + 300, "Go", 25)])
            # The forced check at +120s counts: the next is due 15 minutes after it.
            self.assertEqual(run(cfg, now=NOW + 120 + 14 * 60), "skipped")
            self.assertEqual(run(cfg, now=NOW + 120 + 15 * 60), "published")
        self.assertNotEqual(git(self.remote, "rev-parse", publish.BRANCH), head)
        self.assertEqual(git(self.remote, "rev-list", "--count", publish.BRANCH), "1")
        self.assertIn(">35<", self.show("card.svg"))

    def test_unchanged_data_keeps_its_timestamp(self):
        """updated_at moves only when the numbers do, so an idle machine pushes nothing."""
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60)])
            cfg = cfg_for(self.remote)
            run(cfg, force=True)
            machine = lib.read_source_id()
            self.assertEqual(run(cfg, now=NOW + 3600), "unchanged")
        self.assertEqual(json.loads(self.show(f"machines/{machine}.json"))["updated_at"], NOW)

    def test_machine_file_holds_aggregates_only(self):
        with Home(self.tmp, "a") as home:
            home.add_events([
                {**edit(NOW - 60, "Python", 12), "project_key": PROJECT},
                {"ts": NOW - 30, "language": None, "lines_added": 0, "event_type": "commit"},
            ])
            run(cfg_for(self.remote), force=True)
            machine = lib.read_source_id()
        raw = self.show(f"machines/{machine}.json")
        agg = json.loads(raw)
        self.assertEqual(set(agg), {"format", "languages", "event_types", "days", "bytes", "events",
                                    "first_ts", "repo_count", "updated_at"})
        self.assertEqual(agg["languages"], {"Python": 12})
        self.assertEqual(agg["event_types"], {"commit": 1, "edit": 1})
        everything = raw + "".join(self.show(name) for name in self.tree() if name != f"machines/{machine}.json")
        for secret in ("acme-secret-client", "/home/someone/work", socket.gethostname(), getpass.getuser()):
            if len(secret) >= 5:
                self.assertNotIn(secret, everything, secret)

    def test_two_machines_sum_and_keep_each_others_files(self):
        with Home(self.tmp, "laptop") as laptop:
            laptop.add_events([edit(NOW - 60, "Python", 100)])
            run(cfg_for(self.remote), force=True)
            laptop_id = lib.read_source_id()
        with Home(self.tmp, "desktop") as desktop:
            desktop.add_events([edit(NOW - 30, "Rust", 50), edit(NOW - 20, "Python", 1)])
            self.assertEqual(run(cfg_for(self.remote), now=NOW + 10, force=True), "published")
            desktop_id = lib.read_source_id()
        self.assertNotEqual(laptop_id, desktop_id)
        self.assertEqual(self.tree(), sorted(["README.md", "card-dark.svg", "card.svg",
                                              f"machines/{laptop_id}.json", f"machines/{desktop_id}.json"]))
        card = self.show("card.svg")
        self.assertIn(">151<", card)
        self.assertIn("9 repos", card)  # the same account seen twice, not 18

        with Home(self.tmp, "laptop") as laptop:
            laptop.add_events([edit(NOW + 100, "Python", 9)])
            run(cfg_for(self.remote), now=NOW + 200, force=True)
        self.assertIn(f"machines/{desktop_id}.json", self.tree())
        self.assertIn(">160<", self.show("card.svg"))
        self.assertEqual(json.loads(self.show(f"machines/{desktop_id}.json"))["languages"],
                         {"Python": 1, "Rust": 50})

    def test_a_rejected_lease_is_retried_on_top_of_the_new_head(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60)])
            real_push = publish._Repo.push
            calls = []

            def flaky(repo, commit, expected):
                calls.append(expected)
                if len(calls) == 1:
                    return False, "stale info"
                return real_push(repo, commit, expected)

            with mock.patch.object(publish._Repo, "push", flaky):
                self.assertEqual(run(cfg_for(self.remote), force=True), "published")
        self.assertEqual(len(calls), 2)

    def test_a_stale_lease_never_overwrites(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60)])
            run(cfg_for(self.remote), force=True)
            head = git(self.remote, "rev-parse", publish.BRANCH)
            repo = publish._Repo(os.path.join(config.publish_dir(), "octo-cat__octo-cat"), self.remote)
            tree = repo.write_tree({"x.txt": b"x"})
            ok, _ = repo.push(repo.commit(tree, NOW), expected="0" * 40)
        self.assertFalse(ok)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_an_unreachable_remote_fails_and_waits_out_the_interval(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60)])
            cfg = cfg_for(os.path.join(self.tmp, "does-not-exist.git"))
            with self.assertRaises(publish.PublishError):
                run(cfg, force=True)
            # Recorded, so hooks firing every 20 seconds do not retry git each time.
            self.assertEqual(run(cfg, now=NOW + 60), "skipped")

    def test_unconfigured_publish_refuses(self):
        with Home(self.tmp, "a"):
            with self.assertRaises(publish.PublishError):
                publish.publish({**config.DEFAULTS}, now=NOW, force=True)


class HookIntegrationTest(TempDirTest):
    def test_auto_publish_does_nothing_without_a_config(self):
        with Home(self.tmp, "a"):
            self.assertFalse(lib.publish_configured())
            self.assertIsNone(lib.auto_publish())

    def test_auto_publish_publishes_once_configured(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a") as home:
            home.add_events([edit(int(time.time()) - 60)])
            config.save(cfg_for(remote))
            with mock.patch.object(lib, "repo_count", lambda _conn: 3):
                self.assertEqual(lib.auto_publish(), "published")
                self.assertEqual(lib.auto_publish(), "skipped")
        self.assertIn("3 repos", git(remote, "show", f"{publish.BRANCH}:card.svg"))

    def test_auto_publish_logs_instead_of_raising(self):
        with Home(self.tmp, "a") as home:
            config.save(cfg_for(os.path.join(self.tmp, "missing.git")))
            with mock.patch.object(lib, "repo_count", lambda _conn: 0):
                self.assertIsNone(lib.auto_publish())
            with open(home.paths[(lib, "ERROR_LOG_PATH")], encoding="utf-8") as f:
                self.assertIn("devcard publish", f.read())

    def test_sync_is_silent_on_a_serverless_machine(self):
        """No Worker URL is the normal state here, not an error worth logging hourly."""
        with Home(self.tmp, "a") as home:
            config.save(cfg_for(self.bare_remote()))
            conn = lib.init_db()
            try:
                self.assertFalse(lib.sync_pending(conn))
            finally:
                conn.close()
            self.assertFalse(os.path.exists(home.paths[(lib, "ERROR_LOG_PATH")]))


class AvatarTest(TempDirTest):
    def test_fetched_once_then_cached(self):
        class Resp:
            headers = {"Content-Type": "image/png"}

            def read(self, _n):
                return b"PNG"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with Home(self.tmp, "a"), mock.patch("urllib.request.urlopen", return_value=Resp()) as fake:
            self.assertEqual(REAL_FETCH_AVATAR("octo-cat", now=NOW), "data:image/png;base64,UE5H")
            self.assertEqual(REAL_FETCH_AVATAR("octo-cat", now=NOW + 60), "data:image/png;base64,UE5H")
        self.assertEqual(fake.call_count, 1)

    def test_a_failure_renders_without_one(self):
        with Home(self.tmp, "a"), mock.patch("urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(REAL_FETCH_AVATAR("octo-cat", now=NOW))


if __name__ == "__main__":
    unittest.main()
