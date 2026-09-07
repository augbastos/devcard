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
SOURCE_ID_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/source-id"))
WORKER_URL_PATH = os.path.normpath(os.path.expanduser("~/.claude/devcard/worker-url"))

# Where this installation syncs to. Resolution order: the DEVCARD_WORKER_URL
# environment variable, then ~/.claude/devcard/worker-url, then the value below.
#
# setup.py writes the file. It used to rewrite this constant in place, which
# meant a `git clone && python setup.py` left an edit in tracked source — so
# every fork carried a diff it never meant to make, and `git pull` conflicted
# on it. Deployment config belongs next to the token and the mode, not in the
# module.
DEFAULT_INGEST_URL = "https://card.devcard.workers.dev/ingest"


def _load_worker_url():
    env = os.environ.get("DEVCARD_WORKER_URL", "").strip()
    if env:
        return env
    try:
        with open(WORKER_URL_PATH, encoding="utf-8") as f:
            configured = f.read().strip()
        if configured:
            return configured
    except OSError:
        pass
    return DEFAULT_INGEST_URL


WORKER_INGEST_URL = _load_worker_url()

# How long a fetched GitHub repo count stays fresh. The number moves a handful
# of times a year; refetching per sync would just burn API calls.
GITHUB_CACHE_TTL = 21600  # 6 hours
# Failures are cached too, on a much shorter clock. Without this a broken or
# logged-out `gh` would be re-spawned — and logged — on every sync, which runs
# every 20s and would bury the error log it writes to.
GITHUB_FAILURE_TTL = 600  # 10 minutes


def _restrict_permissions(path):
    """Best-effort 0600 on a file holding a secret. No-op where it means nothing.

    Windows ignores POSIX mode bits (the ACL is what protects the file there),
    and a filesystem may refuse the call entirely — neither is worth failing a
    hook over, so this never raises.
    """
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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

# Characters a source id may contain — kept in sync with SOURCE_ID_RE in the
# Worker, which rejects anything else outright.
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


# What an event queued before `source_id` existed is filed under, on both sides
# of the wire. Kept in sync with LEGACY_SOURCE_ID in the Worker.
LEGACY_SOURCE_ID = "legacy"


def read_source_id(path=None):
    """This installation's id if one is already persisted, else "". Never writes."""
    path = SOURCE_ID_PATH if path is None else path
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read().strip()
    except OSError:
        return ""
    return existing if _SOURCE_ID_RE.match(existing) else ""


def source_id(path=None, create=True):
    """Stable, random, opaque id for this devcard installation.

    The Worker dedupes on (source_id, client_event_id). client_event_id is a
    local SQLite rowid, and every install's sequence starts at 1 — so without
    this, a second machine's event 1 was indistinguishable from the first
    machine's and got dropped as a duplicate, and deleting events.db made a
    fresh sequence collide with already-ingested history.

    Deliberately NOT derived from the hostname, the username, the MAC address
    or any path: those would put an identifying string in the ingest payload.
    It is 16 random bytes, generated once and cached on disk, and it is never
    rendered on the card.

    Returns "" if the id can neither be read nor written. The caller must then
    send NOTHING and retry later — see `sync_pending`. Falling back to the
    shared `legacy` namespace instead would look harmless and quietly
    reintroduce the exact multi-machine collision this field exists to prevent:
    two installations that both failed to persist an id would file their event
    1 under the same key, and one of them would vanish.
    """
    path = SOURCE_ID_PATH if path is None else path
    existing = read_source_id(path)
    if existing:
        return existing
    if not create:
        return ""

    import secrets

    generated = secrets.token_hex(16)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Exclusive create: two hooks racing on a fresh install must not end up
        # with two different ids, which would double-count nothing but would
        # split this machine's identity in two.
        with open(path, "x", encoding="utf-8") as f:
            f.write(generated)
        _restrict_permissions(path)
        return generated
    except FileExistsError:
        try:
            with open(path, encoding="utf-8") as f:
                existing = f.read().strip()
            return existing if _SOURCE_ID_RE.match(existing) else ""
        except OSError:
            return ""
    except OSError:
        # Reported by the caller, which knows how many events are waiting and
        # throttles the message. Logging here too put two lines in errors.log
        # for one condition, every 20 seconds.
        return ""


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


