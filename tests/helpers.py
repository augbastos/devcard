"""Isolation for the devcard package tests.

Every path the package or the hook library could read or write under
~/.claude/ is pointed at a throwaway directory, and the test fails loudly if
that did not take effect — the rule in CLAUDE.md: a test never touches the
owner's real devcard files.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from devcard import cli, config, publish
from devcard._hook import lib

REAL_HOME = os.path.normpath(os.path.expanduser("~/.claude"))
PROJECT = "/home/someone/work/acme-secret-client/src"


class Home:
    """One fake machine: its own devcard directory, database and machine id."""

    def __init__(self, root, name):
        self.dir = os.path.join(root, name)
        os.makedirs(self.dir, exist_ok=True)
        self.paths = {
            (lib, "DB_PATH"): os.path.join(self.dir, "events.db"),
            (lib, "ERROR_LOG_PATH"): os.path.join(self.dir, "errors.log"),
            (lib, "SOURCE_ID_PATH"): os.path.join(self.dir, "source-id"),
            (lib, "GITHUB_CACHE_PATH"): os.path.join(self.dir, "github-repos.json"),
            (lib, "CONFIG_PATH"): os.path.join(self.dir, "config.json"),
            (config, "HOME"): self.dir,
            (cli, "SETTINGS_PATH"): os.path.join(self.dir, "claude-settings.json"),
            (cli, "MODE_PATH"): os.path.join(self.dir, "mode"),
        }
        self._patchers = []

    def __enter__(self):
        for (module, attr), value in self.paths.items():
            patcher = mock.patch.object(module, attr, value)
            patcher.start()
            self._patchers.append(patcher)
        # No network: no Worker, no GitHub API for the repo count, no avatar download.
        for module, attr, value in (
            (lib, "WORKER_INGEST_URL", ""),
            (lib, "github_repo_count", lambda now=None: None),
            (publish, "fetch_avatar", lambda user, now=None: None),
        ):
            patcher = mock.patch.object(module, attr, value)
            patcher.start()
            self._patchers.append(patcher)
        for (module, attr), _ in self.paths.items():
            assert not getattr(module, attr).startswith(REAL_HOME), attr
        return self

    def __exit__(self, *exc):
        while self._patchers:
            self._patchers.pop().stop()

    def add_events(self, events):
        conn = lib.init_db()
        try:
            for e in events:
                lib.insert_event(conn, {"lines_removed": 0, "bytes_added": 0, "language": None,
                                        "project_key": PROJECT, **e})
        finally:
            conn.close()


def edit(ts, language="Python", lines=10):
    return {"ts": ts, "language": language, "lines_added": lines, "bytes_added": lines * 30,
            "event_type": "edit"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, check=True).stdout.strip()


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="devcard-pkg-tests-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def bare_remote(self, name="remote.git"):
        path = os.path.join(self.tmp, name)
        subprocess.run(["git", "init", "-q", "--bare", path], check=True)
        return path
