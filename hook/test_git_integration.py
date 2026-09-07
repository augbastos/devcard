"""Integration tests for the git capture path, against real temporary repos.

These deliberately shell out to real git instead of mocking it. The bugs this
file exists to pin — a merge commit re-counting the branch it merged, a hook
installed into `.git/hooks` when git says the hooks live somewhere else — are
bugs about what git actually does, and a mock would have happily agreed with
the broken version.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import devcard_git_hook as githook
import devcard_lib as lib
import install_git_hook as installer


def git_available():
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


HAVE_GIT = git_available()


REAL_DB = lib.DB_PATH
REAL_ERROR_LOG = lib.ERROR_LOG_PATH


class GitRepoCase(unittest.TestCase):
    """Base with helpers for building throwaway repositories."""

    @classmethod
    def setUpClass(cls):
        if not HAVE_GIT:
            raise unittest.SkipTest("git is not available")

    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="devcard-git-")
        self.addCleanup(shutil.rmtree, self.base, True)

        # Hard guard. `init_db` used to take the real path as a DEFAULT
        # argument, so patching the module constant did nothing and a test run
        # wrote eight rows into the owner's live events.db — rows that the
        # background syncer would then have published to the card. Every test
        # in this file now points the module at throwaway paths, and this
        # asserts that the redirection actually took effect.
        self.devcard_home = os.path.join(self.base, "devcard-home")
        os.makedirs(self.devcard_home, exist_ok=True)
        for attr, name in (
            ("DB_PATH", "events.db"),
            ("ERROR_LOG_PATH", "errors.log"),
            ("SOURCE_ID_PATH", "source-id"),
            ("GITHUB_CACHE_PATH", "github-repos.json"),
        ):
            patcher = mock.patch.object(lib, attr, os.path.join(self.devcard_home, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.assertNotEqual(lib.DB_PATH, REAL_DB)
        self.assertNotEqual(lib.ERROR_LOG_PATH, REAL_ERROR_LOG)

    def assertRealDataUntouched(self):
        self.assertFalse(os.path.exists(REAL_DB) and os.path.getsize(REAL_DB) == 0)

    def git(self, cwd, *args, check=True):
        proc = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, errors="replace"
        )
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc

    def make_repo(self, name="repo"):
        path = os.path.join(self.base, name)
        os.makedirs(path, exist_ok=True)
        self.git(path, "init", "-q", "-b", "main", ".")
        self.git(path, "config", "user.email", "test@example.invalid")
        self.git(path, "config", "user.name", "devcard test")
        self.git(path, "config", "commit.gpgsign", "false")
        # Keep byte counts deterministic across platforms.
        self.git(path, "config", "core.autocrlf", "false")
        return path

    def write(self, repo, name, text):
        full = os.path.join(repo, name)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def commit(self, repo, message):
        self.git(repo, "add", "-A")
        self.git(repo, "commit", "-qm", message)

    def collect(self, repo):
        """What the hook would record for HEAD: (lines per language, bytes)."""
        parents = githook.head_parents(repo)
        return githook.collect(repo, parents)


class TestDiffCounting(GitRepoCase):
    def test_first_commit_counts_its_whole_tree(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\ntwo\nthree\n")
        self.commit(repo, "first")
        per_language, per_bytes = self.collect(repo)
        self.assertEqual(per_language, {"Python": (3, 0)})
        self.assertEqual(per_bytes["Python"], len("onetwothree"))

    def test_ordinary_commit_counts_its_own_diff(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "first")
        self.write(repo, "a.py", "one\ntwo\nthree\n")
        self.commit(repo, "second")
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {"Python": (2, 0)})

    def test_deletions_are_counted_as_removed(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\ntwo\nthree\n")
        self.commit(repo, "first")
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "trim")
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {"Python": (0, 2)})

    def test_unknown_extensions_are_ignored(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.write(repo, "notes.unknownext", "lots\nof\nlines\n")
        self.commit(repo, "first")
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {"Python": (1, 0)})

    def test_a_deleted_file_does_not_donate_bytes_to_the_next_one(self):
        # The patch parser tracks the current file from `+++ b/`. A deletion's
        # header is `+++ /dev/null`, so without a reset the deleted file's
        # language kept collecting the following file's added bytes.
        repo = self.make_repo()
        self.write(repo, "gone.py", "x\n")
        self.write(repo, "keep.ts", "a\n")
        self.commit(repo, "first")
        os.remove(os.path.join(repo, "gone.py"))
        self.write(repo, "keep.ts", "a\nbbbbbbbb\n")
        self.commit(repo, "second")
        _, per_bytes = self.collect(repo)
        self.assertNotIn("Python", per_bytes)
        self.assertEqual(per_bytes["TypeScript"], len("bbbbbbbb"))


class TestMergeCommits(GitRepoCase):
    def _diverged(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "base")
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.write(repo, "a.py", "one\ntwo\nthree\n")
        self.commit(repo, "feature work")
        self.git(repo, "checkout", "-q", "main")
        self.write(repo, "other.ts", "x\n")
        self.commit(repo, "main work")
        return repo

    def test_merge_commit_adds_no_lines(self):
        # The regression: `git diff HEAD~1 HEAD` on a merge reports every line
        # the branch brought in — lines already counted when each of those
        # commits was made. A card that merges feature branches was inflated by
        # the full size of every branch it ever merged.
        repo = self._diverged()
        self.git(repo, "merge", "--no-ff", "--no-commit", "-q", "feature", check=False)
        self.commit(repo, "merge feature")

        parents = githook.head_parents(repo)
        self.assertEqual(len(parents), 2, "expected a real merge commit")

        per_language, per_bytes = self.collect(repo)
        self.assertEqual(per_language, {})
        self.assertEqual(per_bytes, {})

        # And the old approach really did double count, so this is not vacuous.
        old = self.git(repo, "diff", "--numstat", "HEAD~1", "HEAD").stdout
        self.assertIn("a.py", old)

    def test_merge_still_records_one_commit(self):
        repo = self._diverged()
        self.git(repo, "merge", "--no-ff", "--no-commit", "-q", "feature", check=False)
        self.commit(repo, "merge feature")
        with mock.patch.object(lib, "send_to_worker", return_value=False), \
                mock.patch.object(githook, "capture_mode", return_value="git"), \
                mock.patch.object(os, "getcwd", return_value=repo):
            githook.main()
        conn = lib.init_db()
        self.addCleanup(conn.close)
        types = dict(conn.execute("SELECT event_type, COUNT(*) FROM events GROUP BY 1"))
        self.assertEqual(types, {"commit": 1})

    def test_conflict_resolution_merge_also_adds_no_lines(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "base")
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.write(repo, "a.py", "feature\n")
        self.commit(repo, "feature")
        self.git(repo, "checkout", "-q", "main")
        self.write(repo, "a.py", "main\n")
        self.commit(repo, "main")
        self.git(repo, "merge", "-q", "feature", check=False)  # conflicts
        self.write(repo, "a.py", "resolved\n")
        self.commit(repo, "resolve")

        parents = githook.head_parents(repo)
        self.assertEqual(len(parents), 2)
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {})

    def test_octopus_merge_adds_no_lines(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "base")
        for name in ("b1", "b2"):
            self.git(repo, "checkout", "-q", "-b", name, "main")
            self.write(repo, f"{name}.py", "x\n")
            self.commit(repo, name)
        self.git(repo, "checkout", "-q", "main")
        # main must diverge too, or git fast-forwards onto one branch and the
        # result is an ordinary two-parent merge.
        self.write(repo, "main.ts", "m\n")
        self.commit(repo, "main work")
        # An octopus merge cannot be split into merge + commit, so let git make
        # the commit; `collect` is what is under test, not which hook git runs.
        self.git(repo, "merge", "-q", "-m", "octopus", "b1", "b2")

        parents = githook.head_parents(repo)
        self.assertGreaterEqual(len(parents), 3)
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {})

    def test_fast_forward_merge_creates_no_commit_to_count(self):
        # A fast-forward moves the branch pointer; there is no merge commit and
        # no post-commit hook run, so nothing is counted twice.
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "base")
        before = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.write(repo, "a.py", "one\ntwo\n")
        self.commit(repo, "feature")
        tip = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "-q", "feature")
        self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), tip)
        self.assertNotEqual(tip, before)
        self.assertEqual(len(githook.head_parents(repo)), 1)

    def test_squash_merge_is_counted_as_an_ordinary_commit(self):
        # A squash merge produces a normal single-parent commit that is
        # indistinguishable from hand-written work. It IS counted, and if the
        # branch's own commits were captured on this machine those lines are
        # counted twice. Documented in the README rather than papered over.
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "base")
        self.git(repo, "checkout", "-q", "-b", "feature")
        self.write(repo, "a.py", "one\ntwo\nthree\n")
        self.commit(repo, "feature")
        self.git(repo, "checkout", "-q", "main")
        self.git(repo, "merge", "--squash", "-q", "feature", check=False)
        self.commit(repo, "squashed")
        self.assertEqual(len(githook.head_parents(repo)), 1)
        per_language, _ = self.collect(repo)
        self.assertEqual(per_language, {"Python": (2, 0)})


class TestGitModeEvents(GitRepoCase):
    def _run_hook(self, repo):
        """Run the hook exactly as git would, and report the events it wrote.

        The hook closes its own connection, so the rows are read back through a
        fresh one rather than through the handle it was given.
        """
        with mock.patch.object(lib, "send_to_worker", return_value=False), \
                mock.patch.object(githook, "capture_mode", return_value="git"), \
                mock.patch.object(os, "getcwd", return_value=repo):
            githook.main()
        conn = lib.init_db()
        self.addCleanup(conn.close)
        return conn

    def test_language_rows_are_diff_events_not_edits(self):
        # `edit` means one agent tool call. A git-mode row is a per-commit,
        # per-language aggregate. Sharing the type made the card's "code edits"
        # number mean two different things depending on capture mode.
        repo = self.make_repo()
        self.write(repo, "a.py", "one\ntwo\n")
        self.write(repo, "b.ts", "x\n")
        self.commit(repo, "first")
        conn = self._run_hook(repo)
        types = dict(conn.execute("SELECT event_type, COUNT(*) FROM events GROUP BY 1"))
        self.assertEqual(types, {"diff": 2, "commit": 1})

    def test_claude_mode_machine_records_nothing(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "first")
        with mock.patch.object(githook, "capture_mode", return_value="claude"), \
                mock.patch.object(os, "getcwd", return_value=repo):
            githook.main()
        conn = lib.init_db()
        self.addCleanup(conn.close)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

    def test_a_broken_repo_never_raises(self):
        # post-commit must not disturb a commit, whatever it finds.
        plain = os.path.join(self.base, "not-a-repo")
        os.makedirs(plain)
        with mock.patch.object(os, "getcwd", return_value=plain), \
                mock.patch.object(githook, "capture_mode", return_value="git"), \
                mock.patch.object(lib, "log_error") as logged:
            githook.main()  # must not raise
        logged.assert_not_called()


class TestHookInstallation(GitRepoCase):
    def hook_path(self, repo):
        return installer.hook_path_for(repo)

    def read(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_installs_into_a_plain_repo(self):
        repo = self.make_repo()
        self.assertEqual(installer.install_into(self.hook_path(repo)), "installed")
        content = self.read(os.path.join(repo, ".git", "hooks", "post-commit"))
        self.assertIn(installer.MARKER, content)
        self.assertTrue(content.startswith("#!/bin/sh"))

    def test_installing_twice_is_a_no_op(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        installer.install_into(path)
        first = self.read(path)
        self.assertEqual(installer.install_into(path), "already installed")
        self.assertEqual(self.read(path), first)

    def test_respects_core_hookspath(self):
        # `.git/hooks/post-commit` is simply not where this repo's hooks live.
        repo = self.make_repo()
        self.git(repo, "config", "core.hooksPath", "githooks")
        path = self.hook_path(repo)
        self.assertEqual(os.path.normcase(path), os.path.normcase(os.path.join(repo, "githooks", "post-commit")))
        self.assertEqual(installer.install_into(path), "installed")
        self.assertTrue(os.path.exists(os.path.join(repo, "githooks", "post-commit")))
        self.assertFalse(os.path.exists(os.path.join(repo, ".git", "hooks", "post-commit")))

    def test_worktree_resolves_to_the_shared_hooks_directory(self):
        # In a worktree `.git` is a FILE, so joining `.git/hooks` produced a
        # path that could not be created.
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "first")
        wt = os.path.join(self.base, "wt")
        self.git(repo, "worktree", "add", "-q", wt, "-b", "wtbranch")
        self.assertTrue(os.path.isfile(os.path.join(wt, ".git")))

        path = self.hook_path(wt)
        self.assertEqual(
            os.path.normcase(os.path.realpath(path)),
            os.path.normcase(os.path.realpath(os.path.join(repo, ".git", "hooks", "post-commit"))),
        )
        self.assertEqual(installer.install_into(path), "installed")

    def test_repo_and_its_worktree_are_installed_once(self):
        repo = self.make_repo()
        self.write(repo, "a.py", "one\n")
        self.commit(repo, "first")
        self.git(repo, "worktree", "add", "-q", os.path.join(self.base, "wt"), "-b", "wtbranch")
        installer.main([self.base])
        content = self.read(os.path.join(repo, ".git", "hooks", "post-commit"))
        self.assertEqual(content.count(installer.MARKER), 1)

    def test_appends_to_an_existing_shell_hook_without_destroying_it(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/bash\necho existing-hook\n")
        self.assertEqual(installer.install_into(path), "installed")
        content = self.read(path)
        self.assertIn("echo existing-hook", content)
        self.assertIn(installer.MARKER, content)

    def test_appends_when_the_existing_hook_has_no_trailing_newline(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/sh\necho existing")
        installer.install_into(path)
        lines = self.read(path).splitlines()
        self.assertEqual(lines[1], "echo existing")
        self.assertIn(installer.MARKER, lines[2])

    def test_refuses_to_append_shell_to_a_python_hook(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        original = "#!/usr/bin/env python3\nprint('existing')\n"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(original)
        self.assertEqual(installer.install_into(path), "skipped (not a shell hook)")
        self.assertEqual(self.read(path), original)

    def test_accepts_a_hook_with_no_shebang(self):
        # git runs an extensionless hook with sh; husky writes hooks this way.
        repo = self.make_repo()
        path = self.hook_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("npx lint-staged\n")
        self.assertEqual(installer.install_into(path), "installed")
        self.assertIn("npx lint-staged", self.read(path))

    def test_shebang_detection(self):
        for shell in ("#!/bin/sh\n", "#!/bin/bash\n", "#!/usr/bin/env sh\n", "#!/usr/bin/env bash -e\n", "no shebang\n"):
            self.assertTrue(installer.shebang_is_shell(shell), shell)
        for other in ("#!/usr/bin/env python3\n", "#!/usr/bin/ruby\n", "#!/usr/bin/env node\n", "#!/usr/bin/perl\n"):
            self.assertFalse(installer.shebang_is_shell(other), other)

    def test_husky_generated_folder_is_redirected_to_the_user_hook(self):
        # husky regenerates and gitignores `.husky/_`, so a line appended there
        # disappears at the next `npm install`.
        repo = self.make_repo()
        generated = os.path.join(repo, ".husky", "_", "post-commit")
        self.assertEqual(
            os.path.normcase(installer.husky_user_hook(generated)),
            os.path.normcase(os.path.join(repo, ".husky", "post-commit")),
        )
        # A normal hooks path is left alone.
        plain = os.path.join(repo, ".git", "hooks", "post-commit")
        self.assertEqual(installer.husky_user_hook(plain), plain)

    def test_installs_through_husky_hookspath(self):
        repo = self.make_repo()
        os.makedirs(os.path.join(repo, ".husky", "_"), exist_ok=True)
        self.git(repo, "config", "core.hooksPath", ".husky/_")
        installer.main([repo])
        self.assertTrue(os.path.exists(os.path.join(repo, ".husky", "post-commit")))
        self.assertFalse(os.path.exists(os.path.join(repo, ".husky", "_", "post-commit")))

    def test_paths_with_spaces(self):
        repo = self.make_repo("my code projects")
        path = self.hook_path(repo)
        self.assertIn(" ", repo)
        self.assertEqual(installer.install_into(path), "installed")
        # The interpreter and script are quoted, so a space in either survives.
        line = installer.hook_line()
        self.assertEqual(line.count('"'), 4)

    def test_scans_one_level_deep_and_the_folder_itself(self):
        parent = os.path.join(self.base, "projects")
        os.makedirs(parent)
        a = self.make_repo(os.path.join("projects", "a"))
        b = self.make_repo(os.path.join("projects", "b"))
        os.makedirs(os.path.join(parent, "not-a-repo"))
        found = installer.find_repos(parent)
        self.assertEqual(
            sorted(os.path.normcase(os.path.realpath(p)) for p in found),
            sorted(os.path.normcase(os.path.realpath(p)) for p in (a, b)),
        )

    def test_a_subdirectory_of_a_repo_is_not_a_repo(self):
        repo = self.make_repo()
        nested = os.path.join(repo, "src", "deep")
        os.makedirs(nested)
        self.assertIsNone(installer.repo_root(nested))

    def test_uninstall_removes_only_our_line(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/sh\necho existing-hook\n")
        installer.install_into(path)
        self.assertEqual(installer.uninstall_from(path), "line removed")
        content = self.read(path)
        self.assertIn("echo existing-hook", content)
        self.assertNotIn(installer.MARKER, content)

    def test_uninstall_deletes_a_hook_that_was_only_ours(self):
        repo = self.make_repo()
        path = self.hook_path(repo)
        installer.install_into(path)
        self.assertEqual(installer.uninstall_from(path), "removed")
        self.assertFalse(os.path.exists(path))

    def test_uninstall_on_a_repo_without_the_hook_is_harmless(self):
        repo = self.make_repo()
        self.assertEqual(installer.uninstall_from(self.hook_path(repo)), "not installed")

    def test_installed_hook_runs_and_does_not_block_a_commit(self):
        # End to end: the line the installer writes has to be something `sh`
        # can actually run, and a failure inside it must not fail the commit.
        repo = self.make_repo()
        path = self.hook_path(repo)
        installer.install_into(path)
        self.write(repo, "a.py", "one\n")
        self.git(repo, "add", "-A")
        proc = self.git(repo, "commit", "-m", "hooked", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_reports_when_the_path_holds_no_repositories(self):
        empty = os.path.join(self.base, "empty")
        os.makedirs(empty)
        self.assertEqual(installer.main([empty]), 0)

    def test_missing_folder_is_reported_not_crashed(self):
        self.assertEqual(installer.main([os.path.join(self.base, "nope")]), 0)


if __name__ == "__main__":
    unittest.main()
