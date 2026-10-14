"""`devcard render` and `devcard publish`, against temporary local bare repositories only."""
import getpass
import json
import os
import socket
import time
import unittest
import xml.etree.ElementTree as ET
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


class BranchGuardTest(TempDirTest):
    """Exercise the publish guard without unrelated SQLite or git subprocesses."""

    def attempt(self, names, *, default=False, parent=False, marker=b'{"format": 1}', mode=b"100644"):
        repo = publish._Repo(self.tmp, "local")

        def git_output(*args, **kwargs):
            if args[0] == "ls-remote":
                body = f"ref: {publish.REF}\tHEAD\n".encode() if default else b""
            elif args[:2] == ("cat-file", "-p"):
                body = b"tree " + b"a" * 40 + (b"\nparent " + b"b" * 40 if parent else b"") + b"\n\nmessage"
            elif args[0] == "ls-tree":
                body = b"".join(mode + b" blob " + b"a" * 40 + b"\t" + name.encode() + b"\0" for name in names)
            elif args[:2] == ("cat-file", "blob") and args[2].endswith(":.devcard"):
                body = marker
            else:
                self.fail(f"unexpected git fixture command: {args}")
            return mock.Mock(stdout=body, stderr=b"", returncode=0)

        repo.git = mock.Mock(side_effect=git_output)
        repo.ensure = mock.Mock()
        repo.fetch_head = mock.Mock(return_value="head")
        repo.machine_files = mock.Mock(return_value={})
        repo.write_tree = mock.Mock(return_value="tree")
        repo.tree_of = mock.Mock(return_value="old-tree")
        repo.commit = mock.Mock(return_value="new-head")
        repo.push = mock.Mock(return_value=(True, ""))
        aggregate = {"format": 1, "languages": {}, "event_types": {}, "days": {},
                     "bytes": 0, "events": 0, "first_ts": None, "repo_count": 0, "updated_at": NOW}
        with Home(self.tmp, "a"), mock.patch.object(publish, "_Repo", return_value=repo), \
                mock.patch.object(publish, "local_aggregate", return_value=aggregate), \
                mock.patch.object(lib, "source_id", return_value="test-machine"):
            with self.assertRaises(publish.PublishError):
                run(cfg_for("local"), force=True)
        repo.write_tree.assert_not_called()
        repo.commit.assert_not_called()
        repo.push.assert_not_called()

    def test_unmarked_branch_never_reaches_a_write(self):
        self.attempt(["card.svg", "card-dark.svg"])

    def test_foreign_files_never_reach_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg", "important.txt"])

    def test_default_branch_never_reaches_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg"], default=True)

    def test_foreign_history_never_reaches_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg"], parent=True)

    def test_symlinks_never_reach_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg"], mode=b"120000")

    def test_invalid_marker_never_reaches_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg"], marker=b'{"format": true}')


class PublishTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.remote = self.bare_remote()

    def tree(self):
        return sorted(git(self.remote, "ls-tree", "-r", "--name-only", publish.BRANCH).splitlines())

    def show(self, name):
        return git(self.remote, "show", f"{publish.BRANCH}:{name}")

    def seed(self, files, parent=None):
        repo = publish._Repo(os.path.join(self.tmp, "seed.git"), self.remote)
        repo.ensure()
        tree = repo.write_tree(files)
        if parent:
            repo.git("fetch", "-q", "origin", publish.REF)
            commit = repo.out("commit-tree", tree, "-p", parent, "-m", "test",
                              env=publish.AUTHOR_ENV)
        else:
            commit = repo.commit(tree, NOW)
        ok, detail = repo.push(commit, parent)
        self.assertTrue(ok, detail)
        return commit

    def owned_files(self):
        return {".devcard": b'{"format": 1}\n', "card.svg": b"<svg/>", "card-dark.svg": b"<svg/>"}

    def test_refuses_an_unmarked_existing_branch(self):
        head = self.seed({"card.svg": b"someone else's card"})
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "not owned by devcard"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_refuses_foreign_files_even_with_a_marker(self):
        head = self.seed({**self.owned_files(), "important.txt": b"keep me"})
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "not owned by devcard"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_refuses_an_unsupported_marker_version(self):
        head = self.seed({**self.owned_files(), ".devcard": b'{"format": 99}\n'})
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "not owned by devcard"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_refuses_the_default_branch_even_when_owned(self):
        head = self.seed(self.owned_files())
        git(self.remote, "symbolic-ref", "HEAD", publish.REF)
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "default branch"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_refuses_to_erase_foreign_history_under_an_owned_tip(self):
        parent = self.seed({"important.txt": b"history must survive"})
        head = self.seed(self.owned_files(), parent=parent)
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "root commit"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_debounce_rereads_state_after_taking_the_lock(self):
        real_enter = publish._Lock.__enter__

        def racing_enter(lock):
            publish._write_json(config.state_path(), {"last_check": NOW, "last_push": NOW - 1})
            return real_enter(lock)

        with Home(self.tmp, "a"), mock.patch.object(publish._Lock, "__enter__", racing_enter), \
                mock.patch.object(publish, "local_aggregate") as aggregate:
            self.assertEqual(run(cfg_for(self.remote)), "skipped")
            aggregate.assert_not_called()
            self.assertEqual(publish._read_json(config.state_path())["last_push"], NOW - 1)

    def test_invalid_remote_files_warn_and_do_not_break_rendering(self):
        files = self.owned_files()
        valid = {"format": 1, "languages": {"Rust": 5}, "event_types": {}, "days": {},
                 "bytes": 0, "events": 1, "first_ts": NOW, "repo_count": 1, "updated_at": NOW}
        files["machines/good.json"] = json.dumps(valid).encode()
        files["machines/future.json"] = json.dumps({**valid, "first_ts": 10**100}).encode()
        files["machines/control.json"] = json.dumps({**valid, "languages": {"bad\u0001": 999}}).encode()
        files["machines/broken.json"] = b"{"
        self.seed(files)
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 7)])
            with self.assertWarnsRegex(RuntimeWarning, "aggregate"):
                self.assertEqual(run(cfg_for(self.remote), force=True), "published")
        svg = self.show("card.svg")
        ET.fromstring(svg)
        self.assertIn(">12<", svg)
        for name, body in files.items():
            if name.startswith("machines/"):
                self.assertEqual(self.show(name), body.decode())

    def test_first_publish_creates_the_orphan_branch(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 40)])
            self.assertEqual(run(cfg_for(self.remote), force=True), "published")
            machine = lib.read_source_id()
        self.assertEqual(self.tree(), [".devcard", "README.md", "card-dark.svg", "card.svg", f"machines/{machine}.json"])
        self.assertEqual(json.loads(self.show(".devcard")), {"format": 1})
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

    def test_invalid_previous_timestamp_is_replaced_instead_of_reused(self):
        with Home(self.tmp, "a") as home:
            home.add_events([edit(NOW - 60, "Python", 7)])
            run(cfg_for(self.remote), force=True)
            machine = lib.read_source_id()
            old = json.loads(self.show(f"machines/{machine}.json"))
            head = git(self.remote, "rev-parse", publish.BRANCH)
            repo = publish._Repo(os.path.join(config.publish_dir(), "octo-cat__octo-cat"), self.remote)
            files = {name: repo.git("cat-file", "blob", f"{head}:{name}").stdout for name in self.tree()}
            files[f"machines/{machine}.json"] = json.dumps({**old, "updated_at": 10**100}).encode()
            ok, detail = repo.push(repo.commit(repo.write_tree(files), NOW), head)
            self.assertTrue(ok, detail)
            with self.assertWarnsRegex(RuntimeWarning, "aggregate"):
                self.assertEqual(run(cfg_for(self.remote), now=NOW + 60, force=True), "published")
        self.assertEqual(json.loads(self.show(f"machines/{machine}.json"))["updated_at"], NOW + 60)
        ET.fromstring(self.show("card.svg"))

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
        self.assertEqual(self.tree(), sorted([".devcard", "README.md", "card-dark.svg", "card.svg",
                                              f"machines/{laptop_id}.json", f"machines/{desktop_id}.json"]))
        card = self.show("card.svg")
        self.assertIn(">151<", card)
        self.assertIn("9 repos", card)  # the same account seen twice, not 18

        desktop_bytes = self.show(f"machines/{desktop_id}.json")
        with Home(self.tmp, "laptop") as laptop:
            laptop.add_events([edit(NOW + 100, "Python", 9)])
            run(cfg_for(self.remote), now=NOW + 200, force=True)
        # A machine writes its own file only; the other's is carried over as is.
        self.assertEqual(self.show(f"machines/{desktop_id}.json"), desktop_bytes)
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


