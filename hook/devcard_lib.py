"""Shared helpers for the devcard Claude Code hook."""
import json
import os
import re
import sqlite3
import time
# urllib.request is imported lazily inside send_to_worker — it costs ~150ms to
# import and the hot capture path (hook per tool call) never needs it.

DB_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/events.db"))
ERROR_LOG_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/errors.log"))
TOKEN_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/token"))
GITHUB_CACHE_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/github-repos.json"))
WORKER_INGEST_URL = "https://card.devcard.workers.dev/ingest"

# How long a fetched GitHub repo count stays fresh. The number moves a handful
# of times a year; refetching per sync would just burn API calls.
GITHUB_CACHE_TTL = 21600  # 6 hours
# Failures are cached too, on a much shorter clock. Without this a broken or
# logged-out `gh` would be re-spawned — and logged — on every sync, which runs
# every 20s and would bury the error log it writes to.
GITHUB_FAILURE_TTL = 600  # 10 minutes


def _load_token():
    """Env var wins; else the token file. The file means every hook process
    finds the token regardless of when its parent session started."""
    env = os.environ.get("DEVCARD_INGEST_TOKEN", "")
    if env:
        return env
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


INGEST_TOKEN = _load_token()

EXT_LANGUAGE = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".rs": "Rust", ".ps1": "PowerShell", ".psm1": "PowerShell",
    ".sql": "SQL", ".md": "Markdown", ".mdx": "Markdown", ".json": "JSON",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".sh": "Shell", ".bash": "Shell",
    ".go": "Go", ".java": "Java", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++",
    ".rb": "Ruby", ".php": "PHP",
}


def language_for_path(path):
    """Return the language name for a file path, or None if unrecognized."""
    _, ext = os.path.splitext(path.lower())
    return EXT_LANGUAGE.get(ext)


# Directory names that are working directories but never a project of your own:
# agent session scratchpads, dependency trees, virtualenvs, caches. Counting
# these as repos is what made the card claim 115 when the real number was 40.
UNTRACKED_SEGMENTS = frozenset({
    "node_modules", "scratchpad", "scratch", "npm-cache",
    "site-packages", "__pycache__", ".venv", "venv", ".worktrees", ".cache",
})

# Read from the environment rather than `tempfile` — importing tempfile pulls in
# shutil, and this module is imported on every captured tool call. Tests patch
# this to point somewhere they control.
TEMP_ROOT = os.path.normcase(
    os.environ.get("TEMP") or os.environ.get("TMPDIR") or os.environ.get("TMP") or "/tmp"
)


def is_trackable_project(path):
    """True if `path` looks like somewhere real work lives.

    Pure string work — this runs on the hot capture path, so it must never
    touch the filesystem or spawn anything.
    """
    if not path:
        return False
    normalized = path.replace("/", os.sep)
    if any(part in UNTRACKED_SEGMENTS for part in normalized.lower().split(os.sep)):
        return False
    cased = os.path.normcase(normalized)
    # Compare on a separator boundary so ".../Temp" doesn't also swallow
    # ".../Temperature-app".
    return cased != TEMP_ROOT and not cased.startswith(TEMP_ROOT.rstrip(os.sep) + os.sep)


def git_root(path):
    """Nearest ancestor of `path` containing a `.git` entry, or None.

    Walking up matters because a cwd is usually a *subdirectory* of the repo:
    counting raw cwds made one repo (lucky-cat) register as eleven.
    """
    try:
        current = os.path.abspath(path)
    except (OSError, ValueError):
        return None
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return os.path.normcase(current)
        parent = os.path.dirname(current)
        if parent == current:  # hit the drive root
            return None
        current = parent


def count_lines(text):
    """Count lines in a text blob. Empty string counts as 0 lines."""
    if not text:
        return 0
    return text.count("\n") + 1


# Shell separators that start a fresh command within one Bash invocation.
_SHELL_SPLIT = re.compile(r"&&|\|\||[;\n|]")
# A segment that actually *invokes* `git commit`, tolerating a path-qualified
# binary and leading flags (`git -C /repo commit`, `git --no-pager commit`).
_GIT_COMMIT = re.compile(r"^\s*(?:\S*[/\\])?git(?:\.exe)?\s+(?:-\S+\s+\S+\s+|-\S+\s+)*commit\b")


def counts_as_commit(command):
    """True if `command` runs a commit that creates a new one.

    Substring matching used to count `git log --grep="git commit"` and, worse,
    `--amend` — which re-commits work already counted. Splitting on shell
    separators and anchoring per segment keeps a quoted mention from counting.
    """
    if not command:
        return False
    for segment in _SHELL_SPLIT.split(command):
        if not _GIT_COMMIT.match(segment):
            continue
        if "--amend" in segment:
            return False  # rewrites an existing commit, never a new one
        return True
    return False


def tool_failed(payload):
    """True only when the payload positively reports the tool failed.

    PostToolUse generally fires on success, so an absent or unfamiliar
    `tool_response` must not suppress an event — the default stays "count it".
    """
    response = payload.get("tool_response")
    if not isinstance(response, dict):
        return False
    if response.get("success") is False:
        return True
    return bool(response.get("is_error") or response.get("isError"))