def _add_source_id_column(conn):
    """Give `events` a per-row namespace, and stamp the rows that predate it.

    Identity has to belong to the EVENT, not to the installation, because a row
    can outlive the identity the installation had when it was queued.

    The case that forced this: an old hook syncs local row 42 with no
    source_id, so the Worker stores it as `legacy/42`; the response is lost, so
    the row stays `synced = 0`; the user upgrades; the new hook re-sends row 42
    under its brand-new installation id. To the Worker that is a different
    event — different key — and it counts the same work twice. The row has to
    remember which namespace it was queued under.

    The backfill runs exactly once, in the same breath as the ALTER that
    creates the column, and never again. Doing it on every open would be wrong
    in the opposite direction: a NULL after this point means "queued by this
    installation but not yet stamped", and `sync_pending` stamps those with the
    real id.

    Existing rows are stamped `legacy` unconditionally, because that is what a
    database without this column means: it was written by a version that sent no
    source_id, so anything of it that reached D1 is stored under `legacy` and a
    re-send has to match that key.

    An earlier draft chose between `legacy` and the source-id file's value
    depending on whether that file existed yet. It passed, because every entry
    point happens to call this before anything creates the id — and that is
    exactly why it was wrong: a rule whose correctness rests on the order two
    unrelated functions are called in will break silently the first time
    somebody reorders them, and it would mislabel an entire backlog as
    belonging to a brand-new installation. A constant cannot break that way.

    The column and the stamp land in ONE transaction. Apart, a process killed
    between them would leave the column present and every pre-existing row
    NULL — and because the ALTER would then never run again, the backfill would
    never happen. Those rows would look like "captured but not yet stamped",
    `sync_pending` would give them the CURRENT id, and any of them already sent
    as `legacy` with a lost response would be counted a second time. Exactly
    the bug this column exists to prevent, through the crash path.
    """
    columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    if "source_id" in columns:
        return  # fresh dbs get it from CREATE TABLE; upgraded ones already ran

    # Explicit BEGIN: Python's sqlite3 runs DDL in autocommit mode, so without
    # it the ALTER would commit on its own and the UPDATE would be a separate
    # transaction. SQLite itself is happy to have ALTER TABLE inside one.
    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE events ADD COLUMN source_id TEXT")
        conn.execute("UPDATE events SET source_id = ?", (LEGACY_SOURCE_ID,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(db_path=None):
    """Open (creating if needed) the local SQLite db and ensure its schema exists.

    The path is resolved from the module at call time, not captured as a default
    argument. That difference matters: a default is bound when the function is
    defined, so patching `devcard_lib.DB_PATH` in a test silently did nothing
    and the test wrote into the owner's real events.db.
    """
    db_path = DB_PATH if db_path is None else db_path
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
            synced INTEGER NOT NULL DEFAULT 0,
            source_id TEXT
        )
    """)
    try:
        conn.execute("ALTER TABLE events ADD COLUMN bytes_added INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists (fresh dbs get it from CREATE TABLE)
    _add_source_id_column(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS known_repos (
            project_key TEXT PRIMARY KEY,
            first_seen INTEGER NOT NULL
        )
    """)
    # The syncer asks "what is still unsynced?" every ~20 seconds, and `events`
    # only ever grows. A partial index keeps that a lookup over the handful of
    # pending rows instead of a scan of the entire history — which is also why
    # the table can be left to grow without a retention policy. See
    # docs/retention.md.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_unsynced ON events(id) WHERE synced = 0"
    )
    conn.commit()
    return conn


def insert_event(conn, event):
    """Insert a normalized event and record its project in known_repos. Returns the new row id.

    The event is stamped with this installation's namespace at creation, so its
    identity is fixed as early as possible and cannot drift if the source-id
    file is later lost and regenerated.

    `read_source_id` never writes, which keeps this — the Claude Code hot path —
    free of directory creation and of the error logging a failed create would
    produce on every single tool call. Creating the id is the detached syncer's
    job. Until it has, rows land with a NULL namespace; they are held back from
    sending and stamped by `sync_pending` rather than guessed at.
    """
    cur = conn.execute(
        "INSERT INTO events (ts, language, lines_added, lines_removed, bytes_added, event_type, project_key, source_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (event["ts"], event["language"], event["lines_added"], event["lines_removed"],
         event.get("bytes_added", 0), event["event_type"], event["project_key"],
         event.get("source_id") or read_source_id() or None),
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
    """Return up to `limit` unsent events, oldest first, each with its namespace.

    Rows with a NULL `source_id` are deliberately EXCLUDED. A NULL means the
    event was captured but no installation id could be persisted yet, and
    sending it would mean guessing a namespace — which is how an event ends up
    counted twice, or filed under `legacy` where another machine's rowid means
    something else. `sync_pending` stamps them first; until then they simply
    wait. The projection still has no `project_key`: paths never leave.
    """
    rows = conn.execute(
        "SELECT id, ts, language, lines_added, lines_removed, bytes_added, event_type, source_id "
        "FROM events WHERE synced = 0 AND source_id IS NOT NULL ORDER BY id ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"id": r[0], "ts": r[1], "language": r[2], "lines_added": r[3],
         "lines_removed": r[4], "bytes_added": r[5], "event_type": r[6],
         "source_id": r[7]}
        for r in rows
    ]


def count_unstamped(conn):
    """Events captured but still waiting for an installation id."""
    return conn.execute(
        "SELECT COUNT(*) FROM events WHERE synced = 0 AND source_id IS NULL"
    ).fetchone()[0]