class RemoteValidationTest(TempDirTest):
    def test_deep_json_and_invalid_timestamps_do_not_break_the_card(self):
        aggregate = {"format": 1, "languages": {"Python": 7}, "event_types": {}, "days": {},
                     "bytes": 0, "events": 1, "first_ts": NOW, "repo_count": 0, "updated_at": NOW}
        repo = mock.Mock()
        repo.fetch_head.return_value = "head"
        repo.machine_files.return_value = {
            "machines/deep.json": b"[" * 2000 + b"]" * 2000,
            "machines/future.json": json.dumps({**aggregate, "first_ts": 10**100}).encode(),
        }
        repo.write_tree.return_value = "tree"
        repo.tree_of.return_value = None
        repo.push.return_value = (True, "")
        with Home(self.tmp, "a"), mock.patch.object(publish, "_Repo", return_value=repo), \
                mock.patch.object(publish, "local_aggregate", return_value=aggregate), \
                mock.patch.object(lib, "source_id", return_value="test-machine"), \
                self.assertWarnsRegex(RuntimeWarning, "aggregate"):
            self.assertEqual(run(cfg_for("local"), force=True), "published")
        files = repo.write_tree.call_args.args[0]
        ET.fromstring(files["card.svg"])
        self.assertIn(b">7<", files["card.svg"])
        self.assertEqual(files["machines/deep.json"], b"[" * 2000 + b"]" * 2000)


class DebounceRaceTest(TempDirTest):
    def test_completed_publish_between_read_and_lock_is_skipped(self):
        real_enter = publish._Lock.__enter__

        def raced_enter(lock):
            publish._write_json(config.state_path(), {"last_check": NOW, "last_push": NOW - 1})
            return real_enter(lock)

        repo = mock.Mock()
        repo.fetch_head.return_value = None
        repo.machine_files.return_value = {}
        repo.write_tree.return_value = "tree"
        repo.tree_of.return_value = None
        repo.push.return_value = (True, "")
        aggregate = {"format": 1, "languages": {}, "event_types": {}, "days": {}, "bytes": 0,
                     "events": 0, "first_ts": None, "repo_count": 0, "updated_at": NOW}
        with Home(self.tmp, "a"), mock.patch.object(publish._Lock, "__enter__", raced_enter), \
                mock.patch.object(publish, "local_aggregate", return_value=aggregate) as aggregate_fn, \
                mock.patch.object(publish, "_Repo", return_value=repo), \
                mock.patch.object(lib, "source_id", return_value="test-machine"):
            self.assertEqual(run(cfg_for("local")), "skipped")
            aggregate_fn.assert_not_called()
            self.assertEqual(publish._read_json(config.state_path())["last_push"], NOW - 1)