def parse_event(payload):
    """Turn a raw Claude Code hook payload into a normalized event dict, or None."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or ""
    now = int(time.time())

    if tool_name == "Write":
        file_path = tool_input.get("file_path", "")
        language = language_for_path(file_path)
        if not language:
            return None
        content = tool_input.get("content", "")
        return {
            "ts": now, "language": language, "lines_added": count_lines(content),
            "lines_removed": 0, "bytes_added": len(content.encode("utf-8", errors="replace")),
            "event_type": "write", "project_key": cwd,
        }

    if tool_name == "Edit":
        file_path = tool_input.get("file_path", "")
        language = language_for_path(file_path)
        if not language:
            return None
        old_string = tool_input.get("old_string", "")
        new_string = tool_input.get("new_string", "")
        return {
            "ts": now, "language": language, "lines_added": count_lines(new_string),
            "lines_removed": count_lines(old_string), "bytes_added": len(new_string.encode("utf-8", errors="replace")),
            "event_type": "edit", "project_key": cwd,
        }

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if counts_as_commit(command) and not tool_failed(payload):
            return {
                "ts": now, "language": None, "lines_added": 0,
                "lines_removed": 0, "bytes_added": 0,
                "event_type": "commit", "project_key": cwd,
            }
        return None

    return None


def init_db(db_path=DB_PATH):
    """Open (creating if needed) the local SQLite db and ensure its schema exists."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            language TEXT,
            lines_added INTEGER NOT NULL DEFAULT 0,
            lines_removed INTEGER NOT NULL DEFAULT 0,
            bytes_added INTEGER NOT NULL DEFAULT 0,
            event_type TEXT NOT NULL,
            project_key TEXT NOT NULL,
            synced INTEGER NOT NULL DEFAULT 0
        )
    """)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN bytes_added INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists (fresh dbs get it from CREATE TABLE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_repos (
            project_key TEXT PRIMARY KEY,
            first_seen INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def insert_event(conn, event):
    """Insert a normalized event and record its project in known_repos. Returns the new row id."""
    cur = conn.execute(
        "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, project_key) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event["ts"], event["language"], event["lines_added"], event["lines_removed"],
         event.get("bytes_added", 0), event["event_type"], event["project_key"]),
    )
    if is_trackable_project(event["project_key"]):
        conn.execute(
            "INSERT OR IGNORE INTO known_repos (project_key, first_seen) VALUES (?, ?)",
            (event["project_key"], event["ts"]),
        )
    conn.commit()
    return cur.lastrowid


def local_repo_count(conn):
    """Distinct git repositories worked in, resolved from the recorded cwds.

    Collapses subdirectories onto their repo root and drops paths that aren't
    inside a repo at all. Filesystem-bound, so only the detached syncer calls
    it — never the capture hot path.
    """
    roots = set()
    for (key,) in conn.execute("SELECT project_key FROM known_repos"):
        if not is_trackable_project(key):
            continue
        root = git_root(key)
        if root:
            roots.add(root)
    return len(roots)


def github_repo_count(now=None):
    """Repositories owned on GitHub (public + private), or None if unavailable.

    Read through the `gh` CLI, which is already authenticated on the owner's
    machine — that keeps the private half of the count reachable without
    putting a GitHub token in the public Worker. Cached on disk; failures
    return None so the caller can fall back rather than publish a wrong number.
    """
    now = time.time() if now is None else now
    try:
        with open(GITHUB_CACHE_PATH, encoding="utf-8") as f:
            cached = json.load(f)
        age = now - cached["fetched_at"]
        count = cached["count"]
        if count is None:
            if age < GITHUB_FAILURE_TTL:
                return None  # recent failure — don't re-spawn gh or re-log
        elif age < GITHUB_CACHE_TTL:
            return int(count)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # no cache, corrupt cache, or stale — fall through and refetch

    count = None
    try:
        import shutil
        import subprocess

        gh = shutil.which("gh")
        if gh:
            proc = subprocess.run(
                [gh, "api", "user", "--jq", "{public:.public_repos,private:.owned_private_repos}"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                data = json.loads(proc.stdout)
                count = int(data["public"]) + int(data["private"])
            else:
                log_error(f"github_repo_count: gh exited {proc.returncode}")
    except Exception as exc:
        log_error(f"github_repo_count failed: {exc}")

    try:
        os.makedirs(os.path.dirname(GITHUB_CACHE_PATH), exist_ok=True)
        with open(GITHUB_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"count": count, "fetched_at": int(now)}, f)
    except OSError:
        pass  # cache is an optimization; the number is still good
    return count


def repo_count(conn):
    """The repo count the card publishes.

    GitHub is the source of truth — it's the number the card's link resolves
    to. Local git roots are the fallback for machines without `gh`; the raw
    count of working directories is never published, because it counts
    scratchpads and subfolders as repositories.
    """
    remote = github_repo_count()
    if remote is not None:
        return remote
    return local_repo_count(conn)


def get_unsynced_events(conn, limit=50):
    """Return up to `limit` events not yet marked synced, oldest first."""
    rows = conn.execute(
        "SELECT id, ts, language, lines_added, lines_removed, bytes_added, event_type "
        "FROM events WHERE synced = 0 ORDER BY id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "language": r[2], "lines_added": r[3],
         "lines_removed": r[4], "bytes_added": r[5], "event_type": r[6]}
        for r in rows
    ]


def mark_synced(conn, event_ids):
    """Mark the given event ids as synced."""
    if not event_ids:
        return
    conn.executemany("UPDATE events SET synced = 1 WHERE id = ?", [(i,) for i in event_ids])
    conn.commit()


def log_error(message, path=ERROR_LOG_PATH):
    """Append an error message to the local error log. Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def send_to_worker(events, repo_count_value, url=WORKER_INGEST_URL, token=None, timeout=1.5):
    """POST a batch of events plus the current repo count to the Worker. Returns True on success."""
    import urllib.request

    token = token if token is not None else INGEST_TOKEN
    body = json.dumps({"events": events, "repo_count": repo_count_value}).encode("utf-8", errors="replace")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "X-Devcard-Token": token,
            "User-Agent": "devcard-hook/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:
        log_error(f"send_to_worker failed: {exc}")
        return False