def stamp_pending_source(conn, source):
    """Give every not-yet-stamped event this installation's id. Returns the count.

    Safe by construction: a row is only NULL here if it has never been sent, so
    choosing its namespace now cannot contradict anything already in D1. Once
    stamped it never changes again, which is what keeps a retry idempotent even
    if the source-id file is later lost and regenerated.
    """
    if not source:
        return 0
    cur = conn.execute(
        "UPDATE events SET source_id = ? WHERE synced = 0 AND source_id IS NULL", (source,)
    )
    conn.commit()
    return cur.rowcount


def mark_synced(conn, event_ids):
    """Mark the given event ids as synced."""
    if not event_ids:
        return
    conn.executemany("UPDATE events SET synced = 1 WHERE id = ?", [(i,) for i in event_ids])
    conn.commit()


def log_error(message, path=None):
    """Append an error message to the local error log. Never raises."""
    path = ERROR_LOG_PATH if path is None else path
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def send_to_worker(events, repo_count_value, url=None, token=None, timeout=1.5,
                   source=None):
    """POST a batch of events plus the current repo count to the Worker.

    The payload carries exactly three things: the anonymized event rows, the
    repo count, and this installation's opaque `source_id`. No project name, no
    path, no filename, no hostname, no username — the SQL projection that built
    `events` cannot select them and the Worker has no column for them.

    Each event may carry its own `source_id`, which overrides the batch-level
    one. That is what lets a single batch mix a backlog queued before this
    installation had an id (namespace `legacy`) with events captured after it.

    Refuses to send at all without an installation id, and returns False. The
    events then stay unsynced and the next attempt retries them. The tempting
    alternative — omitting the field so the Worker files them under `legacy` —
    would silently undo multi-machine identity for that installation.

    Returns True on success.
    """
    import urllib.request

    url = WORKER_INGEST_URL if url is None else url
    token = token if token is not None else INGEST_TOKEN
    source = source_id() if source is None else source
    if not source:
        log_error("send_to_worker: no installation source id — holding events for the next sync")
        return False
    payload = {"events": events, "repo_count": repo_count_value, "source_id": source}
    body = json.dumps(payload).encode("utf-8", errors="replace")
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


# A persistent local failure repeats every time the syncer runs — roughly every
# 20 seconds. Logging it each time would bury errors.log, which is the
# documented place to start debugging a silent hook. Same reasoning as
# GITHUB_FAILURE_TTL above; that lesson was learnt from a logged-out `gh`.
LOG_THROTTLE_TTL = 3600  # at most one line an hour per condition


def _log_throttled(key, message, ttl=LOG_THROTTLE_TTL, now=None):
    """Log `message` at most once per `ttl` seconds. Returns True if it logged."""
    now = time.time() if now is None else now
    marker = os.path.join(os.path.dirname(ERROR_LOG_PATH), f".last-{key}")
    try:
        # The timestamp is read from the file's CONTENT, not its mtime: a
        # backup, a sync client or a file copy rewrites mtime and would silence
        # or unsilence the message for reasons that have nothing to do with the
        # failure.
        with open(marker, encoding="utf-8") as f:
            last = float(f.read().strip())
        if 0 <= now - last < ttl:
            return False
    except (OSError, ValueError):
        pass
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(int(now)))
    except OSError:
        pass  # cannot throttle; still better to log than to stay silent
    log_error(message)
    return True


def sync_pending(conn, max_batches=40, timeout=10):
    """Drain unsynced events to the Worker. The only place that sends.

    Both callers (the detached syncer and the git post-commit hook) go through
    here so the ordering below cannot be got wrong in one of them:

      1. resolve this installation's id — and if that fails, send NOTHING.
         Events stay unsynced, the failure is logged locally, and the next
         capture spawns another attempt. Falling back to `legacy` would look
         like success while quietly merging this machine's rowids with every
         other unidentified installation's.
      2. stamp events captured before an id existed, so each row carries the
         namespace it is being sent under, permanently.
      3. drain in batches, marking only what the Worker acknowledged.

    Never raises: a hook must not disturb Claude Code or `git commit`.
    """
    try:
        source = source_id()
        if not source:
            pending = count_unstamped(conn)
            _log_throttled(
                "source-id-failure",
                f"sync_pending: no installation source id at {SOURCE_ID_PATH}; "
                f"holding {pending} event(s) unsynced for a later attempt",
            )
            return False

        stamp_pending_source(conn, source)

        for _ in range(max_batches):
            unsynced = get_unsynced_events(conn, limit=50)
            if not unsynced:
                return True
            if not send_to_worker(unsynced, repo_count(conn), timeout=timeout, source=source):
                return False  # network down — the next capture spawns a new attempt
            mark_synced(conn, [e["id"] for e in unsynced])
        return True
    except Exception as exc:
        log_error(f"sync_pending failed: {exc}")
        return False