class GitIsolationTest(TempDirTest):
    def test_publisher_ignores_global_system_config_hooks_and_signing(self):
        remote = self.bare_remote()
        hooks = os.path.join(self.tmp, "hostile-hooks")
        os.makedirs(hooks)
        sentinel = os.path.join(self.tmp, "hook-ran").replace("\\", "/")
        hook = os.path.join(hooks, "pre-push")
        with open(hook, "w", encoding="utf-8", newline="\n") as f:
            f.write(f'#!/bin/sh\nprintf invoked > "{sentinel}"\nexit 1\n')
        os.chmod(hook, 0o755)
        global_config = os.path.join(self.tmp, ".gitconfig")
        system_config = os.path.join(self.tmp, "system.gitconfig")
        with open(global_config, "w", encoding="utf-8") as f:
            f.write(f'[core]\n hooksPath = "{hooks.replace(chr(92), "/")}"\n'
                    '[commit]\n gpgSign = true\n[gpg]\n program = nonexistent-devcard-signer\n'
                    '[devcard]\n globalSentinel = inherited\n')
        with open(system_config, "w", encoding="utf-8") as f:
            f.write('[devcard]\n systemSentinel = inherited\n')
        env = {"GIT_CONFIG_GLOBAL": global_config, "GIT_CONFIG_SYSTEM": system_config,
               "GIT_CONFIG_NOSYSTEM": "0", "GIT_CONFIG_COUNT": "1",
               "GIT_CONFIG_KEY_0": "devcard.injectedSentinel", "GIT_CONFIG_VALUE_0": "inherited",
               "HOME": self.tmp, "USERPROFILE": self.tmp,
               "XDG_CONFIG_HOME": os.path.join(self.tmp, ".config")}
        with Home(self.tmp, "a") as home, mock.patch.dict(os.environ, env):
            home.add_events([edit(NOW - 60)])
            self.assertEqual(run(cfg_for(remote), force=True), "published")
            repo = publish._Repo(os.path.join(config.publish_dir(), "octo-cat__octo-cat"), remote)
            for key in ("devcard.globalSentinel", "devcard.systemSentinel", "devcard.injectedSentinel"):
                self.assertNotEqual(repo.git("config", "--get", key, check=False).returncode, 0)
            self.assertEqual(repo.out("config", "--get", "commit.gpgSign"), "false")
        self.assertFalse(os.path.exists(sentinel))

    def test_git_subprocess_explicitly_disables_external_configuration(self):
        repo = publish._Repo(self.tmp, "local")
        proc = mock.Mock(returncode=0, stdout=b"", stderr=b"")
        with mock.patch.object(publish.subprocess, "run", return_value=proc) as execute:
            repo.git("status")
        env = execute.call_args.kwargs["env"]
        self.assertEqual(env.get("GIT_CONFIG_NOSYSTEM"), "1")
        self.assertEqual(env.get("GIT_CONFIG_GLOBAL"), os.devnull)
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")


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

    def test_a_skipped_publish_leaves_one_waiter(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a") as home, mock.patch.object(publish, "_spawn_waiter") as spawn:
            home.add_events([edit(int(time.time()) - 60)])
            config.save(cfg_for(remote))
            with mock.patch.object(lib, "repo_count", lambda _conn: 3):
                self.assertEqual(publish.auto(), "published")
                spawn.assert_not_called()
                self.assertEqual(publish.auto(), "skipped")
        spawn.assert_called_once_with()

    def test_the_waiter_publishes_when_the_window_closes(self):
        """The last edits of a session must not wait for the next session."""
        remote = self.bare_remote()
        clock = [float(NOW)]
        slept = []

        def sleep(seconds):
            slept.append(seconds)
            clock[0] += seconds

        with Home(self.tmp, "a") as home, mock.patch.object(publish.time, "time", lambda: clock[0]):
            home.add_events([edit(NOW - 60, "Python", 5)])
            config.save(cfg_for(remote))
            with mock.patch.object(lib, "repo_count", lambda _conn: 3):
                self.assertEqual(publish.auto(), "published")
                clock[0] += 600
                home.add_events([edit(int(clock[0]), "Go", 7)])
                self.assertEqual(publish.auto(), "skipped")
                self.assertEqual(publish.when_due(sleep=sleep, clock=lambda: clock[0]), "published")
            self.assertFalse(os.path.exists(config.pending_path()))
        self.assertEqual(slept, [301.0])
        self.assertIn(">12<", git(remote, "show", f"{publish.BRANCH}:card.svg"))

    def test_only_one_waiter_per_machine(self):
        with Home(self.tmp, "a"):
            os.makedirs(os.path.dirname(config.pending_path()), exist_ok=True)
            open(config.pending_path(), "w").close()
            self.assertEqual(publish.when_due(sleep=self.fail), "waiting")

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
