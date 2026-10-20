"""`devcard render` and `devcard publish`, against temporary local bare repositories only."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import getpass
import io
import json
import os
import socket
import time
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from devcard import cli, config, data, publish, render
from devcard._hook import lib

from .helpers import PROJECT, Home, TempDirTest, edit, git
from .test_cli import init

NOW = 1760000000
REAL_FETCH_AVATAR = publish.fetch_avatar  # Home() stubs it out; these tests exercise it


def cfg_for(remote, **extra):
    return {**config.DEFAULTS, "github_user": "octo-cat", "repo": "octo-cat/octo-cat",
            "remote": remote, "avatar": False,
            "consent": {**data.CORE_CATEGORIES, "repo_count_private": True}, **extra}


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

    def test_foreign_language_files_never_reach_a_write(self):
        for name in ("lang/evil.svg", "lang/sub/0.svg", "lang/body-light.svg", "lang/body-dark-dark.svg",
                     "lang/body.svg.bak", "lang/body.svg\n", "lang/body0.svg", "lang/sub/body.svg"):
            with self.subTest(name=name):
                self.attempt([".devcard", "card.svg", "card-dark.svg", name])

    def test_ownership_allows_only_exact_body_and_slice_names(self):
        names = ["lang/body.svg", "lang/body-dark.svg", "lang/0.svg", "lang/12-dark.svg",
                 "lang/cap-left.svg", "lang/cap-right-dark.svg"]
        for name in names:
            with self.subTest(name=name):
                self.assertIsNotNone(publish.SLICE_PATH_RE.fullmatch(name))

    def test_default_branch_never_reaches_a_write(self):
        self.attempt([".devcard", "card.svg", "card-dark.svg"], default=True)

    def test_badge_ownership_accepts_exactly_the_sixteen_names(self):
        from devcard.badges import BADGE_NAMES

        for name in BADGE_NAMES:
            for suffix in ("", "-dark"):
                self.assertIsNotNone(publish.BADGE_PATH_RE.fullmatch(f"badges/{name}{suffix}.svg"))
        for name in ("badges/evil.svg", "badges/lines.svg.bak", "badges/sub/lines.svg",
                     "badges/lines-dark-dark.svg", "badges/lines.svg\n", "badges/language-light.svg"):
            self.assertIsNone(publish.BADGE_PATH_RE.fullmatch(name))
            self.attempt([".devcard", "card.svg", "card-dark.svg", name])

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

    def test_badges_publish_and_each_revocation_removes_derived_files(self):
        from datetime import date, timedelta
        from .test_badges import GATES, NAMES

        today = date(2025, 10, 9)
        agents = {agent: {**dict.fromkeys(data.AGENT_FIELDS, 0), "lines_added": 10, "active_minutes": 0}
                  for agent in ("claude-code", "codex")}
        agg = {"format": 1, "lines": 1_234_567,
               "languages": {"Python": 40, "Rust": 20, "Go": 20, "Shell": 10, "C": 10},
               "days": {(today - timedelta(days=i)).isoformat(): 1 for i in range(31)}, "agents": agents,
               "usage": [{"date": today.isoformat(), "agent": "claude", "model_family": "claude-opus",
                          "input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 3, "cache_write_tokens": 4,
                          "estimated_cost_usd": None}]}
        cfg = cfg_for(self.remote, stat_badges=True, milestone_badges=True, consent=config.FULL_CONSENT)
        expected = {f"badges/{name}{suffix}.svg" for name in NAMES for suffix in ("", "-dark")}
        with Home(self.tmp, "a"), mock.patch.object(publish, "local_aggregate", return_value=agg):
            self.assertEqual(run(cfg, force=True), "published")
            self.assertEqual({p for p in self.tree() if p.startswith("badges/")}, expected)
            for category, removed in GATES.items():
                revoked = {**cfg, "consent": {**config.FULL_CONSENT, category: False}}
                self.assertEqual(run(revoked, force=True), "published")
                remaining = expected - {f"badges/{name}{suffix}.svg" for name in removed for suffix in ("", "-dark")}
                self.assertEqual({p for p in self.tree() if p.startswith("badges/")}, remaining)
            self.assertEqual(run({**cfg, "stat_badges": False, "milestone_badges": False}, force=True), "published")
            self.assertFalse(any(p.startswith("badges/") for p in self.tree()))

    def test_foreign_badge_on_data_branch_is_refused(self):
        head = self.seed({**self.owned_files(), "badges/x.svg": b"foreign"})
        with Home(self.tmp, "a"), self.assertRaisesRegex(publish.PublishError, "not owned by devcard"):
            run(cfg_for(self.remote), force=True)
        self.assertEqual(git(self.remote, "rev-parse", publish.BRANCH), head)

    def test_accepts_owned_body_files_and_removes_them_when_hover_is_disabled(self):
        self.seed({**self.owned_files(), "lang/body.svg": b"<svg/>", "lang/body-dark.svg": b"<svg/>"})
        with Home(self.tmp, "a"):
            self.assertEqual(run(cfg_for(self.remote), force=True), "published")
        self.assertNotIn("lang/body.svg", self.tree())

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
                if name == "machines/good.json":
                    self.assertEqual(self.show(name), body.decode())
                else:
                    self.assertNotIn(name, self.tree())

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
            # Both opt-in lines on: the file then carries its largest allowed set.
            run({**cfg_for(self.remote), "consent": config.FULL_CONSENT,
                 "card": {"show_agents": True, "show_usage": True}}, force=True)
            machine = lib.read_source_id()
        raw = self.show(f"machines/{machine}.json")
        agg = json.loads(raw)
        self.assertEqual(set(agg), {"format", "languages", "event_types", "days", "bytes", "events",
                                    "first_ts", "repo_count", "updated_at", "agents", "active_minutes", "usage", "lines", "repo_count_private"})
        self.assertEqual(set(agg["agents"]["unknown"]), {"events", "commits", "code_edits", "lines_added",
                                                          "lines_removed", "bytes_added", "active_minutes"})
        self.assertEqual(agg["agents"]["unknown"]["active_minutes"], 2.5)
        self.assertEqual(agg["active_minutes"], {"2025-10-09": {"unknown": 2.5}})
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
        self.assertNotIn("machines/deep.json", files)


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
            with mock.patch.object(lib, "repo_count", lambda _conn, **_kw: 3):
                self.assertEqual(lib.auto_publish(), "published")
                self.assertEqual(lib.auto_publish(), "skipped")
        self.assertIn("3 repos", git(remote, "show", f"{publish.BRANCH}:card.svg"))

    def test_a_skipped_publish_leaves_one_waiter(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a") as home, mock.patch.object(publish, "_spawn_waiter") as spawn:
            home.add_events([edit(int(time.time()) - 60)])
            config.save(cfg_for(remote))
            with mock.patch.object(lib, "repo_count", lambda _conn, **_kw: 3):
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
            with mock.patch.object(lib, "repo_count", lambda _conn, **_kw: 3):
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
            with mock.patch.object(lib, "repo_count", lambda _conn, **_kw: 0):
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


def settings(remote="", consent=None):
    return {**config.DEFAULTS, "repo": "octo-cat/cards", "github_user": "octo-cat",
            "remote": remote, "avatar": False,
            "consent": config.NO_CONSENT if consent is None else consent}


def allow(*categories):
    return {**config.NO_CONSENT, **dict.fromkeys(categories, True)}


class ConsentTest(TempDirTest):
    def seed(self, home):
        home.add_events([{**edit(NOW - 60, "Python", 23456), "agent": "codex"},
                         {**edit(NOW - 50, "Rust", 1234), "agent": "claude-code"}])
        import devcard_usage

        conn = lib.init_db()
        devcard_usage.ensure_usage_schema(conn)
        conn.execute("INSERT INTO usage_aggregates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("2025-10-09", "codex", "gpt", 98765, 5678, 4321, 123, "19.8765", 0, 1))
        conn.commit()
        conn.close()

    def test_default_none_and_malformed_consents_fail_closed(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            conn = lib.init_db()
            try:
                for consent in (None, {}, "all", [True], dict.fromkeys(config.CONSENT_CATEGORIES, "true")):
                    self.assertEqual(data.aggregate(conn, NOW, consent=consent), {"format": 1})
            finally:
                conn.close()
            for cfg in (settings(), {k: v for k, v in settings().items() if k != "consent"}):
                with mock.patch.object(publish, "_Repo") as repo, self.assertRaisesRegex(publish.PublishError, "consent"):
                    publish.publish(cfg, now=NOW, force=True)
                repo.assert_not_called()

    def test_each_category_is_the_only_data_in_serialized_bytes(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            for category, fields in data.CATEGORY_FIELDS.items():
                with self.subTest(category=category):
                    cfg = settings(consent=allow(category))
                    agg = publish.local_aggregate(cfg, NOW, repo_count_fn=lambda _c: 37)
                    raw = publish.encode_aggregate(agg)
                    self.assertTrue(set(agg) <= {"format", *fields})
                    for other, denied_fields in data.CATEGORY_FIELDS.items():
                        if other != category:
                            for key in denied_fields:
                                self.assertNotIn(('\n "' + key + '":').encode(), raw)
                    self.assertNotIn(b"acme-secret-client", raw)
                    self.assertNotIn(b"project_key", raw)
                    self.assertNotIn(b"source_id", raw)
                    data._validate_aggregate(agg, NOW)

    def test_languages_without_totals_are_percentages_not_counts(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            agg = publish.local_aggregate(settings(consent=allow("languages")), NOW)
            raw = publish.encode_aggregate(agg)
            self.assertAlmostEqual(sum(agg["language_percentages"].values()), 100)
            for value in (b"23456", b"first_ts", b"bytes", b"events", b"updated_at"):
                self.assertNotIn(value, raw)

    def test_every_excluded_category_is_absent_from_full_serialized_data(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            for category, fields in data.CATEGORY_FIELDS.items():
                consent = {**config.FULL_CONSENT, category: False}
                raw = publish.encode_aggregate(publish.local_aggregate(settings(consent=consent), NOW,
                                                                      repo_count_fn=lambda _c: 37))
                for key in fields:
                    self.assertNotIn(('\n "' + key + '":').encode(), raw)

    def test_agents_and_usage_publish_allowlisted_daily_buckets(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            cfg = settings(consent=allow("agents", "usage"))
            agg = publish.local_aggregate(cfg, NOW)
            self.assertEqual(agg["agents"]["codex"]["lines_added"], 23456)
            self.assertEqual(agg["agents"]["codex"]["active_minutes"], 2)
            self.assertEqual(agg["usage"][0]["input_tokens"], 98765)
            self.assertEqual(agg["usage"][0]["estimated_cost_usd"], "19.8765")
            self.assertEqual(agg["usage"][0]["date"], "2025-10-09")
            self.assertEqual(agg["active_minutes"]["2025-10-09"]["codex"], 2)
            hidden = publish.render_files(cfg, [agg], NOW)["card.svg"]
            self.assertNotIn(b"Codex", hidden)
            cfg["card"] = {"show_agents": True, "show_usage": True}
            visible = publish.render_files(cfg, [agg], NOW)["card.svg"]
            self.assertIn(b"Codex", visible)
            self.assertIn(b"API-equivalent", visible)
            cfg["consent"] = allow("languages")
            denied = publish.render_files(cfg, [agg], NOW)["card.svg"]
            self.assertNotIn(b"Codex", denied)
            self.assertNotIn(b"API-equivalent", denied)

    def test_partial_cards_draw_only_present_sections_in_every_layout(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            for category in data.CATEGORY_FIELDS:
                cfg = settings(consent=allow(category))
                agg = publish.local_aggregate(cfg, NOW, repo_count_fn=lambda _c: 37)
                card = data.card_data(data.merge([agg], now=NOW), "octo-cat", NOW, tz="UTC")
                for layout in render.LAYOUTS:
                    svg = render.render(card, layout=layout, now=NOW)
                    root = ET.fromstring(svg)
                    self.assertGreater(int(root.get("height")), 50)
                    if category != "repo_count":
                        self.assertNotIn("?tab=repositories", svg)
                    if category != "activity":
                        self.assertNotIn('<rect class="heat', svg)
                        self.assertNotIn("day streak", svg)
                    if category != "totals":
                        self.assertNotIn("tracking since", svg)
                        self.assertNotIn("bytes)", svg)
                    if category != "languages":
                        self.assertNotIn("barclip", svg)

    def test_public_count_and_private_count_have_separate_cache_semantics(self):
        with Home(self.tmp, "a"), mock.patch("shutil.which", return_value="gh"), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stdout='{"public":12,"private":28}')) as run:
            # Home's default patch is removed for this isolated API test.
            original = lib.github_repo_count
            # Recover the actual function from the library module's source-free reference.
            count = REAL_GITHUB_COUNT
            with mock.patch.object(lib, "github_repo_count", count):
                self.assertEqual(lib.repo_count(None), 12)
                self.assertNotIn("owned_private_repos", run.call_args.args[0][-1])
                self.assertEqual(lib.repo_count(None, include_private=True), 40)
                self.assertIn("owned_private_repos", run.call_args.args[0][-1])
                self.assertEqual(lib.repo_count(None), 12)
            self.assertIs(lib.github_repo_count, original)

    def test_legacy_combined_cache_cannot_be_used_as_public(self):
        with Home(self.tmp, "a"), mock.patch("shutil.which", return_value=None):
            with open(lib.GITHUB_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"count": 40, "fetched_at": NOW}, f)
            self.assertIsNone(REAL_GITHUB_COUNT(now=NOW))
            with mock.patch.object(lib, "local_repo_count", return_value=900), \
                    mock.patch.object(lib, "github_repo_count", return_value=None):
                self.assertIsNone(lib.repo_count(None))

    def test_local_count_api_uses_opt_in_and_skips_api_without_consent(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            with mock.patch.object(lib, "repo_count", return_value=12) as count:
                public = publish.local_aggregate(settings(consent=allow("repo_count")), NOW)
                self.assertEqual(public["repo_count"], 12)
                count.assert_called_once_with(mock.ANY, include_private=False)
                count.reset_mock()
                private = publish.local_aggregate(settings(consent=allow("repo_count", "repo_count_private")), NOW)
                self.assertTrue(private["repo_count_private"])
                count.assert_called_once_with(mock.ANY, include_private=True)
                count.reset_mock()
                publish.local_aggregate(settings(consent=allow("totals")), NOW)
                count.assert_not_called()

    def test_old_config_hook_notices_at_most_once_a_day(self):
        with Home(self.tmp, "a") as home:
            with open(lib.CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({"github_user": "octo-cat", "repo": "octo-cat/cards"}, f)
            self.assertFalse(config.has_consent(config.load()))
            with mock.patch.object(publish.time, "time", return_value=NOW), mock.patch.object(publish, "_Repo") as repo:
                for _ in range(3):
                    self.assertIsNone(lib.auto_publish())
                repo.assert_not_called()
            with open(os.path.join(home.dir, "errors.log"), encoding="utf-8") as f:
                self.assertEqual(len(f.readlines()), 1)
            with mock.patch.object(publish.time, "time", return_value=NOW + 86400):
                self.assertIsNone(lib.auto_publish())
            with open(os.path.join(home.dir, "errors.log"), encoding="utf-8") as f:
                self.assertEqual(len(f.readlines()), 2)

    def test_init_yes_does_not_publish_or_grant_consent(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a"), mock.patch.object(cli, "publish") as send:
            code, out = init(["--yes", "--user", "octo-cat", "--repo", "octo-cat/cards", "--remote", remote, "--mode", "git"])
            self.assertEqual(code, 0)
            self.assertEqual(config.consents(config.load()), config.NO_CONSENT)
            send.assert_not_called()
            self.assertIn("publication is paused", out)
        self.assertEqual(git(remote, "for-each-ref"), "")

    def test_concurrent_hooks_emit_only_one_notice(self):
        with Home(self.tmp, "a") as home:
            config.save(settings())
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _: lib.auto_publish(), range(24)))
            with open(os.path.join(home.dir, "errors.log"), encoding="utf-8") as f:
                self.assertEqual(len(f.readlines()), 1)

    def test_init_prompts_default_no_even_when_rerun_with_previous_grants(self):
        with Home(self.tmp, "a"), mock.patch.object(cli, "publish") as send:
            config.save(settings(self.bare_remote(), config.FULL_CONSENT))
            code, _ = init(["--mode", "claude"], answers=["", "", *[""] * len(config.CONSENT_CATEGORIES), "", "", ""])
            self.assertEqual(code, 0)
            self.assertEqual(config.consents(config.load()), config.NO_CONSENT)
            send.assert_not_called()

    def test_legacy_wire_is_blocked_without_required_consents(self):
        with Home(self.tmp, "a") as home:
            self.seed(home)
            config.save(settings(consent=allow("languages")))
            with mock.patch("urllib.request.urlopen") as network, mock.patch.object(lib, "WORKER_INGEST_URL", "https://example.test/ingest"):
                self.assertFalse(lib.send_to_worker([], 12, source="testsource"))
                conn = lib.init_db()
                try:
                    self.assertFalse(lib.sync_pending(conn))
                finally:
                    conn.close()
                network.assert_not_called()


REAL_GITHUB_COUNT = lib.github_repo_count


class PrivacyCommandsTest(TempDirTest):
    def command(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = cli.main(list(args))
        return code, out.getvalue()

    def test_private_opt_in_alone_is_saved_without_authorizing_or_removing_publication(self):
        with Home(self.tmp, "a"), mock.patch.object(publish, "_Repo") as repo:
            config.save(settings())
            code, out = self.command("privacy", "--grant", "repo_count_private")
            self.assertEqual(code, 0)
            self.assertTrue(config.consents(config.load())["repo_count_private"])
            self.assertFalse(config.has_consent(config.load()))
            self.assertIn("publication remains paused", out)
            repo.assert_not_called()

    def test_grant_revoke_and_revoke_last_category_remove_remote_bytes(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a") as home:
            home.add_events([edit(int(time.time()) - 60, "Python", 23456)])
            config.save(settings(remote))
            code, out = self.command("privacy")
            self.assertEqual(code, 0)
            self.assertIn("nothing (paused)", out)
            self.assertEqual(self.command("privacy", "--grant", "languages")[0], 0)
            self.assertEqual(self.command("privacy", "--grant", "totals")[0], 0)
            machine = lib.source_id()
            self.assertIn('"lines": 23456', git(remote, "show", f"{publish.BRANCH}:machines/{machine}.json"))
            self.assertEqual(self.command("privacy", "--revoke", "totals")[0], 0)
            raw = git(remote, "show", f"{publish.BRANCH}:machines/{machine}.json")
            self.assertNotIn("23456", raw)
            self.assertNotIn('"first_ts"', raw)
            self.assertIn("language_percentages", raw)
            self.assertEqual(self.command("privacy", "--revoke", "languages")[0], 0)
            self.assertEqual(git(remote, "for-each-ref", publish.REF), "")
            self.assertFalse(config.has_consent(config.load()))

    def test_revoking_back_to_an_earlier_state_in_the_same_second_still_publishes(self):
        # Same tree + same second = the same parentless commit as an earlier push.
        remote = self.bare_remote()
        start = int(time.time())
        with Home(self.tmp, "a") as home, mock.patch.object(publish.time, "time", return_value=start):
            home.add_events([edit(start - 60, "Python", 23456)])
            config.save(settings(remote))
            self.assertEqual(self.command("privacy", "--grant", "languages")[0], 0)
            self.assertEqual(self.command("privacy", "--grant", "totals")[0], 0)
            code, out = self.command("privacy", "--revoke", "totals")
            self.assertEqual(code, 0, out)
            raw = git(remote, "show", f"{publish.BRANCH}:machines/{lib.source_id()}.json")
            self.assertNotIn("23456", raw)

    def test_revoke_scrubs_all_machines_and_stale_full_config_cannot_republish(self):
        remote = self.bare_remote()
        full = {**data.CORE_CATEGORIES, "repo_count_private": True}
        for name, language in (("a", "Python"), ("b", "Rust")):
            with Home(self.tmp, name) as home:
                home.add_events([edit(int(time.time()) - 60, language, 23456)])
                cfg = settings(remote, full)
                config.save(cfg)
                publish.publish(cfg, force=True, repo_count_fn=lambda _c: 40)
        with Home(self.tmp, "a"):
            self.assertEqual(self.command("privacy", "--revoke", "totals")[0], 0)
            publish.publish(settings(remote, full), force=True, repo_count_fn=lambda _c: 40)
        for name in git(remote, "ls-tree", "-r", "--name-only", publish.BRANCH, "machines").splitlines():
            raw = git(remote, "show", f"{publish.BRANCH}:{name}")
            self.assertNotIn('"first_ts"', raw)
            self.assertNotIn('"event_types"', raw)
            self.assertIn("language_percentages", raw)

    def test_private_count_revocation_discards_legacy_counts_from_other_machines(self):
        old = {"format": 1, "repo_count": 40}
        self.assertNotIn("repo_count", data.consented(old, allow("repo_count")))
        self.assertNotIn("repo_count", data.consented({**old, "repo_count_private": True}, allow("repo_count")))
        self.assertEqual(data.consented({**old, "repo_count_private": False}, allow("repo_count"))["repo_count"], 40)

    def test_unpublish_refuses_foreign_branch_and_leaves_it_untouched(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a"):
            cfg = settings(remote, allow("totals"))
            config.save(cfg)
            repo = publish._Repo(os.path.join(self.tmp, "builder.git"), remote)
            repo.ensure()
            commit = repo.commit(repo.write_tree({"important.txt": b"keep"}), NOW)
            self.assertTrue(repo.push(commit, None)[0])
            code, out = self.command("unpublish")
            self.assertEqual(code, 1)
            self.assertIn("not owned", out)
            self.assertEqual(git(remote, "rev-parse", publish.REF), commit)
            self.assertFalse(config.has_consent(config.load()))

    def test_unpublish_refuses_devcard_owned_default_branch(self):
        remote = self.bare_remote()
        with Home(self.tmp, "a"):
            cfg = settings(remote, allow("totals"))
            config.save(cfg)
            publish.publish(cfg, force=True)
            git(remote, "symbolic-ref", "HEAD", publish.REF)
            head = git(remote, "rev-parse", publish.REF)
            code, out = self.command("unpublish")
            self.assertEqual(code, 1)
            self.assertIn("default branch", out)
            self.assertEqual(git(remote, "rev-parse", publish.REF), head)

    def test_failed_remote_update_saves_denial_and_reports_pending_cleanup(self):
        with Home(self.tmp, "a"):
            config.save(settings(os.path.join(self.tmp, "missing.git"), allow("totals", "languages")))
            code, out = self.command("privacy", "--revoke", "totals")
            self.assertEqual(code, 1)
            self.assertFalse(config.consents(config.load())["totals"])
            self.assertIn("remote update failed", out)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
